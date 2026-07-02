#!/usr/bin/env bash
# scripts/demo-trigger-grafana.sh — drive the validated live Grafana Loki trigger path.
#
# Validates the canonical live Grafana Loki path from docs/demo/guide.md: a Grafana Loki `DNSFailureLogSpike`
# alert for service `user` is fired by REAL log content, ingested by the RCA backend
# webhook, and (when access logs are on) observed as a backend 202.
#
# What this script does (all observable, nothing fabricated):
#   1. injects DNS-failure log lines into the `user` pod stdout (Alloy -> Loki labels
#      them namespace=demo, service=user);
#   2. waits for the Grafana LogQL rule to evaluate (interval 30s, `for: 1m` hold);
#   3. checks the three validated signals and prints a presenter pass/fail summary:
#        a. Loki saw > 5 matching `dns`+`failure` lines for service=user (logs arrived),
#        b. Grafana has a firing DNSFailureLogSpike alert with service=user,
#        c. backend received POST /api/alerts/grafana -> 202 (ONLY if observable).
#
# Truthfulness: Grafana firing depends on Loki ingestion lag + rule timing + the 1m
# hold, so a miss inside the wait window is NOT proof of breakage — the summary says
# exactly what was observed and what was not. The backend 202 is often NOT in pod
# logs (uvicorn access logging is off by default); that check is best-effort.
#
# Prerequisites: kubectl + curl on PATH. jq recommended (falls back to grep).
# Port-forwards (run in separate terminals):
#   kubectl -n observability port-forward deploy/grafana 3000:3000
#   kubectl -n observability port-forward deploy/loki    3100:3100
#   kubectl -n rca          port-forward deploy/rca-backend 8000:8000
#
# Usage:
#   ./scripts/demo-trigger-grafana.sh                         # inject + wait + check (defaults)
#   ./scripts/demo-trigger-grafana.sh --no-inject             # logs already present; just check
#   ./scripts/demo-trigger-grafana.sh --count 12 --wait 180   # more logs, longer wait
#   ./scripts/demo-trigger-grafana.sh --once                  # single check, no polling
#   WAIT=90 POLL=10 ./scripts/demo-trigger-grafana.sh         # config via env
#
# Env defaults: DEMO_NS=demo  USER_DEPLOY=user  OBS_NS=observability  RCA_NS=rca
#   RCA_DEPLOY=rca-backend  LOKI_URL=http://localhost:3100
#   GRAFANA_URL=http://localhost:3000  GRAFANA_USER=admin  GRAFANA_PASSWORD=admin
#   BACKEND_URL=http://localhost:8000  COUNT=8  WAIT=120  POLL=15
#
# Exit codes: 0 = the validated alert signal was observed; 1 = it was not (or a
# prerequisite failed). Either way a full summary is printed.
set -uo pipefail

# --- config (env) ---------------------------------------------------------------
DEMO_NS="${DEMO_NS:-demo}"
USER_DEPLOY="${USER_DEPLOY:-user}"
OBS_NS="${OBS_NS:-observability}"
RCA_NS="${RCA_NS:-rca}"
RCA_DEPLOY="${RCA_DEPLOY:-rca-backend}"
LOKI_URL="${LOKI_URL:-http://localhost:3100}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
COUNT="${COUNT:-8}"          # must exceed the LogQL threshold of 5
WAIT="${WAIT:-120}"          # seconds to wait for the rule to fire
POLL="${POLL:-15}"           # seconds between re-checks
DO_INJECT=1
ONCE=0

# --- arg parsing ----------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      sed -n '2,/^set -uo pipefail/p' "$0" | sed '/^set -uo pipefail/d; s/^# \?//; s/^#//'
      exit 0
      ;;
    --no-inject) DO_INJECT=0; shift ;;
    --once)      ONCE=1; WAIT=0; shift ;;
    --count)     COUNT="${2:?--count needs a number}"; shift 2 ;;
    --wait)      WAIT="${2:?--wait needs seconds}"; shift 2 ;;
    --poll)      POLL="${2:?--poll needs seconds}"; shift 2 ;;
    *) echo "unknown arg: $1 (try --help)" >&2; exit 1 ;;
  esac
