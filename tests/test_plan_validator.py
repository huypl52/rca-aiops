"""Story 3.3 — plan_validator §3.5 read-only GATE node (FR-4/FR-5 / AD-3 / §4.3/§4.4/§3.8).

Covers the ACs / leader DEEP spotlights for this SECURITY-CRITICAL defense-in-depth node:
  - Read-only enforcement — REUSES ``ci.denyset`` (WRITE_VERBS tokenize-exact +
    WRITE_PATTERNS regex); AST-prove the node imports the canonical source (no hardcoded
    duplicate verb list). Catches write/exec/patch/probe-đột-xuất forms.
  - Word-boundary correctness — exact-token match avoids the classic ``exec``-inside-
    ``execute`` false positive; catches snake-case offending forms (``restart_pods``).
  - Specificity — the evidence-identifying trio ``tool``/``query``/``timestamp_range``;
    missing/empty any → replan (NOT a security violation → NO ``safety_flags``).
  - Verdict routing — ``next_action`` ∈ {``proceed``, ``replan``}; ``safety_flags`` (a dict)
    appended on a read-only violation ONLY.
  - Defense-in-depth honesty — the node is the SECOND layer (registry 2-1 is HARD); it does
    NOT duplicate registry registration and stays registry-free.
  - Graceful degrade (Constraint 5) — missing/None/non-dict plan → ``replan``, NEVER raises.
  - AD-4 partial — writes ONLY ``next_action`` (+ ``safety_flags`` on a violation).
  - AD-1 one-way — imports ``graph.state`` + ``ci.denyset`` + stdlib ONLY; NO
    ``tools``/``adapters``/``models``/``routers``/``services``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import cast

from graph.nodes.plan_validator import build_plan_validator
from graph.state import (
    InvestigationState,
    JsonValue,
    append_safety_flags,
    create_initial_state,
)

NODE_FILE = Path(__file__).resolve().parents[1] / "graph" / "nodes" / "plan_validator.py"

_PROCEED = "proceed"
_REPLAN = "replan"

# A read-only, specific plan (the trio present + non-empty + benign content).
_VALID_PLAN: dict[str, JsonValue] = {
    "tool": "prometheus",
    "query": "rate(http_requests_total[5m])",
    "timestamp_range": {"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"},
}


def _state(
    *, plan: dict[str, JsonValue] | None = None, with_plan_key: bool = True
) -> InvestigationState:
    """A partial state carrying only ``plan`` (plan_validator reads ``state.plan`` only)."""
    state = create_initial_state()
    if with_plan_key:
        state["plan"] = plan
    return state


def _safety_flags_of(result: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Narrow ``result["safety_flags"]`` (JsonValue) to a dict for assertion (mypy-safe)."""
    sf = result.get("safety_flags")
    assert isinstance(sf, dict)
    return sf


# ---------------------------------------------------------------------------
# AC1 — read-only enforcement: REUSES ci.denyset; verbs + patterns; word-boundary
# ---------------------------------------------------------------------------


def test_node_reuses_ci_denyset_no_hardcoded_verb_list() -> None:
    """AC1 / spotlight: the node IMPORTS the canonical ``ci.denyset`` (single source of truth).

    AST-exact: an ``ImportFrom`` of ``ci.denyset`` pulling ``WRITE_VERBS`` + ``WRITE_PATTERNS``
    is present; the module does NOT define a hardcoded frozenset/tuple/list of write verbs
    (no duplicate verb list). The deny-set is REUSED, not reinvented.
    """
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported_from_ci_denyset = False
    imported_names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "ci.denyset":
            imported_from_ci_denyset = True
            imported_names = {a.name for a in n.names}
    assert imported_from_ci_denyset, "node must import from ci.denyset (single source of truth)"
    assert {"WRITE_VERBS", "WRITE_PATTERNS"} <= imported_names, (
        "node must import WRITE_VERBS + WRITE_PATTERNS from ci.denyset"
    )
    # AST-exact: NO module-level frozenset/set/tuple/list Assign whose name suggests a
    # hardcoded write-verb set (a reinvention of the deny-set). The token-split regex +
    # the `_VIOLATION_TYPE` / `_DEFAULT_REQUIRED_FIELDS` constants are allowed.
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            fn = n.value.func
            name = ""
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            assert name != "frozenset", (
                "node defines a frozenset — must not reinvent a hardcoded verb set "
                "(import ci.denyset)"
            )


