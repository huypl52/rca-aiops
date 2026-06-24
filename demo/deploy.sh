#!/usr/bin/env bash
# demo/deploy.sh — bring up the 5 demo microservices on a local kind cluster (Story 7.1).
#
# Prerequisites: docker, kind, kubectl on PATH. (This repo's dev environment lacks a
# local K8s — see the Environment note in demo/README.md; the Python deliverable is
# verified in-process by the test suite regardless.)
#
# Usage:   ./demo/deploy.sh                     # create + build + apply + wait + smoke
#          CLUSTER=rca-demo ./demo/deploy.sh    # custom kind cluster name
#          UNINSTALL=1 ./demo/deploy.sh         # tear the namespace down instead
set -euo pipefail

CLUSTER="${CLUSTER:-rca-demo}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

if [[ "${UNINSTALL:-0}" == "1" ]]; then
  echo "==> uninstalling namespace 'demo' on cluster '$CLUSTER'"
  kubectl delete namespace demo --ignore-not-found=true
  exit 0
fi

echo "==> [1/6] ensuring kind cluster '$CLUSTER'"
if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER"
fi
kind export kubeconfig --name "$CLUSTER"

echo "==> [2/6] building the lean demo/app image (fastapi+uvicorn+httpx only)"
docker build -f "$HERE/Dockerfile" -t demo/app:latest "$REPO"

echo "==> [3/6] loading image into kind"
kind load docker-image demo/app:latest --name "$CLUSTER"

echo "==> [4/6] applying manifests (namespace + config + services + deployments + runner)"
kubectl apply -f "$HERE/k8s/"

echo "==> [5/6] waiting for rollouts"
for svc in api-gateway user order inventory payment; do
  kubectl -n demo rollout status "deployment/$svc" --timeout=180s
done

echo "==> [6/6] smoke (api-gateway /health via port-forward)"
kubectl -n demo port-forward deployment/api-gateway 18080:8080 >/tmp/demo-pf.log 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
sleep 3
curl -fsS http://127.0.0.1:18080/health
echo
echo "==> demo system up in namespace 'demo' (cluster '$CLUSTER')"
