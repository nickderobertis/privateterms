#!/usr/bin/env bash
# Build and run the consumer in e2e/consumer against the crate exactly as a dependent
# gets it, then exit 0 — or print the failing step's output and exit 1.
#
#   usage: package-smoke.sh packaged            # the `.crate` `cargo package` builds here
#          package-smoke.sh published <version> # that version, from crates.io
#
# `packaged` proves the published file list builds and works (cargo package compiles the
# extracted crate on its own, then the consumer uses it); `published` proves the release
# a registry serves is the one that works. Output is quiet on success.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-}"
work="$(mktemp -d "${TMPDIR:-/tmp}/privateterms-smoke.XXXXXXXX")"
trap 'rm -rf "$work"' EXIT
log="$work/log"

fail() {
  printf 'package-smoke: %s\n' "$1" >&2
  [ -s "$log" ] && tail -n 60 "$log" >&2
  printf 'package-smoke: next: %s\n' "$2" >&2
  exit 1
}

case "$mode" in
  packaged)
    (cd "$ROOT" && cargo package -p privateterms --locked --quiet --allow-dirty) >"$log" 2>&1 \
      || fail "cargo package could not build the packaged crate" \
        "fix what the packaged build reports above (a file missing from Cargo.toml's include list, most often)"
    version="$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' "$ROOT/crates/privateterms/Cargo.toml" | head -n 1)"
    crate="$ROOT/target/package/privateterms-$version.crate"
    [ -f "$crate" ] || fail "cargo package wrote no $crate" "re-run; check the target directory"
    tar -xzf "$crate" -C "$work"
    extracted="$work/privateterms-$version"
    # On Windows (Git Bash) the manifest is read by a native cargo, which needs the
    # drive-letter spelling of the path rather than the shell's.
    if command -v cygpath >/dev/null 2>&1; then
      extracted="$(cygpath -m "$extracted")"
    fi
    dependency="{ path = \"$extracted\" }"
    ;;
  published)
    version="${2:-}"
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$ ]] \
      || fail "a published smoke needs a version, got '${version}'" "pass the released version, e.g. 0.1.0"
    dependency="\"=$version\""
    ;;
  *)
    fail "unknown mode '${mode}'" "run 'package-smoke.sh packaged' or 'package-smoke.sh published <version>'"
    ;;
esac

consumer="$work/consumer"
mkdir -p "$consumer/src"
cp "$ROOT/e2e/consumer/src/main.rs" "$consumer/src/main.rs"
sed "s|@DEPENDENCY@|$dependency|" "$ROOT/e2e/consumer/Cargo.toml.in" >"$consumer/Cargo.toml"
(cd "$consumer" && CARGO_TARGET_DIR="$ROOT/target/consumer-smoke" cargo run --quiet) >"$log" 2>&1 \
  || fail "the consumer did not build or its journey failed against the $mode crate" \
    "read the consumer's output above; e2e/consumer/src/main.rs is the journey"
