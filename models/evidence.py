"""Evidence contract model — 9 fields spec §3.6, tiered (AD-6 MUST).

Pydantic v2 model living at the port (`evidence_normalizer` model_validate-on-
read in E4). The canonical field vocabulary lives in `ci.contract_schema`
(gate #5 single source of truth). Consumer wiring (evidence_normalizer node)
is Story 4-2, NOT here.

Tiers (project-context Cat 2):
  - required (non-null): source_type, source_name, query, timestamp_range, summary
  - optional-nullable: raw_excerpt, confidence
  - derived (list, [] when empty, NEVER null): supports, contradicts
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TimestampRange(BaseModel):
    """Evidence time window — {start, end} ISO-8601 UTC (spec §3.6)."""

    model_config = ConfigDict(extra="forbid")

    start: str
    """Window start — ISO-8601 UTC."""

    end: str | None = None
    """Window end — ISO-8601 UTC; None while the incident is still firing."""


class Evidence(BaseModel):
    """Normalized evidence object — 9 fields spec §3.6, tiered (AD-6 MUST).

    `extra="forbid"` rejects invented fields at runtime (defense-in-depth
    alongside CI gate #5, which guards source-level drift). `supports`/
    `contradicts` are derived lists filled by `evidence_normalizer`/`reflector`
    (E4), not by raw tools.
    """

    model_config = ConfigDict(extra="forbid")

    # --- required (non-null) ---
    source_type: str
    """Type of evidence source (e.g. prometheus, loki, kubernetes, playbook, topology)."""

    source_name: str
    """Name/identifier of the source (service, endpoint, playbook id)."""

    query: str
    """The read-only query that produced this evidence (PromQL/LogQL/K8s/etc.)."""

    timestamp_range: TimestampRange
    """Time window the evidence covers (ISO-8601 UTC)."""

    summary: str
    """Human-readable summary of the evidence."""

    # --- optional-nullable ---
    raw_excerpt: str | None = None
    """Raw excerpt backing the summary; None when not applicable. Required non-null for any root-cause claim (AD-6 no-RC-without-evidence)."""

    confidence: float | None = None
    """Numeric confidence 0.0–1.0 (AD-7 authority); None until derived."""

    # --- derived (list, [] when empty, NEVER null) ---
    supports: list[str] = Field(default_factory=list)
    """Hypothesis ids this evidence supports (filled by normalizer/reflector)."""

    contradicts: list[str] = Field(default_factory=list)
    """Hypothesis ids this evidence contradicts (filled by normalizer/reflector)."""
