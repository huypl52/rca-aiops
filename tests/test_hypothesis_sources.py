from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest

from graph.compiled import build_default_compiled_runner
from graph.hypothesis_sources import build_configured_hypothesis_source
from graph.nodes.hypothesis_planner import _rule_based_source
from graph.state import JsonValue


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


@pytest.fixture()
def sample_inputs() -> tuple[
    Mapping[str, JsonValue],
    Sequence[Mapping[str, JsonValue]],
    Sequence[Mapping[str, JsonValue]],
]:
    context: dict[str, JsonValue] = {
        "service": "checkout",
        "namespace": "demo",
        "time_window": {"start": "2026-06-30T11:00:00Z", "end": "2026-06-30T11:05:00Z"},
        "labels": {"severity": "critical"},
        "topology_seed": {"services": ["checkout", "payment"]},
    }
    playbook_hits: list[dict[str, JsonValue]] = [
        {"id": "pb-1", "score": 0.91, "title": "Payment timeout playbook"},
    ]
    evidence: list[dict[str, JsonValue]] = [
        {
            "source_type": "prometheus",
            "source_name": "checkout",
            "query": "up",
            "timestamp_range": {"start": "2026-06-30T11:00:00Z", "end": "2026-06-30T11:05:00Z"},
            "summary": "error rate increased",
            "raw_excerpt": "checkout errors are rising",
        },
    ]
    return context, playbook_hits, evidence


@pytest.mark.parametrize(
    ("provider", "key_env"),
    [("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")],
)
def test_configured_source_falls_back_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    key_env: str,
) -> None:
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_ENABLED", "1")
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_PROVIDER", provider)
    monkeypatch.delenv("RCA_HYPOTHESIS_LLM_API_KEY", raising=False)
    monkeypatch.delenv(key_env, raising=False)
    source = build_configured_hypothesis_source()
    assert source is _rule_based_source


@pytest.mark.parametrize(
    ("provider", "key_env"),
    [("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")],
)
def test_provider_error_falls_back_to_executable_prometheus_source(
    monkeypatch: pytest.MonkeyPatch,
    sample_inputs: tuple[
        Mapping[str, JsonValue],
        Sequence[Mapping[str, JsonValue]],
        Sequence[Mapping[str, JsonValue]],
    ],
    provider: str,
    key_env: str,
) -> None:
    context, playbook_hits, evidence = sample_inputs
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_ENABLED", "true")
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_PROVIDER", provider)
    monkeypatch.setenv(key_env, "dummy")
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_MODEL", "model-name")

    def _boom(*args: object, **kwargs: object) -> _FakeResponse:
        del args, kwargs
        raise httpx.HTTPError("simulated provider failure")

    monkeypatch.setattr("graph.hypothesis_sources.httpx.post", _boom)
    source = build_configured_hypothesis_source()
    result = source(context, playbook_hits, evidence)

    assert len(result) == 3
    assert [item["priority"] for item in result] == [1, 2, 3]
    for item in result:
        plan = cast(dict[str, JsonValue], item["plan"])
        assert item["status"] == "proposed"
        assert plan["tool"] == "query_prometheus_raw"
        assert isinstance(plan["query"], str) and plan["query"]
        assert plan["timestamp_range"] == context["time_window"]


