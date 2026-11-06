"""Which jobs ci.yml starts on which event, and its contract with the released action."""

import json
import re
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import released_action

ROOT = released_action.ROOT
PREDECESSORS = {"lint", "test-linux", "test-windows", "test-macos"}
REPORT_ONLY = ["release-tail", "host-variable"]
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
    "privateterms-release-cycle-time": [*FIGURES, "release-cycle-time"],
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
            carried,
            set(listed),
            "no root budget is enforced in this job or left unlisted",
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
            self.assertEqual(budget["labels"], wanted, key)

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


if __name__ == "__main__":
    unittest.main(verbosity=1)
