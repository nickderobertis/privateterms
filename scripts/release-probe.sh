#!/usr/bin/env bash
# What crates.io serves right now for one artifact this repository publishes.
#
#   usage: release-probe.sh <registry>:<name>
#
# Exactly three answers, and keeping the last two apart is the whole point:
#
#   * exit 0 with one line on stdout — the version the registry serves now;
#   * exit 0 with nothing on stdout — the registry has no release of it yet;
#   * a non-zero exit with the reason on stderr — not answered (exit 2 is a usage error).
#
# "Not answered" is never degraded into "not released": an empty answer is only ever
# the registry saying so — a 404, or a `max_stable_version` crates.io itself set to
# null — never a body this could not read or a tool it could not run. It answers only
# for the `[[target]]` ids of release-targets.toml, resolved from this script's own
# location. It runs `curl` and `python3`, needs no credential, makes one request with
# --max-time 25 and no retry.
set -euo pipefail

readonly USER_AGENT="privateterms-release-probe (+https://github.com/nickderobertis/privateterms)"

refuse() {
  printf 'release-probe: %s\n' "$1" >&2
  printf 'release-probe: next: %s\n' "$2" >&2
  exit "${3:-1}"
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)" || refuse \
  "could not reach the repository root from ${BASH_SOURCE[0]}" \
  "run this from a checkout of this repository, at scripts/release-probe.sh"
readonly DECLARATION="$ROOT/release-targets.toml"

[ $# -eq 1 ] || refuse "takes exactly one registry-qualified identifier, and was given $#" \
  "run 'scripts/release-probe.sh crate:privateterms'" 2
identifier="$1"

for tool in curl python3; do
  command -v "$tool" >/dev/null 2>&1 || refuse "$tool is not on PATH, so no registry can be read" \
    "install $tool, or put it on the PATH this probe is spawned with"
done
[ -r "$DECLARATION" ] || refuse "release-targets.toml is missing or unreadable" \
  "restore release-targets.toml from git; it is this repository's one declaration of what it releases"

# The declared targets, read with a real TOML parser rather than scanned.
python3 - "$identifier" "$DECLARATION" <<'PY' || refuse \
  "'$identifier' is not a release target this repository declares (the reason is above)" \
  "ask for one of the declared ids, or declare the target in release-targets.toml"
import sys
import tomllib

identifier, path = sys.argv[1], sys.argv[2]
with open(path, "rb") as handle:
    document = tomllib.load(handle)
ids = [t.get("id") for t in document.get("target", []) if isinstance(t, dict)]
if identifier not in ids:
    print("declared: " + ", ".join(str(i) for i in ids), file=sys.stderr)
    raise SystemExit(1)
PY

registry="${identifier%%:*}"
name="${identifier#*:}"
[ "$registry" = "crate" ] || refuse "'$identifier' names the registry '$registry', which this probe cannot read" \
  "declare the target under crate:, the one registry this repository publishes to"
case "$name" in
  "" | [!A-Za-z0-9]* | *[!A-Za-z0-9_-]*)
    refuse "'$identifier' has a name crates.io does not serve" "spell the crate name exactly" ;;
esac

body_file="$(mktemp "${TMPDIR:-/tmp}/release-probe.XXXXXXXX")" || refuse \
  "could not create a temporary file to read the registry into" \
  "check the temporary directory's permissions and free space, then re-ask"
trap 'rm -f "$body_file"' EXIT
url="https://crates.io/api/v1/crates/$name"
status=0
http_status="$(curl -q -sS --connect-timeout 10 --max-time 25 -A "$USER_AGENT" \
  -o "$body_file" -w '%{http_code}' -- "$url")" || status=$?
[ "$status" -eq 0 ] || refuse "curl exited $status reading $url, so no registry answered" \
  "re-ask once crates.io is reachable; nothing about a release has been established"
case "$http_status" in
  200) ;;
  404) exit 0 ;;
  *) refuse "crates.io answered $http_status for $identifier" \
    "re-ask once crates.io answers; nothing about a release has been established" ;;
esac

python3 - "$body_file" <<'PY' || refuse "crates.io answered 200 for $identifier without a readable crate.max_stable_version" \
  "re-ask once crates.io answers a document of the documented shape; nothing has been established"
import json
import re
import sys

with open(sys.argv[1], "rb") as handle:
    document = json.load(handle)
version = document["crate"]["max_stable_version"]
if version is None:
    raise SystemExit(0)  # crates.io itself says it serves no stable version
if not isinstance(version, str) or not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", version):
    raise SystemExit(1)
print(version)
PY
