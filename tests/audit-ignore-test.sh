#!/usr/bin/env bash
# The advisory ignore list acknowledges ONE assessed advisory at a time, and it expires.
#
# WHY THIS FILE EXISTS. On 2026-10-10 two Cloak advisories with no fixed release blocked
# every cobenian-panel PR, though Panel uses neither affected cipher. `.audit-ignore.yml`
# lets a repo say so for a bounded time without turning the audit off. The ways that can go
# wrong are all "greener than it should be", so most cases below are ones that MUST fail:
#
#   * an advisory nobody listed            -> the gate still fails
#   * an entry past its date               -> fails, naming the entry
#   * an entry further out than the cap    -> fails
#   * a malformed entry (typo'd key, wildcard id, no reason, impossible date) -> fails,
#     rather than being read as "ignore with no expiry"
#   * a retired package                    -> never ignorable, even if listed
#   * mix.exs `hex: [ignore_advisories:]`  -> refused: Hex honours it with no expiry
#
# and the positive controls: a listed, in-date advisory passes, and a stale entry only warns.
#
# The steps are extracted from elixir-ci.yml and run against a stubbed `mix`, as in
# scan-posture-test.sh, so this exercises the real shell rather than a copy of it.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
t() {
  if [ "$2" = "$3" ]; then echo "  ok    $1"; else
    echo "  FAIL  $1 — expected '$2', got '$3'"; fails=$((fails+1)); fi
}

for tool in jq yq git; do
  command -v "$tool" >/dev/null || { echo "audit-ignore-test: $tool not installed — FAILED (cannot test)"; exit 1; }
done
python3 -c "import yaml" 2>/dev/null || { echo "audit-ignore-test: pyyaml missing — FAILED (cannot test)"; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

python3 - "$work" <<'PY'
import sys, yaml
want = {
    "validate.sh": "Advisory ignore list (.audit-ignore.yml)",
    "hex.sh":      "hex.audit (retired packages + advisories)",
    "deps.sh":     "deps.audit (Hex CVEs)",
    "stale.sh":    "Advisory ignore list — stale entries (warning only)",
}
d = yaml.safe_load(open(".github/workflows/elixir-ci.yml"))
steps = {st.get("name"): st for j in d["jobs"].values() for st in j.get("steps", [])}
for out, name in want.items():
    st = steps.get(name)
    if not st or "run" not in st:
        raise SystemExit(f"no step named {name!r} — this test has gone stale")
    if "${{" in st["run"]:
        raise SystemExit(f"step {name!r} interpolates an expression into its script; pass it via env")
    open(sys.argv[1] + "/" + out, "w").write(st["run"])
# The harness below passes the ids to each step itself, so the YAML wiring that does it in
# CI is asserted here: a gate reading the wrong output ignores nothing (red) or the wrong
# thing, and no shell-level case could see it.
ids = "${{ steps.audit_ignores.outputs.ids }}"
wiring = [
    (want["validate.sh"], "id", None, "audit_ignores"),
    (want["hex.sh"],      "env", "HEX_IGNORE_ADVISORIES", ids),
    (want["deps.sh"],     "env", "IGNORE_IDS", ids),
    (want["stale.sh"],    "env", "IGNORE_IDS", ids),
]
for name, field, key, expected in wiring:
    got = steps[name].get(field)
    if key is not None:
        got = (got or {}).get(key)
    if got != expected:
        raise SystemExit(f"step {name!r}: {field}{'.' + key if key else ''} is {got!r}, expected {expected!r}")
if "HEX_IGNORE_RETIREMENTS" in (steps[want["hex.sh"]].get("env") or {}):
    raise SystemExit("the hex.audit gate sets HEX_IGNORE_RETIREMENTS — retirements must never be ignorable")
PY
[ $? -eq 0 ] || { echo "  FAIL  could not extract the steps"; exit 1; }

# A `mix` that ignores advisories the way Hex 2.5.1 and mix_audit do: by exact id (or, for
# Hex, alias), case-insensitively. REPORTED is "ID[:ALIAS]" space-separated; RETIRED is a
# package name. Prints the Hex 2.5 deprecation warning first, as CI does.
mkdir -p "$work/stub"
cat > "$work/stub/mix" <<'STUB'
#!/usr/bin/env bash
listed() { # $1 = id, $2 = comma list
  local x; IFS=, read -ra xs <<<"$2"
  local want; want=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  for x in "${xs[@]}"; do [ "$(printf '%s' "$x" | tr '[:upper:]' '[:lower:]')" = "$want" ] && return 0; done
  return 1; }
case "$1" in
  hex.audit)
    printf '\033[33mAuthenticating to the cobenian repository with a stored key is deprecated and will be removed.\n\nFor CI generate an organization key\n\033[0m\n'
    [ -n "${HEX_IGNORE_RETIREMENTS:-}" ] && { echo "retirements ignored: $HEX_IGNORE_RETIREMENTS"; RETIRED=""; }
    rc=0; out=""
    for a in ${REPORTED:-}; do
      id="${a%%:*}"; alias="${a#*:}"
      if listed "$id" "${HEX_IGNORE_ADVISORIES:-}" || listed "$alias" "${HEX_IGNORE_ADVISORIES:-}"; then continue; fi
      out+="  pkg 1.0.0 - $id (HIGH)\n    aka: $alias\n"; rc=1
    done
    [ -n "${RETIRED:-}" ] && { echo "Retired:"; echo "  ${RETIRED} 1.0.0 - (deprecated) use something else"; rc=1; }
    if [ -n "$out" ]; then echo "Advisories:"; printf "$out"; fi
    [ "$rc" = 0 ] && [ -z "${RETIRED:-}" ] && echo "No retired or security advisory packages found"
    exit $rc ;;
  deps.audit)
    shift; ign=""; json=no
    while [ $# -gt 0 ]; do case "$1" in
      --ignore-advisory-ids) ign="$2"; shift 2 ;; --format) json=yes; shift 2 ;; *) shift ;; esac; done
    rc=0; v=""
    for id in ${MIX_REPORTED:-}; do
      listed "$id" "$ign" && continue
      v+="{\"advisory\":{\"id\":\"$id\"}},"; rc=1
    done
    [ "$json" = yes ] && echo "{\"pass\":$([ $rc = 0 ] && echo true || echo false),\"vulnerabilities\":[${v%,}]}"
    exit $rc ;;
