#!/usr/bin/env bash
# deploy/deploy.sh — build + deploy the RCA backend (Story 7.3 AC2).
#
# REPORTED, not executed in this POC dev env: there is NO local K8s here
# (kind/k3d/minikube/kubectl are absent — only docker). Run on a cluster-backed host. The agent
# code is UNCHANGED by this story; only the deploy artifacts (this dir) are new.
#
# PRODUCTION HARDENING (Phase 3, 2026-07-01):
# - The deployment now REQUIRES a pre-created Secret (rca-backend-secrets).
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
  cat <<'EOF' >&2
ERROR: missing required Secret rca-backend-secrets in namespace rca.
Create it before deploying:
  kubectl -n rca create secret generic rca-backend-secrets \
    --from-literal=RCA_HYPOTHESIS_LLM_API_KEY=<your-key> \
    --from-literal=RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint> \
    --dry-run=client -o yaml | kubectl apply -f -
EOF
  exit 1
fi

echo "==> applying deploy/k8s/00-rca-backend.yaml (namespace rca + PVC + Deployment + Service + PDB)"
kubectl apply -f deploy/k8s/00-rca-backend.yaml

echo "==> waiting for rca-backend rollout"
kubectl -n rca rollout status deployment/rca-backend

cat <<'HONEST'
==> honest POC smoke (expected output, NOT a green RCA):

  # a 7.2 trigger source POSTs an alert body the chaos layer (chaos.inject) reproduces:
  curl -fsS -X POST http://rca-backend.rca.svc.cluster.local:8000/api/alerts/prometheus \
       -H 'content-type: application/json' \
       -d '{"fingerprint":"chaos-dependency_timeout","startsAt":"2026-06-24T10:00:00Z",
            "labels":{"alertname":"DependencyTimeout","service":"order","severity":"critical",
                      "scenario":"dependency_timeout"},
            "annotations":{"summary":"upstream dependency timing out",
                           "description":"order -> payment upstream errors"}}'
  # -> 202 {"investigation_id":"..."}

  # poll the investigation — the HONEST single-node result:
  curl -fsS http://rca-backend.rca.svc.cluster.local:8000/api/investigations/<id>
  # -> {"status":"success","report":null,...}
  #
  # status="success" + report=None is CORRECT POC output: the default dispatcher
  # (ContextBuilderRunner) runs one node; no green RCA is manufactured (graph non-convergent
  # until 5-A1 real-transport; SqliteSaver durability is Story 7.4). The deploy proves WIRING,
  # not working RCA.

==> PRODUCTION DEPLOY NOTE:
  Before deploying, create the required Secret:
    kubectl -n rca create secret generic rca-backend-secrets \
      --from-literal=RCA_HYPOTHESIS_LLM_API_KEY=<your-key> \
      --from-literal=RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint> \
      --dry-run=client -o yaml | kubectl apply -f -
  Or use External Secrets Operator / Vault for production secret management.
HONEST
