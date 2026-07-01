"""tests for graph.nodes.rca_writer — Story 5.1 (AD-6 / AD-7 / AD-9 / AD-12 / FR-9 / T9 / AC1-AC3).

Covers the DEEP-review spotlights for the §3.5 WRT node (the output-side anti-hallucination backbone,
twin of DEC-3 on the loop side):
  - **AD-6 (decisive / the backbone)**: every root-cause claim cites ≥1 evidence with a NON-NULL
    ``raw_excerpt``. A hypothesis backed ONLY by null/absent/empty ``raw_excerpt`` evidence is NEVER cited
    — the null-excerpt evidence is textually UNREACHABLE as a citation (the WRT twin of DEC-3: the unsafe
    output is unreachable by construction, not merely asserted-against). No-evidence → no-claim; the
    hypothesis is DROPPED to ``open_questions``, never invented.
  - **AD-7 single-authority**: ``confidence`` = ``{ceiling_confidence, categorical}`` projected VERBATIM
    from ``sufficiency`` — the writer PROJECTS, never recomputes (a sufficiency whose value a re-derivation
    would estimate differently is projected AS-IS). ``None`` when ``sufficiency`` is absent/non-dict.
  - **AD-9 (report is a STATE DICT, NOT a Pydantic model)**: the report is a plain JSON-safe ``dict`` on the
    14-key spine (key #14 ``report``); there is NO ``models/report.py``; the node imports NO pydantic.
  - **AD-12 determinism**: same state → identical report across calls AND across PYTHONHASHSEED (every
    emitted list is sorted by an explicit tuple key).
  - **FR-9 / 6-key report shape**: ``{root_cause, evidence_backing, confidence, open_questions,
    uncertainty, remediation}``; ranking priority-ASC then id-ASC; ``evidence_backing`` the deduped cited
    union; ``open_questions`` sorted; ``remediation`` ``[]`` (T9 / AC3 — remediation OFF by default, never
    invented).
  - **Constraint 5 never-raise**: malformed state / non-list evidence or hypotheses / non-dict sufficiency /
    a non-Mapping ``state`` → deterministic degrade to the honest EMPTY report, NEVER an exception.

AD-1 note: this test file imports ``graph.compiled`` + ``graph.nodes.rca_writer`` — tests are CONSUMERS
(outside ``root_packages``; the import-linter contract governs production modules only). The WRT NODE
itself imports {graph, stdlib, typing} ONLY (AST-asserted below). Read-only (AD-3) is enforced at CI gate
#1; the node has no adapter/tool in scope (proven by the import-purity test — it cannot call one).

AST-discipline (docstring-immune): assertions are statement-level.
"""

from __future__ import annotations

import ast
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

from graph.compiled import NA_PROCEED, NA_WRITE, CompiledGraphRunner, build_compiled_graph
from graph.nodes.rca_writer import build_rca_writer
from graph.state import InvestigationState, JsonValue, create_initial_state

# AD-1 note: tests are CONSUMERS (outside root_packages) — importing graph.* is fine. The WRT NODE's
# import surface is AST-asserted below (⊆ {graph, stdlib, typing}).

_WRT_PATH = Path("graph/nodes/rca_writer.py")
_WRT_SRC = _WRT_PATH.read_text(encoding="utf-8")
_WRT_TREE = ast.parse(_WRT_SRC)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _state(
    *,
    hypotheses: list[dict[str, JsonValue]] | None = None,
    evidence: list[dict[str, JsonValue]] | None = None,
    sufficiency: dict[str, JsonValue] | None = None,
) -> InvestigationState:
    """Build an InvestigationState seeding only the three WRT input keys (honest synthetic)."""
    state = create_initial_state()
    if hypotheses is not None:
        state["hypotheses"] = hypotheses
    if evidence is not None:
        state["evidence"] = evidence
    if sufficiency is not None:
        state["sufficiency"] = sufficiency
    return state


def _hyp(hid: str, priority: int = 1, status: str = "open") -> dict[str, JsonValue]:
    """A hypothesis (EXACTLY {id, priority, plan, status}; claim rides inside plan)."""
    return {"id": hid, "priority": priority, "plan": {}, "status": status}


