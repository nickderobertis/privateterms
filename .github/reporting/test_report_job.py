"""The budgets job, driven through ci.yml's real `uses:` and `with:`.

Each journey runs what the job pins: action.yml's own steps, the released driver and plugin archive,
the published core wheel, the real `gh` and the real `actions/upload-artifact` code, over a copy of
this repository's tree. Only GitHub's services, the release host and the package index are doubled,
by the harness the action ships at that same tag. `test_record_a_complete_job` saves the job's
telemetry for `privateterms-budget-report-command-seconds` and its full REST figure.
`ReleaseTailEnforcement` runs the two checks that hold the budgets the job leaves out.
"""

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "workflows" / "tests"))
import released_action

ROOT = released_action.ROOT
RELEASED = released_action.load()
harness = RELEASED.harness
OWN_BUDGET = "privateterms-budget-report-command-seconds"
JOB_COUNT = "privateterms-ci-job-count"
CATALOG_RUNNABLE = {
    "fixture-bundle-bytes": "bytes",
    "fixture-coverage-percent": "percent",
    "fixture-host-reads": "requests",
    "fixture-walltime": "seconds",
    "fixture-laptop-figure": "count",
}
CATALOG_UNAVAILABLE = {
    "fixture-needs-a-tool": "no-such-tool-on-this-runner",
    "fixture-needs-telemetry": ".telemetry/predecessor.json",
}
COVERAGE_COMMAND = """\
import { appendFileSync, writeFileSync } from 'node:fs';
appendFileSync(process.env.JOURNEY_COUNTS, `${process.env.ONEBUDGETSPEC_BUDGET_ID}\\n`);
writeFileSync(process.env.ONEBUDGETSPEC_RESULT, JSON.stringify({ value: 91 }));
"""
CI_CHECK_TIME = "privateterms-ci-check-time"
CI_TIME_PAIR = {CI_CHECK_TIME, JOB_COUNT}
FIGURES_NEED_ONEVCS = "onevcs is not on PATH"
NO_CREDENTIAL = "no GitHub credential"
OMIT_LABEL = "not-measured-on-pr"
GATE_TIME = "privateterms-gate-time"
# What a pull request cannot move, so its report runs and shows none of them.
OMITTED = {
    "privateterms-cd-job-time",
    "privateterms-release-cycle-time",
    "privateterms-cd-job-count",
    "privateterms-release-read-requests",
    "privateterms-pr-read-requests",
    GATE_TIME,
}
LEFT_OUT_LINE = (
    f"{len(OMITTED)} budgets are left out because a pull request cannot measure them "
    f"(label {OMIT_LABEL})."
)
RELEASE_TAIL = (OMITTED - {GATE_TIME}) | CI_TIME_PAIR
OVER_LONGEST = 2000
# The workload of the budget's record: the production catalog and a rolling file of 20 commits. The
# scalars in that file are synthetic copies of one recorded job's.
CATALOG_ROWS = len(OMITTED) + len(CI_TIME_PAIR) + 1
COMMITS = 20
DESIGN_REQUESTS = 20
TELEMETRY = HERE / ".telemetry"
# A `gh` holding no token for its host reads the keyring, which autolaunches a session bus: a daemon
# that outlives the job and keeps one of the host's inotify instances. This value stops the launch.
SESSION_BUS = "DBUS_SESSION_BUS_ADDRESS"
DBUS_LAUNCH_CALLS = "dbus-launch-calls"


def runner_path(directory: Path) -> str:
    """What a hosted runner gives a budget command: no uv, cargo, bun or onevcs."""
    directory.mkdir()
    (directory / "node").symlink_to(shutil.which("node"))
    # Ahead of /usr/bin's real one, so a `gh` that asks for a bus is recorded and starts nothing.
    stand_in = directory / "dbus-launch"
    calls = shlex.quote(str(directory / DBUS_LAUNCH_CALLS))
    stand_in.write_text(f"#!/bin/sh\necho asked >> {calls}\nexit 1\n")
    stand_in.chmod(0o755)
    return f"{directory}{os.pathsep}/usr/bin{os.pathsep}/bin"


def bus_requests(directory: Path) -> int:
    """How many times a `gh` on `runner_path(directory)` has asked for a session bus."""
    calls = directory / DBUS_LAUNCH_CALLS
    return len(calls.read_text().splitlines()) if calls.exists() else 0


def job_environment(counts: Path, path: str, run_id: int, event_name: str) -> dict:
    """What a journey adds to the harness's environment for every step of its job."""
    return {
        "JOURNEY_COUNTS": str(counts),
        "PATH": path,
        SESSION_BUS: "disabled:",
        # What a runner sets for every step, which the figures script reads.
        "GITHUB_REPOSITORY": harness.REPOSITORY,
        "GITHUB_RUN_ID": str(run_id),
        "GITHUB_EVENT_NAME": event_name,
        "RUNNER_NAME": "hosted-runner",
    }


def tracked_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [name for name in listed.stdout.split("\0") if name]


