#!/usr/bin/env bash
# scripts/demo-watch-investigation.sh — poll an RCA investigation to terminal + summarize.
#
# Polls GET /api/investigations/<investigation_id> (the read-store; no SSE in this POC),
# prints each status transition with elapsed time, and on a terminal status prints a
# concise, presenter-friendly summary. When a cited RCA report is present it highlights
# root_cause / confidence / evidence_backing / open_questions (and notes uncertainty and
# the always-empty remediation slot).
#
# Truthfulness:
#   - status is one of running | success | failed | partial (partial = ended inconclusive).
#   - report may be null even on success (lifecycle worked, no cited report this run);
#     that is reported plainly — nothing is fabricated.
#   - remediation is intentionally empty in this POC; the script never invents actions.
#
# Prerequisites: curl on PATH; jq recommended, else python3 is used as the JSON parser.
# Port-forward: kubectl -n rca port-forward deploy/rca-backend 8000:8000
#
# Usage:
#   ./scripts/demo-watch-investigation.sh <investigation_id>
#   ./scripts/demo-watch-investigation.sh <id> --once        # single fetch, no polling
#   ./scripts/demo-watch-investigation.sh <id> --poll 2 --timeout 600
#   BACKEND_URL=http://localhost:8000 ./scripts/demo-watch-investigation.sh <id>
#
# Env defaults: BACKEND_URL=http://localhost:8000  POLL=3  TIMEOUT=300
#
# Exit codes: 0 = reached a terminal status; 1 = not found, unreachable, or timed out.
set -uo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
POLL="${POLL:-3}"
TIMEOUT="${TIMEOUT:-300}"
ONCE=0
ID=""

# --- args -----------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      sed -n '2,/^set -uo pipefail/p' "$0" | sed '/^set -uo pipefail/d; s/^# \?//; s/^#//'
      exit 0
      ;;
    --once)         ONCE=1; shift ;;
    --poll)         POLL="${2:?--poll needs seconds}"; shift 2 ;;
    --timeout)      TIMEOUT="${2:?--timeout needs seconds}"; shift 2 ;;
    --backend-url)  BACKEND_URL="${2:?--backend-url needs a url}"; shift 2 ;;
    -*) echo "unknown flag: $1 (try --help)" >&2; exit 1 ;;
    *)
      if [[ -z "$ID" ]]; then ID="$1"; else
        echo "unexpected extra argument: $1 (only one investigation_id)" >&2; exit 1
      fi
      shift ;;
  esac
done

if [[ -z "$ID" ]]; then
  echo "usage: $0 <investigation_id> [--once] [--poll N] [--timeout S]" >&2
  exit 1
fi

# --- output helpers -------------------------------------------------------------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'
  C_CYAN=$'\033[36m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_CYAN=""; C_BOLD=""; C_DIM=""; C_OFF=""
fi
have() { command -v "$1" >/dev/null 2>&1; }

# JSON parser: prefer jq, fall back to python3 (stdlib only — not a framework).
if have jq; then
  JSON=jq
elif have python3; then
  JSON=python3
else
  echo "need jq or python3 to parse the investigation response" >&2; exit 1
fi

status_of() {  # status_of <body> -> status string
  case "$JSON" in
    jq)      printf '%s' "$1" | jq -r '.status // empty' 2>/dev/null ;;
    python3) printf '%s' "$1" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("status",""))' 2>/dev/null ;;
  esac
}

report_is_null() {  # report_is_null <body> -> 0 if null, 1 if present
  case "$JSON" in
    jq)      printf '%s' "$1" | jq -e '.report == null' >/dev/null 2>&1 ;;
    python3) printf '%s' "$1" | python3 -c 'import json,sys;sys.exit(0 if json.load(sys.stdin).get("report") is None else 1)' >/dev/null 2>&1 ;;
  esac
}

# Print the report highlight block from the response body.
highlight_report() {  # highlight_report <body>
  if [[ "$JSON" == "python3" ]]; then
    printf '%s' "$1" | python3 - <<'PY'
import json, sys
d = json.load(sys.stdin).get("report") or {}
def num(x):
    try: return int(x)
    except (TypeError, ValueError): return 0
rc = d.get("root_cause") or []
ev = d.get("evidence_backing") or []
oq = d.get("open_questions") or []
conf = d.get("confidence") or {}
cc = conf.get("ceiling_confidence")
cat = conf.get("categorical") or "-"
unc = d.get("uncertainty") or "-"
top = sorted(rc, key=lambda h: h.get("rank", 999))[:1]
top_s = "-"
if top:
    h = top[0]
    top_s = f"{h.get('hypothesis_id','?')} (priority={h.get('priority','?')})"
print(f"    root_cause       : {len(rc)} candidate(s)")
if rc:
    print(f"      top candidate  : {top_s}")
print(f"    evidence_backing : {len(ev)} cited excerpt(s)")
print(f"    confidence       : ceiling={cc if cc is not None else '-'}  categorical={cat}")
print(f"    open_questions   : {len(oq)} ungrounded")
print(f"    uncertainty      : {unc}")
print(f"    remediation      : [] (intentionally empty in this POC)")
PY
    return
  fi
  # jq path
  local body="$1"
  local rc_n ev_n oq_n cc cat unc top
  rc_n="$(printf '%s' "$body" | jq -r '.report.root_cause | length' 2>/dev/null)"
  ev_n="$(printf '%s' "$body" | jq -r '.report.evidence_backing | length' 2>/dev/null)"
  oq_n="$(printf '%s' "$body" | jq -r '.report.open_questions | length' 2>/dev/null)"
  cc="$(printf '%s'  "$body" | jq -r '.report.confidence.ceiling_confidence // "-"' 2>/dev/null)"
  cat="$(printf '%s' "$body" | jq -r '.report.confidence.categorical // "-"' 2>/dev/null)"
  unc="$(printf '%s' "$body" | jq -r '.report.uncertainty // "-"' 2>/dev/null)"
  top="$(printf '%s'  "$body" | jq -r '
    (.report.root_cause | sort_by(.rank) | first |
     "\(.hypothesis_id // "?") (priority=\(.priority // "?"))") // "-"' 2>/dev/null)"
  printf '    root_cause       : %s candidate(s)\n' "$rc_n"
  [[ "$rc_n" =~ ^[1-9] ]] && printf '      top candidate  : %s\n' "$top"
  printf '    evidence_backing : %s cited excerpt(s)\n' "$ev_n"
  printf '    confidence       : ceiling=%s  categorical=%s\n' "$cc" "$cat"
  printf '    open_questions   : %s ungrounded\n' "$oq_n"
  printf '    uncertainty      : %s\n' "$unc"
  printf '    remediation      : [] (intentionally empty in this POC)\n'
}

