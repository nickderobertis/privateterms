# AGENTS.md

Durable instructions for humans and agents working in this repo. `CLAUDE.md` is a
symlink to this file; edit `AGENTS.md` only. Keep it terse: it is always-loaded context.

## What this repo is

The open **private-terms specification** (`spec/private-terms.md`, Specification 1), its
language-neutral **conformance suite** (`conformance/`), and the Rust SDK crate
**`privateterms`** (`crates/privateterms`) that implements it and is published to
crates.io. onevcs and onetaskgraph consume the crate to detect, replace and reject
private terms identically.

## Highly important constraints

- **The specification is storage-independent.** It defines the data model, matching and
  outcomes, and never a file name, file format, directory layout or parsing rule. TOML
  and YAML appear in it only as marked illustrations. File names, encodings and level
  discovery are the crate's bindings, documented in its rustdoc and README.
- **Every rule cites its cases and every case cites its rules.** A spec rule is
  `**[RULE-ID]**` followed by a `Cases:` line; a case lists `exercises`. The crate's
  conformance test reconciles both ways — change them together.
- **Contract 0 is a shared interface.** The crate's public API (pinned by
  `crates/privateterms/tests/contract_api.rs`) and the serialization of its types are
  what consumers build on; never change them unilaterally.
- **Matching stays byte-for-byte with onevcs v0.57.6**, whose own outcomes the
  conformance suite holds.
- **Every example and fixture name is invented**: this is a public repository.

## Two standing goals on every task

1. **Engineer the context for next time**: realistic tests through the public API,
   scripts that shrink output to signal, terse notes here for what the code does not
   make obvious.
2. **Engineer the codebase and environment**: keep `just bootstrap` working from a clean
   clone and the gate strict, local and CI running the same recipes.

## Stack and composition

- **Product shape:** library
- **Language(s):** rust
- **References composed:** base.md, project-graph.md, shapes/library.md, languages/rust.md, ci.md, llmlint.md, releasing.md, tools/onebudgetspec.md
  (`compose_repo_plan.py --shape library --language rust --releasing`, then `--wiring .`
  and `--ci-cd . --language rust --name privateterms`, create-repo v1.54.0).
- **Projects in the graph:** `privateterms` (the crate: format, lint, test, build),
  `conformance` and `spec` (`type:contract`, depending on nothing; the crate depends on
  both, so a case or rule change reruns its tests), `consumer` (`e2e/consumer`, the e2e
  tier: the packaged crate built and driven as a dependent gets it), and `workspace`
  (the root: the dependency-ban fixture and the project-boundary check), plus
  `github-workflows` (`.github/workflows`: ci.yml's job selection and its contract with the
  released action) and `report-job` (`.github/reporting`: the budgets job, driven through the
  released action, its budget and fixtures). Those two are `type:budgets`, run Linux-only
  through `uv` (`just ci-test`), and fetch the pinned release into `target/report-job`.
  `scripts/check-project-boundaries.mjs` enforces the tags.
- **Excluded, and why:** asdf/`.tool-versions` and direnv — rustup's
  `rust-toolchain.toml` pins the toolchain and nothing else needs a version manager; a
  separate repo-level `coverage` target — the one crate's `test` target measures and
  enforces the 95% line bar itself (`scripts/crate-test.sh`), as there is no second
  crate's profile to combine; per-platform release archives — the one artifact is a
  platform-independent crate, so each `build-<platform>` release job proves the packaged
  crate on its platform and `publish` publishes it once; a bench tier — no hot path has
  a performance requirement yet; `msrv` in a `clippy.toml` — clippy reads Cargo.toml's
  `rust-version` itself, so the MSRV keeps one source.

## Command surface

Use the `just` recipes (`just --list`); each delegates to Nx. `just check` is the
deterministic gate (affected tier; `just check all` sweeps), `just gate` adds the supply
chain and times it. `just lint-llm-diff` is the judged tier, out of `check`.
`just deny-bans` is the dependency-ban check `check` and CI's required `lint` job run.

## Commits, releases, and merging

- **Squash-merge only, via PR, with auto-merge**; head branches auto-delete; admins may
  override. The PR title (Conventional Commits, linted in CI) becomes the squash subject
  and the PR body (`.github/pull_request_template.md`: What, Why) its body.
- **Required checks** are exactly those in `.github/governance.json`: `lint` (format,
  lint, the supply chain with the dependency bans, the PR title and llmlint),
  `test-linux`, `test-windows`, `test-macos` and `budgets`; branches need not be up to
  date. The declaration leads: branch protection gains `budgets` only after the job lands.
- **No broader-tier sweep runs in CI**: the composed CI/CD shape gates each pull request
  at the affected tier, and a push to main runs only `budgets`, saving the merged pull
  request's figures as the history pull requests compare with; the release re-gates nothing.
- **Releases**: release-plz on every push to main opens the release PR (version,
  CHANGELOG.md) and arms auto-merge on it; when it merges, release-plz tags `v<version>`
  and cuts the GitHub Release, which runs `release.yml`: each `build-<platform>` job
  packages the crate and runs the consumer against it, and `publish` publishes to
  crates.io (skipping a version already served) and verifies it from the registry.
  Nobody hand-edits a version, tags or dispatches a publish. Pre-1.0 regime: `feat` is a
  minor bump, `fix` a patch, a breaking change a minor; the first release is 0.1.0.

## Invariants (non-negotiable)

- The gate is strict: no warnings-only mode. A diagnostic is an error or a suppression
  at its site with a stated reason.
- Tests drive the public API and real files and directories; never mock the layer under
  test. Proof is proportionate to the change per the
  [create-repo base rules](https://github.com/nickderobertis/dero-skills/blob/main/skills/bootstrap/create-repo/assets/llmlint/base.llmlint.yml).
- 95% line coverage on the crate.
- Validate every external input at its boundary; refuse a declaration whole.
- Secrets live in the repository's secret store (`gh-secrets.json` names them).

## Tests are context engineering

- The conformance suite is the matching contract; add a case for every rule change, and
  a crate test for every binding change.
- A cost figure is a budget, never a test assertion; a wall-clock bound never tells two
  behaviours apart.

## Keeping the allowlist current

When a routine command joins the workflow, add it to `.claude/settings.json` rather than
re-approving it; keep the list narrow.

## Budget reports

Approved budget thresholds alone decide failures: the required `budgets` check goes
red only on an ordinary budget verdict, and the budget stays the requirement. CI
artifacts retain the base branch's recent measurements for informational comparison,
and each report states their provenance, retention and coverage. A stored measurement
is never a line to hold.

1. When a performance problem appears that a failing budget check does not already identify (for example a CI timeout), read the PR report first through `onevcs change comments` or the host PR view. If the failing check already identifies it, skip the duplicate read. Read earlier PR comments and job results when several changes may contribute.
2. Never time base versus branch on a shared host. Profile to investigate, and use CI comparisons through the repository's existing publication path.
3. When reading a report or seeing a failing budget check, fix the regression as part of the work. For an adverse change of at least one standard deviation shown in a report being read (a `max` budget rising, a `min` budget falling), make the change cheaper or make room in existing code, profiling to find where. Improvements show numbers without flags, in a row's history too, and are no reason to optimize further, and other figures need no work. Informational flags do not fail a check or start other work.
4. Stay inside existing budgets. Make room for new tests and code by speeding up existing work; never raise limits or timeouts.
5. Suspect the current change first when something degrades, before intermittent slowness or the outside world.