def _evidence(
    *,
    supports: list[str],
    raw_excerpt: str | None,
    source_name: str = "checkout",
    source_type: str = "prometheus",
    query: str = "rate(...)",
    summary: str = "latency spike",
    start: str = "2026-06-24T00:00:00Z",
    end: str | None = "2026-06-24T01:00:00Z",
) -> dict[str, JsonValue]:
    """An honest-synthetic 9-field Evidence dict (real ENV shape, with ``supports`` injected — the POC
    real graph leaves ``supports=[]``; per K2 we inject the hypothesis→evidence linkage synthetically)."""
    window: dict[str, JsonValue] = {"start": start}
    if end is not None:
        window["end"] = end
    ev: dict[str, JsonValue] = {
        "source_type": source_type,
        "source_name": source_name,
        "query": query,
        "summary": summary,
        "timestamp_range": window,
        "supports": cast(JsonValue, supports),
    }
    if raw_excerpt is not None:
        ev["raw_excerpt"] = raw_excerpt
    return ev


def _sufficiency(
    *,
    floor_pass: bool = True,
    ceiling_confidence: float | None = 0.9,
    categorical: str | None = "high",
    matched_count: int = 2,
    min_count: int = 2,
    gap: str | None = None,
    floor_reason: str = "pass",
) -> dict[str, JsonValue]:
    """The 4-3 reflector sufficiency verdict shape (the AD-7 authority the writer PROJECTS)."""
    verdict: dict[str, JsonValue] = {
        "floor_pass": floor_pass,
        "matched_count": matched_count,
        "min_count": min_count,
        "floor_reason": floor_reason,
    }
    if ceiling_confidence is not None:
        verdict["ceiling_confidence"] = ceiling_confidence
    else:
        verdict["ceiling_confidence"] = None
    if categorical is not None:
        verdict["categorical"] = categorical
    else:
        verdict["categorical"] = None
    if gap is not None:
        verdict["gap"] = gap
    return verdict


# ---------------------------------------------------------------------------
# AD-6 — every root-cause claim cites ≥1 evidence with a NON-NULL raw_excerpt
# ---------------------------------------------------------------------------


def test_ad6_grounded_hypothesis_cited_with_real_excerpt() -> None:
    """AC2/AD-6: a hypothesis backed by citable evidence → a root_cause candidate whose citation carries
    the REAL raw_excerpt (grounded, not invented)."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt="p99 latency 4.2s > 1s")],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    root_cause = cast(list[dict[str, JsonValue]], report["root_cause"])
    assert len(root_cause) == 1
    candidate = root_cause[0]
    assert candidate["hypothesis_id"] == "H01"
    citations = cast(list[dict[str, JsonValue]], candidate["citations"])
    assert len(citations) == 1
    assert (
        citations[0]["raw_excerpt"] == "p99 latency 4.2s > 1s"
    )  # AD-6: the REAL excerpt, grounded


def test_ad6_drop_probe_null_excerpt_never_cited() -> None:
    """AD-6 / DEC-3-twin (decisive): a hypothesis whose ONLY supporting evidence has a NULL raw_excerpt is
    NEVER cited — the null-excerpt evidence is textually UNREACHABLE as a citation. The hypothesis is
    DROPPED to open_questions; NO root-cause claim is invented."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt=None)],  # null excerpt → uncitable
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert (
        cast(list[dict[str, JsonValue]], report["root_cause"]) == []
    )  # NO claim (no-evidence → no-claim)
    assert report["open_questions"] == ["H01"]  # dropped, surfaced honestly
    assert (
        cast(list[dict[str, JsonValue]], report["evidence_backing"]) == []
    )  # null excerpt NOT in backing


def test_ad6_empty_string_excerpt_not_citable() -> None:
    """AD-6: an EMPTY-STRING raw_excerpt is NOT a citation (non-empty str required) → hypothesis dropped."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt="")],  # empty → not a citation
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert cast(list[dict[str, JsonValue]], report["root_cause"]) == []
    assert report["open_questions"] == ["H01"]


def test_ad6_no_supporting_evidence_no_claim() -> None:
    """AD-6: a hypothesis with NO supporting evidence (supports does not name it) → no-claim → open."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01"), _hyp("H02")],
            evidence=[_evidence(supports=["H02"], raw_excerpt="oom-killed")],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    candidates = cast(list[dict[str, JsonValue]], report["root_cause"])
    assert [c["hypothesis_id"] for c in candidates] == ["H02"]  # only the grounded one
    assert report["open_questions"] == ["H01"]  # H01 has no citation → dropped


