#!/usr/bin/env bash
# scripts/demo-mode-b.sh — one-command replay for the validated Prometheus report-centric demo.
#
# Reuses the existing deploy + preflight + trigger + watch scripts, but owns the replay flow:
#   1. deploy demo, observability, and RCA backend layers in order
#   2. run demo preflight
#   3. start a deterministic backend port-forward on 127.0.0.1:${RCA_BACKEND_PORT:-18000}
#   4. trigger the validated DependencyTimeout alert
#   5. watch the investigation until terminal status
#   6. fail unless a cited report is present
#
# Required env on a fresh machine when rca-backend-secrets does not already exist:
#   RCA_HYPOTHESIS_LLM_API_KEY
#   RCA_HYPOTHESIS_LLM_API_URL
#
# Usage:
#   scripts/demo-mode-b.sh
#   RCA_BACKEND_PORT=18000 scripts/demo-mode-b.sh
#   SKIP_DEPLOY=1 scripts/demo-mode-b.sh
#
# Exit codes:
#   0  validated Mode B replay completed with a non-null report
#   1  deploy, preflight, trigger, watch, or report validation failed
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,/^set -euo pipefail/p' "$0" | sed '/^set -euo pipefail/d; s/^# \?//; s/^#//'
  exit 0
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

RCA_BACKEND_PORT="${RCA_BACKEND_PORT:-18000}"
RCA_BACKEND_URL="${RCA_BACKEND_URL:-http://127.0.0.1:${RCA_BACKEND_PORT}}"
SKIP_DEPLOY="${SKIP_DEPLOY:-0}"
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-0}"
PF_PID=""

if [[ -t 1 ]]; then
  C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_YELLOW=$'\033[1;33m'
  C_BOLD=$'\033[1m'; C_CYAN=$'\033[1;36m'; C_RESET=$'\033[0m'
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_BOLD=""; C_CYAN=""; C_RESET=""
fi

step() { printf '%s==>%s %s\n' "$C_BOLD$C_CYAN" "$C_RESET" "$*"; }
info() { printf '  %s\n' "$*"; }
fail() { printf '%s[FAIL]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }

cleanup() {
  if [[ -n "$PF_PID" ]] && kill -0 "$PF_PID" >/dev/null 2>&1; then
    kill "$PF_PID" >/dev/null 2>&1 || true
    wait "$PF_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

wait_for_backend() {
  local i
  for i in $(seq 1 30); do
    if curl -fsS "$RCA_BACKEND_URL/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

extract_investigation_id() {
  printf '%s\n' "$1" | sed -n 's/.*investigation_id:[[:space:]]*//p' | tail -n1 | tr -d '[:space:]'
}

step "Mode B replay configuration"
info "backend url: $RCA_BACKEND_URL"
info "skip deploy : $SKIP_DEPLOY"
info "skip preflight: $SKIP_PREFLIGHT"

if [[ "$SKIP_DEPLOY" != "1" ]]; then
  step "deploy demo stack"
  ./demo/deploy.sh

  step "deploy observability stack"
  ./observability/deploy.sh

  step "deploy RCA backend"
  ./deploy/deploy.sh
else
  step "skipping deploy (SKIP_DEPLOY=1)"
fi

if [[ "$SKIP_PREFLIGHT" != "1" ]]; then
  step "run demo preflight"
  scripts/demo-preflight.sh
else
  step "skipping preflight (SKIP_PREFLIGHT=1)"
fi

step "start backend port-forward on 127.0.0.1:${RCA_BACKEND_PORT}"
kubectl -n rca port-forward deploy/rca-backend "${RCA_BACKEND_PORT}:8000" >/tmp/demo-mode-b-port-forward.log 2>&1 &
PF_PID=$!

if ! wait_for_backend; then
  fail "backend did not become healthy at $RCA_BACKEND_URL"
  fail "port-forward log: /tmp/demo-mode-b-port-forward.log"
  exit 1
fi

step "trigger validated Prometheus alert"
trigger_output="$(RCA_BACKEND_URL="$RCA_BACKEND_URL" scripts/demo-trigger-prometheus.sh)"
printf '%s\n' "$trigger_output"

investigation_id="$(extract_investigation_id "$trigger_output")"
if [[ -z "$investigation_id" ]]; then
  fail "could not extract investigation_id from trigger output"
  exit 1
fi

step "watch investigation until terminal status with report requirement"
RCA_BACKEND_URL="$RCA_BACKEND_URL" scripts/demo-watch-investigation.sh "$investigation_id" --require-report

printf '%sMode B replay completed with a cited RCA report.%s\n' "$C_GREEN$C_BOLD" "$C_RESET"
