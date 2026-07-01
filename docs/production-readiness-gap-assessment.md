# Production-Readiness Gap Assessment

**Project:** 26-rca-aiops
**Date:** 2026-07-01
**Phase:** 3 — Production readiness hardening + handoff
**Assessment owner:** worker-cong-marten

## Recommendation: Production-ready with conditions

The RCA backend is deployable and functionally proven on the seeded demo path, but several
production-critical concerns require operator action before a clean production claim. The
hardening changes landed in Phase 3 close the highest-value gaps. Remaining items are
environment-dependent or require organizational decisions.

## Gap assessment (ranked by severity)

### CRITICAL — LLM API key in plaintext K8s manifest

**Before:** `RCA_HYPOTHESIS_LLM_API_KEY` was a plaintext env var value (`ccs-internal-managed`)
in the Deployment manifest. Anyone with read access to the manifest or `kubectl describe deploy`
could see the key.

**Fix landed:** API key and LLM endpoint URL moved to a K8s Secret (`rca-backend-secrets`).
The manifest ships with placeholder values (`REPLACE_AT_DEPLOY_TIME`). Operators must create
the Secret with real values before deploying.

**Status:** Fixed in manifest. Operators must create the Secret at deploy time.

### CRITICAL — Hardcoded WSL2 gateway IP as LLM endpoint

**Before:** `RCA_HYPOTHESIS_LLM_API_URL` was hardcoded to `http://10.255.255.254:8317` — the
WSL2 gateway IP on the development host. This IP is meaningless in any other environment.

**Fix landed:** The URL is now sourced from the Secret. The manifest comment documents the
WSL2 dev value and instructs operators to set the actual endpoint for their environment.

**Status:** Fixed. Operator sets the endpoint at deploy time.

### HIGH — Checkpoint DB on ephemeral `/tmp`

**Before:** `RCA_CHECKPOINT_DB` pointed to `/tmp/rca-checkpoint.db`. Pod restarts, evictions,
or node pressure would lose all checkpoint state, breaking cross-restart investigation resume
(the core durability promise of Story 7.4).

**Fix landed:** A PVC (`rca-checkpoint-pvc`, 1Gi `ReadWriteOnce`) mounts at `/data`. The
checkpoint DB path is now `/data/rca-checkpoint.db`. State persists across pod restarts.

**Status:** Fixed in manifest. Operators must ensure a storage class is available.

### HIGH — No container security context

**Before:** The container ran as root by default with no security restrictions.

**Fix landed:**
- `runAsNonRoot: true`, `runAsUser: 1000`, `runAsGroup: 1000`
- `readOnlyRootFilesystem: true` with writable `/tmp` via emptyDir
- All Linux capabilities dropped (`drop: [ALL]`)
- `allowPrivilegeEscalation: false`
- Seccomp profile: `RuntimeDefault`
- Dockerfile: `USER 1000:1000`, `/data` owned by app user

**Status:** Fixed.

### MEDIUM — TCP-only health probes

**Before:** Readiness and liveness probes used `tcpSocket` only — they confirmed the port was
open but not that the app was actually serving HTTP.

**Fix landed:** Added `GET /health` endpoint to `routers/app.py` returning `{"status": "ok"}`.
Both probes now use `httpGet` against `/health`.

**Status:** Fixed. Tests in `tests/test_health.py`.

### MEDIUM — No PodDisruptionBudget

**Before:** No PDB — voluntary disruptions (node drain, cluster upgrade) could evict the single
replica with no guarantee of availability.

**Fix landed:** PDB (`rca-backend-pdb`) with `minAvailable: 1`.

**Status:** Fixed. Note: with `replicas: 1`, the PDB prevents eviction but does not provide HA.
Multi-replica deployment is an out-of-scope production decision (see below).

### MEDIUM — No PVC for observability data (Loki, Alertmanager)

**Before:** Loki and Alertmanager use `emptyDir` for data storage. Data is lost on pod restart.

**Fix NOT landed (out of scope):** This is an observability stack concern, not the RCA backend
deploy. For production, operators should:
- Loki: use S3/GCS object storage backend instead of filesystem
- Alertmanager: use a PVC for the `--storage.path` volume
- Prometheus: use a PVC or remote-write backend for long-term metrics storage