def test_ad6_supports_non_list_not_citable() -> None:
    """AD-6 / never-raise: evidence with a NON-LIST ``supports`` (e.g. a bare str) → not a citation path
    (Constraint 5 defensive read); never raises."""
    node = build_rca_writer()
    malformed = _evidence(supports=[], raw_excerpt="x")
    malformed["supports"] = "H01"  # malformed on purpose (str, not list)
    out = node(_state(hypotheses=[_hyp("H01")], evidence=[malformed], sufficiency=_sufficiency()))
    report = cast(dict[str, JsonValue], out["report"])
    assert (
        cast(list[dict[str, JsonValue]], report["root_cause"]) == []
    )  # non-list supports → no link
    assert report["open_questions"] == ["H01"]


def test_ad6_null_excerpt_cannot_leak_into_a_mixed_citation() -> None:
    """AD-6: a candidate backed by BOTH a real-excerpt and a null-excerpt evidence → only the real one is
    cited; the null one NEVER leaks into the citation list (the unreachable-as-citation guarantee)."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[
                _evidence(supports=["H01"], raw_excerpt=None, source_name="null-src"),
                _evidence(supports=["H01"], raw_excerpt="real signal", source_name="real-src"),
            ],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    candidate = cast(list[dict[str, JsonValue]], report["root_cause"])[0]
    excerpts = [
        cast(str, c["raw_excerpt"])
        for c in cast(list[dict[str, JsonValue]], candidate["citations"])
    ]
    assert excerpts == ["real signal"]  # only the real one; null-src NEVER cited
    backing_names = [
        cast(str, b["source_name"])
        for b in cast(list[dict[str, JsonValue]], report["evidence_backing"])
    ]
    assert backing_names == ["real-src"]  # null-src also absent from backing


# ---------------------------------------------------------------------------
# AD-7 — single-authority confidence (PROJECT, never recompute)
# ---------------------------------------------------------------------------


def test_ad7_confidence_projects_sufficiency_verbatim() -> None:
    """AD-7: confidence == {ceiling_confidence, categorical} projected VERBATIM from sufficiency."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt="x")],
            sufficiency=_sufficiency(ceiling_confidence=0.85, categorical="high"),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    confidence = cast(dict[str, JsonValue], report["confidence"])
    assert confidence == {"ceiling_confidence": 0.85, "categorical": "high"}


def test_ad7_confidence_projects_even_when_recompute_would_differ() -> None:
    """AD-7 (decisive): the writer PROJECTS the authority, never recomputes. sufficiency says 0.3 even
    though 4 strong evidence would naively score ~1.0 → the report emits 0.3 (authority > estimate)."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt=f"signal-{i}") for i in range(4)],
            sufficiency=_sufficiency(ceiling_confidence=0.3, categorical="low"),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    confidence = cast(dict[str, JsonValue], report["confidence"])
    assert confidence["ceiling_confidence"] == 0.3  # PROJECTED, not recomputed to ~1.0
    assert confidence["categorical"] == "low"  # projected verbatim


def test_ad7_confidence_none_when_sufficiency_absent() -> None:
    """AD-7: no sufficiency verdict → confidence {None, None} (honest — we project nothing we don't have)."""
    node = build_rca_writer()
    out = node(
        _state(hypotheses=[_hyp("H01")], evidence=[_evidence(supports=["H01"], raw_excerpt="x")])
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert report["confidence"] == {"ceiling_confidence": None, "categorical": None}


def test_ad7_confidence_none_when_sufficiency_non_dict() -> None:
    """AD-7 / Constraint 5: a non-dict sufficiency → confidence {None, None}; never raises."""
    node = build_rca_writer()
    malformed = dict(
        _state(hypotheses=[_hyp("H01")], evidence=[_evidence(supports=["H01"], raw_excerpt="x")])
    )
    malformed["sufficiency"] = "not-a-dict"  # malformed on purpose
    out = node(cast(InvestigationState, malformed))
    report = cast(dict[str, JsonValue], out["report"])
    assert report["confidence"] == {"ceiling_confidence": None, "categorical": None}


def test_ad7_bool_ceiling_rejected() -> None:
    """AD-7: a ``bool`` ceiling (int subclass) must NOT silently read as 1.0 → projected as None."""
    node = build_rca_writer()
    malformed = _sufficiency()
    malformed["ceiling_confidence"] = True  # bool ⊂ int — must be rejected
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt="x")],
            sufficiency=malformed,
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert cast(dict[str, JsonValue], report["confidence"])["ceiling_confidence"] is None