@pytest.mark.parametrize(
    ("provider", "key_env", "endpoint", "response_payload"),
    [
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            "https://api.anthropic.com/v1/messages",
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            [
                                {
                                    "priority": 1,
                                    "plan": {
                                        "tool": "query_prometheus_raw",
                                        "query": 'rate(http_requests_total{service="checkout"}[5m])',
                                        "timestamp_range": {
                                            "start": "2026-06-30T11:00:00Z",
                                            "end": "2026-06-30T11:05:00Z",
                                        },
                                        "extra": "ignored",
                                    },
                                    "status": "proposed",
                                    "junk": "drop-me",
                                }
                            ]
                        ),
                    }
                ]
            },
        ),
        (
            "openai",
            "OPENAI_API_KEY",
            "http://127.0.0.1:8317/v1/chat/completions",
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [
                                    {
                                        "priority": 1,
                                        "plan": {
                                            "tool": "query_prometheus_raw",
                                            "query": 'rate(http_requests_total{service="checkout"}[5m])',
                                            "timestamp_range": {
                                                "start": "2026-06-30T11:00:00Z",
                                                "end": "2026-06-30T11:05:00Z",
                                            },
                                            "extra": "ignored",
                                        },
                                        "status": "proposed",
                                        "junk": "drop-me",
                                    }
                                ]
                            )
                        }
                    }
                ]
            },
        ),
    ],
)
def test_valid_llm_output_is_normalized_and_uses_provider_wiring(
    monkeypatch: pytest.MonkeyPatch,
    sample_inputs: tuple[
        Mapping[str, JsonValue],
        Sequence[Mapping[str, JsonValue]],
        Sequence[Mapping[str, JsonValue]],
    ],
    provider: str,
    key_env: str,
    endpoint: str,
    response_payload: dict[str, object],
) -> None:
    context, playbook_hits, evidence = sample_inputs
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_ENABLED", "1")
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_PROVIDER", provider)
    monkeypatch.setenv(key_env, "dummy")
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_MODEL", "custom-model")
    if provider == "openai":
        monkeypatch.setenv("OPENAI_API_URL", "http://127.0.0.1:8317")

    calls: list[dict[str, object]] = []

    def _good_post(
        url: str,
        *,
        headers: Mapping[str, str],
        json: object,
        timeout: float,
    ) -> _FakeResponse:
        calls.append({"url": url, "headers": dict(headers), "json": json, "timeout": timeout})
        return _FakeResponse(response_payload)

    monkeypatch.setattr("graph.hypothesis_sources.httpx.post", _good_post)
    source = build_configured_hypothesis_source()
    result = source(context, playbook_hits, evidence)

    assert len(calls) == 1
    assert calls[0]["url"] == endpoint
    assert calls[0]["timeout"] == 20.0
    if provider == "anthropic":
        assert calls[0]["headers"] == {
            "x-api-key": "dummy",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        request_body = calls[0]["json"]
        assert isinstance(request_body, dict)
        assert request_body["model"] == "custom-model"
        assert request_body["system"]
        assert request_body["messages"][0]["role"] == "user"
    else:
        assert calls[0]["headers"] == {
            "authorization": "Bearer dummy",
            "content-type": "application/json",
        }
        request_body = calls[0]["json"]
        assert isinstance(request_body, dict)
        assert request_body["model"] == "custom-model"
        assert request_body["messages"][0]["role"] == "system"
        assert request_body["messages"][1]["role"] == "user"

    assert len(result) == 1
    assert set(result[0].keys()) == {"priority", "plan", "status"}
    assert result[0]["priority"] == 1
    assert result[0]["status"] == "proposed"
    assert isinstance(result[0]["plan"], dict)
    assert result[0]["plan"] == {
        "tool": "query_prometheus_raw",
        "query": 'rate(http_requests_total{service="checkout"}[5m])',
        "timestamp_range": {
            "start": "2026-06-30T11:00:00Z",
            "end": "2026-06-30T11:05:00Z",
        },
    }
    assert "junk" not in result[0]


def test_non_executable_llm_plan_falls_back_to_prometheus_queries(
    monkeypatch: pytest.MonkeyPatch,
    sample_inputs: tuple[
        Mapping[str, JsonValue],
        Sequence[Mapping[str, JsonValue]],
        Sequence[Mapping[str, JsonValue]],
    ],
) -> None:
    context, playbook_hits, evidence = sample_inputs
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_ENABLED", "1")
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("OPENAI_API_URL", "http://127.0.0.1:8317")

    payload = [
        {
            "priority": 1,
            "plan": {
                "tool": "collect_prometheus_metric_evidence",
                "query": "check latency",
                "timestamp_range": {
                    "start": "2026-06-30T11:00:00Z",
                    "end": "2026-06-30T11:05:00Z",
                },
            },
            "status": "proposed",
        }
    ]

    def _bad_but_200(*args: object, **kwargs: object) -> _FakeResponse:
        del args, kwargs
        return _FakeResponse({"choices": [{"message": {"content": json.dumps(payload)}}]})

    monkeypatch.setattr("graph.hypothesis_sources.httpx.post", _bad_but_200)
    source = build_configured_hypothesis_source()
    result = source(context, playbook_hits, evidence)

    assert len(result) == 3
    for item in result:
        plan = cast(dict[str, JsonValue], item["plan"])
        assert plan["tool"] == "query_prometheus_raw"
        assert plan["timestamp_range"] == context["time_window"]


def test_default_compiled_runner_uses_env_gated_llm_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_ENABLED", "1")
    monkeypatch.setenv("RCA_HYPOTHESIS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("OPENAI_API_URL", "http://127.0.0.1:8317")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-5.4-mini")
    monkeypatch.delenv("RCA_HYPOTHESIS_LLM_MODEL", raising=False)

    calls: list[object] = []

    def _good_post(
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        **kwargs: object,
    ) -> _FakeResponse:
        del headers, timeout, kwargs
        calls.append(url)
        payload = [
            {
                "priority": 1,
                "plan": {
                    "tool": "query_prometheus_raw",
                    "query": 'up{service="checkout"}',
                    "timestamp_range": {
                        "start": "2026-06-30T11:00:00Z",
                        "end": "2026-06-30T11:05:00Z",
                    },
                },
                "status": "proposed",
            }
        ]
        return _FakeResponse({"choices": [{"message": {"content": json.dumps(payload)}}]})

    monkeypatch.setattr("graph.hypothesis_sources.httpx.post", _good_post)

    runner = build_default_compiled_runner()
    result = asyncio.run(runner.run({"service": "checkout"}, "inv-llm", max_iterations=1))

    assert calls, "expected the env-gated LLM source to execute inside the compiled graph path"
    tool_calls_count = result["state_snapshot"]["tool_calls_count"]
    assert isinstance(tool_calls_count, int)
    assert tool_calls_count >= 1