def zipped(name: str, content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def run_jobs(longest: int = 226, extra: tuple[str, ...] = ()) -> list[dict]:
    """A run's job records as GitHub lists them: four finished and the budgets job in progress."""

    def job(name: str, seconds: int | None, label: str = "ubuntu-latest") -> dict:
        finished = seconds is not None
        return {
            "name": name,
            "workflow_name": "ci",
            "status": "completed" if finished else "in_progress",
            "conclusion": "success" if finished else None,
            "runner_name": "GitHub Actions 1",
            "labels": [label],
            "started_at": "2026-11-07T00:00:00Z",
            "completed_at": (
                f"2026-11-07T{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}Z"
                if finished
                else None
            ),
        }

    return [
        job("lint", longest),
        job("test-linux", 120),
        job("test-windows", 180, "windows-latest"),
        job("test-macos", 150, "macos-latest"),
        *[job(name, 1) for name in extra],
        job("budgets", None),
    ]


class Host(harness.Host):
    """The action's GitHub double, answering a run's job listing too, which its harness leaves out."""

    def __init__(self):
        super().__init__()
        self.jobs = run_jobs()

    def read(self, handler, path):
        if re.fullmatch(r"/repos/owner/repo/actions/runs/\d+/jobs", path.split("?")[0]):
            listing = {"total_count": len(self.jobs), "jobs": self.jobs}
            return self.reply(handler, 200, json.dumps(listing).encode())
        return super().read(handler, path)


def one_row(markdown: str, budget: str) -> str:
    rows = [
        line
        for line in markdown.splitlines()
        if line.startswith("|") and f"/ {budget} " in line
    ]
    assert len(rows) == 1, (budget, rows)
    return rows[0]


class Journey(unittest.TestCase):
    """This repository's tree in a real git repository, and one host double."""

    def setUp(self):
        self.host = Host()
        self.addCleanup(self.host.close)
        self.repository = harness.Repository()
        self.addCleanup(self.repository.close)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.counts = self.scratch / "counts"
        self.runner_bin = self.scratch / "runner-bin"
        self.path = runner_path(self.runner_bin)
        self.next_run = 1000
        for name in tracked_files():
            source, target = ROOT / name, self.repository.path / name
            if source.is_file() or source.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target, follow_symlinks=False)
        # Discovery must skip these: either would make the catalog refuse whole.
        self.repository.write("tests/fixtures/budgets.yaml", "not: a budgets file\n")
        self.repository.write("conformance/case/budgets.yaml", "not: a budgets file\n")
        self.base_sha = self.repository.commit("the tree")

    def tearDown(self):
        self.assertEqual(
            bus_requests(self.runner_bin),
            0,
            f"a `gh` of this job asked for a session bus: keep {SESSION_BUS} in its environment",
        )

    def inputs(self) -> dict:
        given = dict(released_action.action_step(released_action.workflow())["with"])
        self.assertEqual(given.pop("token"), "${{ github.token }}")
        return {"token": "job-token", **given}

    def run_job(self, event_name, sha, **options):
        self.next_run += 1
        self.counts.unlink(missing_ok=True)
        run_id = options.pop("run_id", self.next_run)
        job = harness.Job(
            self.host,
            self.repository,
            event_name,
            sha,
            inputs=options.pop("inputs", self.inputs()),
            run_id=run_id,
            environment=job_environment(self.counts, self.path, run_id, event_name),
            **options,
        )
        self.addCleanup(job.close)
        return job.run()

    def base_push(self):
        self.repository.git("checkout", "--quiet", "main")
        self.base_sha = self.repository.commit("merged")
        return self.run_job("push", self.base_sha)

    def pull_request(self, head_repository=harness.REPOSITORY, draft=False, files=None):
        self.repository.git("checkout", "--quiet", "-B", "change", self.base_sha)
        return self.pull_request_head(head_repository, draft, files)

    def pull_request_head(
        self, head_repository=harness.REPOSITORY, draft=False, files=None
    ):
        for name, content in (
            files or {"README.md": "An unrelated path changed.\n"}
        ).items():
            self.repository.write(name, content)
        head = self.repository.commit("change")
        self.host.head = head
        event = harness.event_pull_request(
            1, head, self.base_sha, head_repository=head_repository, draft=draft
        )
        return self.run_job(
            "pull_request", head, event=event, base_ref="main", register=False
        )

    def merged_base_push(self, pull):
        """The push of `pull`'s squash commit, with GitHub answering which pull request it was."""
        self.host.add_run(
            pull.run_id, pull.sha, event="pull_request", branch="change", minute=1
        )
        self.repository.git("checkout", "--quiet", "main")
        self.base_sha = self.repository.commit("merged")
        self.host.merge_pull_request(self.base_sha, pull.sha)
        return self.run_job("push", self.base_sha)

    def executed(self) -> list[str]:
        return sorted(self.counts.read_text().split()) if self.counts.exists() else []

    def saved(self, job, name="budget-results") -> dict:
        return json.loads(
            self.host.artifact_files(job.run_id, name)["budget-run.json"].decode()
        )


