"""Env-gated hypothesis source builders for the first runtime LLM insertion point.

This module owns the only runtime non-determinism for Story 3.2:
- gated by env/config
- falls back to the deterministic rule-based source when disabled, misconfigured,
  unavailable, or when the model output does not validate
- keeps the existing hypothesis schema/IDs/contracts intact
- supports Anthropic and OpenAI provider seams without widening planner scope
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence

import httpx

from graph.nodes.hypothesis_planner import HypothesisSource, _rule_based_source
from graph.state import JsonValue

_LLM_ENABLED_ENV = "RCA_HYPOTHESIS_LLM_ENABLED"
_LLM_PROVIDER_ENV = "RCA_HYPOTHESIS_LLM_PROVIDER"
_LLM_MODEL_ENV = "RCA_HYPOTHESIS_LLM_MODEL"
_LLM_API_KEY_ENV = "RCA_HYPOTHESIS_LLM_API_KEY"
_LLM_API_URL_ENV = "RCA_HYPOTHESIS_LLM_API_URL"
_LLM_PROVIDER_ANTHROPIC = "anthropic"
_LLM_PROVIDER_OPENAI = "openai"
_LLM_DEFAULT_PROVIDER = _LLM_PROVIDER_ANTHROPIC
_LLM_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
_LLM_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_OPENAI_API_MODEL_ENV = "OPENAI_API_MODEL"
_OPENAI_API_URL_ENV = "OPENAI_API_URL"
_LLM_ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
_LLM_OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_LLM_TIMEOUT_SECONDS = 20.0
_LLM_MAX_TOKENS = 800
_LLM_SYSTEM_PROMPT = (
    "You are a read-only hypothesis planner for an RCA investigation. "
    "Return only valid JSON. No markdown, no prose, no code fences. "
    "Your response must be a JSON array of 1-3 objects. "
    "Each object must have exactly these conceptual parts: priority, plan, status. "
    "The plan object must include tool, query, and timestamp_range. "
    "For the current runtime contract, tool MUST be query_prometheus_raw and query MUST be an "
    "executable PromQL string, because the executor accepts only {query, time_window}. "
    "Keep the output minimal, concrete, and aligned to the supplied context."
)


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _first_non_empty(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _extract_text(payload: Mapping[str, JsonValue]) -> str | None:
    content = payload.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        text = "".join(parts).strip()
        if text:
            return text

    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        text = output_text.strip()
        if text:
            return text

    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if isinstance(message, Mapping):
                message_content = message.get("content")
                if isinstance(message_content, str):
                    text = message_content.strip()
                    if text:
                        return text
            text = choice.get("text")
            if isinstance(text, str):
                stripped = text.strip()
                if stripped:
                    return stripped

    return None


def _normalize_descriptors(raw: object) -> list[dict[str, JsonValue]] | None:
    if not isinstance(raw, list) or not raw:
        return None

    descriptors: list[dict[str, JsonValue]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return None
        priority = item.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool):
            return None
        plan = item.get("plan")
        if not isinstance(plan, Mapping):
            return None
        status = item.get("status")
        if not isinstance(status, str) or not status.strip():
            return None

        normalized_plan = dict(plan)
        tool = normalized_plan.get("tool")
        query = normalized_plan.get("query")
        timestamp_range = normalized_plan.get("timestamp_range")
        if tool != "query_prometheus_raw":
            return None
        if not isinstance(query, str) or not query.strip():
            return None
        if not isinstance(timestamp_range, Mapping):
            return None

        descriptors.append(
            {
                "priority": priority,
                "plan": {
                    "tool": tool,
                    "query": query,
                    "timestamp_range": dict(timestamp_range),
                },
                "status": status,
            }
        )
    return descriptors


def _build_prompt(
    context: Mapping[str, JsonValue],
    playbook_hits: Sequence[Mapping[str, JsonValue]],
    evidence: Sequence[Mapping[str, JsonValue]],
) -> dict[str, object]:
    return {
        "context": context,
        "playbook_hits": list(playbook_hits),
        "evidence": list(evidence),
        "requirements": {
            "count": "1-3",
            "output": "json_array",
            "tool_candidates": ["query_prometheus_raw"],
            "required_plan_fields": ["tool", "query", "timestamp_range"],
            "query_contract": "query must be an executable PromQL string",
            "status": "proposed",
        },
    }


def _prometheus_query_fallback(
    context: Mapping[str, JsonValue],
    playbook_hits: Sequence[Mapping[str, JsonValue]],
    evidence: Sequence[Mapping[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    """Deterministic executable fallback for the env-gated LLM seam.

    The 3.2 node-level ``_rule_based_source`` stays unchanged for the planner's non-LLM default. This
    helper is narrower: when the LLM path is enabled but provider output is unavailable/invalid, we need
    FALLBACK plans that still satisfy the current EXR runtime contract (`query_prometheus_raw` with
    `{query, time_window}`). The queries are pure functions of the incident context, so the fallback is
    still deterministic and read-only.
    """
    del playbook_hits, evidence
    service = context.get("service") if isinstance(context.get("service"), str) else "unknown-service"
    namespace = context.get("namespace") if isinstance(context.get("namespace"), str) else "default"
    time_window = context.get("time_window")
    if not isinstance(time_window, Mapping):
        time_window = {"start": None, "end": None}

    queries = [
        (
            1,
            f'sum by (status) (rate(http_requests_total{{namespace="{namespace}",service="{service}"}}[5m]))',
        ),
        (
            2,
            f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{namespace="{namespace}",service="{service}"}}[5m])) by (le))',
        ),
        (
            3,
            f'rate(http_request_duration_seconds_count{{namespace="{namespace}",service="{service}"}}[5m])',
        ),
    ]
    return [
        {
            "priority": priority,
            "plan": {
                "tool": "query_prometheus_raw",
                "query": query,
                "timestamp_range": dict(time_window),
            },
            "status": "proposed",
        }
        for priority, query in queries
        if isinstance(time_window.get("start"), str) and time_window.get("start")
    ]


def _build_request_body(
    provider: str,
    model: str,
    prompt: Mapping[str, object],
) -> dict[str, object]:
    user_text = (
        "Plan hypotheses for the RCA investigation using only read-only evidence. "
        "Return JSON only. Input: " + _json_text(prompt)
    )
    if provider == _LLM_PROVIDER_ANTHROPIC:
        return {
            "model": model,
            "max_tokens": _LLM_MAX_TOKENS,
            "temperature": 0,
            "system": _LLM_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_text}],
                }
            ],
        }

    return {
        "model": model,
        "max_tokens": _LLM_MAX_TOKENS,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": _LLM_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_text,
            },
        ],
    }


def _build_request_headers(provider: str, api_key: str) -> dict[str, str]:
    if provider == _LLM_PROVIDER_ANTHROPIC:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    return {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }


def _provider_endpoint(provider: str) -> str:
    if provider == _LLM_PROVIDER_OPENAI:
        custom_base = _first_non_empty(_LLM_API_URL_ENV, _OPENAI_API_URL_ENV)
        if custom_base is not None:
            return custom_base.rstrip("/") + "/v1/chat/completions"
        return _LLM_OPENAI_ENDPOINT
    return _LLM_ANTHROPIC_ENDPOINT


def _provider_model(provider: str, requested_model: str | None) -> str:
    if requested_model is not None and requested_model.strip():
        return requested_model.strip()
    if provider == _LLM_PROVIDER_OPENAI:
        configured_model = _first_non_empty(_OPENAI_API_MODEL_ENV)
        if configured_model is not None:
            return configured_model
        return _LLM_DEFAULT_OPENAI_MODEL
    return _LLM_DEFAULT_ANTHROPIC_MODEL


def _provider_api_key(provider: str) -> str | None:
    if provider == _LLM_PROVIDER_OPENAI:
        return _first_non_empty(_LLM_API_KEY_ENV, "OPENAI_API_KEY")
    if provider == _LLM_PROVIDER_ANTHROPIC:
        return _first_non_empty(_LLM_API_KEY_ENV, "ANTHROPIC_API_KEY")
    return None


def _llm_hypothesis_source(provider: str, api_key: str, model: str) -> HypothesisSource:
    def _source(
        context: Mapping[str, JsonValue],
        playbook_hits: Sequence[Mapping[str, JsonValue]],
        evidence: Sequence[Mapping[str, JsonValue]],
    ) -> list[dict[str, JsonValue]]:
        prompt = _build_prompt(context, playbook_hits, evidence)
        body = _build_request_body(provider, model, prompt)
        try:
            response = httpx.post(
                _provider_endpoint(provider),
                headers=_build_request_headers(provider, api_key),
                json=body,
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping):
                return _prometheus_query_fallback(context, playbook_hits, evidence)
            text = _extract_text(payload)
            if text is None:
                return _prometheus_query_fallback(context, playbook_hits, evidence)
            raw = json.loads(text)
        except Exception:  # noqa: BLE001 — provider failure must degrade deterministically
            return _prometheus_query_fallback(context, playbook_hits, evidence)

        descriptors = _normalize_descriptors(raw)
        if descriptors is None:
            return _prometheus_query_fallback(context, playbook_hits, evidence)
        return descriptors

    return _source


def build_configured_hypothesis_source() -> HypothesisSource:
    """Build the runtime hypothesis source from env/config.

    Behavior:
    - flag disabled → deterministic rule-based source
    - provider or key unavailable → deterministic rule-based source
    - provider enabled + key available → LLM-backed source with strict fallback
    - invalid model output / API failure → deterministic rule-based source
    """
    if not _env_flag(_LLM_ENABLED_ENV):
        return _rule_based_source

    provider = os.environ.get(_LLM_PROVIDER_ENV, _LLM_DEFAULT_PROVIDER).strip().lower()
    if provider not in {_LLM_PROVIDER_ANTHROPIC, _LLM_PROVIDER_OPENAI}:
        return _rule_based_source

    api_key = _provider_api_key(provider)
    if api_key is None:
        return _rule_based_source

    model = _provider_model(provider, os.environ.get(_LLM_MODEL_ENV))
    return _llm_hypothesis_source(provider, api_key, model)


__all__ = ["build_configured_hypothesis_source"]
