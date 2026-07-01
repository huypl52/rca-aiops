# Operator Runbook — RCA Backend Production Deployment

**Project:** 26-rca-aiops
**Date:** 2026-07-01
**Audience:** SRE / platform operators deploying the RCA backend to production

## 1. Pre-deploy checklist

Before applying the manifest, ensure:

- [ ] A Kubernetes cluster (>= 1.28) is reachable via `kubectl`
- [ ] A storage class is available for PVC provisioning (check: `kubectl get storageclass`)
- [ ] The LLM endpoint is accessible from inside the cluster (in-cluster proxy or external API)
- [ ] The LLM API key is available (do NOT commit it to git)
- [ ] The `observability` namespace is already deployed (trigger sources must exist)
- [ ] The `demo` namespace is already deployed (SUT must exist for the observability stack)

## 2. Secret creation

The backend manifest reads from an existing Secret and no longer ships placeholder credential
values. Create the real Secret BEFORE applying the manifest:

```bash
kubectl -n rca create secret generic rca-backend-secrets \
  --from-literal=RCA_HYPOTHESIS_LLM_API_KEY=<your-api-key> \
  --from-literal=RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint-url> \
  --dry-run=client -o yaml | kubectl apply -f -
```

For production, prefer External Secrets Operator or Vault:

```yaml
# Example: External Secrets Operator
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rca-backend-secrets
  namespace: rca
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: rca-backend-secrets
  data:
    - secretKey: RCA_HYPOTHESIS_LLM_API_KEY
      remoteRef:
        key: rca/llm
        property: api_key
    - secretKey: RCA_HYPOTHESIS_LLM_API_URL
      remoteRef:
        key: rca/llm
        property: api_url
```

## 3. LLM endpoint strategy

### Dev (WSL2)
- Use the WSL2 gateway IP: `http://10.255.255.254:8317`
- This is environment-specific and will NOT work in other environments

### Production (recommended patterns)
1. **In-cluster LLM proxy:** Deploy an OpenAI-compatible proxy (e.g. LiteLLM, cliproxyapi) as
   a K8s Service in the `rca` or a shared namespace. Set `RCA_HYPOTHESIS_LLM_API_URL` to the
   in-cluster DNS name (e.g. `http://llm-proxy.shared.svc.cluster.local:8317`).

2. **External API gateway:** Use a cloud API gateway or direct provider endpoint
   (e.g. `https://api.openai.com`). Ensure egress network policy and firewall rules allow
   the traffic.

3. **Service mesh:** If using a service mesh (Istio, Linkerd), route LLM traffic through the
   mesh for mTLS, retries, and observability.

**Do NOT use:**
- `host.docker.internal` (does not resolve inside kind on Linux)
- `localhost` or `127.0.0.1` (refers to the pod itself, not the host)

## 4. Storage

### Checkpoint PVC
The manifest creates a 1Gi PVC (`rca-checkpoint-pvc`) for the durable checkpoint DB.

- Default: uses the cluster's default storage class
- To specify a storage class, uncomment `storageClassName` in the PVC spec
- For high-write environments, increase the size (1Gi is sufficient for POC/demo scale)
- Back up the PVC regularly — checkpoint data is not replicated

### Observability stack storage
The POC observability manifests use `emptyDir` for Loki, Alertmanager, and Prometheus. For
production:
- **Loki:** configure S3/GCS object storage backend (change `storage_config` in `30-loki-alloy.yaml`)
- **Alertmanager:** add a PVC for `--storage.path`
- **Prometheus:** add a PVC or configure remote-write to a long-term storage backend

## 5. Deploy

```bash
# From the repo root:
docker build -t rca-backend:7.3 -f deploy/Dockerfile .
kind load docker-image rca-backend:7.3 --name <cluster-name>  # or registry push
kubectl apply -f deploy/k8s/00-rca-backend.yaml
kubectl -n rca rollout status deployment/rca-backend
```

## 6. Post-deploy verification

### 6.1 Pod health
```bash
kubectl -n rca get pods -l app.kubernetes.io/name=rca-backend
# EXPECTED: 1/1 Running

kubectl -n rca logs deploy/rca-backend --tail=20
# EXPECTED: uvicorn startup logs, no errors
```

### 6.2 Health endpoint
```bash
kubectl -n rca port-forward deploy/rca-backend 8000:8000 &
curl http://localhost:8000/health
# EXPECTED: {"status":"ok"}
```