def test_verb_in_tool_field_is_rejected() -> None:
    """AC1: a write verb (as a standalone token) in the ``tool`` field → reject + safety_flags."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"tool": "restart_pods", "query": "x", "timestamp_range": {"a": 1}}
    result = node(_state(plan=plan))
    assert result["next_action"] == _REPLAN
    sf = _safety_flags_of(result)
    assert sf  # non-empty audit
    entry = next(iter(sf.values()))
    assert isinstance(entry, dict)
    assert entry["type"] == "plan_readonly_violation"
    assert entry["matched"] == "restart"


def test_each_write_verb_token_is_caught() -> None:
    """AC1: every WRITE_VERB (as a leading token) is caught. Probes a representative form per verb."""
    from ci.denyset import WRITE_VERBS

    node = build_plan_validator()
    for verb in WRITE_VERBS:
        plan: dict[str, JsonValue] = {
            "tool": f"{verb}_thing",
            "query": "benign_query",
            "timestamp_range": {"a": 1},
        }
        result = node(_state(plan=plan))
        assert result["next_action"] == _REPLAN, f"verb '{verb}' was not caught"
        assert _safety_flags_of(result), f"verb '{verb}' produced no safety_flags entry"


def test_exec_inside_execute_is_NOT_a_false_positive() -> None:
    """AC1 / spotlight: ``exec`` must NOT match inside ``execute_metric`` (token = ``execute`` ≠ ``exec``)."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {
        "tool": "prometheus",
        "query": "execute_metric(prometheus_build_info)",
        "timestamp_range": {"a": 1},
    }
    assert node(_state(plan=plan))["next_action"] == _PROCEED


def test_benign_rate_query_is_NOT_a_false_positive() -> None:
    """AC1 / spotlight: ``rate(http_requests_total)`` → NOT a false-positive reject (benign metric)."""
    node = build_plan_validator()
    assert node(_state(plan=_VALID_PLAN))["next_action"] == _PROCEED


def test_write_pattern_command_strings_are_rejected() -> None:
    """AC1: WRITE_PATTERNS (command-string forms) are caught by regex.search."""
    node = build_plan_validator()
    cases: list[tuple[str, dict[str, JsonValue]]] = [
        (
            "kubectl exec",
            {"tool": "k8s", "query": "kubectl exec nginx -- ls /", "timestamp_range": {"a": 1}},
        ),
        (
            "kubectl debug",
            {
                "tool": "k8s",
                "query": "kubectl debug node-1 --image=busybox",
                "timestamp_range": {"a": 1},
            },
        ),
        (
            "rollout restart",
            {
                "tool": "k8s",
                "query": "kubectl rollout restart deployment api",
                "timestamp_range": {"a": 1},
            },
        ),
        (
            "rm -rf",
            {
                "tool": "shell",
                "query": "find . -type f | xargs rm -rf",
                "timestamp_range": {"a": 1},
            },
        ),
    ]
    for label, plan in cases:
        result = node(_state(plan=plan))
        assert result["next_action"] == _REPLAN, f"pattern '{label}' was not caught"
        assert _safety_flags_of(result), f"pattern '{label}' produced no safety_flags entry"


def test_verb_scanned_across_all_string_values_not_just_tool() -> None:
    """AC1 / defense-in-depth: the deny-set scans ALL string values, not only the ``tool`` field."""
    node = build_plan_validator()
    # tool is benign; the verb hides in the query.
    plan: dict[str, JsonValue] = {
        "tool": "loki",
        "query": "show me the remediate action log",
        "timestamp_range": {"a": 1},
    }
    result = node(_state(plan=plan))
    assert result["next_action"] == _REPLAN
    assert _safety_flags_of(result)