# --- poll loop ------------------------------------------------------------------
printf '%s=>%s watching %s/api/investigations/%s  (poll=%ss timeout=%ss)%s\n' \
  "$C_BOLD$C_CYAN" "$C_OFF" "$BACKEND_URL" "$ID" "$POLL" "$TIMEOUT"

start=$(date +%s)
prev=""
final_status=""
final_body=""
notified_notfound=0

while :; do
  now=$(date +%s); elapsed=$((now - start))
  code_body="$(curl -sS -w '\n%{http_code}' "$BACKEND_URL/api/investigations/$ID" 2>/dev/null)" || code_body=$'\n000'
  http_code="$(printf '%s' "$code_body" | tail -n1)"
  body="$(printf '%s' "$code_body" | sed '$d')"

  if [[ "$http_code" == "404" ]]; then
    if [[ $notified_notfound -eq 0 ]]; then
      printf '  [%sWAIT%s] investigation not found yet (404) — webhook may not have landed\n' "$C_YELLOW" "$C_OFF"
      notified_notfound=1
    fi
  elif [[ "$http_code" != "200" ]]; then
    printf '  [%sWARN%s] unexpected HTTP %s from backend (is the port-forward up?)\n' "$C_YELLOW" "$C_OFF" "$http_code"
  else
    status="$(status_of "$body")"
    if [[ "$status" != "$prev" ]]; then
      case "$status" in
        success)  col="$C_GREEN" ;;
        failed)   col="$C_RED" ;;
        partial)  col="$C_YELLOW" ;;
        *)        col="$C_CYAN" ;;
      esac
      printf '  [+%-4ss] %sstatus=%s%s\n' "$elapsed" "$C_BOLD$col" "$status" "$C_OFF"
      prev="$status"
    fi
    if [[ "$status" == "success" || "$status" == "failed" || "$status" == "partial" ]]; then
      final_status="$status"; final_body="$body"; break
    fi
  fi

  [[ "$ONCE" == "1" ]] && break
  if [[ $elapsed -ge $TIMEOUT ]]; then
    printf '  [%sTIMEOUT%s] reached %ss before a terminal status\n' "$C_YELLOW" "$C_OFF" "$TIMEOUT"
    break
  fi
  sleep "$POLL"
done

# --- final summary --------------------------------------------------------------
echo
printf '%s=>%s final summary%s\n' "$C_BOLD$C_CYAN" "$C_OFF" "$C_OFF"
printf '    investigation_id : %s\n' "$ID"

if [[ -z "$final_status" ]]; then
  if [[ "$ONCE" == "1" ]] && [[ "$prev" != "" ]]; then
    printf '    status           : %s (non-terminal snapshot from --once)\n' "$prev"
  else
    printf '    status           : %snot reached a terminal status%s\n' "$C_YELLOW" "$C_OFF"
  fi
  printf '    report           : not evaluated (run without --once to wait for completion)\n'
  exit 1
fi

printf '    status           : %s\n' "$final_status"
if report_is_null "$final_body"; then
  printf '    report           : %snull%s — lifecycle completed, no cited RCA report this run\n' "$C_YELLOW" "$C_OFF"
  echo "    (honest scope: trigger ingestion + lifecycle worked; do not infer a grounded report)"
  case "$final_status" in
    success) printf '%s  RESULT: lifecycle success, report not produced.%s\n' "$C_YELLOW$C_BOLD" "$C_OFF"; exit 0 ;;
    *)       printf '%s  RESULT: ended %s.%s\n' "$C_RED$C_BOLD" "$final_status" "$C_OFF"; exit 1 ;;
  esac
fi

printf '    report           : present — cited RCA fields below\n'
highlight_report "$final_body"

case "$final_status" in
  success) printf '%s  RESULT: success with a cited RCA report.%s\n' "$C_GREEN$C_BOLD" "$C_OFF"; exit 0 ;;
  *)       printf '%s  RESULT: ended %s (report present).%s\n' "$C_YELLOW$C_BOLD" "$final_status" "$C_OFF"; exit 1 ;;
esac
