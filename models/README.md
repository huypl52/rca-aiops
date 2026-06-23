# `models/` — Pydantic contracts AT PORTS (AD-9)

Trách nhiệm: Pydantic contract models chỉ ở port — `IncidentTrigger`
(18-field §3.4 + `incident_id` optional H3) + `Evidence` (9-field §3.6 tier).

## Story 0.2 — ĐÃ implement

- `models/incident_trigger.py` — `IncidentTrigger` (đúng 18 field §3.4 theo thứ
  tự bảng, row 18 = `raw_payload_ref` None POC) + optional `incident_id` (H3,
  FR-2/DEC-1, KHÔNG phải field §3.4) + enums `TriggerSource` / `Severity` /
  `SignalType`.
- `models/evidence.py` — `Evidence` (9 field theo tier: 5 required non-null /
  2 optional-nullable / 2 derived list `[]`) + `TimestampRange` (`{start, end}`
  ISO-8601 UTC).

## Ranh giới (AD-9 port boundary)

- Models = port contract, validate-on-ingress (api-gateway) /
  model_validate-on-read (evidence_normalizer). KHÔNG import `routers`/
  `services`/`graph`/`adapters`/`tools` (one-way AD-1).
- **Consumer wiring DEFERRED**: routers ingest normalize → IncidentTrigger =
  Story 1-1 (E1); `evidence_normalizer` node → Evidence = Story 4-2 (E4).
  Story 0.2 chỉ DEFINE models + wire CI gate #5.
- `extra="forbid"` trên cả 2 model — reject invented field runtime (phòng vệ
  chiều sâu cùng CI gate #5, gate #5 chặn drift ở mức source/CI).

## Nguồn sự thật field vocabulary

- Canonical field-set (gate #5 drift source-of-truth) = `ci/contract_schema.py`,
  KHÔNG derive từ model (nếu không gate vô nghĩa).
- Đếm field theo spec **table**, KHÔNG prose (bài học D-1 17-vs-18:
  `raw_payload_ref` LÀ §3.4 row 18).