class ProductionCatalog(Journey):
    """The real budgets files and commands, on what a real runner holds."""

    def setUp(self):
        super().setUp()
        # Each command the budgets name logs its arguments before it does anything else.
        log = 'echo "$0 $*" >> "$JOURNEY_COUNTS"\n'
        figures = "scripts/actions-budget-figures.sh"
        script = (ROOT / figures).read_text()
        shebang, rest = script.split("\n", 1)
        self.repository.write(figures, f"{shebang}\n{log}{rest}")
        gate = "scripts/gate-time-budget.mjs"
        self.repository.write(
            gate,
            "import { appendFileSync } from 'node:fs';\n"
            "appendFileSync(process.env.JOURNEY_COUNTS, 'gate-time\\n');\n"
            + (ROOT / gate).read_text(),
        )
        self.base_sha = self.repository.commit("commands that log")

    def commands_run(self) -> list[str]:
        if not self.counts.exists():
            return []
        return sorted(
            line.split(".sh ", 1)[-1] for line in self.counts.read_text().splitlines()
        )

    def results(self, job) -> dict:
        return {
            result["id"]: result for result in self.saved(job)["results"]["results"]
        }

    def assert_the_left_out_budgets_have_no_row(self, job):
        rows = job.rows()
        self.assertEqual(set(rows), {OWN_BUDGET, *CI_TIME_PAIR})
        markdown = job.markdown()
        self.assertEqual(markdown.count(LEFT_OUT_LINE), 1, markdown)
        for budget in OMITTED:
            self.assertNotIn(budget, markdown)
        self.assertNotIn("gate-time", self.commands_run())
        catalog = {entry["id"] for entry in self.saved(job)["catalog"]}
        self.assertLessEqual(OMITTED, catalog, "the saved catalog keeps them")

    def test_a_draft_reports_its_own_runs_figures_and_leaves_out_the_rest(self):
        job = self.pull_request(draft=True)
        self.assertEqual(job.exit_code, 0, job.stdout)
        self.assert_the_left_out_budgets_have_no_row(job)
        self.assertEqual(
            self.commands_run(), ["job-count --stage pr", "longest-job --stage pr"]
        )
        self.assertEqual(
            self.host.count(rf"/actions/runs/{job.run_id}/jobs"),
            2,
            "one read of this run's jobs per figure, and no other run's",
        )
        self.assertEqual(self.host.count(r"/releases|/compare"), 0)

        rows = job.rows()
        # The longest finished job, the budgets job in progress counting toward the jobs alone.
        self.assertEqual(rows[CI_CHECK_TIME]["current"], 226)
        self.assertEqual(rows[JOB_COUNT]["current"], 5)
        for budget in CI_TIME_PAIR:
            self.assertEqual(rows[budget]["verdict"], "within", budget)
            self.assertIn("report-only", one_row(job.markdown(), budget))
        self.assertEqual(self.saved(job)["unavailable"], [])

        self.assertEqual(len(self.host.comments), 1)
        body = self.host.comments[0]["body"]
        self.assertIn(LEFT_OUT_LINE, body)
        for budget in (OWN_BUDGET, *CI_TIME_PAIR):
            # Its figure and verdict: the baseline columns wait for five base samples.
            self.assertRegex(one_row(body, budget), r"\| within \| [\d.]+ \|")
        # The comment carries no breakdown: those stay in the artifact and the job's log.
        for detail in ("install_seconds", "phases", "profile", "per test"):
            self.assertNotIn(detail, body)

        # The job judged itself after its main upload, and saved that verdict beside it.
        self.assertEqual(job.outcomes["main-upload"], "success", job.stdout)
        self.assertEqual(job.outcomes["final-upload"], "success", job.stdout)
        own = self.results(job)[OWN_BUDGET]
        self.assertEqual(own["verdict"], "within")
        self.assertEqual(own["unit"], "seconds")
        main = self.saved(job, "budget-results-main")
        self.assertEqual(
            {result["id"] for result in main["results"]["results"]},
            CI_TIME_PAIR,
            "the main upload precedes the own verdict",
        )

    def test_a_ci_time_figure_over_its_line_is_reported_and_fails_nothing(self):
        self.host.jobs = run_jobs(longest=OVER_LONGEST, extra=("one-more",))
        job = self.pull_request()
        self.assertEqual(job.exit_code, 0, job.stdout)
        rows = job.rows()
        self.assertEqual(rows[CI_CHECK_TIME]["current"], OVER_LONGEST)
        self.assertEqual(rows[JOB_COUNT]["current"], 6)
        for budget in CI_TIME_PAIR:
            self.assertEqual(rows[budget]["verdict"], "over", budget)
            self.assertIn("report-only", one_row(job.markdown(), budget))

    def test_a_refused_read_of_the_run_is_a_row_with_its_reason_and_no_number(self):
        self.host.refuse.append(
            {"path": r"/actions/runs/\d+/jobs", "status": 403, "times": 2}
        )
        job = self.pull_request()
        self.assertEqual(job.exit_code, 0, job.stdout)
        rows = job.rows()
        for budget in CI_TIME_PAIR:
            self.assertNotIn("verdict", rows[budget], budget)
            self.assertIsNone(rows[budget].get("current"), budget)
            self.assertIn("unavailable", one_row(job.markdown(), budget))
        self.assertEqual(self.results(job)[OWN_BUDGET]["verdict"], "within")

    def test_a_base_push_records_the_merged_runs_figures_running_no_command(self):
        self.host.jobs = run_jobs(longest=300)
        pull = self.pull_request()
        self.assertEqual(pull.exit_code, 0, pull.stdout)
        figures = {
            budget: self.results(pull)[budget]["actual"] for budget in CI_TIME_PAIR
        }
        self.assertEqual(figures, {CI_CHECK_TIME: 300, JOB_COUNT: 5})
        posted = list(self.host.comments)
        self.host.clear_requests()
        # The push's own run lists something else, so a figure read from it could not pass.
        self.host.jobs = run_jobs(longest=999)

        base = self.merged_base_push(pull)
        self.assertEqual(base.exit_code, 0, base.stdout)
        self.assertEqual(self.host.comments, posted, "a base push posts nothing")
        self.assertEqual(self.commands_run(), [], "not one figure was re-measured")
        self.assertEqual(self.host.count(r"/runs/\d+/jobs"), 0)
        self.assert_the_left_out_budgets_have_no_row(base)

        history = json.loads(
            self.host.artifact_files(base.run_id)["rolling-history.json"].decode()
        )
        self.assertEqual([run["head_sha"] for run in history["runs"]], [base.sha])
        entry = {
            result["id"]: result for result in history["runs"][0]["results"]["results"]
        }
        self.assertEqual(set(entry), {OWN_BUDGET, *CI_TIME_PAIR})
        for budget, figure in figures.items():
            self.assertEqual(entry[budget]["actual"], figure, budget)
            self.assertEqual(entry[budget]["verdict"], "within", budget)

        # What a later pull request compares with is that same measurement.
        self.host.jobs = run_jobs(longest=300)
        later = self.pull_request()
        self.assertEqual(later.rows()[CI_CHECK_TIME]["baseline_n"], 1)

    def test_a_base_push_with_no_pull_request_says_why_it_has_no_figures(self):
        base = self.base_push()
        self.assertEqual(base.exit_code, 0, base.stdout)
        self.assertEqual(
            self.commands_run(), ["job-count --stage pr", "longest-job --stage pr"]
        )
        rows = base.rows()
        for budget in CI_TIME_PAIR:
            self.assertNotIn("verdict", rows[budget], budget)
            self.assertIn(FIGURES_NEED_ONEVCS, rows[budget]["unavailable"])
        # The own budget measures after the main upload, so only the final upload's history holds it.
        history = json.loads(
            self.host.artifact_files(base.run_id)["rolling-history.json"].decode()
        )
        saved = {
            result["id"]: result for result in history["runs"][0]["results"]["results"]
        }
        self.assertEqual(set(saved), {OWN_BUDGET})
        self.assertEqual(saved[OWN_BUDGET]["verdict"], "within")

        pull = self.pull_request()
        self.assertEqual(pull.exit_code, 0, pull.stdout)
        self.assertEqual(pull.rows()[OWN_BUDGET]["baseline_n"], 1)
        self.assertIn(" | 1 | ", one_row(self.host.comments[0]["body"], OWN_BUDGET))

    def test_a_merged_run_whose_artifact_expired_leaves_the_rows_as_they_would_be(self):
        pull = self.pull_request()
        self.host.expire(pull.run_id)
        base = self.merged_base_push(pull)
        self.assertEqual(base.exit_code, 0, base.stdout)
        rows = base.rows()
        for budget in CI_TIME_PAIR:
            self.assertNotIn("verdict", rows[budget], budget)
            self.assertIn(FIGURES_NEED_ONEVCS, rows[budget]["unavailable"])

    def test_a_fork_has_no_credential_for_the_ci_time_rows_and_no_other_runs_figure(
        self,
    ):
        # Real figures already stand on the base, which the fork's rows must not borrow.
        merged = self.pull_request()
        self.assertEqual(self.merged_base_push(merged).exit_code, 0)
        self.host.clear_requests()
        self.host.comments.clear()

        job = self.pull_request(head_repository="someone/fork")
        self.assertEqual(job.exit_code, 0, job.stdout)
        self.assertEqual(self.host.comments, [])
        self.assertEqual(
            self.host.count("comments|graphql"), 0, "no comment is even read"
        )
        self.assertEqual(self.host.count(r"/runs/\d+/jobs"), 0, "no read was made")
        self.assertIn("someone/fork", job.summary)
        self.assertIsNotNone(self.host.artifact_files(job.run_id))
        rows = job.rows()
        self.assertEqual(set(rows), {OWN_BUDGET, *CI_TIME_PAIR})
        reasons = {
            entry["id"]: entry["reason"] for entry in self.saved(job)["unavailable"]
        }
        self.assertEqual(set(reasons), CI_TIME_PAIR)
        for budget in CI_TIME_PAIR:
            self.assertNotIn("verdict", rows[budget], budget)
            self.assertIsNone(rows[budget].get("current"), budget)
            self.assertIn(NO_CREDENTIAL, reasons[budget])
            self.assertIn(NO_CREDENTIAL, rows[budget]["unavailable"])
            self.assertIn(NO_CREDENTIAL, one_row(job.markdown(), budget))

    def test_the_own_budget_over_its_line_fails_the_job_and_keeps_its_results(self):
        self.repository.write(
            ".github/reporting/budgets.yaml",
            (HERE / "budgets.yaml")
            .read_text()
            .replace("threshold: 120", "threshold: 0"),
        )
        self.base_sha = self.repository.commit("no time at all")
        job = self.pull_request()
        self.assertEqual(job.exit_code, 1, job.stdout)
        self.assertEqual(self.results(job)[OWN_BUDGET]["verdict"], "over")
        self.assertEqual(len(self.host.comments), 1)
        self.assertIsNotNone(
            self.host.artifact_files(job.run_id, "budget-results-main")
        )

    def test_the_declared_budget_is_what_the_released_reader_measures(self):
        budget = yaml.safe_load((HERE / "budgets.yaml").read_text())["budgets"]
        self.assertEqual([entry["id"] for entry in budget], [OWN_BUDGET])
        command = budget[0]["command"]
        self.assertEqual(command[:2], ["onebudgetspec-github-action", "telemetry"])
        metric = command[command.index("--metric") + 1]
        source = RELEASED.tree / "crates/onebudgetspec-github-action/src/finish.rs"
        self.assertIn(f'name: "{metric}"', source.read_text())
        self.assertEqual(budget[0]["threshold"], 120)
        self.assertEqual(
            budget[0]["labels"], [RELEASED.declared["inputs"]["labels"]["default"]]
        )
        self.assertEqual(
            command[command.index("--input") + 1], ".telemetry/report-job.json"
        )


