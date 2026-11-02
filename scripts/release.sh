#!/usr/bin/env bash
# One phase of one job of .github/workflows/release.yml:
#
#   usage: release.sh <job> <phase> --tag v<version>
#
# This repository publishes one platform-independent artifact, the `privateterms` crate
# (release-targets.toml). So each `build-<platform>` job proves the crate on its own
# platform — `build` packages it and runs the consumer journey against the packaged
# crate there — and has nothing of its own to publish or verify; the `publish` job
# publishes the crate once and verifies it from crates.io:
#
#   publish available  nothing per-platform is published, so nothing to wait for
#   publish build      cargo package (the packaged crate builds on its own)
#   publish publish    cargo publish, skipped when crates.io already serves this version
#   publish verify     wait until crates.io serves it, then run the consumer against it
#
# Idempotent: a re-run after a partial failure skips a version already published.
# Quiet on success; a failure names the step and what to do.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
job="${1:-}"
phase="${2:-}"
shift 2 || true
tag=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) tag="${2:-}"; shift 2 ;;
    *) printf 'release: unknown argument %s\n' "$1" >&2; exit 2 ;;
  esac
done

fail() {
  printf 'release: %s\n' "$1" >&2
  printf 'release: next: %s\n' "$2" >&2
  exit 1
}

[[ "$tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?)$ ]] \
  || fail "'--tag ${tag}' is not a release tag v<semver>" "pass the tag the GitHub Release names"
version="${BASH_REMATCH[1]}"
manifest_version="$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' "$ROOT/crates/privateterms/Cargo.toml" | head -n 1)"
[ "$manifest_version" = "$version" ] || fail \
  "the tag says $version but crates/privateterms/Cargo.toml says $manifest_version" \
  "release only from the commit release-plz tagged"

served() { bash "$ROOT/scripts/release-probe.sh" crate:privateterms; }

case "$job:$phase" in
  build-linux:build | build-linux-arm64:build | build-macos:build | build-windows:build)
    bash "$ROOT/scripts/package-smoke.sh" packaged
    ;;
  build-linux:publish | build-linux-arm64:publish | build-macos:publish | build-windows:publish \
    | build-linux:verify | build-linux-arm64:verify | build-macos:verify | build-windows:verify \
    | publish:available)
    # The crate is platform-independent and published once, by the publish job.
    ;;
  publish:build)
    (cd "$ROOT" && cargo package -p privateterms --locked --quiet) \
      || fail "the crate does not package" "fix what cargo package reports above"
    ;;
  publish:publish)
    current="$(served)" || fail "crates.io could not be asked what it serves" "re-run the job once crates.io answers"
    if [ "$current" = "$version" ]; then
      exit 0
    fi
    [ -n "${CARGO_REGISTRY_TOKEN:-}" ] || fail "CARGO_REGISTRY_TOKEN is not set" \
      "add the CARGO_REGISTRY_TOKEN repository secret, then re-run the job"
    (cd "$ROOT" && cargo publish -p privateterms --locked --quiet) \
      || fail "cargo publish failed for $version" "read cargo's error above; a re-run skips a version already published"
    ;;
  publish:verify)
    for _ in $(seq 1 30); do
      current="$(served || true)"
      [ "$current" = "$version" ] && break
      sleep 20
    done
    [ "$current" = "$version" ] || fail "crates.io does not serve $version after ten minutes" \
      "check https://crates.io/crates/privateterms, then re-run the job"
    # The index lags the API: retry the consumer build briefly before calling it a failure.
    for attempt in 1 2 3 4 5; do
      bash "$ROOT/scripts/package-smoke.sh" published "$version" && exit 0
      [ "$attempt" -lt 5 ] && sleep 30
    done
    fail "the consumer journey fails against the published $version" "read its output above"
    ;;
  *)
    printf 'release: no phase %s of job %s\n' "$phase" "$job" >&2
    printf 'release: next: use a job of release.yml (build-linux, build-linux-arm64, build-macos, build-windows, publish) and a phase (build, publish, verify, available)\n' >&2
    exit 2
    ;;
esac
