"""Which jobs ci.yml starts on which event, and its contract with the released action."""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import released_action

ROOT = released_action.ROOT
PREDECESSORS = {"lint", "test-linux", "test-windows", "test-macos"}
REPORT_ONLY = ["release-tail", "host-variable"]
RECORDED_RUN = Path(__file__).resolve().parent / "fixtures/own-run-jobs.json"
OMITTED_LABEL = "not-measured-on-pr"
# What a pull request cannot move: its report counts these in one line and runs none of them.
OMITTED = {
    "privateterms-cd-job-time",
    "privateterms-release-cycle-time",
    "privateterms-cd-job-count",
    "privateterms-release-read-requests",
    "privateterms-pr-read-requests",
    "privateterms-gate-time",
}
# Everything this repository held before the report job, but the one permitted increment.
THRESHOLDS = {
    "privateterms-ci-check-time": 1800,
    "privateterms-cd-job-time": 1800,
    "privateterms-release-cycle-time": 5400,
    "privateterms-ci-job-count": 5,
    "privateterms-cd-job-count": 6,
    "privateterms-release-read-requests": 6,
    "privateterms-pr-read-requests": 2,
    "privateterms-gate-time": 1800,
}
FIGURES = ["bash", "scripts/actions-budget-figures.sh"]
COMMANDS = {
    "privateterms-ci-check-time": [*FIGURES, "longest-job", "--stage", "pr"],
    "privateterms-cd-job-time": [
        *FIGURES,
        "longest-job",
        "--stage",
        "cd",
        "--exclude-workflow",
        "ci",
    ],
    "privateterms-release-cycle-time": [
        *FIGURES,
        "release-cycle-time",
        "--published-paths",
        ".github/release-published-paths",
    ],
    "privateterms-ci-job-count": [*FIGURES, "job-count", "--stage", "pr"],
    "privateterms-cd-job-count": [
        *FIGURES,
        "job-count",
        "--stage",
        "cd",
        "--exclude-workflow",
        "ci",
    ],
    "privateterms-release-read-requests": [
        *FIGURES,
        "release-read-requests",
        "--exclude-workflow",
        "ci",
    ],
    "privateterms-pr-read-requests": [*FIGURES, "pr-read-requests"],
    "privateterms-gate-time": ["node", "scripts/gate-time-budget.mjs"],
}


def evaluate(expression, github):
    """A job's `if:` over the `github` context, in the operators ci.yml uses."""

    def lookup(path):
        value = {"github": github}
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value

    text = re.sub(r"\bgithub(\.[A-Za-z_]+)+", lambda m: f"lookup('{m[0]}')", expression)
    text = text.replace("&&", " and ").replace("||", " or ").replace("!(", " not (")
    names = {
        "lookup": lookup,
        "true": True,
        "always": lambda: True,
        "startsWith": lambda value, prefix: str(value or "").startswith(prefix),
    }
    return bool(eval(text, {"__builtins__": {}}, names))


def pull_request(head_ref="change", head_repository="owner/repo", draft=False):
    return {
        "event_name": "pull_request",
        "repository": "owner/repo",
        "head_ref": head_ref,
        "event": {
            "pull_request": {
                "draft": draft,
                "head": {"repo": {"full_name": head_repository}},
            }
        },
    }


