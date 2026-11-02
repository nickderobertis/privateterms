#!/usr/bin/env bash
# Prove deny.toml's bans refuse what they say they refuse. For each banned YAML crate,
# a scratch workspace depending on this repository's crate *and* that one crate is
# checked with `cargo deny check bans` under this repository's deny.toml, which must
# fail naming it; and this repository's own graph must pass. Quiet on success. Needs
# crates.io reachable (cargo resolves each scratch graph) and cargo-deny on PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
banned=(serde_yaml serde_yaml_ng serde_norway serde_yml unsafe-libyaml unsafe-libyaml-norway libyml)

command -v cargo-deny >/dev/null 2>&1 || {
  echo "check-deny-bans: cargo-deny is not installed" >&2
  echo "check-deny-bans: next: cargo install --locked cargo-deny (CI's lint job installs it)" >&2
  exit 1
}
for crate in "${banned[@]}"; do
  grep -q "{ crate = \"$crate\", reason = \"RUSTSEC-2024-0449" "$ROOT/deny.toml" || {
    echo "check-deny-bans: deny.toml does not ban $crate with a RUSTSEC-2024-0449 reason" >&2
    echo "check-deny-bans: next: restore its [bans] deny entry" >&2
    exit 1
  }
done

work="$(mktemp -d "${TMPDIR:-/tmp}/deny-bans.XXXXXXXX")"
trap 'rm -rf "$work"' EXIT
for crate in "${banned[@]}"; do
  dir="$work/$crate"
  mkdir -p "$dir/src"
  : >"$dir/src/lib.rs"
  cat >"$dir/Cargo.toml" <<TOML
[package]
name = "deny-fixture"
version = "0.0.0"
edition = "2021"
publish = false
license = "MIT"

[workspace]

[dependencies]
privateterms = { path = "$ROOT/crates/privateterms", version = "*" }
$crate = "*"
TOML
  # A wildcard requirement is itself refused (deny.toml's `wildcards = "deny"`), so both
  # requirements are pinned to what resolves before the bans are checked.
  if ! (cd "$dir" && cargo generate-lockfile --quiet) >"$dir/log" 2>&1; then
    cat "$dir/log" >&2
    echo "check-deny-bans: could not resolve a graph adding $crate (above)" >&2
    echo "check-deny-bans: next: re-run with crates.io reachable" >&2
    exit 1
  fi
  version="$(cd "$dir" && cargo pkgid "$crate" 2>/dev/null | sed 's/.*[@#]//')"
  own="$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' "$ROOT/crates/privateterms/Cargo.toml" | head -n 1)"
  sed -i.bak -e "s/^$crate = \"\\*\"/$crate = \"=$version\"/" -e "s/version = \"\\*\" }/version = \"=$own\" }/" "$dir/Cargo.toml"
  if (cd "$dir" && cargo deny --manifest-path Cargo.toml check --config "$ROOT/deny.toml" bans) >"$dir/log" 2>&1; then
    echo "check-deny-bans: a graph adding $crate passed cargo deny check bans" >&2
    echo "check-deny-bans: next: restore deny.toml's [bans] deny entry for $crate" >&2
    exit 1
  fi
  grep -q "error\[banned\]: crate '$crate = " "$dir/log" || {
    cat "$dir/log" >&2
    echo "check-deny-bans: the refusal of a graph adding $crate does not name it (above)" >&2
    exit 1
  }
done
(cd "$ROOT" && cargo deny check bans) >"$work/own.log" 2>&1 || {
  cat "$work/own.log" >&2
  echo "check-deny-bans: this repository's own graph fails the bans (above)" >&2
  exit 1
}