# ---------------------------------------------------------------------------
# FR-9 ranking (AD-12) — priority ASC, then id ASC
# ---------------------------------------------------------------------------


def test_ranking_priority_asc_then_id_asc() -> None:
    """AD-12: candidates ranked priority ASC; ties broken by id ASC. ranks ascend from 1."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01", priority=3), _hyp("H02", priority=1), _hyp("H03", priority=1)],
            evidence=[
                _evidence(
                    supports=["H01", "H02", "H03"], raw_excerpt="shared signal", source_name="s"
                ),
            ],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    candidates = cast(list[dict[str, JsonValue]], report["root_cause"])
    assert [c["hypothesis_id"] for c in candidates] == ["H02", "H03", "H01"]  # p1 tie → id, then p3
    assert [c["rank"] for c in candidates] == [1, 2, 3]


def test_ranking_missing_or_non_numeric_priority_sorts_last() -> None:
    """AD-12: a missing / non-int-float / bool priority sorts LAST (sentinel); never raises."""
    node = build_rca_writer()
    h_missing = _hyp("H01")
    del h_missing["priority"]  # no priority → sentinel
    h_bool = _hyp("H02")
    h_bool["priority"] = True  # bool → sentinel
    out = node(
        _state(
            hypotheses=[h_missing, h_bool, _hyp("H03", priority=1)],
            evidence=[_evidence(supports=["H01", "H02", "H03"], raw_excerpt="x", source_name="s")],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    candidates = cast(list[dict[str, JsonValue]], report["root_cause"])
    assert [c["hypothesis_id"] for c in candidates] == [
        "H03",
        "H01",
        "H02",
    ]  # p1 first; sentinels last


# ---------------------------------------------------------------------------
# evidence_backing — deduped cited union + sorted (AD-12)
# ---------------------------------------------------------------------------


def test_evidence_backing_is_deduped_union() -> None:
    """FR-9/AD-12: two hypotheses both cite the SAME evidence → it appears ONCE in evidence_backing."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01"), _hyp("H02")],
            evidence=[
                _evidence(supports=["H01", "H02"], raw_excerpt="shared", source_name="shared")
            ],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    backing = cast(list[dict[str, JsonValue]], report["evidence_backing"])
    assert len(backing) == 1  # deduped — shared evidence backs both candidates but listed once
    assert backing[0]["source_name"] == "shared"


def test_evidence_backing_sorted_deterministically() -> None:
    """AD-12: evidence_backing is sorted by a deterministic identity key (order-independent)."""
    node = build_rca_writer()
    out_a = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[
                _evidence(supports=["H01"], raw_excerpt="z", source_name="zeta"),
                _evidence(supports=["H01"], raw_excerpt="a", source_name="alpha"),
            ],
            sufficiency=_sufficiency(),
        )
    )
    out_b = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[
                _evidence(supports=["H01"], raw_excerpt="a", source_name="alpha"),
                _evidence(supports=["H01"], raw_excerpt="z", source_name="zeta"),
            ],
            sufficiency=_sufficiency(),
        )
    )
    report_a = cast(dict[str, JsonValue], out_a["report"])
    report_b = cast(dict[str, JsonValue], out_b["report"])
    names_a = [
        cast(str, b["source_name"])
        for b in cast(list[dict[str, JsonValue]], report_a["evidence_backing"])
    ]
    names_b = [
        cast(str, b["source_name"])
        for b in cast(list[dict[str, JsonValue]], report_b["evidence_backing"])
    ]
    assert names_a == names_b == ["alpha", "zeta"]  # sorted + order-independent


# ---------------------------------------------------------------------------
# open_questions — sorted (AD-12); uncertainty projected; remediation off (T9)
# ---------------------------------------------------------------------------


