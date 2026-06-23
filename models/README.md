# `models/` — Pydantic contracts AT PORTS (AD-9)

Trách nhiệm: Pydantic contract models chỉ ở port — `IncidentTrigger` (18-field §3.4 + `incident_id` optional) + `Evidence` (9-field §3.6 tier).

**⚠️ KHÔNG implement ở Story 0.1.** Contract 18-field/9-field = **Story 0.2**. File này chỉ placeholder/README.

Bài học (IR 2026-06-23): đếm field theo spec table, không theo label prose (`raw_payload_ref` LÀ §3.4 row 18).