done

# --- output helpers -------------------------------------------------------------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'
  C_CYAN=$'\033[36m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_CYAN=""; C_BOLD=""; C_OFF=""
fi
step()  { printf '%s==>%s %s\n' "$C_BOLD$C_CYAN" "$C_OFF" "$*"; }
ok()    { printf '  [%sPASS%s] %s\n' "$C_GREEN" "$C_OFF" "$*"; }
warn()  { printf '  [%sWARN%s] %s\n' "$C_YELLOW" "$C_OFF" "$*"; }
fail()  { printf '  [%sFAIL%s] %s\n' "$C_RED" "$C_OFF" "$*"; }

have() { command -v "$1" >/dev/null 2>&1; }

# --- pre-flight -----------------------------------------------------------------
step "pre-flight checks"
miss=0
for bin in kubectl curl; do
  if have "$bin"; then ok "$bin on PATH"; else fail "$bin missing"; miss=1; fi
done
if have jq; then ok "jq on PATH (JSON parsing)"
else warn "jq missing — falling back to grep (less precise)"; fi
[[ $miss -eq 1 ]] && { fail "install missing prerequisites first"; exit 1; }

if curl -sf "$BACKEND_URL/health" >/dev/null 2>&1; then
  ok "backend health OK at $BACKEND_URL/health"
else
  warn "backend not reachable at $BACKEND_URL (is the port-forward up? checks that need it will degrade)"
fi

# --- signal probes --------------------------------------------------------------
# Loki: confirm matching logs arrived for service=user (the LogQL the rule uses).
# Rule expr: sum by (service) (count_over_time({namespace="demo"} |= "dns" |= "failure" [5m])) > 5
loki_count_for_user() {
  local expr='sum by (service) (count_over_time({namespace="demo"} |= "dns" |= "failure" [5m]))'
  local body
  body="$(curl -fsS --data-urlencode "query=$expr" "$LOKI_URL/loki/api/v1/query" 2>/dev/null)" || return 1
  if have jq; then
    # result[].value is [timestamp, "count"]; pick the stream whose service == user.
    printf '%s' "$body" \
      | jq -r '.data.result[] | select(.metric.service=="user") | .value[1] // empty' 2>/dev/null
  else
    printf '%s' "$body" | grep -o '"service":"user"[^]]*value":\[[^,]*,"\([0-9]*\)"' | tail -1
  fi
}

# Grafana unified alerting: a firing alert instance carries labels + status.state.
grafana_alert_firing() {
  local body
  body="$(curl -fsS -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
            "$GRAFANA_URL/api/alertmanager/api/v2/alerts" 2>/dev/null)" || return 1
  if have jq; then
    # firing + matching labels. status.state "alerting" == firing.
    printf '%s' "$body" | jq -r '
      .[] | select(.labels.alertname=="DNSFailureLogSpike" and .labels.service=="user")
           | .status.state // "unknown"' 2>/dev/null
  else
    if printf '%s' "$body" | grep -q '"alertname":"DNSFailureLogSpike"'; then
      printf 'alerting'
    else
      return 1
    fi
  fi
}

# Backend 202: best-effort grep of the backend access log (often off — honest if absent).
backend_saw_202() {
  local logs
  logs="$(kubectl -n "$RCA_NS" logs "deploy/$RCA_DEPLOY" --tail=500 2>/dev/null)" || return 1
  printf '%s' "$logs" | grep -E 'POST /api/alerts/grafana' | tail -1
}

