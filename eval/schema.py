"""eval/schema — ground-truth + inject-contract dataclasses (Story 6.1 — §3.7 benchmark scaffold).

Plain JSON-safe frozen dataclasses (AD-9 — NO Pydantic models are DEFINED here; the contract
field-vocabulary lives in ``ci.contract_schema`` and the runtime models live in ``models/``). The 11
``Scenario`` instances in :mod:`eval.scenarios` are **DERIVED from spec §3.7** (the scenario /
trigger-source / canonical-trigger / supporting-evidence table) — NOT invented — and the A8
multi-node ``prod_only`` marking is **DERIVED from the brainstorm ground-truth** (disk + memory are
trustworthy ONLY multi-node — A8/Q15), NOT invented. No 12th scenario, no renamed canonical.

Import-pure (gate #2 does NOT enforce ``eval/`` — it is NOT a contracted layer, so ``eval/``
SELF-DISCIPLINES): this module imports STDLIB ONLY (``collections.abc`` / ``dataclasses``). It
NEVER imports ``ci.contract_schema`` / ``models`` / ``graph`` / ``adapters`` / ``routers`` /
``services`` / ``tools``. This is a conservative subset of the allowed
``ci.contract_schema + stdlib`` self-discipline: the scenario ``trigger_source`` / ``signal_type``
/ ``severity`` are held as plain ``str`` here (NOT statically coupled to the spec-domain
frozensets), and their spec-domain membership is enforced in the TEST
(``tests/test_eval_benchmark_scenarios.py`` asserts each value ``in`` the ``ci.contract_schema``
frozenset). Keeping the data layer dependency-free keeps the ground-truth trivially JSON-
serializable (AD-9).

The inject → Evidence pipeline (real adapter + real normalizer) lives in
``tests/eval_harness.py`` — the ONE place that imports ``adapters`` + ``graph``. ``eval/`` holds
DATA + the deterministic inject contract only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# eval/ never imports ``models`` — see module docstring. The frozen dataclasses below are plain
# JSON-safe (AD-9); the 9-field Evidence / 18-field IncidentTrigger contracts are validated in the
# TEST (``tests/test_eval_benchmark_scenarios.py``), not coupled at the data layer.


@dataclass(frozen=True)
class RootCauseLabel:
    """Ground-truth root-cause LABEL the 6.2 binary conjunction scores against (§3.7).

    ``faulty_service`` is the service the agent's RCA report must point at; ``hypothesis`` is the
    human-readable fault description. Both are **DERIVED** from §3.7 supporting-evidence + the POC
    demo service vocabulary. NOTE: spec §3.7 gives the fault TYPE + supporting evidence per
    scenario, NOT a pinned faulty-service string — the labels here are conservative + explicitly
    flagged for leader confirmation in REVIEW-READY (they are a best-effort derivation, not a
    spec mandate; the SCHEMA + 11-scenario SET + A8 marking are the spec-mandated part).
    """

    faulty_service: str
    hypothesis: str


@dataclass(frozen=True)
class ExpectedEvidence:
    """Conjunction-condition-a contract — the source evidence the inject MUST routably produce.

    Story 6.2 consumes this: the agent's emitted ``Evidence.source_type`` / ``source_name`` must
    COVER these (conjunction condition *a* — routable evidence exists for the scenario).
    ``adapter_method`` is one of the 8 ``ReadOnlyAdapterPort`` methods the scenario's inject drives
    (``query_promql`` / ``query_loki`` / ``k8s_get`` / ``k8s_describe`` / ``k8s_logs`` /
    ``k8s_get_events`` / ``search_playbook`` / ``topology_read``).
    """

    source_type: str  # prometheus | loki | kubernetes | playbook | topology
    source_name: str
    adapter_method: str


@dataclass(frozen=True)
class InjectCall:
    """One canned read-only call: the adapter method + its kwargs + the transport response.

    The test harness wraps a REAL ``CompositeReadOnlyAdapter(ScenarioTransport)`` and calls
    ``getattr(adapter, adapter_method)(**kwargs)``; the ``ScenarioTransport``
    (``tests/eval_harness.py``) returns ``response`` (a canned ``RawBackendResponse`` wire shape —
    JSON-safe, modeled on the real backend shapes ``FakeReadOnlyTransport`` models). Same inject →
    byte-stable ``RawOutput`` (AD-12 / NFR-Determinism). ``kwargs`` carries the adapter-method
    keyword args (including the ``time_window`` mapping for the windowed prometheus/loki tools).
    """

    adapter_method: str  # one of the 8 ReadOnlyAdapterPort methods
    kwargs: Mapping[str, object]  # adapter-method kwargs (JSON-safe); time_window for prom/loki
    response: Mapping[str, object]  # canned RawBackendResponse wire shape (JSON-safe)


@dataclass(frozen=True)
class Scenario:
    """One §3.7 benchmark scenario — the unit the 6.2 binary conjunction evaluates.

    Every field is **DERIVED** from spec §3.7 + the brainstorm (A8) + the POC ingest fixtures
    (service vocabulary), never invented:

      - ``name``            : the §3.7 snake_case scenario id (e.g. ``dependency_timeout``).
      - ``canonical_trigger``: the §3.7 PascalCase canonical (∈ the 11 frozen triggers).
      - ``trigger_source``  : the §3.7 trigger source (∈ ``TRIGGER_SOURCES`` — 3 sources).
      - ``signal_type``     : derived from ``trigger_source`` (∈ ``TRIGGER_SIGNAL_TYPES`` — metric /
                              log / kubernetes_event).
      - ``severity``        : derived from §3.7 + the ingest fixtures (∈ ``TRIGGER_SEVERITIES``).
      - ``service``/``namespace``: POC demo vocabulary (namespace = ``demo``).
      - ``supporting_evidence``: the §3.7 "Supporting evidence chính" text (verbatim).
      - ``root_cause``      : the ground-truth label (see :class:`RootCauseLabel`).
      - ``expected_evidence``: conjunction-condition-a source contract (6.2 consumes).
      - ``inject``          : the deterministic canned read-only inject (AC1: inject → stable symptom).
      - ``prod_only``       : A8 multi-node marking (brainstorm:53,74 — disk/memory ONLY).
      - ``non_deterministic_extension``: ``None`` | ``"memory_leak"`` | ``"latency_spike"`` — the two
        scenarios whose REAL metric shape is non-deterministic (brainstorm M3); the POC canned
        fixtures ARE deterministic — this flag records that the REAL metric would need a tolerance
        window, which lands at 6.3 (NOT built here). ORTHOGONAL to ``prod_only``: ``memory_leak``
        carries BOTH flags; ``disk_pressure`` carries ``prod_only`` only; ``latency_spike`` carries
        ``non_deterministic_extension`` only.
    """

    name: str
    canonical_trigger: str
    trigger_source: str  # ∈ TRIGGER_SOURCES
    signal_type: str  # ∈ TRIGGER_SIGNAL_TYPES
    severity: str  # ∈ TRIGGER_SEVERITIES
    service: str
    namespace: str
    supporting_evidence: str
    root_cause: RootCauseLabel
    expected_evidence: tuple[ExpectedEvidence, ...]
    inject: tuple[InjectCall, ...]
    prod_only: bool
    non_deterministic_extension: str | None


__all__ = [
    "ExpectedEvidence",
    "InjectCall",
    "RootCauseLabel",
    "Scenario",
]
