# privateterms

An open specification and Rust SDK for declaring private terms and detecting or replacing
them in public text.

- **[Specification 1](spec/private-terms.md)** — the one normative statement: a
  storage-independent data model of declarations (terms, exceptions, replacements, public
  phrases) layered nearest first, how a text is matched against it, and the outcomes:
  detect, replace, reject, and check unavailable — including how a diagnostic's
  identifiers are screened.
- **[The conformance suite](conformance/)** — every rule of the specification as
  data-model cases any implementation, in any language, can run; its
  [README](conformance/README.md) states the runner contract.
- **[The `privateterms` crate](crates/privateterms/)** — the Rust implementation, with
  its own storage bindings (`private-terms.toml` / `.yaml` / `.yml` and level discovery),
  published to [crates.io](https://crates.io/crates/privateterms).

A private name can leak from any tool that writes in public. One versioned specification
with a conformance suite, and one crate implementing it, let every tool find a term the
same way wherever it is rejected or replaced.

## Development

`just bootstrap` from a clean clone (needs rustup and bun), then `just check` — the full
deterministic gate. `AGENTS.md` records how the repository is put together.

MIT licensed.
