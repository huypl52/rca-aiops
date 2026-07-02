#!/usr/bin/env bash
# scripts/demo-preflight.sh — one-shot readiness check before the live RCA demo.
#
# Verifies the demo SUT (ns demo), the observability read-target stack (ns observability),
# and the RCA backend (ns rca) are ready enough to run the report-centric Prometheus path,
# then prints a clear GO / NO-GO summary. Read-only: it runs only `kubectl get` + one
# in-pod `/health` probe against deploy/rca-backend (the Python app image, so the probe
# uses python urllib — no curl/wget dependency inside the container).
#
# GO gate: the 3 report-centric SUT services (order, payment, api-gateway) ready,
# prometheus + alertmanager ready, rca-backend service present + healthy.
# WARN (non-blocking): supporting SUT services, traffic-runner, and the Grafana/Loki
# (Mode C) stack are reported but do not fail a Mode B (Prometheus report) run.
#
# This dev box has no cluster; run it on the demo host. See docs/demo/operator-cheatsheet.md for commands and docs/demo/guide.md for policy.
set -uo pipefail

# --- color (auto-off when not a TTY so logs stay clean) -----------------------
if [[ -t 1 ]]; then
  C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_YELLOW=$'\033[1;33m'
  C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_RESET=$'\033[0m'
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_BOLD=""; C_DIM=""; C_RESET=""
fi

PASS=0; WARN=0; FAIL=0
FAILED_ITEMS=()

ok()   { printf '  %s[ OK ]%s  %s\n' "$C_GREEN" "$C_RESET" "$1"; PASS=$((PASS+1)); }
warn() { printf '  %s[WARN]%s  %s\n' "$C_YELLOW" "$C_RESET" "$1"; WARN=$((WARN+1)); }
fail() { printf '  %s[FAIL]%s  %s\n' "$C_RED" "$C_RESET" "$1"; FAIL=$((FAIL+1)); FAILED_ITEMS+=("$1"); }

print_help() {
  cat <<'EOF'
Usage: scripts/demo-preflight.sh [-h|--help]

Readiness check for the live RCA demo (report-centric Prometheus path).
Read-only; safe to rerun. No arguments needed — just run it on the demo host.

Environment:
  KUBECONFIG     standard kubectl config selection (optional)

Examples:
  scripts/demo-preflight.sh
  KUBECONFIG=~/demo.conf scripts/demo-preflight.sh

Exit code:
  0  GO    (report-centric path is demonstrable)
  1  NO-GO (at least one critical check failed)
EOF
}

case "${1:-}" in
  -h|--help) print_help; exit 0 ;;
  "") : ;;
  *) printf 'Unknown argument: %s\n\n' "$1" >&2; print_help >&2; exit 2 ;;
esac

printf '%s=== RCA demo preflight ===%s\n' "$C_BOLD" "$C_RESET"

# --- tooling -----------------------------------------------------------------
if command -v kubectl >/dev/null 2>&1; then
  ok "kubectl found ($(kubectl version --client --short 2>/dev/null || echo ok))"
else
  fail "kubectl not found on PATH (no cluster checks can run)"
  printf '\n%sResult: NO-GO — kubectl is required.%s\n' "$C_RED" "$C_RESET"
  exit 1
fi

# --- namespaces --------------------------------------------------------------
printf '\n%s[namespaces]%s\n' "$C_BOLD" "$C_RESET"
for ns in demo observability rca; do
  if kubectl get namespace "$ns" >/dev/null 2>&1; then
    ok "namespace '$ns' exists"
  else
    fail "namespace '$ns' missing"
  fi
done

# --- helper: deployment ready? ----------------------------------------------
# 0 = ready (readyReplicas >= replicas > 0), 1 = not ready / not found.
deploy_ready() {
  local ns="$1" name="$2"
  local spec ready
  spec=$(kubectl -n "$ns" get deploy "$name" -o 'jsonpath={.spec.replicas}' 2>/dev/null)
  [[ -z "$spec" ]] && spec=1            # default replicas=1 when omitted
  ready=$(kubectl -n "$ns" get deploy "$name" -o 'jsonpath={.status.readyReplicas}' 2>/dev/null)
  [[ -z "$ready" ]] && ready=0
  [[ "$ready" -ge "$spec" && "$spec" -gt 0 ]]
}