def test_open_questions_sorted_ascending() -> None:
    """AD-12: dropped hypothesis ids are sorted ascending (order-independent)."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H03"), _hyp("H01"), _hyp("H02")],  # none grounded
            evidence=[],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert report["open_questions"] == ["H01", "H02", "H03"]


def test_uncertainty_projects_gap_when_present() -> None:
    """AD-7/FR-9: uncertainty projects the sufficiency ``gap`` when present (honest "chưa đủ")."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt="x")],
            sufficiency=_sufficiency(gap="chưa đủ — cần thêm traces"),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert cast(str, report["uncertainty"]) == "chưa đủ — cần thêm traces"


def test_uncertainty_margin_note_when_no_gap() -> None:
    """FR-9: no gap → a deterministic matched/min margin note (never invented prose)."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt="x")],
            sufficiency=_sufficiency(matched_count=2, min_count=3),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert "2" in cast(str, report["uncertainty"]) and "3" in cast(str, report["uncertainty"])


def test_remediation_empty_by_default() -> None:
    """T9 / AC3: remediation is OFF by default — the field is PRESENT but ``[]`` (never invented)."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt="x")],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert report["remediation"] == []
    # AC3: the report surfaces remediation ONLY via this field, which is empty by default — NO
    # remediation text is invented anywhere in the report.
    assert "remediation" in report


# ---------------------------------------------------------------------------
# Report structure — 6 keys; single-key AD-4 partial
# ---------------------------------------------------------------------------


def test_report_has_exactly_six_keys() -> None:
    """FR-9: the report has EXACTLY 6 keys (concise / 1-màn hình)."""
    node = build_rca_writer()
    out = node(
        _state(
            hypotheses=[_hyp("H01")],
            evidence=[_evidence(supports=["H01"], raw_excerpt="x")],
            sufficiency=_sufficiency(),
        )
    )
    report = cast(dict[str, JsonValue], out["report"])
    assert set(report.keys()) == {
        "root_cause",
        "evidence_backing",
        "confidence",
        "open_questions",
        "uncertainty",
        "remediation",
    }


def test_node_returns_single_key_report_partial() -> None:
    """AD-4: the node returns a SINGLE-key partial ``{"report": <dict>}`` (exactly one key)."""
    node = build_rca_writer()
    out = node(
        _state(hypotheses=[_hyp("H01")], evidence=[_evidence(supports=["H01"], raw_excerpt="x")])
    )
    assert set(out.keys()) == {"report"}


# ---------------------------------------------------------------------------
# Constraint 5 — never-raise (deterministic degrade to the honest empty report)
# ---------------------------------------------------------------------------


_REPORT_KEYSET = {
    "root_cause",
    "evidence_backing",
    "confidence",
    "open_questions",
    "uncertainty",
    "remediation",
}


def _assert_empty_report(report: object) -> None:
    """The honest EMPTY report: 6 keys, root_cause/evidence_backing/open_questions/remediation empty,
    confidence {None, None}, uncertainty ""."""
    assert isinstance(report, dict)
    assert set(report.keys()) == _REPORT_KEYSET
    assert report["root_cause"] == []
    assert report["evidence_backing"] == []
    assert report["open_questions"] == []
    assert report["remediation"] == []
    assert report["confidence"] == {"ceiling_confidence": None, "categorical": None}
    assert report["uncertainty"] == ""


def test_constraint5_empty_initial_state_does_not_raise() -> None:
    """A bare create_initial_state() → the honest empty report (no hypotheses → no candidates)."""
    node = build_rca_writer()
    out = node(create_initial_state())
    _assert_empty_report(out["report"])


def test_constraint5_non_list_evidence_does_not_raise() -> None:
    """non-list evidence → evidence treated as empty (NO hallucinated candidate); the surviving hypothesis
    surfaces honestly as an open_question; never raises."""
    node = build_rca_writer()
    malformed = dict(_state(hypotheses=[_hyp("H01")], sufficiency=_sufficiency()))
    malformed["evidence"] = "not-a-list"  # malformed on purpose
    out = node(cast(InvestigationState, malformed))
    report = cast(dict[str, JsonValue], out["report"])
    assert set(report.keys()) == _REPORT_KEYSET  # a valid 6-key report
    assert report["root_cause"] == []  # no citable evidence → no candidate (AD-6: no-claim)
    assert report["open_questions"] == ["H01"]  # the hypothesis honestly surfaced (no citation)