class OrdinaryCatalog(Journey):
    """Runnable budgets beside an unavailable command, through the job and a real base history."""

    def setUp(self):
        super().setUp()
        self.repository.write(
            "budgets.yaml", (HERE / "fixtures/catalog.yaml").read_text()
        )
        self.repository.write("fixture-coverage.mjs", COVERAGE_COMMAND)
        self.repository.write("fixture-bundle-size", "500\n")
        self.base_sha = self.repository.commit("the catalog")

    def test_every_runnable_entry_runs_once_labelled_or_not(self):
        job = self.pull_request()
        self.assertEqual(job.exit_code, 0, job.stdout)
        self.assertEqual(self.executed(), sorted(CATALOG_RUNNABLE))
        saved = self.saved(job)
        verdicts = {result["id"]: result for result in saved["results"]["results"]}
        for budget, unit in CATALOG_RUNNABLE.items():
            wanted = "over" if budget == "fixture-laptop-figure" else "within"
            self.assertEqual(verdicts[budget]["verdict"], wanted, budget)
            self.assertEqual(verdicts[budget]["unit"], unit)
        self.assertEqual(verdicts["fixture-coverage-percent"]["actual"], 91)
        reasons = {entry["id"]: entry["reason"] for entry in saved["unavailable"]}
        self.assertEqual(set(reasons), set(CATALOG_UNAVAILABLE))
        for budget, reason in CATALOG_UNAVAILABLE.items():
            self.assertIn(reason, reasons[budget])
        self.assertIn(
            "report-only",
            one_row(self.host.comments[0]["body"], "fixture-laptop-figure"),
        )

    def test_a_base_push_saves_the_same_results_and_starts_the_rolling_file(self):
        pull = self.pull_request()
        base = self.base_push()
        self.assertEqual(base.exit_code, 0, base.stdout)
        self.assertEqual(len(self.host.comments), 1, "only the pull request posted")
        self.assertEqual(self.executed(), sorted(CATALOG_RUNNABLE))
        base_files = self.host.artifact_files(base.run_id)
        pull_files = self.host.artifact_files(pull.run_id)
        self.assertEqual(set(base_files), {*pull_files, "rolling-history.json"})
        self.assertEqual(set(self.saved(base)), set(self.saved(pull)))
        history = json.loads(base_files["rolling-history.json"].decode())
        self.assertEqual([run["head_sha"] for run in history["runs"]], [base.sha])
        carried = {result["id"] for result in history["runs"][0]["results"]["results"]}
        self.assertLessEqual(set(CATALOG_RUNNABLE), carried)

    def test_a_failed_predecessors_telemetry_is_unavailable_and_a_saved_one_measures(
        self,
    ):
        missing = self.pull_request()
        self.assertEqual(missing.exit_code, 0, missing.stdout)
        self.assertNotIn(
            "verdict",
            missing.rows()["fixture-needs-telemetry"],
            "an absent input is no error",
        )
        self.assertEqual(missing.outcomes["final-upload"], "success")
        saved = self.pull_request(files={".telemetry/predecessor.json": "{}\n"})
        self.assertEqual(saved.rows()["fixture-needs-telemetry"]["verdict"], "within")
        self.assertIn("fixture-needs-telemetry", self.executed())

    def test_a_real_base_history_flags_only_adverse_moves_and_one_comment_keeps_them(
        self,
    ):
        for _ in range(5):
            self.assertEqual(self.base_push().exit_code, 0)
        worse = self.pull_request(draft=True, files={"fixture-bundle-size": "900\n"})
        self.assertEqual(worse.exit_code, 0, worse.stdout)
        row = worse.rows()["fixture-bundle-bytes"]
        self.assertEqual(row["verdict"], "within")
        self.assertEqual(row["baseline_n"], 5)
        self.assertTrue(row["flag"], row)
        self.assertIn("provisional", worse.markdown())
        self.assertEqual(len(self.host.comments), 1)

        better = self.pull_request_head(files={"fixture-bundle-size": "100\n"})
        self.assertEqual(better.exit_code, 0, better.stdout)
        row = better.rows()["fixture-bundle-bytes"]
        self.assertEqual(row["current"], 100)
        self.assertFalse(row["flag"], "an improvement keeps its number without a flag")
        self.assertEqual(len(self.host.comments), 1, "one standing comment")
        body = self.host.comments[0]["body"]
        self.assertIn(worse.sha, body)
        self.assertIn(better.sha, body)
        kept = [
            line
            for line in body.splitlines()
            if line.startswith("- ") and "fixture-bundle-bytes" in line
        ]
        self.assertEqual(
            len(kept), 1, f"the first head's flag stays, the second adds none: {body}"
        )
        flags = body.split("### Per-head adverse flags")[1]
        # Only the bundle: a wall-clock row may also flag on a loaded host, and tells nothing here.
        first, second = flags.split(worse.sha)[1].split(better.sha)
        self.assertIn("fixture-bundle-bytes", first)
        self.assertNotIn(
            "fixture-bundle-bytes", second.split("<!-- onebudgetspec-history")[0]
        )

    def test_host_faults_are_diagnostics_and_a_real_failure_survives_them(self):
        self.host.write_status = 403
        unposted = self.pull_request()
        self.assertEqual(unposted.exit_code, 0, unposted.stdout)
        self.assertIn("not delivered", unposted.summary)
        self.host.write_status = None

        self.host.refuse.append(
            {"path": r"actions/runs/\d+$", "status": 429, "times": 1}
        )
        unread = self.pull_request()
        self.assertEqual(unread.exit_code, 0, unread.stdout)
        self.assertIn("baseline unavailable", unread.markdown())

        self.host.upload_failures = 1
        lost = self.pull_request()
        self.assertEqual(lost.exit_code, 0, lost.stdout)
        self.assertEqual(lost.outcomes["main-upload"], "failure", lost.stdout)

        self.host.write_status = 403
        over = self.pull_request(files={"fixture-bundle-size": "5000\n"})
        self.assertEqual(over.exit_code, 1, over.stdout)
        self.assertEqual(over.rows()["fixture-bundle-bytes"]["verdict"], "over")
        self.assertIn("not delivered", over.summary)
        self.assertIsNotNone(
            self.host.artifact_files(over.run_id), "a failing job keeps its results"
        )
        self.assertEqual(
            sorted(CATALOG_RUNNABLE), self.executed(), "nothing is rerun to fill a row"
        )

    def test_a_token_the_host_refuses_changes_no_verdict(self):
        inputs = {**self.inputs(), "token": ""}
        self.repository.git("checkout", "--quiet", "-B", "change", self.base_sha)
        head = self.repository.commit("change")
        self.host.head = head
        job = self.run_job(
            "pull_request",
            head,
            event=harness.event_pull_request(1, head, self.base_sha),
            base_ref="main",
            register=False,
            inputs=inputs,
        )
        self.assertEqual(job.exit_code, 0, job.stdout)
        self.assertEqual(self.host.comments, [])
        self.assertIn("not delivered", job.summary)
        self.assertIsNotNone(self.host.artifact_files(job.run_id))


