"""The budgets job, driven through ci.yml's real `uses:` and `with:`.

Each journey runs what the job pins: action.yml's own steps, the released driver and plugin archive,
the published core wheel, the real `gh` and the real `actions/upload-artifact` code, over a copy of
this repository's tree. Only GitHub's services, the release host and the package index are doubled,
by the harness the action ships at that same tag. `test_record_a_complete_job` saves the job's
telemetry for `privateterms-budget-report-command-seconds` and its full REST figure.
"""

import json
import os
import shutil
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
FIGURES_NEED_ONEVCS = "onevcs is not on PATH"
# The rows a runner cannot measure, each with its command's own words.
PRODUCTION_UNAVAILABLE = {
    "privateterms-ci-check-time": FIGURES_NEED_ONEVCS,
    "privateterms-cd-job-time": FIGURES_NEED_ONEVCS,
    "privateterms-release-cycle-time": FIGURES_NEED_ONEVCS,
    JOB_COUNT: FIGURES_NEED_ONEVCS,
    "privateterms-cd-job-count": FIGURES_NEED_ONEVCS,
    "privateterms-release-read-requests": FIGURES_NEED_ONEVCS,
    "privateterms-pr-read-requests": FIGURES_NEED_ONEVCS,
    "privateterms-gate-time": "Cannot find package '@onebudgetspec/sdk'",
}
# The workload of the budget's record: 100 rows and a rolling file of 20 commits. The scalars in
# that file are synthetic copies of one real run, since the spike held no typed scalar archive.
ROWS = 100
COMMITS = 20
COMMANDS_READING_REST = 12
DESIGN_REQUESTS = 20
TELEMETRY = HERE / ".telemetry"


def runner_path(directory: Path) -> str:
    """What a hosted runner gives a budget command: no uv, cargo, bun or onevcs."""
    directory.mkdir()
    (directory / "node").symlink_to(shutil.which("node"))
    return f"{directory}{os.pathsep}/usr/bin{os.pathsep}/bin"


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
        self.host = harness.Host()
        self.addCleanup(self.host.close)
        self.repository = harness.Repository()
        self.addCleanup(self.repository.close)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.counts = self.scratch / "counts"
        self.path = runner_path(self.scratch / "runner-bin")
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
            environment={
                "JOURNEY_COUNTS": str(self.counts),
                "PATH": self.path,
                # What a runner sets for every step, which the figures script reads.
                "GITHUB_REPOSITORY": harness.REPOSITORY,
                "GITHUB_RUN_ID": str(run_id),
                "RUNNER_NAME": "hosted-runner",
            },
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

    def executed(self) -> list[str]:
        return sorted(self.counts.read_text().split()) if self.counts.exists() else []

    def saved(self, job, name="budget-results") -> dict:
        return json.loads(
            self.host.artifact_files(job.run_id, name)["budget-run.json"].decode()
        )