def test_constraint5_non_list_hypotheses_does_not_raise() -> None:
    """non-list hypotheses → hypotheses treated as empty (NO candidate, NO open_question); never raises."""
    node = build_rca_writer()
    malformed = dict(
        _state(evidence=[_evidence(supports=["H01"], raw_excerpt="x")], sufficiency=_sufficiency())
    )
    malformed["hypotheses"] = 42  # malformed on purpose
    out = node(cast(InvestigationState, malformed))
    report = cast(dict[str, JsonValue], out["report"])
    assert set(report.keys()) == _REPORT_KEYSET  # a valid 6-key report
    assert report["root_cause"] == []  # no hypotheses → no candidate
    assert report["open_questions"] == []


def test_constraint5_non_mapping_state_does_not_raise() -> None:
    """A NON-Mapping state (e.g. a list) → the outer try/except → the honest empty report (Constraint 5)."""
    node = build_rca_writer()
    # A list has no .get → AttributeError inside _build_report → caught → _empty_report.
    out = node(cast(InvestigationState, []))
    _assert_empty_report(out["report"])


def test_constraint5_evidence_items_non_mapping_skipped() -> None:
    """non-Mapping evidence items are skipped (no raise); a valid sibling is still cited."""
    node = build_rca_writer()
    evidence = [
        cast(dict[str, JsonValue], "str-item"),  # malformed on purpose
        _evidence(supports=["H01"], raw_excerpt="real"),
    ]
    out = node(_state(hypotheses=[_hyp("H01")], evidence=evidence, sufficiency=_sufficiency()))
    report = cast(dict[str, JsonValue], out["report"])
    candidates = cast(list[dict[str, JsonValue]], report["root_cause"])
    assert len(candidates) == 1  # the malformed item skipped; the valid one cited


# ---------------------------------------------------------------------------
# AD-12 determinism
# ---------------------------------------------------------------------------


def test_determinism_same_inputs_identical_report_in_process() -> None:
    node = build_rca_writer()
    state = _state(
        hypotheses=[_hyp("H01"), _hyp("H02", priority=2)],
        evidence=[_evidence(supports=["H01", "H02"], raw_excerpt="x", source_name="s")],
        sufficiency=_sufficiency(),
    )
    assert node(state) == node(state)


def test_determinism_order_independent_inputs() -> None:
    """AD-12: the SAME hypothesis/evidence SET in any input order → identical report (all lists sorted)."""
    node = build_rca_writer()
    hyps_a = [_hyp("H02"), _hyp("H01")]
    hyps_b = list(reversed(hyps_a))
    ev_a = [
        _evidence(supports=["H01"], raw_excerpt="a", source_name="alpha"),
        _evidence(supports=["H01"], raw_excerpt="z", source_name="zeta"),
    ]
    ev_b = list(reversed(ev_a))
    assert node(_state(hypotheses=hyps_a, evidence=ev_a, sufficiency=_sufficiency())) == node(
        _state(hypotheses=hyps_b, evidence=ev_b, sufficiency=_sufficiency())
    )


_XPROC_SCRIPT = (
    "import json; "
    "from graph.nodes.rca_writer import build_rca_writer; "
    "state = {"
    "'hypotheses': ["
    "{'id': 'H02', 'priority': 2, 'plan': {}, 'status': 'open'}, "
    "{'id': 'H01', 'priority': 1, 'plan': {}, 'status': 'open'}], "
    "'evidence': ["
    "{'source_name': 'a', 'source_type': 'prometheus', 'query': 'q', 'summary': 's', "
    "'raw_excerpt': 'boom', 'supports': ['H01', 'H02'], "
    "'timestamp_range': {'start': 't1', 'end': 't2'}}], "
    "'sufficiency': {'floor_pass': True, 'ceiling_confidence': 0.9, 'categorical': 'high', "
    "'matched_count': 2, 'min_count': 2, 'gap': None}}; "
    "print(json.dumps(build_rca_writer()(state)['report'], sort_keys=True))"
)