PUSH = {"event_name": "push", "repository": "owner/repo", "head_ref": "", "event": {}}


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = released_action.workflow()
        cls.jobs = cls.workflow["jobs"]
        cls.job = cls.jobs["budgets"]
        cls.step = released_action.action_step(cls.workflow)
        cls.budgets = {
            budget["id"]: budget
            for budget in yaml.safe_load((ROOT / "budgets.yaml").read_text())["budgets"]
        }

    def started(self, github):
        return {
            name
            for name, job in self.jobs.items()
            if evaluate(job.get("if", "true"), github)
        }

    def test_triggers_are_unfiltered_pull_requests_and_pushes_to_main(self):
        triggers = self.workflow[True]  # YAML 1.1 reads the bare `on` key as true
        self.assertEqual(set(triggers), {"pull_request", "push"})
        self.assertIsNone(
            triggers["pull_request"],
            "no type, path or branch filter, so drafts run too",
        )
        self.assertEqual(triggers["push"], {"branches": ["main"]})

    def test_a_pull_request_starts_every_job_and_a_draft_the_same(self):
        everything = {*PREDECESSORS, "budgets"}
        self.assertEqual(
            set(self.jobs), everything, "exactly one job beside the platform jobs"
        )
        self.assertEqual(self.started(pull_request()), everything)
        self.assertEqual(self.started(pull_request(draft=True)), everything)
        self.assertEqual(
            self.started(pull_request(head_repository="someone/fork")), everything
        )

    def test_a_push_to_main_starts_only_the_report_job(self):
        self.assertEqual(self.started(PUSH), {"budgets"})

    def test_the_release_pull_request_keeps_its_cadence_and_gets_a_report(self):
        self.assertEqual(
            self.started(pull_request(head_ref="release-plz-2026")), {"lint", "budgets"}
        )
        fork = pull_request(head_ref="release-plz-2026", head_repository="someone/fork")
        self.assertEqual(self.started(fork), {*PREDECESSORS, "budgets"})

    def test_the_report_job_runs_after_every_predecessor_however_they_ended(self):
        self.assertEqual(set(self.job["needs"]), PREDECESSORS)
        self.assertEqual(self.job["if"], "always()")
        for name in PREDECESSORS:
            self.assertNotIn("needs", self.jobs[name], "only budgets waits")

    def test_every_job_keeps_the_thirty_minute_line(self):
        for name, job in self.jobs.items():
            self.assertEqual(job["timeout-minutes"], 30, name)

    def test_the_report_job_builds_nothing_and_holds_what_the_action_asks(self):
        uses = [step.get("uses", "").split("@")[0] for step in self.job["steps"]]
        self.assertEqual(uses, ["actions/checkout", released_action.ACTION])
        self.assertEqual(
            self.job["steps"][0]["with"]["fetch-depth"], 0, "local git proves ancestry"
        )
        self.assertEqual(
            self.job["permissions"],
            {"contents": "read", "actions": "read", "pull-requests": "write"},
        )

    def test_comment_writers_are_serialized_and_only_a_superseded_pull_request_cancels(
        self,
    ):
        self.assertIs(self.job["concurrency"]["cancel-in-progress"], False)
        self.assertIn("pull_request.number", self.job["concurrency"]["group"])
        self.assertEqual(
            self.workflow["concurrency"]["cancel-in-progress"],
            "${{ github.event_name == 'pull_request' }}",
        )

    def test_the_inputs_passed_are_the_ones_the_pinned_release_declares(self):
        released = released_action.load()
        self.assertRegex(
            released.tag, r"^v\d+\.\d+\.\d+$", "an exact release, not a floating ref"
        )
        declared = released.declared["inputs"]
        given = self.step["with"]
        self.assertLessEqual(set(given), set(declared))
        self.assertLessEqual(
            {name for name, spec in declared.items() if spec.get("required")},
            set(given),
        )
        self.assertEqual(given["token"], "${{ github.token }}")
        # What leaving the rest out means is what this repository relies on.
        self.assertEqual(declared["budget-files"]["default"], "**/budgets.yaml")
        self.assertEqual(declared["labels"]["default"], "ci-report")
        self.assertEqual(declared["artifact-name"]["default"], "budget-results")
        self.assertFalse({"budget-files", "labels", "artifact-name"} & set(given))

    def test_exactly_the_labels_that_cannot_measure_here_are_report_only(self):
        listed = self.step["with"]["enforcement-exclude-labels"].split(",")
        self.assertEqual(listed, REPORT_ONLY)
        carried = {
            label
            for budget in self.budgets.values()
            for label in budget.get("labels", [])
        }
        self.assertEqual(
            carried - {OMITTED_LABEL},
            set(listed),
            "no root budget is enforced in this job or left unlisted",
        )

    def test_exactly_the_budgets_a_pull_request_cannot_move_are_left_out(self):
        self.assertEqual(self.step["with"]["omit-labels"], OMITTED_LABEL)
        self.assertIn("omit-labels", released_action.load().declared["inputs"])
        self.assertEqual(
            {
                key
                for key, budget in self.budgets.items()
                if OMITTED_LABEL in budget["labels"]
            },
            OMITTED,
        )

    def test_the_report_job_takes_no_saved_results_since_no_test_job_saves_any(self):
        self.assertNotIn("saved-results-artifacts", self.step["with"])
        for name in PREDECESSORS:
            uses = [step.get("uses", "") for step in self.jobs[name]["steps"]]
            self.assertFalse(
                [used for used in uses if "upload-artifact" in used],
                f"{name} uploads nothing for the report job to read",
            )

    def test_root_budgets_keep_their_limits_labels_and_commands(self):
        self.assertEqual(
            {key: budget["threshold"] for key, budget in self.budgets.items()},
            THRESHOLDS,
        )
        self.assertEqual(
            {key: budget["command"] for key, budget in self.budgets.items()}, COMMANDS
        )
        for key, budget in self.budgets.items():
            wanted = (
                ["host-variable"]
                if key == "privateterms-gate-time"
                else ["release-tail"]
            )
            if key in OMITTED:
                wanted = [*wanted, OMITTED_LABEL]
            self.assertEqual(budget["labels"], wanted, key)

    def test_the_cycle_time_figure_gets_the_history_and_the_paths_it_reads(self):
        release = yaml.safe_load(
            (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        )
        checkout = release["jobs"]["publish"]["steps"][0]
        self.assertTrue(checkout["uses"].startswith("actions/checkout@"))
        self.assertEqual(checkout["with"]["fetch-depth"], 0, "it diffs merge^1 merge")
        command = self.budgets["privateterms-release-cycle-time"]["command"]
        paths = command[command.index("--published-paths") + 1]
        specs = [
            line
            for line in (ROOT / paths).read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        self.assertTrue(specs)
        for spec in specs:
            tracked = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", spec],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertTrue(tracked, f"{spec} names nothing this repository holds")

    def test_the_job_count_budget_allows_exactly_the_jobs_a_pull_request_starts(self):
        limit = self.budgets["privateterms-ci-job-count"]["threshold"]
        self.assertEqual(limit, len(self.started(pull_request())))

    def test_the_cd_figures_name_the_workflow_that_carries_the_report_jobs_push(self):
        name = self.workflow["name"]
        for key in ("cd-job-time", "cd-job-count", "release-read-requests"):
            command = self.budgets[f"privateterms-{key}"]["command"]
            self.assertEqual(command[-2:], ["--exclude-workflow", name], key)

    def test_the_desired_required_checks_name_the_report_job(self):
        governance = json.loads((ROOT / ".github/governance.json").read_text())
        self.assertEqual(set(governance["required_checks"]), {*PREDECESSORS, "budgets"})
        self.assertIs(governance["strict"], False)


class OwnRunFigures(unittest.TestCase):
    """The real commands over one recorded run, doubled only at the `gh` they read it through."""

    def check(self, budget, event_name="pull_request"):
        with tempfile.TemporaryDirectory() as directory:
            stand_in = Path(directory) / "gh"
            stand_in.write_text(
                f'#!/bin/sh\necho "$*" >> {directory}/asked\ncat {RECORDED_RUN}\n'
            )
            stand_in.chmod(0o755)
            done = subprocess.run(
                [
                    str(ROOT / "node_modules/.bin/onebudgetspec"),
                    "check",
                    "budgets.yaml",
                    "--id",
                    budget,
                    "--json",
                ],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{directory}{os.pathsep}{os.environ['PATH']}",
                    "GITHUB_EVENT_NAME": event_name,
                    "GITHUB_REPOSITORY": "owner/repo",
                    "GITHUB_RUN_ID": "42",
                    "ONEVCS": "no-such-onevcs",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            asked = Path(directory, "asked")
            return (
                done,
                json.loads(done.stdout)["results"][0],
                asked.read_text() if asked.exists() else "",
            )

    def test_a_pull_request_reports_its_own_runs_longest_finished_job(self):
        _, result, asked = self.check("privateterms-ci-check-time")
        print(
            f"replayed privateterms-ci-check-time: {result['actual']}s of "
            f"{result['threshold']}s, {result['verdict']}"
        )
        self.assertEqual((result["verdict"], result["actual"]), ("within", 226), result)
        self.assertIn("repos/owner/repo/actions/runs/42/jobs", asked)

    def test_a_pull_request_counts_its_own_runs_jobs_the_one_in_progress_too(self):
        _, result, asked = self.check("privateterms-ci-job-count")
        print(
            f"replayed privateterms-ci-job-count: {result['actual']} of "
            f"{result['threshold']} jobs, {result['verdict']}"
        )
        self.assertEqual((result["verdict"], result["actual"]), ("within", 5), result)
        self.assertEqual(len(asked.splitlines()), 1, "one read of the run's jobs")

    def test_any_other_event_never_reads_its_own_run(self):
        done, result, asked = self.check("privateterms-ci-job-count", "push")
        self.assertEqual(done.returncode, 3, done.stdout)
        self.assertEqual(asked, "")
        self.assertEqual(result["verdict"], "error", result)


class FetchingTheRelease(unittest.TestCase):
    """The release fetch, with only the download doubled: Nx starts two fetches on a cold tree."""

    TAG = "v9.9.9"
    ARCHIVE = "onebudgetspec-github-action-9.9.9-x86_64-unknown-linux-gnu.tar.gz"
    ACTION_YML = b"name: invented\n"

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.target = Path(scratch.name) / "report-job"
        self.tree = self.target / f"action-{self.TAG}"

    def downloads(self, sums_body=None, on_sums=lambda: None):
        source = io.BytesIO()
        with tarfile.open(fileobj=source, mode="w:gz") as archive:
            member = tarfile.TarInfo(f"action-{self.TAG}/action.yml")
            member.size = len(self.ACTION_YML)
            archive.addfile(member, io.BytesIO(self.ACTION_YML))
        assets = {self.ARCHIVE: b"invented archive", "action.yml": self.ACTION_YML}
        sums = "".join(
            f"{hashlib.sha256(body).hexdigest()}  {name}\n"
            for name, body in assets.items()
        )

        def download(url):
            name = url.rsplit("/", 1)[-1]
            if name == "SHA256SUMS":
                on_sums()
                return (sums if sums_body is None else sums_body).encode()
            return assets.get(name, source.getvalue())

        return mock.patch.object(released_action, "_get", download)

    def fetch(self):
        released_action._fetch(self.TAG, self.tree, self.ARCHIVE)

    def test_two_fetches_on_a_cold_tree_both_end_with_the_whole_release(self):
        # Neither passes the checksums until both have started, so both reach the publish.
        both_started = threading.Barrier(2, timeout=30)
        with self.downloads(on_sums=both_started.wait), ThreadPoolExecutor(2) as pool:
            for fetch in [pool.submit(self.fetch) for _ in range(2)]:
                fetch.result()
        self.assertEqual((self.tree / "action.yml").read_bytes(), self.ACTION_YML)
        self.assertEqual(
            (self.tree / "dist" / self.ARCHIVE).read_bytes(), b"invented archive"
        )
        self.assertEqual(
            [path.name for path in self.target.iterdir()], [self.tree.name]
        )

    def test_a_fetch_that_fails_its_checksums_leaves_nothing_a_later_one_would_trust(
        self,
    ):
        with (
            self.downloads(sums_body="not the release\n"),
            self.assertRaisesRegex(AssertionError, "is not what release"),
        ):
            self.fetch()
        self.assertEqual(list(self.target.iterdir()), [])
        with self.downloads():
            self.fetch()
        self.assertTrue((self.tree / "dist" / self.ARCHIVE).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=1)
