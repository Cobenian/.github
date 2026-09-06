#!/usr/bin/env bash
# A scan posture must never report clean from a scanner that could not look.
#
# WHY THIS FILE EXISTS. On imsearch/searchlink-assay run 33995805827, `mix deps.get` failed on
# a private Hex package and ten verification steps were skipped -- test, credo, sobelow,
# dialyzer, format, compile, hex.audit and deps.audit. The run still uploaded
# `cobenian-scan-posture` containing:
#
#     {"hex_audit": [], "gitleaks": {"secrets_found": 0}, "hex_outdated": []}
#
# A clean security posture from a run in which nothing was scanned. The step's own contract
# already said "a scanner that did not run or failed is OMITTED -- never fabricated as clean",
# so this was code diverging from its documented intent, which is the kind that survives review.
#
# TWO MECHANISMS, both reproduced below:
#
#   1. `jq -sc .` on empty input prints `[]` and NEVER null, so an awk parse that matched
#      nothing -- because the tool printed an error instead of a table -- is byte-identical to
#      one that matched nothing because there was nothing to find. The `|| echo null` fallback
#      never fires, because the pipeline SUCCEEDS.
#
#   2. `mix hex.audit` and `mix hex.outdated` exit 0 when they cannot run at all, so the
#      honest-empty branch fires for a scanner that did nothing.
#
# The `clean` case is the POSITIVE control and matters as much as the others: a fix that
# omitted everything would pass a test that only checked the failure, while destroying the
# ability to report a genuinely clean repository.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
t() {
  if [ "$2" = "$3" ]; then echo "  ok    $1"; else
    echo "  FAIL  $1 — expected '$2', got '$3'"; fails=$((fails+1)); fi
}

command -v jq >/dev/null || { echo "scan-posture-test: jq not installed — SKIPPED"; exit 0; }
python3 -c "import yaml" 2>/dev/null || { echo "scan-posture-test: pyyaml missing — SKIPPED"; exit 0; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

python3 - "$work" <<'PY'
import sys, yaml
d = yaml.safe_load(open(".github/workflows/elixir-ci.yml"))
for j in d["jobs"].values():
    for st in j.get("steps", []):
        if "scan posture" in (st.get("name") or "").lower() and "run" in st:
            open(sys.argv[1] + "/posture.sh", "w").write(st["run"])
            raise SystemExit(0)
raise SystemExit("no scan posture step found — this test has gone stale")
PY
[ -s "$work/posture.sh" ] || { echo "  FAIL  could not extract the posture step"; exit 1; }

# A `mix` that reproduces each shape the real one produces.
mkdir -p "$work/stub"
cat > "$work/stub/mix" <<'STUB'
#!/bin/bash
case "$1" in
  hex.audit)
    case "$MIXCASE" in
      clean)   exit 0 ;;
      found)   echo "Retired packages"; echo "  poison 3.1.0  (deprecated: use jason)"; exit 1 ;;
      broken)  echo "** (Mix) Unknown package fleet_auth in lockfile"; exit 1 ;;
    esac ;;
  hex.outdated)
    case "$MIXCASE" in
      clean)   exit 0 ;;
      found)   echo "Dependency  Current  Latest"
               echo "phoenix     1.8.12   1.8.13   Update possible"; exit 1 ;;
      broken)  echo "** (Mix) Unknown package fleet_auth in lockfile"; exit 1 ;;
    esac ;;
esac
exit 0
STUB
chmod +x "$work/stub/mix"

posture() { # $1 = MIXCASE, $2 = DEPS_OK ; prints "hex_audit|hex_outdated"
  ( cd "$work" && rm -rf .scan scan-posture.json && mkdir -p .scan
    env PROFILE=library SOBELOW_ROOT=. HEAD_SHA=abc GITLEAKS_VERSION=8.28.0 \
        GITHUB_SERVER_URL=https://github.com GITHUB_REPOSITORY=o/r GITHUB_RUN_ID=1 \
        MIXCASE="$1" DEPS_OK="$2" PATH="$work/stub:$PATH" \
        bash posture.sh >/dev/null 2>&1
    a=$(jq -c 'if has("hex_audit")    then .hex_audit    else "OMITTED" end' scan-posture.json 2>/dev/null)
    o=$(jq -c 'if has("hex_outdated") then .hex_outdated else "OMITTED" end' scan-posture.json 2>/dev/null)
    echo "$a|$o" )
}

echo "a scanner that could not look is omitted, not clean:"
# THE REGRESSION. Before the fix both of these printed `[]|[]`, so a broken run and a clean
# one were byte-identical in the artifact.
t "the tool errored — omitted"        '"OMITTED"|"OMITTED"' "$(posture broken true)"
t "no dependency tree — omitted"      '"OMITTED"|"OMITTED"' "$(posture clean false)"

echo "and a scanner that DID look still reports what it found:"
# THE POSITIVE CONTROL. A fix that omitted everything would pass the two cases above while
# destroying the ability to report a clean repository at all.
t "ran, found nothing — honest empty" '[]|[]'              "$(posture clean true)"
t "ran, found something — reported"   \
  '[{"package":"poison","version":"3.1.0","reason":"use jason)"}]|[{"package":"phoenix","current":"1.8.12","latest":"1.8.13"}]' \
  "$(posture found true)"

[ "$fails" -eq 0 ] && echo "scan-posture-test: all passed" || echo "scan-posture-test: $fails failed"
exit $((fails > 0))