check_deploy() {  # ns name critical?(1|0)
  local ns="$1" name="$2" critical="${3:-0}"
  if kubectl -n "$ns" get deploy "$name" >/dev/null 2>&1; then
    if deploy_ready "$ns" "$name"; then
      ok "deploy $ns/$name ready"
    else
      if [[ "$critical" == "1" ]]; then fail "deploy $ns/$name NOT ready"
      else warn "deploy $ns/$name NOT ready"; fi
    fi
  else
    if [[ "$critical" == "1" ]]; then fail "deploy $ns/$name missing"
    else warn "deploy $ns/$name missing"; fi
  fi
}

# --- demo SUT (ns demo) ------------------------------------------------------
printf '\n%s[demo SUT — ns/demo]%s\n' "$C_BOLD" "$C_RESET"
# report-centric path: order (trigger) -> payment (upstream), entered via api-gateway
check_deploy demo order 1
check_deploy demo payment 1
check_deploy demo api-gateway 1
# supporting services — WARN only, do not block Mode B
check_deploy demo user 0
check_deploy demo inventory 0
check_deploy demo traffic-runner 0

# --- observability read-targets (ns observability) ---------------------------
printf '\n%s[observability — ns/observability]%s\n' "$C_BOLD" "$C_RESET"
# report-centric Prometheus path
check_deploy observability prometheus 1
check_deploy observability alertmanager 1
# Mode C (live Grafana Loki) stack — WARN only
check_deploy observability grafana 0
check_deploy observability loki 0
check_deploy observability alloy 0
check_deploy observability event-watcher 0

# --- RCA backend (ns rca): service + health ---------------------------------
printf '\n%s[RCA backend — ns/rca]%s\n' "$C_BOLD" "$C_RESET"
if kubectl -n rca get svc rca-backend >/dev/null 2>&1; then
  ok "service rca/rca-backend exists"
else
  fail "service rca/rca-backend missing"
fi
check_deploy rca rca-backend 1

# /health probe via in-pod python (the app image has no curl/wget; urllib always works).
if kubectl -n rca get deploy rca-backend >/dev/null 2>&1 && deploy_ready rca rca-backend; then
  health=$(kubectl -n rca exec deploy/rca-backend -- python -c \
    "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health', timeout=5).read().decode())" \
    2>/dev/null || true)
  if printf '%s' "$health" | grep -q '"ok"'; then
    ok "rca-backend /health -> ${health:-<empty>}"
  else
    fail "rca-backend /health probe failed (manual: kubectl -n rca port-forward deploy/rca-backend 8000:8000 && curl localhost:8000/health)"
  fi
else
  warn "rca-backend /health skipped (deployment not ready)"
fi

# --- summary -----------------------------------------------------------------
printf '\n%s=== summary ===%s  %sOK=%d%s  %sWARN=%d%s  %sFAIL=%d%s\n' \
  "$C_BOLD" "$C_RESET" "$C_GREEN" "$PASS" "$C_RESET" \
  "$C_YELLOW" "$WARN" "$C_RESET" "$C_RED" "$FAIL" "$C_RESET"

if [[ "$FAIL" -eq 0 ]]; then
  printf '%sGO — the report-centric Prometheus path is demonstrable.%s\n' "$C_GREEN" "$C_RESET"
  printf '%sNext:%s\n' "$C_DIM" "$C_RESET"
  printf '  kubectl -n rca port-forward deploy/rca-backend 8000:8000\n'
  printf '  scripts/demo-trigger-prometheus.sh\n'
  exit 0
else
  printf '%sNO-GO — fix before presenting:%s\n' "$C_RED" "$C_RESET"
  for item in "${FAILED_ITEMS[@]}"; do printf '    - %s\n' "$item"; done
  printf '%s(tip) %sRe-run after fixing: scripts/demo-preflight.sh\n' "$C_DIM" "$C_RESET"
  exit 1
fi