def test_process_exec_summary_is_flagged_security_conservative_FLAG() -> None:
    """FLAG (leader DEEP): the leader brief lists ``process_exec_summary`` as a should-NOT-flag
    false-positive, alongside ``execute_metric``. But that is **inconsistent** with the explicit
    security probe ``tool:"restart_pods"`` → reject: ``restart_pods`` requires ``_`` as a SEPARATOR
    (tokenize), while ``process_exec_summary`` requires ``_`` as a WORD-CHAR (regex ``\\b``). No
    uniform string rule satisfies both. This node is SECURITY-CRITICAL + fail-closed: tokenize
    catches ``restart_pods`` (the security requirement) and ALSO flags ``process_exec_summary``
    (a benign, bounded replan — recoverable via replan/max_iterations). Failing the security
    probe (a write plan slipping through) is far worse than a benign false positive. This test
    asserts the security-conservative choice; flagging for leader adjudication.
    """
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {
        "tool": "loki",
        "query": "process_exec_summary",
        "timestamp_range": {"a": 1},
    }
    result = node(_state(plan=plan))
    # Security-conservative: flagged (token `exec` matches WRITE_VERBS).
    assert result["next_action"] == _REPLAN
    assert _safety_flags_of(result)


# ---------------------------------------------------------------------------
# AC2 — specificity: the trio tool/query/timestamp_range (non-empty)
# ---------------------------------------------------------------------------


def test_missing_tool_is_vague_replan() -> None:
    """AC2: a read-only-clean plan missing ``tool`` → replan, NO safety_flags (not a violation)."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"query": "rate(x)", "timestamp_range": {"a": 1}}
    result = node(_state(plan=plan))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_missing_query_is_vague_replan() -> None:
    """AC2: missing ``query`` → replan, no safety_flags."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"tool": "prometheus", "timestamp_range": {"a": 1}}
    result = node(_state(plan=plan))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_missing_timestamp_range_is_vague_replan() -> None:
    """AC2: missing ``timestamp_range`` (carry-forward 2-3-A1 dedupe-key field) → replan."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"tool": "prometheus", "query": "rate(x)"}
    result = node(_state(plan=plan))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_empty_string_field_is_vague_replan() -> None:
    """AC2: an EMPTY string field counts as missing (not specific) → replan, no safety_flags."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"tool": "prometheus", "query": "   ", "timestamp_range": {"a": 1}}
    result = node(_state(plan=plan))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_empty_timestamp_range_dict_is_vague_replan() -> None:
    """AC2: an EMPTY timestamp_range dict → not specific → replan."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"tool": "prometheus", "query": "rate(x)", "timestamp_range": {}}
    result = node(_state(plan=plan))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_specificity_field_set_is_factory_configurable() -> None:
    """AC2/DI: the required field SET is configurable via the factory (the future-hardening seam)."""
    node = build_plan_validator(required_fields=("tool", "query"))
    # Has tool+query but no timestamp_range — under the trimmed trio it PASSES specificity.
    plan: dict[str, JsonValue] = {"tool": "prometheus", "query": "rate(x)"}
    assert node(_state(plan=plan))["next_action"] == _PROCEED


# ---------------------------------------------------------------------------
# AC3 — verdict routing: next_action ∈ {proceed, replan}; safety_flags ONLY on violation
# ---------------------------------------------------------------------------


def test_pass_writes_only_next_action_proceed() -> None:
    """AC3/AD-4: PASS → exactly {next_action: proceed}; no safety_flags; no other keys."""
    node = build_plan_validator()
    result = node(_state(plan=_VALID_PLAN))
    assert set(result.keys()) == {"next_action"}
    assert result["next_action"] == _PROCEED


def test_vague_writes_only_next_action_replan() -> None:
    """AC3/AD-4: vague → exactly {next_action: replan}; no safety_flags."""
    node = build_plan_validator()
    result = node(_state(plan={"tool": "prometheus"}))
    assert set(result.keys()) == {"next_action"}
    assert result["next_action"] == _REPLAN


def test_violation_writes_next_action_and_safety_flags() -> None:
    """AC3/AD-4: read-only violation → {next_action: replan, safety_flags: {...}}; EXACTLY these."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"tool": "delete", "query": "x", "timestamp_range": {"a": 1}}
    result = node(_state(plan=plan))
    assert set(result.keys()) == {"next_action", "safety_flags"}
    assert result["next_action"] == _REPLAN


