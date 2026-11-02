# Conformance suite — Specification 1

The executable form of [`spec/private-terms.md`](../spec/private-terms.md). Every case is
stated in the specification's data model, so an implementation in any language can run
the suite. The cases are encoded as JSON files here; that encoding is a detail of this
suite, not a storage format the specification requires — an implementation reads them
however it likes and feeds the model values to its own API.

## Case layout

`cases/*.json` each hold one object: `description` (prose) and `cases`, a list. Each case:

| Member | Required | Meaning |
|---|---|---|
| `id` | yes | Unique across the suite. |
| `exercises` | yes | The specification rules (`DECL-…`, `LEVEL-…`, `MATCH-…`, `OUT-…`, `LOC-…`) the case exercises. |
| `operation` | yes | `validate`, `resolve`, `detect`, `replace` or `screen-locators`. |
| `description`, `source`, `note` | no | Prose; `source` names where a seeded case came from. |
| `levels` | no | The ordered level list, nearest first (default empty). |
| `rules` | no | The repository's own derived rules (default empty), each `{term, mode, case_sensitive}` with `mode` one of `substring`, `whole-word`, `owner-name-only`. |
| `caller` | no | The caller list: replacement entries, `{term, with}` or `{term, reject: true}`. |
| `text` | `detect`, `replace` | The input text. |
| `locators` | `screen-locators` | The locators, in emission order, each `{kind, value}`. |
| `first_ordinal` | no | The ordinal the first redacted locator takes (default 1). |
| `expect` | yes | The expected outcome (below). |

A level is `{kind, declaration}` — `kind` is `repository`, `directory` or `fallback`, and
`declaration` is a model value (a declaration's members, as the specification names
them) — or `{kind, unreadable: true}`, a level whose declaration could not be read. A
level may carry `location`, a string: levels with one `location` are at one distance
(LEVEL-ONE-DISTANCE); a level without one is at a distance of its own.

## Running a case

1. **Levels.** Validate each level's declaration for its kind (DECL-INVALID). An
   unreadable level, or an invalid one, makes the check unavailable; its error kind is
   `unreadable` or the declaration's error kind.
2. **`validate`** stops here: the outcome is `valid` or `declaration-error`.
3. **Resolve** the case's `rules` (origin: derived), its levels and its caller list
   (section 2). A resolution error (`exception-names-no-term`) makes the check
   unavailable. **`resolve`** stops here with the resolved rules, in order.
4. **Match**: compile one matcher over the resolved rules and the phrases of every level,
   nearest first, and run `detect`, `replace` (checking every replacement string first,
   OUT-REPLACEMENT-CARRIES) or `screen-locators` on it. An unavailable check skips the
   matcher: `detect`, `replace` and `resolve` answer `unavailable`, and
   `screen-locators` redacts every locator (LOC-UNAVAILABLE).

## Expected outcomes

`expect.outcome` is always present. A runner compares every member `expect` states and
ignores any it does not state; `found` and `remaining` are sets (order-free), every other
member is compared exactly. Spans are `[start, end]` byte offsets into the UTF-8
encoding of the case's `text`.

| `outcome` | Other members |
|---|---|
| `valid` | — |
| `declaration-error` | `error`: the error kind (DECL-INVALID's names). |
| `unavailable` | `error`: the kind that made the check unavailable. |
| `resolved` | `rules`: each `{term, mode, case_sensitive, action}`, `action` being `"reject"` or `{"replace": "…"}`. |
| `clean`, `detected` | `found`: the terms of the rules found; `hits`: each `{term, span, text}` in hit order (MATCH-HITS), `text` the original text at the span; `exempted`: the exempted count. |
| `replaced` | `text`: the result; `replaced`: how many spans were rewritten. |
| `refused` | `refusal`: `term-remains`; `remaining`: the terms the result still carries; `text`: the rewritten text that was refused. |
| `error` | `error`: `replacement-carries-term`. |
| `screened` | `locators`: each a string (passed) or `{"redacted": true, "kind", "ordinal"}`; `unfixable`: whether any was redacted; `reason`: `identifier carries a private term` when unfixable, otherwise `null`. |

## Reporting

A runner reports one result per case: its `id`, pass or fail, and on a failure the first
member that differed, with the expected and actual values. A run passes only when every
case passes; a case a runner cannot run is a failure, never a skip. The reference runner
is [`crates/privateterms/tests/conformance.rs`](../crates/privateterms/tests/conformance.rs),
which also reconciles every case's `exercises` with the specification's `Cases:` lines.

## Provenance

`onevcs-v0.57.6-matcher.json` reproduces every matcher case of onevcs's tests and
contract at the immutable tag `v0.57.6` — `crates/onevcs/src/boundary/matcher.rs` and the
tests exercising it, and every example of the contract's *Host public phrases* section —
each with the `found` set and exempted count onevcs's own `TermMatcher` returns at that
tag. `onevcs-v0.57.6-phrases.json` restates onevcs's public-phrase file tests
(`phrases.rs`) in the model, its version-1 phrase file being a version-2 declaration's
`phrases`. Three kinds of those tests are about that file's own storage rather than the
model, so they are not conformance cases: a document that does not parse as YAML and one
that is not UTF-8 are the reference crate's binding tests, and the file's required
`phrases` key is a rule of that file alone — in the model every member but the version is
optional. The other case files hold the cases this specification's own rules define.