class SessionBus(unittest.TestCase):
    """The job's environment, handed to the real `gh` at a loopback port that refuses it."""

    def test_the_job_environment_keeps_a_tokenless_gh_from_asking_for_a_bus(self):
        if sys.platform != "linux" or shutil.which("gh") is None:
            self.skipTest("only `gh` on Linux can autolaunch a session bus")
        with (
            tempfile.TemporaryDirectory() as directory,
            socket.socket() as refusing,
        ):
            scratch = Path(directory)
            runner_bin = scratch / "runner-bin"
            path = runner_path(runner_bin)
            refusing.bind(("127.0.0.1", 0))
            port = str(refusing.getsockname()[1])
            # No GH_TOKEN: a step adds its own, an empty one asks, and so does any call without it.
            environment = {
                "HOME": directory,
                **harness.real_gh_environment(f"http://127.0.0.1:{port}", directory),
                **job_environment(scratch / "counts", path, 1, "pull_request"),
            }

            def requests_of(given: dict) -> int:
                before = bus_requests(runner_bin)
                done = subprocess.run(
                    [
                        shutil.which("gh"),
                        "api",
                        "repos/owner/repo/commits/main",
                    ],
                    env=given,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertIn(port, done.stderr, "`gh` reached only the loopback port")
                return bus_requests(runner_bin) - before

            without = dict(environment)
            without.pop(SESSION_BUS, None)
            if requests_of(without) == 0:
                self.skipTest(
                    "the installed `gh` no longer asks for a session bus without "
                    f"{SESSION_BUS}, so none can leak"
                )
            self.assertEqual(
                requests_of(environment),
                0,
                f"the job's environment must carry {SESSION_BUS}=disabled:",
            )


class ReplayedFigures(unittest.TestCase):
    """The real commands of budgets.yaml over saved answers at their ONEVCS boundary: never live CI."""

    def check(self, budget, answers=None):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "asked"
            environment = {
                **os.environ,
                "ONEVCS": str(HERE / "fixtures/replay-onevcs"),
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_REF_TYPE": "tag",
                "GITHUB_REF_NAME": "v0.0.1",
                "REPLAY_HOST_LOG": str(log),
            }
            environment.pop("RUNNER_TEMP", None)
            environment.pop("GITHUB_RUN_ID", None)
            if answers is not None:
                saved = Path(directory) / "answers.json"
                saved.write_text(json.dumps(answers))
                environment["REPLAY_HOST_ANSWERS"] = str(saved)
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
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            result = json.loads(done.stdout)["results"][0]
            return done.returncode, result, log.read_text().split("\n")

    def test_the_finished_workflows_five_jobs_are_within_the_job_count(self):
        code, result, _ = self.check(JOB_COUNT)
        self.assertEqual(
            (code, result["verdict"], result["actual"]), (0, "within", 5), result
        )
        self.assertEqual(result["threshold"], 5)

    def test_a_sixth_job_is_over_the_job_count(self):
        answers = json.loads((HERE / "fixtures/replayed-host.json").read_text())
        jobs = answers["change-checks 1"]["runs"][0]["jobs"]
        jobs.append({**jobs[0], "id": 1, "name": "one-more"})
        code, result, _ = self.check(JOB_COUNT, answers)
        self.assertEqual(
            (code, result["verdict"], result["actual"]), (1, "over", 6), result
        )

    def test_the_cd_figures_leave_out_the_report_jobs_push_run(self):
        code, result, asked = self.check("privateterms-cd-job-count")
        self.assertEqual(
            (code, result["verdict"], result["actual"]), (0, "within", 6), result
        )
        self.assertNotIn("run-jobs 2000", asked, "the ci run's jobs are never read")
        self.assertIn("run-jobs 2002", asked)

        _, result, asked = self.check("privateterms-release-read-requests")
        self.assertEqual(result["verdict"], "within", result)
        self.assertNotIn("run-jobs 2000", asked)
        _, result, asked = self.check("privateterms-cd-job-time")
        self.assertEqual(result["verdict"], "within", result)
        self.assertNotIn("run-jobs 2000", asked)


class ReleaseTailEnforcement(unittest.TestCase):
    """The two checks holding what the job leaves out, each at its real entry point."""

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.checkout = Path(scratch.name) / "checkout"
        self.checkout.mkdir()
        for name in (
            "budgets.yaml",
            ".github/release-published-paths",
            "scripts/actions-budget-figures.sh",
            "scripts/gate-time-budget.mjs",
            "scripts/gate-time.sh",
        ):
            target = self.checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        (self.checkout / "node_modules").symlink_to(ROOT / "node_modules")
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("add", ".")
        self.commit("the tree")

    def git(self, *arguments) -> str:
        identity = ["-c", "user.name=invented", "-c", "user.email=invented@example.com"]
        return subprocess.run(
            ["git", *identity, *arguments],
            cwd=self.checkout,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("commit", "--quiet", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def over_every_line(self, merge: str) -> Path:
        """Saved answers with each figure past its budget's threshold, at the merge given."""
        answers = json.loads((HERE / "fixtures/replayed-host.json").read_text())
        changes = answers["release-changes"]
        changes["commits"][0]["sha"] = merge
        changes["changes"][0]["merge_commit_sha"] = merge
        changes["cost"]["rest_requests"] = 100
        checks = answers["change-checks 1"]
        checks["cost"]["rest_requests"] = 100
        pr_jobs = checks["runs"][0]["jobs"]
        pr_jobs.append(
            {
                **pr_jobs[0],
                "id": 1,
                "name": "one-more",
                "completed_at": "2026-11-03T02:00:00Z",
            }
        )
        cd_jobs = answers["run-jobs 2002"]["jobs"]
        for index in range(7):
            cd_jobs.append(
                {
                    **cd_jobs[0],
                    "id": 2 + index,
                    "name": f"one-more-{index}",
                    "completed_at": "2026-11-05T02:00:00Z",
                }
            )
        saved = self.checkout.parent / "answers.json"
        saved.write_text(json.dumps(answers))
        return saved

    def run_in_checkout(self, command: list[str], answers: Path | None = None):
        """What the release's job gives a step, the host's answers saved rather than asked."""
        environment = {
            **os.environ,
            "PATH": f"{ROOT / 'node_modules/.bin'}{os.pathsep}{os.environ['PATH']}",
            "ONEVCS": str(HERE / "fixtures/replay-onevcs"),
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_EVENT_NAME": "release",
            "GITHUB_REF_TYPE": "tag",
            "GITHUB_REF_NAME": "v0.0.1",
            "GITHUB_RUN_ID": "2002",
        }
        environment.pop("RUNNER_TEMP", None)
        environment.pop("GITHUB_EVENT_PATH", None)
        if answers is not None:
            environment["REPLAY_HOST_ANSWERS"] = str(answers)
        return subprocess.run(
            command,
            cwd=self.checkout,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_the_publish_jobs_step_still_selects_and_fails_every_recorded_over_figure(
        self,
    ):
        (self.checkout / "crates/privateterms").mkdir(parents=True)
        (self.checkout / "crates/privateterms/Cargo.toml").write_text("[package]\n")
        self.git("add", ".")
        answers = self.over_every_line(self.commit("a change the crate publishes"))
        release = yaml.safe_load(
            (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        )
        step = next(
            step
            for step in release["jobs"]["publish"]["steps"]
            if step.get("name") == "Report the release-tail budgets"
        )
        # The step's own text, with --json added so each verdict can be read.
        done = self.run_in_checkout(["bash", "-c", f"{step['run']} --json"], answers)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        results = {
            result["id"]: result for result in json.loads(done.stdout)["results"]
        }
        self.assertEqual(set(results), RELEASE_TAIL)
        for budget, result in results.items():
            self.assertEqual(result["verdict"], "over", (budget, result))

    def test_a_merge_outside_the_published_paths_is_left_out_of_the_cycle_time(self):
        answers = self.over_every_line(self.commit("a change nothing publishes"))
        done = self.run_in_checkout(
            [
                "onebudgetspec",
                "check",
                "budgets.yaml",
                "--id",
                "privateterms-release-cycle-time",
            ],
            answers,
        )
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn(
            "carries no pull request that changes a published path",
            done.stdout + done.stderr,
        )

    def test_the_gate_still_warns_on_a_recorded_over_figure_and_passes(self):
        (self.checkout / ".gate-time.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "invocation": "recorded",
                    "started_at": "2026-11-07T00:00:00Z",
                    "ended_at": "2026-11-07T01:00:00Z",
                    "exit": 0,
                }
            )
        )
        done = self.run_in_checkout(["bash", "scripts/gate-time.sh", "--check"])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(
            f"warning: {GATE_TIME} is over its budget", done.stdout + done.stderr
        )
        self.assertIn("3600", done.stdout + done.stderr)


class RecordedJob(Journey):
    """One complete job at the budget's workload, for `report-job:budgets` to read."""

    def test_record_a_complete_job(self):
        heads = [self.repository.commit(f"base {index}") for index in range(COMMITS)]
        self.base_sha = heads[-1]
        self.repository.git("checkout", "--quiet", "-b", "feature")
        merged_head = self.repository.commit("the merged change")
        self.host.head = merged_head
        sample = self.run_job(
            "pull_request",
            merged_head,
            run_id=400,
            base_ref="main",
            register=False,
            event=harness.event_pull_request(1, merged_head, heads[-1]),
        )
        self.assertEqual(sample.exit_code, 0, sample.stdout)

        run = sample.saved("budget-run.json")
        runs = [
            {**run, "head_sha": head, "run_id": str(500 + index), "attempt": 1}
            for index, head in enumerate(heads)
        ]
        history = {
            "schema_version": 1,
            "repository": harness.REPOSITORY,
            "base_ref": "main",
            "runs": runs,
        }
        self.host.add_run(519, heads[-1], minute=519)
        self.host.attach(
            519, "budget-results", zipped("rolling-history.json", json.dumps(history))
        )
        self.host.add_run(
            400, merged_head, event="pull_request", branch="feature", minute=1
        )
        self.host.merge_pull_request(heads[-1], merged_head)

        head = self.repository.commit("change")
        self.host.head = head
        recorded = []
        for options in (
            {
                "event_name": "pull_request",
                "sha": head,
                "run_id": 601,
                "base_ref": "main",
                "register": False,
                "event": harness.event_pull_request(1, head, heads[-1]),
            },
            {
                "event_name": "push",
                "sha": heads[-1],
                "run_id": 602,
                "attempt": 2,
                "register": False,
            },
        ):
            self.host.clear_requests()
            # One retried rate limit: the design total holds retries too.
            self.host.refuse.append(
                {"path": r"artifacts\?", "status": 429, "times": 1, "retry_after": 1}
            )
            job = self.run_job(**options)
            self.assertEqual(job.exit_code, 0, job.stdout)
            self.assertEqual(len(job.saved("budget-run.json")["catalog"]), CATALOG_ROWS)
            self.assertEqual(set(job.rows()), {OWN_BUDGET, *CI_TIME_PAIR})
            self.assertEqual(job.saved("budget-run.json")["unavailable"], [])
            self.assertEqual(job.outcomes["final-upload"], "success", job.stdout)
            telemetry = job.saved("report-job.json")
            reads = self.host.count("")
            self.assertEqual(
                telemetry["metrics"]["report-github-api-requests-per-run"]["value"],
                reads,
                f"the job and the host disagree: {self.host.requests}",
            )
            print(
                f"{options['event_name']}: {telemetry['metrics']['report-command-seconds']['value']:.1f}s, "
                f"{reads} GitHub API requests against the {DESIGN_REQUESTS}-request design total"
            )
            recorded.append((telemetry, reads, job))
        self.assertEqual(
            self.host.count(r"commits/[^/]+/pulls"), 1, "the push read its merged run"
        )

        slowest = max(
            recorded,
            key=lambda each: each[0]["metrics"]["report-command-seconds"]["value"],
        )
        shutil.rmtree(TELEMETRY, ignore_errors=True)
        (TELEMETRY / "tools").mkdir(parents=True)
        (TELEMETRY / "report-job.json").write_text(json.dumps(slowest[0]))
        (TELEMETRY / "rest-requests.json").write_text(
            json.dumps(
                {
                    "requests_per_job": max(each[1] for each in recorded),
                    "design_total": DESIGN_REQUESTS,
                }
            )
        )
        driver = (
            slowest[2].temp / "onebudgetspec-action/tools/onebudgetspec-github-action"
        )
        shutil.copy2(driver, TELEMETRY / "tools")


if __name__ == "__main__":
    unittest.main(verbosity=1)
