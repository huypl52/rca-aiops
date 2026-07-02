#!/usr/bin/env bash
# observability/deploy.sh — deploy the Story 7.2 observability READ-TARGET stack.
#
# Deploys Prometheus / Alertmanager / Loki / Grafana Alloy / Grafana Alerting / K8s Event
# Watcher into namespace `observability`, reading FROM the `demo` SUT namespace (Story 7.1).
# Mirrors demo/deploy.sh (kind-based, idempotent). The event-watcher image is built locally
# (project observability package + the kubernetes runtime client).
#
# ENVIRONMENT: this dev env has NO local K8s (kind/k3d/minikube/kubectl absent, only docker).
# This script is AUTHORED here; the live deploy + smoke is NOT executed and NOT claimed
# green in this environment (per Story 7.2 LOCK — ENVIRONMENT dependency). Run it where a
# kind cluster + the demo SUT namespace already exist.
set -euo pipefail

CLUSTER="${CLUSTER:-rca-demo}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
EVENT_WATCHER_IMAGE="observability/event-watcher:latest"
MANIFESTS="$HERE/manifests"

if [[ "${UNINSTALL:-0}" == "1" ]]; then
  echo ">> uninstalling observability stack"
  kubectl delete namespace observability --ignore-not-found=true
  exit 0
fi

echo ">> ensuring kind cluster '$CLUSTER'"
if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER"
fi
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
kind export kubeconfig --name "$CLUSTER" --kubeconfig "$KUBECONFIG"

echo ">> applying demo SUT first (the read source — Story 7.1)"
if [[ -f "$REPO/demo/deploy.sh" ]]; then
  bash "$REPO/demo/deploy.sh"
else
  echo "demo/deploy.sh absent — apply demo SUT separately" >&2
  exit 1
fi

echo ">> building event-watcher image (observability pkg + kubernetes client)"
docker build -f "$HERE/Dockerfile.event-watcher" -t "$EVENT_WATCHER_IMAGE" "$REPO"
kind load docker-image "$EVENT_WATCHER_IMAGE" --name "$CLUSTER"

echo ">> applying observability stack manifests"
kubectl apply -f "$MANIFESTS"

# Grafana alerting contact points/rules are file-provisioned from ConfigMaps and only
# reloaded reliably on startup. Restart Grafana so provisioning changes actually apply.
echo ">> restarting Grafana to reload file-provisioned alerting config"
kubectl -n observability rollout restart deployment/grafana

for d in prometheus alertmanager loki alloy grafana event-watcher; do
  echo ">> rollout status deployment/$d"
  kubectl -n observability rollout status "deployment/$d" --timeout=180s
done

echo ">> smoke: Prometheus ready + scraping demo"
kubectl -n observability port-forward svc/prometheus 19090:9090 &
PF=$!
trap 'kill "$PF" 2>/dev/null || true' EXIT
sleep 3
for attempt in 1 2 3 4 5; do
  if curl -fsS "http://127.0.0.1:19090/api/v1/targets?state=active" | grep -q demo; then
    kill "$PF" 2>/dev/null || true
    trap - EXIT
    echo ">> observability stack deployed (namespace: observability; reads: demo)"
    exit 0
  fi
  sleep 3
done
kill "$PF" 2>/dev/null || true
trap - EXIT
echo "demo scrape targets did not appear in Prometheus" >&2
exit 1
