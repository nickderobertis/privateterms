#!/usr/bin/env bash
# The crate's test target: every unit, integration and conformance test under coverage,
# failing below 95% line coverage, then the doctests (which llvm-cov measures only on
# nightly). Quiet on success; on failure, the run's output and what to do.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
log="$(mktemp "${TMPDIR:-/tmp}/crate-test.XXXXXXXX")"
trap 'rm -f "$log"' EXIT
if ! cargo llvm-cov nextest -p privateterms --locked --fail-under-lines 95 --summary-only \
  --status-level fail --final-status-level fail >"$log" 2>&1; then
  cat "$log" >&2
  echo "crate-test: the tests failed or line coverage fell below 95% (the table above)" >&2
  echo "crate-test: next: fix the failing test, or cover the new lines with a test that drives the public API" >&2
  exit 1
fi
if ! cargo test -p privateterms --doc --locked >"$log" 2>&1; then
  cat "$log" >&2
  echo "crate-test: a doctest failed (above); the README's examples are doctests too" >&2
  exit 1
fi
# DEMONSTRATION ONLY, never lands: the startup timing harness and this runner's processor.
case "$(uname -s)" in
  Linux) cpu="$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2-)" ;;
  Darwin) cpu="$(sysctl -n machdep.cpu.brand_string)" ;;
  *) cpu="$(powershell -NoProfile -Command '(Get-CimInstance Win32_Processor).Name')" ;;
esac
echo "STARTUP-TIMING-CPU ${cpu}"
cargo run -q --release --locked -p privateterms --example startup_timing
