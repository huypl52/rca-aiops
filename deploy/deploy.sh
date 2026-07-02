#!/usr/bin/env bash
# deploy/deploy.sh — build + deploy the RCA backend (Story 7.3 AC2).
#
# REPORTED, not executed in this POC dev env: there is NO local K8s here
# (kind/k3d/minikube/kubectl are absent — only docker). Run on a cluster-backed host. The agent
# code is UNCHANGED by this story; only the deploy artifacts (this dir) are new.
#
# PRODUCTION HARDENING (Phase 3, 2026-07-01):
# - The deployment now REQUIRES a Secret (rca-backend-secrets).
# - If that Secret is missing but RCA_HYPOTHESIS_LLM_API_KEY and
#   RCA_HYPOTHESIS_LLM_API_URL are present in the shell, this script creates it.
# - The manifest includes a PVC for durable checkpoint storage.
# - The manifest includes a PodDisruptionBudget.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> building rca-backend:7.3"
docker build -t rca-backend:7.3 -f deploy/Dockerfile .

echo "==> loading into the cluster (kind: kind load docker-image; else your registry push)"
kind load docker-image rca-backend:7.3 --name "${CLUSTER:-rca-demo}"

kubectl get namespace rca >/dev/null 2>&1 || kubectl create namespace rca >/dev/null
if ! kubectl -n rca get secret rca-backend-secrets >/dev/null 2>&1; then
  if [[ -n "${RCA_HYPOTHESIS_LLM_API_KEY:-}" && -n "${RCA_HYPOTHESIS_LLM_API_URL:-}" ]]; then
    echo "==> creating secret rca/rca-backend-secrets from current shell env"
    kubectl -n rca create secret generic rca-backend-secrets \
      --from-literal=RCA_HYPOTHESIS_LLM_API_KEY="$RCA_HYPOTHESIS_LLM_API_KEY" \
      --from-literal=RCA_HYPOTHESIS_LLM_API_URL="$RCA_HYPOTHESIS_LLM_API_URL" \
      --dry-run=client -o yaml | kubectl apply -f -
  else
    cat <<'EOF' >&2
ERROR: missing required Secret rca-backend-secrets in namespace rca.
Set these env vars first to let deploy/deploy.sh create it automatically:
  export RCA_HYPOTHESIS_LLM_API_KEY=<your-key>
  export RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint>

Or create it yourself before deploying:
  kubectl -n rca create secret generic rca-backend-secrets \
    --from-literal=RCA_HYPOTHESIS_LLM_API_KEY=<your-key> \
    --from-literal=RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint> \
    --dry-run=client -o yaml | kubectl apply -f -
EOF
    exit 1
  fi
fi

echo "==> applying deploy/k8s/00-rca-backend.yaml (namespace rca + PVC + Deployment + Service + PDB)"
kubectl apply -f deploy/k8s/00-rca-backend.yaml

echo "==> restarting rca-backend so the rebuilt local image tag is actually picked up"
kubectl -n rca rollout restart deployment/rca-backend

echo "==> waiting for rca-backend rollout"
kubectl -n rca rollout status deployment/rca-backend

cat <<'HONEST'
==> honest deploy note:

  This script proves image build/load + Kubernetes rollout + backend health.
  It does NOT, by itself, prove the full report-centric demo path.

  After port-forwarding the deployed backend, /ui should now be served from the same image:
    kubectl -n rca port-forward deploy/rca-backend 18000:8000
    curl -I http://127.0.0.1:18000/ui/
    curl http://127.0.0.1:18000/ui/app.js

  To validate the replayable Mode B flow end-to-end, run:
    scripts/demo-mode-b.sh

  Manual fallback:
    kubectl -n rca port-forward deploy/rca-backend 18000:8000
    scripts/demo-trigger-prometheus.sh

  Then confirm the investigation reaches terminal status and inspect the report:
    scripts/demo-watch-investigation.sh <investigation_id> --require-report

==> PRODUCTION DEPLOY NOTE:
  Before deploying, create the required Secret:
    kubectl -n rca create secret generic rca-backend-secrets \
      --from-literal=RCA_HYPOTHESIS_LLM_API_KEY=<your-key> \
      --from-literal=RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint> \
      --dry-run=client -o yaml | kubectl apply -f -
  Or use External Secrets Operator / Vault for production secret management.
HONEST