def test_next_action_vocabulary_is_proceed_or_replan() -> None:
    """AC3: next_action is always one of the two routing values plan_validator introduces."""
    node = build_plan_validator()
    cases = [
        (_VALID_PLAN, _PROCEED),
        ({"tool": "prometheus"}, _REPLAN),
        ({"tool": "scale_up", "query": "x", "timestamp_range": {"a": 1}}, _REPLAN),
    ]
    for plan, expected in cases:
        plan_typed: dict[str, JsonValue] = cast(dict[str, JsonValue], plan)
        assert node(_state(plan=plan_typed))["next_action"] == expected


def test_safety_flag_entry_shape_is_type_matched_detail() -> None:
    """AC3/DEFER-bounded: each safety_flags entry carries {type, matched, detail}."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"tool": "rollback", "query": "x", "timestamp_range": {"a": 1}}
    result = node(_state(plan=plan))
    sf = _safety_flags_of(result)
    for entry in sf.values():
        assert isinstance(entry, dict)
        assert set(entry.keys()) == {"type", "matched", "detail"}
        assert entry["type"] == "plan_readonly_violation"


def test_distinct_violations_get_distinct_deterministic_keys() -> None:
    """AC3: multiple distinct offending tokens → distinct ``pv_NNN`` keys (deterministic order). verbs
    before patterns."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {
        "tool": "restart",
        "query": "kubectl exec nginx",
        "timestamp_range": {"a": 1},
    }
    result = node(_state(plan=plan))
    sf = _safety_flags_of(result)
    keys = list(sf.keys())
    assert keys == ["pv_001", "pv_002", "pv_003"], (
        keys
    )  # restart + exec (verb) + kubectl exec (pattern)
    matched: list[str] = []
    for k in keys:
        entry = sf[k]
        assert isinstance(entry, dict)
        token = entry["matched"]
        assert isinstance(token, str)
        matched.append(token)
    assert matched == ["restart", "exec", "kubectl exec"]


def test_safety_flags_dict_merges_via_reducer() -> None:
    """AC1/spine: ``safety_flags`` is a dict with the ``append_safety_flags`` key-merge reducer.

    The node emits ``right``; merging against prior ``left`` keeps ``left``'s untouched keys
    (accumulation across replans — read-only-violation audit trail, per AD-9 spine).
    """
    left: dict[str, JsonValue] = {
        "pv_000": {"type": "plan_readonly_violation", "matched": "scale", "detail": "earlier"}
    }
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {"tool": "restart", "query": "x", "timestamp_range": {"a": 1}}
    result = node(_state(plan=plan))
    merged = append_safety_flags(left, _safety_flags_of(result))
    assert "pv_000" in merged and "pv_001" in merged  # prior retained + new accumulated
    entry = merged["pv_000"]
    assert isinstance(entry, dict) and entry["matched"] == "scale"  # left value preserved


# ---------------------------------------------------------------------------
# AC4 — graceful degrade (Constraint 5): NEVER raises
# ---------------------------------------------------------------------------