esac
exit 0
STUB
chmod +x "$work/stub/mix"

TODAY=2026-10-10
entry() { # id expires [reason]
  printf '  - id: %s\n    package: cloak\n    reason: "%s"\n    expires: %s\n    added_by: Bryan Weber\n' \
    "$1" "${3:-Uses only Cloak.Ciphers.AES.GCM; no fixed release exists}" "$2"; }

# Runs validate -> hex -> deps -> stale in a fresh git repo, as the job would.
# Prints "validate=RC hex=RC deps=RC"; leaves the combined log at $work/log.
run() { # $1 = .audit-ignore.yml content ("" = no file); env passes through
  local r="$work/repo"; rm -rf "$r"; mkdir -p "$r"
  ( cd "$r" && git init -q . && printf 'defmodule X.MixProject do\nend\n' > mix.exs
    [ -n "${MIXEXS:-}" ] && printf '%s\n' "$MIXEXS" > mix.exs
    [ -n "$1" ] && printf '%s' "$1" > .audit-ignore.yml
    git add -A >/dev/null 2>&1
    : > out; export GITHUB_OUTPUT="$PWD/out" RUNNER_TEMP="$PWD/tmp" PATH="$work/stub:$PATH"
    export AUDIT_IGNORE_TODAY="$TODAY" MAX_DAYS="${MAX_DAYS:-90}"
    bash "$work/validate.sh" > "$work/log" 2>&1; v=$?
    ids=$(sed -n 's/^ids=//p' out)
    h=skip; d=skip
    if [ $v = 0 ]; then
      HEX_IGNORE_ADVISORIES="$ids" bash "$work/hex.sh" >> "$work/log" 2>&1; h=$?
      IGNORE_IDS="$ids" bash "$work/deps.sh" >> "$work/log" 2>&1; d=$?
      if [ -n "$ids" ]; then IGNORE_IDS="$ids" bash "$work/stale.sh" >> "$work/log" 2>&1 || echo "STALE-STEP-FAILED" >> "$work/log"; fi
    fi
    echo "validate=$v hex=$h deps=$d" )
}
logs() { grep -c -- "$1" "$work/log" | tr -d ' '; }