# --- step 1: inject DNS-failure logs into the user pod --------------------------
if [[ "$DO_INJECT" == "1" ]]; then
  step "injecting $COUNT DNS-failure log lines into $USER_DEPLOY pod stdout"
  # Alloy tails the pod's main PID stdout; /proc/1/fd/1 is uvicorn's stdout
  # (PYTHONUNBUFFERED=1 in the image, so lines flush immediately).
  if kubectl -n "$DEMO_NS" exec "deploy/$USER_DEPLOY" -- sh -c '
       i=0; while [ "$i" -lt '"$COUNT"' ]; do
         echo "dns resolution failure nxdomain user lookup seq='"$i"' (dns: transient upstream failure)" > /proc/1/fd/1 2>/dev/null || \
         echo "dns resolution failure nxdomain user lookup seq='"$i"'";
         i=$((i+1));
       done' >/dev/null 2>&1; then
    ok "injected $COUNT lines (namespace=$DEMO_NS service=$USER_DEPLOY)"
    warn "Grafana rule needs Loki ingestion + a 1m hold — it will not fire instantly"
  else
    fail "could not exec into deploy/$USER_DEPLOY (is the demo stack up? try --no-inject if logs already exist)"
  fi
else
  step "skipping injection (--no-inject); assuming DNS-failure logs are already present"
fi

# --- step 2 + 3: wait and probe the validated signals ---------------------------
step "checking validated Grafana alert signals (wait up to ${WAIT}s, poll ${POLL}s)"

LOGI=""   # loki count for user
STATE=""  # grafana alert state
BACK="";  # backend 202 line
probe_all() {
  LOGI="$(loki_count_for_user 2>/dev/null || true)"
  STATE="$(grafana_alert_firing 2>/dev/null || true)"
  BACK="$(backend_saw_202 2>/dev/null || true)"
}

elapsed=0
probe_all
while :; do
  # short-circuit once the headline signal (firing alert) is seen.
  if [[ "$STATE" == "alerting" ]]; then break; fi
  [[ "$ONCE" == "1" ]] && break
  [[ $elapsed -ge $WAIT ]] && break
  sleep "$POLL"; elapsed=$((elapsed + POLL))
  probe_all
done

# --- summary --------------------------------------------------------------------
step "summary"
verdict=0

if [[ -n "$LOGI" ]]; then
  if [[ "$LOGI" =~ ^[0-9]+$ && "$LOGI" -gt 5 ]]; then
    ok "Loki saw $LOGI matching dns+failure lines for service=user (logs arrived in Loki)"
  else
    warn "Loki returned count=$LOGI for service=user (threshold is > 5; ingestion lag?)"
  fi
else
  fail "Loki did not return a count for service=user (is the Loki port-forward + Alloy up?)"
  verdict=1
fi

if [[ "$STATE" == "alerting" ]]; then
  ok "Grafana firing alert: alertname=DNSFailureLogSpike service=user (state=$STATE)"
elif [[ -n "$STATE" ]]; then
  warn "Grafana alert exists for DNSFailureLogSpike/service=user but state=$STATE (pending/normal) — re-run --once after the 1m hold"
  verdict=1
else
  fail "no firing DNSFailureLogSpike/service=user alert in Grafana at $GRAFANA_URL"
  verdict=1
fi

if [[ -n "$BACK" ]]; then
  ok "backend access log shows: $BACK"
else
  warn "backend 202 for POST /api/alerts/grafana NOT observable (uvicorn access logging is off by default) — not a failure"
fi

echo
if [[ $verdict -eq 0 ]]; then
  printf '%s  RESULT: validated live Grafana trigger path OBSERVED.%s\n' "$C_GREEN$C_BOLD" "$C_OFF"
  echo "  Next: poll the investigation the webhook created with scripts/demo-watch-investigation.sh"
  echo "  (the backend does not expose a list endpoint; pass the investigation_id the webhook created)."
else
  printf '%s  RESULT: validated signals NOT yet observed.%s\n' "$C_YELLOW$C_BOLD" "$C_OFF"
  echo "  This is not proof of breakage — re-run with --once after a minute, or increase --wait."
  echo "  Honest scope: trigger ingestion only; a grounded RCA report is not guaranteed from this path."
fi
exit $verdict