class ProductionCatalog(Journey):
    """The real budgets files and commands, on what a real runner holds."""

    def production(self) -> set[str]:
        ids = set()
        for path in ("budgets.yaml", ".github/reporting/budgets.yaml"):
            document = yaml.safe_load((ROOT / path).read_text())
            ids |= {budget["id"] for budget in document["budgets"]}
        return ids

    def assert_no_figure_fakes_a_verdict(self, job):
        saved = self.saved(job)
        self.assertEqual(
            {result["id"] for result in saved["results"]["results"]}, {OWN_BUDGET}
        )
        reasons = {entry["id"]: entry["reason"] for entry in saved["unavailable"]}
        self.assertEqual(set(reasons), set(PRODUCTION_UNAVAILABLE))
        rows = job.rows()
        for budget, reason in PRODUCTION_UNAVAILABLE.items():
            self.assertIn(reason, reasons[budget])
            self.assertNotIn(
                "verdict", rows[budget], "an absent tool is never a verdict"
            )
            self.assertIn(reason, rows[budget]["unavailable"])
            row = one_row(job.markdown(), budget)
            self.assertIn("unavailable", row)
            self.assertIn("report-only", row)
        self.assertEqual(
            [
                row["id"]
                for row in job.saved("comparison-report.json")["rows"]
                if row.get("verdict") == "error"
            ],
            [],
        )

    def test_a_draft_touching_an_unrelated_path_reports_every_production_row(self):
        job = self.pull_request(draft=True)
        self.assertEqual(job.exit_code, 0, job.stdout)
        self.assertEqual(set(job.rows()), self.production())
        self.assert_no_figure_fakes_a_verdict(job)

        self.assertEqual(len(self.host.comments), 1)
        body = self.host.comments[0]["body"]
        for budget in self.production():
            one_row(body, budget)
        # The comment carries no breakdown: those stay in the artifact and the job's log.
        for detail in ("install_seconds", "phases", "profile", "per test"):
            self.assertNotIn(detail, body)
        self.assertEqual(
            self.host.count(r"/releases|/runs/\d+/jobs|/compare"),
            0,
            "figures cost no read here",
        )

        # The job judged itself after its main upload, and saved that verdict beside it.
        self.assertEqual(job.outcomes["main-upload"], "success", job.stdout)
        self.assertEqual(job.outcomes["final-upload"], "success", job.stdout)
        own = {
            result["id"]: result for result in self.saved(job)["results"]["results"]
        }[OWN_BUDGET]
        self.assertEqual(own["verdict"], "within")
        self.assertEqual(own["unit"], "seconds")
        main = self.saved(job, "budget-results-main")
        self.assertEqual(
            main["results"]["results"], [], "the main upload precedes the own verdict"
        )

    def test_a_base_push_saves_the_same_results_and_posts_nothing(self):
        pull = self.pull_request()
        self.host.clear_requests()
        posted = list(self.host.comments)
        base = self.base_push()
        self.assertEqual(base.exit_code, 0, base.stdout)
        self.assertEqual(self.host.comments, posted)
        self.assert_no_figure_fakes_a_verdict(base)
        base_files = self.host.artifact_files(base.run_id)
        pull_files = self.host.artifact_files(pull.run_id)
        self.assertEqual(set(base_files), set(pull_files))
        self.assertEqual(set(self.saved(base)), set(self.saved(pull)))
        # Only the own budget measures here, after the main upload, so no base run of this catalog
        # has a measurement to carry: its row stays without a baseline, with this reason.
        self.assertIn("no rolling file saved", base.markdown())

    def test_a_fork_gets_its_summary_and_artifact_with_no_comment_or_credential(self):
        self.assertEqual(self.base_push().exit_code, 0)
        self.host.clear_requests()
        job = self.pull_request(head_repository="someone/fork")
        self.assertEqual(job.exit_code, 0, job.stdout)
        self.assertEqual(self.host.comments, [])
        self.assertEqual(
            self.host.count("comments|graphql"), 0, "no comment is even read"
        )
        self.assertIn("someone/fork", job.summary)
        self.assertIsNotNone(self.host.artifact_files(job.run_id))
        self.assertEqual(set(job.rows()), self.production())

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
        own = {
            result["id"]: result for result in self.saved(job)["results"]["results"]
        }[OWN_BUDGET]
        self.assertEqual(own["verdict"], "over")
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


class RecordedJob(Journey):
    """One complete job at the budget's workload, for `report-job:budgets` to read."""

    def catalog(self):
        """Beside the production rows, reads and local commands up to the workload's row count."""
        write = 'echo "{\\"value\\": 1}" > "$ONEBUDGETSPEC_RESULT"'
        entries = []
        for index in range(COMMANDS_READING_REST):
            read = f"gh api repos/owner/repo/commits/{index} > /dev/null || exit 1; {write}"
            entries.append(
                (f"load-reads-rest-{index}", ["bash", "-c", read], {"unit": "requests"})
            )
        production = len(PRODUCTION_UNAVAILABLE) + 1
        while len(entries) < ROWS - production:
            entries.append(
                (f"load-local-{len(entries)}", ["bash", "-c", write], {"unit": "bytes"})
            )
        return harness.budgets_yaml(entries)

    def test_record_a_complete_job(self):
        self.repository.write("load/budgets.yaml", self.catalog())
        heads = [self.repository.commit(f"base {index}") for index in range(COMMITS)]
        self.base_sha = heads[-1]
        first = self.run_job("push", heads[-1], run_id=400, register=False)
        self.assertEqual(first.exit_code, 0, first.stdout)

        self.host.artifacts.clear()
        self.host.runs.clear()
        run = first.saved("budget-run.json")
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

        self.repository.git("checkout", "--quiet", "-b", "feature")
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
            self.assertEqual(len(job.rows()), ROWS)
            self.assertEqual(self.host.count("commits/"), COMMANDS_READING_REST)
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
                f"{reads} GitHub API requests ({COMMANDS_READING_REST} budget-command reads) "
                f"against the {DESIGN_REQUESTS}-request design total"
            )
            recorded.append((telemetry, reads, job))

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