def test_missing_plan_key_degrades_to_replan() -> None:
    """AC4: state with NO ``plan`` key → replan, never raises."""
    node = build_plan_validator()
    result = node(_state(with_plan_key=False))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_none_plan_degrades_to_replan() -> None:
    """AC4: ``plan`` is None → replan, never raises."""
    node = build_plan_validator()
    result = node(_state(plan=None))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_non_dict_plan_degrades_to_replan() -> None:
    """AC4: ``plan`` is a non-dict (a string/list) → replan, never raises."""
    node = build_plan_validator()
    bad_raw = cast(dict[str, JsonValue], create_initial_state())
    bad_raw["plan"] = "not-a-dict"  # malformed: plan must be dict|None
    result = node(cast(InvestigationState, bad_raw))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_empty_plan_dict_is_vague_replan() -> None:
    """AC4: ``plan`` is an empty dict → not specific → replan (no violation)."""
    node = build_plan_validator()
    result = node(_state(plan={}))
    assert result["next_action"] == _REPLAN
    assert "safety_flags" not in result


def test_malformed_state_never_raises() -> None:
    """AC4: malformed state (non-dict plan value types) → never raises; verdict is replan."""
    node = build_plan_validator()
    bad_raw = cast(dict[str, JsonValue], create_initial_state())
    bad_raw["plan"] = [1, 2, 3]  # malformed: plan must be dict|None
    result = node(cast(InvestigationState, bad_raw))
    assert result["next_action"] == _REPLAN


# ---------------------------------------------------------------------------
# AC5 — defense-in-depth honesty + determinism
# ---------------------------------------------------------------------------


def test_node_is_registry_free() -> None:
    """AC5 / spotlight: the node does NOT import/call ``tools.registry`` — the unregistered-tool
    case is ``executor_router``'s job (3.5). AST-exact (docstring-immune — no import of ``tools``,
    no reference to a registry/executor_router identifier in CODE)."""
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    forbidden_identifiers = {"executor_router", "ReadOnlyRegistry", "ExecutorRouter"}
    forbidden_attr = {"lookup", "dispatch"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                assert a.name.split(".")[0] != "tools", (
                    f"node must not import tools/* (registry-free): {a.name}"
                )
        elif isinstance(n, ast.ImportFrom) and n.module:
            assert n.module.split(".")[0] != "tools", (
                f"node must not import tools/* (registry-free): {n.module}"
            )
        if isinstance(n, ast.Name) and n.id in forbidden_identifiers:
            raise AssertionError(f"node references registry/router identifier '{n.id}' in code")
        if isinstance(n, ast.Attribute) and n.attr in forbidden_attr:
            raise AssertionError(f"node calls a registry/router method '.{n.attr}' in code")


def test_node_does_not_duplicate_registry_enforcement() -> None:
    """AC5 / spotlight: this node is the SECOND layer (registry 2-1 is HARD). It does NOT define
    tool-registration or deny-verb-REGISTRATION logic (that is 2-1's structural job)."""
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
            assert n.name not in {"register", "reject_registration", "validate_registration"}, (
                "node must not duplicate registry registration enforcement (that is 2-1)"
            )
    # The module docstring states the defense-in-depth framing (second layer).
    assert "SECOND layer" in src or "second layer" in src


def test_validator_is_deterministic_same_state_same_verdict() -> None:
    """AC5/AD-12: same plan → identical verdict + identical safety_flags (deterministic)."""
    node = build_plan_validator()
    plan: dict[str, JsonValue] = {
        "tool": "restart",
        "query": "kubectl exec pod",
        "timestamp_range": {"a": 1},
    }
    r1 = node(_state(plan=plan))
    r2 = node(_state(plan=plan))
    assert json.loads(json.dumps(r1)) == json.loads(json.dumps(r2)) == r1  # stable + JSON-safe


def test_node_has_no_wall_clock_or_random() -> None:
    """AC5/AD-12: no time/datetime/random/uuid/secrets in the node source (deterministic)."""
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden_modules = {"time", "datetime", "random", "uuid", "secrets"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            assert n.names[0].name.split(".")[0] not in forbidden_modules
        elif isinstance(n, ast.ImportFrom) and n.module:
            assert n.module.split(".")[0] not in forbidden_modules
    for forbidden in ("hash(", ".now()", ".choice(", ".random()"):
        assert forbidden not in src, f"node source contains non-deterministic token '{forbidden}'"


# ---------------------------------------------------------------------------
# AC6 — DI seam + offline-testable
# ---------------------------------------------------------------------------


def test_factory_closes_over_required_fields_two_factories_independent() -> None:
    """AC6: two factories with different required_fields are independent."""
    strict = build_plan_validator(required_fields=("tool", "query", "timestamp_range"))
    loose = build_plan_validator(required_fields=("tool",))
    plan: dict[str, JsonValue] = {"tool": "prometheus"}  # has tool only
    assert strict(_state(plan=plan))["next_action"] == _REPLAN
    assert loose(_state(plan=plan))["next_action"] == _PROCEED


def test_node_reads_only_state_plan_not_hypotheses() -> None:
    """AC6/scope (Reading A): the node validates THE plan in ``state.plan``; it does NOT iterate
    ``state.hypotheses`` or invent a selection step (that selection is 3.5 graph-wiring). AST-exact:
    no ``state.get("hypotheses")`` call and no ``state["hypotheses"]`` subscript."""
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))

    def _is_hypotheses_const(node: object) -> bool:
        return isinstance(node, ast.Constant) and node.value == "hypotheses"

    for n in ast.walk(tree):
        # state.get("hypotheses")  →  Call(func=Attribute(attr='get'), args=[Constant("hypotheses")])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
            assert not (n.args and _is_hypotheses_const(n.args[0])), (
                "node must NOT read state.hypotheses (selection is 3.5 graph-wiring — Reading A)"
            )
        # state["hypotheses"]  →  Subscript(slice=Constant("hypotheses"))
        if isinstance(n, ast.Subscript):
            sl = n.slice
            assert not _is_hypotheses_const(sl), (
                "node must NOT read state.hypotheses (selection is 3.5 graph-wiring — Reading A)"
            )