### 6.3 Runtime mode
```bash
kubectl -n rca exec deploy/rca-backend -- env | grep RCA_
# EXPECTED:
#   RCA_CHECKPOINT_DB=/data/rca-checkpoint.db
#   RCA_HYPOTHESIS_LLM_ENABLED=true
#   RCA_HYPOTHESIS_LLM_PROVIDER=openai
#   RCA_HYPOTHESIS_LLM_MODEL=gpt-5.4-mini
#   RCA_HYPOTHESIS_LLM_API_KEY=<from secret>
#   RCA_HYPOTHESIS_LLM_API_URL=<from secret>
```

### 6.4 PVC bound
```bash
kubectl -n rca get pvc rca-checkpoint-pvc
# EXPECTED: Bound
```

### 6.5 PDB active
```bash
kubectl -n rca get pdb rca-backend-pdb
# EXPECTED: minAvailable=1, allowed disruptions=0 (with 1 replica)
```

### 6.6 Security context
```bash
kubectl -n rca get pod -l app.kubernetes.io/name=rca-backend -o jsonpath='{.items[0].spec.securityContext}'
# EXPECTED: {"runAsNonRoot":true,"runAsUser":1000,...}

kubectl -n rca get pod -l app.kubernetes.io/name=rca-backend -o jsonpath='{.items[0].spec.containers[0].securityContext}'
# EXPECTED: {"allowPrivilegeEscalation":false,"readOnlyRootFilesystem":true,...}
```

## 7. Trigger-path smoke test

```bash
# Send a test alert
kubectl -n rca port-forward deploy/rca-backend 8000:8000 &
curl -X POST http://localhost:8000/api/alerts/prometheus \
  -H 'content-type: application/json' \
  -d '{"fingerprint":"smoke-test-001","startsAt":"2026-07-01T10:00:00Z",
       "labels":{"alertname":"DependencyTimeout","service":"order-service","severity":"critical",
                 "scenario":"dependency_timeout"},
       "annotations":{"summary":"upstream dependency timing out",
                      "description":"order -> payment upstream errors"}}'
# EXPECTED: 202 {"investigation_id":"...","status":"accepted"}

# Poll the investigation
curl http://localhost:8000/api/investigations/<investigation_id>
# EXPECTED: {"status":"running",...} or {"status":"success",...}
```

## 8. Common operational issues

### Pod stuck in Pending
- Check PVC: `kubectl -n rca get pvc` — if Pending, no storage class is available
- Fix: set `storageClassName` in the PVC to an available class, or install a default provisioner

### Pod crashes with `permission denied`
- The container runs as UID 1000 with read-only root FS
- If the app needs to write outside `/data` or `/tmp`, add a writable volume mount

### LLM planner falls back to deterministic
- Check: `kubectl -n rca logs deploy/rca-backend | grep -i fallback`
- Cause: LLM endpoint unreachable or API key invalid
- Fix: verify the Secret values, verify network connectivity from the pod to the LLM endpoint
- The deterministic fallback is SAFE — the system continues to function with rule-based hypotheses

### Checkpoint DB not persisting
- Check PVC is Bound: `kubectl -n rca get pvc rca-checkpoint-pvc`
- Check the DB file exists: `kubectl -n rca exec deploy/rca-backend -- ls -la /data/`
- If PVC was recreated, checkpoint data was lost (expected for a new PVC)

## 9. Scaling considerations

The current deployment is `replicas: 1`. To scale horizontally:

1. **Replace SqliteSaver with PostgresSaver** — the checkpoint store must be shared across pods.
   The swap is designed (see `graph/checkpoint.py` docstring) but not implemented.
2. **Replace in-process InvestigationStore** — the current store is per-pod. A shared store
   (Redis, Postgres) is needed for multi-replica.
3. **Add session affinity** — or make the ingest endpoint stateless (dispatch to a queue).
4. **Increase PDB minAvailable** — set to `replicas - 1` for rolling update safety.

These are architectural decisions beyond the current POC scope.

## 10. Security hardening checklist (production)

- [ ] Secret created with real API key and endpoint URL
- [ ] No plaintext secrets in manifests or git
- [ ] Container runs as non-root (verified in post-deploy §6.6)
- [ ] readOnlyRootFilesystem enabled
- [ ] All capabilities dropped
- [ ] NetworkPolicy applied (restrict ingress to observability namespace, egress to LLM endpoint)
- [ ] TLS terminated at ingress or sidecar
- [ ] API key rotated regularly (via External Secrets Operator or manual rotation)
- [ ] Audit logging enabled on the cluster
- [ ] RBAC reviewed (currently no ClusterRole — least privilege)
