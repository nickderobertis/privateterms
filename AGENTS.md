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
- **Matching stays byte-for-byte with onevcs v0.57.6.** `conformance/cases/onevcs-v0.57.6-*.json`
  hold onevcs's own outcomes at that tag; a case there is never edited to fit the crate.
- **No error discloses a term.** Errors name the problem only; a path is a separate
  field printed only as a screened locator.
- **YAML only through serde-saphyr, under `src/yaml/options.rs`.** `deny.toml` bans the
  libyaml crates (RUSTSEC-2024-0449).
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
  (the root: the dependency-ban fixture and the project-boundary check).
  `scripts/check-project-boundaries.mjs` enforces the tags.
- **Excluded, and why:** asdf/`.tool-versions` and direnv — rustup's
  `rust-toolchain.toml` pins the toolchain and nothing else needs a version manager; a
  separate repo-level `coverage` target — the one crate's `test` target measures and
  enforces the 95% line bar itself (`scripts/crate-test.sh`), as there is no second
  crate's profile to combine; per-platform release archives — the one artifact is a
  platform-independent crate, so each `build-<platform>` release job proves the packaged
  crate on its platform and `publish` publishes it once; a bench tier — no hot path has
  a performance requirement yet.

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
  lint, the supply chain with the dependency bans, the PR title and llmlint) and
  `test-linux`, `test-windows`, `test-macos`; branches need not be up to date.
- **No broader-tier sweep runs in CI**: the composed CI/CD shape gates each pull request
  at the affected tier and runs no CI on push to main; the release re-gates nothing.
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