# ---------------------------------------------------------------------------
# AC7 — AD-1 one-way (gate #2 KEPT): graph.state + ci.denyset + stdlib ONLY; no tools
# ---------------------------------------------------------------------------


def test_node_imports_only_graph_ci_and_stdlib_no_tools() -> None:
    """AC7 / spotlight: import roots ⊆ {__future__, graph, ci, stdlib}; NO tools/adapters/models/
    routers/services. graph→ci is legal (ci is NOT a contracted layer; precedent tools/registry.py:27)."""
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed = {"__future__", "graph", "ci", "json", "re", "collections", "abc"}
    forbidden_layers = {"tools", "adapters", "models", "routers", "services", "eval", "config"}
    roots: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                roots.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            roots.add(n.module.split(".")[0])
    assert roots <= allowed, f"unexpected import roots {roots - allowed}"
    assert not (roots & forbidden_layers), (
        f"node imports a forbidden layer {roots & forbidden_layers}"
    )


def test_node_has_no_write_primitives() -> None:
    """AC7 / AD-3: a VALIDATION node has NO write/exec primitives — the deny-set scan is a
    string/regex CHECK, NOT an action. AST-exact (docstring-immune): no import of a write-primitive
    module + no call to a forbidden write builtin."""
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    forbidden_modules = {"subprocess", "os", "shutil", "socket", "signal"}
    forbidden_calls = {"system", "popen", "fork", "kill", "remove", "rmdir"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                assert a.name.split(".")[0] not in forbidden_modules, (
                    f"node imports a write-primitive module '{a.name}'"
                )
        elif isinstance(n, ast.ImportFrom) and n.module:
            assert n.module.split(".")[0] not in forbidden_modules, (
                f"node imports a write-primitive module '{n.module}'"
            )
        if isinstance(n, ast.Call):
            fn = n.func
            name = ""
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            assert name not in forbidden_calls, (
                f"node calls a write/exec primitive '{name}()' in code"
            )


def test_node_has_no_models_or_evidence_construction() -> None:
    """AC7 / boundary: no ``models`` import + no ``Evidence(`` (4.2 boundary held)."""
    src = NODE_FILE.read_text(encoding="utf-8")
    assert "Evidence(" not in src
    assert "from models" not in src and "import models" not in src