**Status:** Documented as operator requirement. Not fixed in this phase.

### LOW-MEDIUM — No structured logging configuration

**Before:** Uvicorn ran with default logging. No `LOG_LEVEL` env var or structured JSON output.

**Fix landed:** Dockerfile sets `LOG_LEVEL=INFO` env var and enables `--access-log` in the
uvicorn CMD. Operators can override `LOG_LEVEL` via K8s env var.

**Status:** Partially fixed. Full structured JSON logging (vs. uvicorn's text format) requires
a logging middleware or `--log-config` — deferred as a low-priority enhancement.

### LOW — No multi-replica / HA strategy

**Before and after:** `replicas: 1`. The backend is a single replica with no HA guarantee.

**Decision required:** Multi-replica deployment requires:
- A shared checkpoint store (PostgresSaver instead of SqliteSaver — the swap is designed but
  not implemented, see `graph/checkpoint.py` docstring)
- Session affinity or stateless dispatch (the in-process `InvestigationStore` is not shared)
- These are architectural decisions beyond Phase 3 scope.

**Status:** Out of scope. Documented as a production requirement.

### LOW — No network policy

**Before and after:** No NetworkPolicy restricts traffic to/from the `rca` namespace.

**Operator action:** In production, apply a NetworkPolicy that allows ingress only from the
`observability` namespace (Alertmanager, Grafana, event-watcher) and egress only to the LLM
endpoint and observability read targets.

**Status:** Out of scope. Documented as operator requirement.

## Summary table

| Gap | Severity | Status | Fix |
|---|---|---|---|
| Plaintext API key in manifest | CRITICAL | Fixed | Moved to K8s Secret |
| Hardcoded WSL2 IP as LLM endpoint | CRITICAL | Fixed | Sourced from Secret |
| Checkpoint DB on /tmp | HIGH | Fixed | PVC at /data |
| No container security context | HIGH | Fixed | Non-root, read-only FS, caps dropped |
| TCP-only health probes | MEDIUM | Fixed | HTTP /health endpoint |
| No PodDisruptionBudget | MEDIUM | Fixed | PDB minAvailable: 1 |
| No PVC for observability data | MEDIUM | Documented | Operator requirement |
| No structured logging | LOW-MEDIUM | Partial | LOG_LEVEL env + access log |
| No multi-replica / HA | LOW | Out of scope | Architectural decision |
| No network policy | LOW | Out of scope | Operator requirement |

## Remaining out-of-scope or environment-dependent production blockers

1. **Secret management at scale:** The manifest includes a Secret with placeholder values.
   Production should use External Secrets Operator, Vault, or cloud-native secret managers.
2. **Shared checkpoint store for HA:** SqliteSaver is single-node. Multi-replica deployment
   requires PostgresSaver or equivalent shared state backend.
3. **Observability data persistence:** Loki, Alertmanager, and Prometheus use ephemeral storage
   in the POC manifests. Production needs persistent volumes or external storage backends.
4. **Network policies:** No NetworkPolicy is defined. Production should restrict ingress/egress.
5. **LLM endpoint strategy for production:** The LLM proxy/endpoint must be a stable, in-cluster
   or properly routed external service. The WSL2 gateway IP is dev-only.
6. **Broad target-stack certification:** Only `DependencyTimeout/order-service` is proven E2E.
   Broader incident classes and service topologies require additional acceptance runs.
7. **Monitoring of the RCA backend itself:** No self-observability (metrics endpoint, tracing)
   is exposed by the backend. Production should add Prometheus `/metrics` and OpenTelemetry.
8. **TLS/HTTPS:** The backend serves plain HTTP. Production should terminate TLS at an ingress
   or sidecar proxy.
9. **Rate limiting / payload size bounds:** No explicit rate limiting or payload size limits
   beyond FastAPI/uvicorn defaults. Production should add API gateway rate limiting.
10. **Backup/restore for checkpoint data:** The PVC is not backed up. Production should define
    a backup strategy for the checkpoint DB.