def _xproc_output(seed: int) -> str:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    proc = subprocess.run(
        [sys.executable, "-c", _XPROC_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"xproc seed={seed} failed:\n{proc.stderr}"
    return proc.stdout.strip()


def test_determinism_pythonhashseed_cross_process() -> None:
    """AD-12: identical report across fresh interpreters under different PYTHONHASHSEED values."""
    base = _xproc_output(0)
    for seed in (1, 7, 42, 99):
        assert _xproc_output(seed) == base, f"PYTHONHASHSEED drift at seed={seed}"


# ---------------------------------------------------------------------------
# AD-1 layer purity + AC4/D4 no-hardcoded-numeric (AST)
# ---------------------------------------------------------------------------


def test_layer_purity_imports_only_graph_stdlib_typing() -> None:
    """AD-1: rca_writer imports ⊆ {graph, collections, typing, __future__} — ZERO back-edges/yaml/models/compiled."""
    roots: set[str] = set()
    for node in ast.walk(_WRT_TREE):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    allowed = {"graph", "collections", "typing", "__future__"}
    assert roots <= allowed, f"forbidden import roots in rca_writer: {roots - allowed}"


def test_layer_purity_no_forbidden_attr_calls() -> None:
    """AD-12/AD-3: no LLM/clock/random/IO/serialization — ZERO forbidden attribute calls in rca_writer."""
    forbidden = {
        "now",
        "today",
        "strftime",
        "sleep",
        "random",
        "randint",
        "uniform",
        "uuid4",
        "uuid1",
        "open",
        "read_text",
        "write",
        "loads",
        "dumps",
        "request",
    }
    found: list[tuple[object, str]] = []
    for node in ast.walk(_WRT_TREE):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            found.append((getattr(node, "lineno", "?"), node.attr))
    assert not found, f"forbidden attr calls in rca_writer: {found}"


def _module_level_numeric_const_ids(tree: ast.Module) -> set[int]:
    """The id() of every numeric (int/float, non-bool) Constant that is the direct value of a module-level
    assignment — i.e. the ALLOWED named constants. Covers both ``ast.Assign`` (``X = 8``) and annotated
    ``ast.AnnAssign`` (``X: int = 8``); the WRT POC-default constants are annotated, so both forms are
    recognized as module-level."""
    allowed: set[int] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign) and isinstance(stmt.value, ast.Constant):
            value = stmt.value.value
            if isinstance(value, int | float) and not isinstance(value, bool):
                allowed.add(id(stmt.value))
    return allowed


def test_ac4_no_inline_numeric_threshold_literals() -> None:
    """AC4/D4: ZERO bare numeric (int/float, non-bool) literals inside function bodies — every bound/
    sentinel/rank is a module-level CONSTANT referenced by name (module-level assigns allowed)."""
    allowed = _module_level_numeric_const_ids(_WRT_TREE)
    offenders: list[tuple[object, object]] = []
    for node in ast.walk(_WRT_TREE):
        if isinstance(node, ast.Constant):
            value = node.value
            if (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and id(node) not in allowed
            ):
                offenders.append((getattr(node, "lineno", "?"), value))
    assert not offenders, (
        f"inline numeric literals in rca_writer logic (must be named constants): {offenders}"
    )


# ---------------------------------------------------------------------------
# AD-9 — report is a STATE DICT, NOT a Pydantic model
# ---------------------------------------------------------------------------


def test_ad9_report_is_plain_dict_not_pydantic_model() -> None:
    """AD-9: the report is a plain ``dict`` (Pydantic runs ONLY at the port; the spine stays model-free)."""
    node = build_rca_writer()
    out = node(
        _state(hypotheses=[_hyp("H01")], evidence=[_evidence(supports=["H01"], raw_excerpt="x")])
    )
    report = out["report"]
    assert isinstance(report, dict)
    # NOT a pydantic BaseModel instance (no model_dump / model_fields).
    assert not hasattr(report, "model_dump")


def test_ad9_no_models_report_module_exists() -> None:
    """AD-9: there is NO ``models/report.py`` — the report stays a state dict (the story must NOT add a
    Pydantic Report model)."""
    assert not Path("models/report.py").exists(), "AD-9 violation: a models/report.py was created"


def test_ad9_no_pydantic_import_in_wrt_node() -> None:
    """AD-9: the WRT node imports NO pydantic (the source has no ``pydantic`` import root)."""
    roots: set[str] = set()
    for node in ast.walk(_WRT_TREE):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    assert "pydantic" not in roots


# ---------------------------------------------------------------------------
# AD-9 spine — 13 keys unchanged (5-1 report pre-exists)
# ---------------------------------------------------------------------------


def test_spine_unchanged_thirteen_keys() -> None:
    """5-1 adds NO spine key — ``report`` pre-exists; the spine stays 13 keys."""
    assert len(InvestigationState.__annotations__) == 13


# ---------------------------------------------------------------------------
# ONE end-to-end — real WRT in a synthetic floor-Pass→write graph (K2 discipline)
# ---------------------------------------------------------------------------


def _noop_node(state: InvestigationState) -> dict[str, JsonValue]:
    del state
    return {}


def _val_proceed_node(state: InvestigationState) -> dict[str, JsonValue]:
    del state
    return {"next_action": NA_PROCEED}


def _hyp_node(state: InvestigationState) -> dict[str, JsonValue]:
    """A synthetic HYP emitting ONE hypothesis the writer can ground (claim rides inside plan)."""
    del state
    return {"hypotheses": [{"id": "H01", "priority": 1, "plan": {}, "status": "open"}]}


def _env_node(state: InvestigationState) -> dict[str, JsonValue]:
    """A synthetic ENV emitting honest-synthetic Evidence WITH the supports linkage injected (the POC real
    graph leaves supports=[]; per K2 the synthetic floor-Pass→write state injects it)."""
    del state
    return {
        "evidence": [
            {
                "source_type": "prometheus",
                "source_name": "checkout",
                "query": "histogram_quantile(0.99, ...)",
                "summary": "p99 latency spike",
                "raw_excerpt": "p99=4.2s",
                "timestamp_range": {"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"},
                "supports": ["H01"],
            }
        ]
    }


def _write_reflector_node(state: InvestigationState) -> dict[str, JsonValue]:
    """A synthetic REF that routes ``write`` + writes a real-shape sufficiency verdict (honest synthetic
    REF output — the floor-Pass→write handoff WRT consumes; per K2)."""
    del state
    return {
        "sufficiency": {
            "floor_pass": True,
            "ceiling_confidence": 0.9,
            "categorical": "high",
            "matched_count": 2,
            "min_count": 2,
            "floor_reason": "pass",
            "gap": None,
        },
        "next_action": NA_WRITE,
    }


def _write_runner() -> CompiledGraphRunner:
    """A synthetic floor-Pass→write graph wiring the REAL rca_writer (5-1) — the WRT-under-test end-to-end."""
    graph = build_compiled_graph(
        incident_context_builder=_noop_node,
        preplanning_playbook_retriever=_noop_node,
        hypothesis_planner=_hyp_node,
        plan_validator=_val_proceed_node,
        executor_router=_noop_node,
        evidence_normalizer=_env_node,
        reflector=_write_reflector_node,
        rca_writer=build_rca_writer(),  # 5-1: the REAL WRT (was the DI-default stub)
    )
    return CompiledGraphRunner(graph)


def test_end_to_end_real_wrt_in_write_graph_produces_cited_report() -> None:
    """K2 / FR-9: a synthetic floor-Pass→write graph wiring the REAL rca_writer → a NON-None cited report
    (root_cause grounded, confidence projected, remediation off). The real WRT (not the stub) is proven."""
    runner = _write_runner()
    result = asyncio.run(runner.run({"service": "checkout"}, "inv-e2e-wrt", max_iterations=2))
    assert result["status"] == "success"
    report = result["report"]
    assert isinstance(report, dict)  # real WRT produced a report (the stub would yield None)
    candidates = cast(list[dict[str, JsonValue]], report["root_cause"])
    assert len(candidates) == 1
    assert candidates[0]["hypothesis_id"] == "H01"
    citations = cast(list[dict[str, JsonValue]], candidates[0]["citations"])
    assert len(citations) == 1
    assert citations[0]["raw_excerpt"] == "p99=4.2s"  # AD-6: grounded in the real ENV excerpt
    assert (
        cast(dict[str, JsonValue], report["confidence"])["categorical"] == "high"
    )  # AD-7 projected
    assert report["remediation"] == []  # T9 off
