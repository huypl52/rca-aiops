#!/usr/bin/env bash
# scripts/demo-trigger-prometheus.sh — send the validated DependencyTimeout alert to the RCA backend.
#
# POSTs the report-centric demo payload (alertname=DependencyTimeout, service=order-service)
# to POST /api/alerts/prometheus, then prints the HTTP status and the extracted
# investigation_id, plus the next poll command. This is the trigger half of the
# report-centric demo path; it does NOT wait for the investigation to finish.
#
# Backend URL resolution (first wins): --url/-u flag, else $RCA_BACKEND_URL, else
# http://localhost:8000 (assumes `kubectl -n rca port-forward deploy/rca-backend 8000:8000`).
# This dev box has no cluster; run it on the demo host. See docs/demo-operator-cheatsheet.md.
set -uo pipefail

# --- color (auto-off when not a TTY) -----------------------------------------
if [[ -t 1 ]]; then
  C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_YELLOW=$'\033[1;33m'
  C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_RESET=$'\033[0m'
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_BOLD=""; C_DIM=""; C_RESET=""
fi

# Default backend URL: env override, else localhost (port-forward assumption).
BACKEND_URL="${RCA_BACKEND_URL:-http://localhost:8000}"

# The validated DependencyTimeout payload (matches docs/demo-operator-cheatsheet.md §8, Mode B).
read -r -d '' PAYLOAD <<'JSON' || true
{"fingerprint":"demo-dependency-timeout-001","startsAt":"2026-07-01T10:00:00Z","labels":{"alertname":"DependencyTimeout","service":"order-service","severity":"critical","scenario":"dependency_timeout","namespace":"demo"},"annotations":{"summary":"upstream dependency timing out","description":"order -> payment upstream errors"}}
JSON

print_help() {
  cat <<EOF
Usage: scripts/demo-trigger-prometheus.sh [-u URL|--url URL] [-h|--help]

Send the validated DependencyTimeout Prometheus alert to the RCA backend and
print the HTTP result + investigation_id.

Backend URL (first wins):
  -u, --url URL     e.g. http://localhost:8000
  \$RCA_BACKEND_URL  environment override
  (default)         http://localhost:8000

Examples:
  # after: kubectl -n rca port-forward deploy/rca-backend 8000:8000
  scripts/demo-trigger-prometheus.sh

  RCA_BACKEND_URL=http://localhost:8000 scripts/demo-trigger-prometheus.sh
  scripts/demo-trigger-prometheus.sh --url http://rca-backend.rca.svc.cluster.local:8000

Exit code:
  0  accepted (HTTP 202 + investigation_id present)
  1  rejected / network error / no investigation_id
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -u|--url) BACKEND_URL="${2:?--url requires a value}"; shift 2 ;;
    -h|--help) print_help; exit 0 ;;
    *) printf 'Unknown argument: %s\n\n' "$1" >&2; print_help >&2; exit 2 ;;
  esac
done

ENDPOINT="${BACKEND_URL%/}/api/alerts/prometheus"

printf '%s=== RCA demo trigger (Prometheus, DependencyTimeout) ===%s\n' "$C_BOLD" "$C_RESET"
printf '%sPOST %s%s\n' "$C_DIM" "$ENDPOINT" "$C_RESET"

# Capture HTTP status code + body separately so both can be shown clearly.
http_code=$(curl -sS --connect-timeout 5 --max-time 20 \
  -o /tmp/rca-trigger-body.$$ -w '%{http_code}' \
  -X POST "$ENDPOINT" \
  -H 'content-type: application/json' \
  --data "$PAYLOAD" 2>/tmp/rca-trigger-err.$$) || curl_rc=$?
body=$(cat /tmp/rca-trigger-body.$$ 2>/dev/null || true)
rm -f /tmp/rca-trigger-body.$$ /tmp/rca-trigger-err.$$

# Network-level failure (curl could not complete the request).
if [[ -n "${curl_rc:-}" ]]; then
  printf '  %s[FAIL]%s curl request failed (rc=%s). Is the port-forward up?\n' "$C_RED" "$C_RESET" "$curl_rc"
  printf '  %srun:%s kubectl -n rca port-forward deploy/rca-backend 8000:8000\n' "$C_DIM" "$C_RESET"
  exit 1
fi

printf '  HTTP status: %s%s%s\n' "$C_BOLD" "$http_code" "$C_RESET"

# Extract investigation_id: prefer jq, fall back to a sed/grep scan (no jq dependency).
if command -v jq >/dev/null 2>&1; then
  investigation_id=$(printf '%s' "$body" | jq -r '.investigation_id // empty' 2>/dev/null || true)
else
  investigation_id=$(printf '%s' "$body" | sed -n 's/.*"investigation_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
fi

if [[ "$http_code" == "202" && -n "$investigation_id" ]]; then
  printf '  %sinvestigation_id: %s%s%s\n' "$C_GREEN" "$C_BOLD" "$investigation_id" "$C_RESET"
  printf '\n%sNext — poll the investigation:%s\n' "$C_DIM" "$C_RESET"
  printf '  curl %s/api/investigations/%s\n' "${BACKEND_URL%/}" "$investigation_id"
  printf '%s(hint)%s status=running -> keep polling; status=success + non-null report = validated report path.\n' "$C_DIM" "$C_RESET"
  exit 0
fi

# Non-202 or missing id: show the body so the presenter sees the real rejection.
printf '  %s[FAIL]%s no usable investigation_id (HTTP %s).\n' "$C_RED" "$C_RESET" "$http_code"
printf '  response body: %s\n' "${body:-<empty>}"
exit 1