CTR=EEF-CVE-2026-95105; PB=EEF-CVE-2026-94206

echo "an advisory nobody acknowledged still blocks:"
t "no file — the gate fails"                 "validate=0 hex=1 deps=0" "$(REPORTED="$CTR:CVE-2026-95105" run '')"
t "listed one, a second is unlisted — fails" "validate=0 hex=1 deps=0" \
  "$(REPORTED="$CTR:CVE-2026-95105 $PB:CVE-2026-94206" run "advisories:
$(entry $CTR 2027-01-08)")"
t "unlisted mix_audit finding — deps.audit fails" "validate=0 hex=0 deps=1" \
  "$(REPORTED="$CTR:CVE-2026-95105" MIX_REPORTED="GHSA-aaaa-bbbb-cccc" run "advisories:
$(entry $CTR 2027-01-08)")"

echo "a listed, in-date advisory passes (the positive control):"
t "both Cloak advisories listed — passes"    "validate=0 hex=0 deps=0" \
  "$(REPORTED="$CTR:CVE-2026-95105 $PB:CVE-2026-94206" run "advisories:
$(entry $CTR 2027-01-08)
$(entry $PB 2027-01-08)")"
t "the Hex 2.5 deprecation warning does not confuse it" "1" "$(logs 'deprecated and will be removed')"
t "listed by its CVE alias — passes"          "validate=0 hex=0 deps=0" \
  "$(REPORTED="$CTR:CVE-2026-95105" run "advisories:
$(entry CVE-2026-95105 2027-01-08)")"
t "the same id silences mix_audit too"        "validate=0 hex=0 deps=0" \
  "$(MIX_REPORTED="GHSA-aaaa-bbbb-cccc" run "advisories:
$(entry GHSA-aaaa-bbbb-cccc 2027-01-08)")"
t "expires today — still valid"              "validate=0 hex=0 deps=0" \
  "$(REPORTED="$CTR:x" run "advisories:
$(entry $CTR 2026-10-10)")"
t "expires within 14 days — warns"           "1" "$(logs '::warning title=Advisory ignore list::.*(0 days)')"
t "an empty list is fine"                    "validate=0 hex=0 deps=0" "$(run 'advisories: []')"

echo "expiry is enforced:"
t "expired yesterday — fails before the gates" "validate=1 hex=skip deps=skip" \
  "$(REPORTED="$CTR:x" run "advisories:
$(entry $CTR 2026-10-09)")"
t "…naming the entry and saying to re-assess" "1" "$(logs "entry 1 ($CTR): EXPIRED on 2026-10-09. Re-assess")"
t "one expired entry fails the whole list"   "validate=1 hex=skip deps=skip" \
  "$(REPORTED="$CTR:x $PB:y" run "advisories:
$(entry $CTR 2027-01-08)
$(entry $PB 2026-01-01)")"
t "91 days out — fails"                      "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
$(entry $CTR 2027-01-09)")"
t "…and says the latest allowed date"        "1" "$(logs 'no later than 2027-01-08')"
t "exactly 90 days out — passes"             "validate=0 hex=0 deps=0" \
  "$(REPORTED="$CTR:x" run "advisories:
$(entry $CTR 2027-01-08)")"
t "a repo's tighter cap is honoured"         "validate=1 hex=skip deps=skip" \
  "$(MAX_DAYS=30 run "advisories:
$(entry $CTR 2026-11-10)")"
t "a cap over 365 is refused"                "validate=1 hex=skip deps=skip" \
  "$(MAX_DAYS=1000 run "advisories:
$(entry $CTR 2027-01-08)")"
t "no expires — fails"                       "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
  - id: $CTR
    package: cloak
    reason: Uses only Cloak.Ciphers.AES.GCM here
    added_by: Bryan Weber
")"
t "a typo'd key (expire:) — fails, not 'no expiry'" "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
  - id: $CTR
    package: cloak
    reason: Uses only Cloak.Ciphers.AES.GCM here
    expire: 2027-01-08
    added_by: Bryan Weber
")"
t "an impossible date (Feb 30) — fails"      "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
$(entry $CTR 2026-02-30)")"
t "a date in another format — fails"         "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
$(entry $CTR 01/08/2027)")"

echo "an entry names exactly one assessed advisory:"
t "a wildcard id — fails"                    "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
$(entry 'EEF-CVE-2026-*' 2027-01-08)")"
t "two ids in one entry — fails"             "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
$(entry "$CTR,$PB" 2027-01-08)")"
t "a duplicate id — fails"                   "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
$(entry $CTR 2027-01-08)
$(entry $CTR 2027-01-08)")"
t "a reason that says nothing — fails"       "validate=1 hex=skip deps=skip" \
  "$(run "advisories:
$(entry $CTR 2027-01-08 'n/a')")"
t "not a list under advisories: — fails"     "validate=1 hex=skip deps=skip" "$(run "advisories: $CTR")"
t "a bare list with no advisories: key — fails" "validate=1 hex=skip deps=skip" "$(run "- id: $CTR")"
t "an empty file — fails"                    "validate=1 hex=skip deps=skip" "$(run ' ')"
t "a multi-line reason cannot inject a workflow command" "0" \
  "$(REPORTED="$CTR:x" run "advisories:
  - id: $CTR
    package: cloak
    reason: |
      Uses only Cloak.Ciphers.AES.GCM here.
      ::error::injected
    expires: 2027-01-08
    added_by: Bryan Weber
" >/dev/null; grep -c '^::error::injected' "$work/log" | tr -d ' ')"

echo "retired packages stay blocking:"
t "a retired package fails even with the list in place" "validate=0 hex=1 deps=0" \
  "$(RETIRED=poison REPORTED="$CTR:x" run "advisories:
$(entry $CTR 2027-01-08)")"
t "…even if HEX_IGNORE_RETIREMENTS leaked into the environment" "validate=0 hex=1 deps=0" \
  "$(HEX_IGNORE_RETIREMENTS=poison RETIRED=poison run '')"
t "mix.exs hex ignore_advisories (no expiry) is refused" "validate=1 hex=skip deps=skip" \
  "$(MIXEXS='def project, do: [hex: [ignore_advisories: ["EEF-CVE-2026-95105"]]]' run '')"
t "mix.exs hex ignore_retirements is refused" "validate=1 hex=skip deps=skip" \
  "$(MIXEXS='def project, do: [hex: [ignore_retirements: [:poison]]]' run '')"

echo "a stale entry warns and never fails:"
t "listed but no longer reported — passes"   "validate=0 hex=0 deps=0" \
  "$(REPORTED="$CTR:CVE-2026-95105" run "advisories:
$(entry $CTR 2027-01-08)
$(entry $PB 2027-01-08)")"
t "…with a warning naming only the stale one" "1" "$(logs "entry $PB is not reported")"
t "…and none for the one still reported"      "0" "$(logs "entry $CTR is not reported")"
t "the stale step itself did not fail"        "0" "$(logs STALE-STEP-FAILED)"
t "an entry for a mix_audit-only advisory is not stale" "0" \
  "$(MIX_REPORTED="GHSA-aaaa-bbbb-cccc" run "advisories:
$(entry GHSA-aaaa-bbbb-cccc 2027-01-08)" >/dev/null; logs 'is not reported')"

[ "$fails" -eq 0 ] && echo "audit-ignore-test: all passed" || echo "audit-ignore-test: $fails failed"
exit $((fails > 0))
