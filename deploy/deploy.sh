#!/usr/bin/env bash
# deploy/deploy.sh — build + deploy the RCA backend (Story 7.3 AC2).
#
# REPORTED, not executed in this POC dev env: there is NO local K8s here
# (kind/k3d/minikube/kubectl are absent — only docker). Run on a cluster-backed host. The agent
# code is UNCHANGED by this story; only the deploy artifacts (this dir) are new.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> building rca-backend:7.3"
docker build -t rca-backend:7.3 -f deploy/Dockerfile .

echo "==> loading into the cluster (kind: kind load docker-image; else your registry push)"
# kind load docker-image rca-backend:7.3   # uncomment for a kind cluster

echo "==> applying deploy/k8s/00-rca-backend.yaml (namespace rca)"
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
  # -> 202 {"investigation_id":"...","status":"accepted"}   (InvestigationAccepted)

  # poll the investigation — the HONEST single-node result:
  curl -fsS http://rca-backend.rca.svc.cluster.local:8000/api/investigations/<id>
  # -> {"status":"success","report":null,...}
  #
  # status="success" + report=None is CORRECT POC output: the default dispatcher
  # (ContextBuilderRunner) runs one node; no green RCA is manufactured (graph non-convergent
  # until 5-A1 real-transport; SqliteSaver durability is Story 7.4). The deploy proves WIRING,
  # not working RCA.
HONEST
