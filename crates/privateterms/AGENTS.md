# crates/privateterms

- **YAML only through serde-saphyr, under `src/yaml/options.rs`.** That one options
  function is the only reader configuration; `tests/yaml_hardening.rs` holds every read
  to it. Never add another YAML crate: `deny.toml` bans the libyaml family.
- **No error discloses a term.** An error names the problem, the member and the entry
  number only; a path lives in its own field, never in `Display` or `Debug`
  (`tests/privacy.rs` searches every rendering).
- **The storage bindings are this crate's, not the specification's.** File names,
  encodings and discovery are documented in rustdoc and `README.md` (both doctested) and
  tested in `tests/bindings.rs` — never as conformance cases.
