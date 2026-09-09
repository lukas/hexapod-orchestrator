"""Tool-free provider review with synthetic usage; no paid calls or agent CLIs."""
from dataclasses import replace
from decimal import Decimal
import json

import pytest

from rl_move.overseer import reviewer
from rl_move.overseer.reviewer import ReviewConfig, review_once
from rl_move.overseer.store import BudgetExceeded, Store


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai-private-key")
    return ReviewConfig(
        provider="codex", model="gpt-fixture-codex",
        input_usd_per_million="2", output_usd_per_million="10",
        cached_input_usd_per_million="0.5", cache_write_usd_per_million="3",
        model_context_tokens=200000, max_output_tokens=2048,
        pricing_verified=True, pricing_reference="Synthetic fixture rates; not production pricing",
    )


@pytest.fixture
def response(config):
    advisory = {
        "summary": "Two tasks have no new progress evidence.", "risks": ["Receipts are incomplete."],
        "recommended_actions": [{"action": "inspect", "target": "task-a",
                                 "reason": "Check the latest artifact", "evidence": ["snapshot:task-a"]}],
        "goal_assessment": {
            goal: {"sim": "Unknown", "physical": "Unknown", "next_step": "Inspect the latest demo"}
            for goal in ("any_means", "rl_only")
        },
    }
    return {
        "model": config.model, "status": "completed", "service_tier": "default",
        "error": None, "incomplete_details": None,
        "usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300,
                  "input_tokens_details": {"cached_tokens": 40, "cache_write_tokens": 10},
                  "output_tokens_details": {"reasoning_tokens": 150}},
        "output": [{"type": "reasoning", "summary": []},
                   {"type": "message", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(advisory), "annotations": []}]}],
    }


@pytest.fixture
def ledger(tmp_path):
    store = Store(tmp_path / "review.sqlite3")
    wake = store.start_wake("Synthetic provider review")["wake_id"]
    return store, wake


def invoke(ledger, config, response, *, operation="call", transport=None, snapshot=None):
    store, wake = ledger
    return review_once(store, wake, operation, snapshot or {}, config,
                       transport=transport or (lambda *args: response))


def test_responses_request_is_bounded_and_reserved_before_single_call(ledger, config, response):
    calls = []

    def transport(payload, key, timeout):
        store, wake = ledger
        assert store.snapshot()["active_wake_charged_usd"] == "0.620480"
        assert payload == {
            "model": config.model, "max_output_tokens": 2048,
            "instructions": reviewer.REVIEW_SYSTEM_PROMPT,
            "input": [{"role": "user", "content": '{"task": "a"}'}],
            "reasoning": {"effort": "low"}, "text": {"format": {"type": "json_object"}},
            "tools": [], "tool_choice": "none", "service_tier": "default", "stream": False,
            "store": False, "background": False, "truncation": "disabled",
        }
        assert key == "fixture-openai-private-key" and timeout == 45
        calls.append(wake)
        return response

    result = invoke(ledger, config, response, transport=transport, snapshot={"task": "a"})
    assert len(calls) == 1
    assert result["status"] == "completed" and result["advisory_only"] is True
    assert result["provider"] == "codex"
    # Cached/write inputs are subsets, and reasoning is already in output tokens.
    assert result["actual_cost_usd"] == "0.002150"
    assert result["provider_usage"] == {
        "input_tokens": 100, "uncached_input_tokens": 50, "cached_input_tokens": 40,
        "cache_write_input_tokens": 10, "output_tokens": 200,
        "reasoning_tokens": 150, "total_tokens": 300,
    }
    assert ledger[0].snapshot()["active_wake_charged_usd"] == "0.002150"


def test_automatic_openai_cache_without_explicit_rates_uses_verified_upper_bound(ledger, config, response):
    config = replace(config, cached_input_usd_per_million=None, cache_write_usd_per_million=None)
    result = invoke(ledger, config, response)
    assert result["actual_cost_usd"] == "0.002200"
    assert result["cost_basis"] == "caller_verified_upper_bound_rates"
    assert result["reserved_usd"] == "0.420480"


def test_claude_cache_usage_adds_to_uncached_input(ledger, config, response, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-claude-key")
    config = replace(config, provider="claude", model="claude-fixture")
    response = {
        "model": config.model, "stop_reason": "end_turn",
        "usage": {"input_tokens": 50, "cache_read_input_tokens": 40,
                  "cache_creation_input_tokens": 10, "output_tokens": 200},
        "content": [{"type": "text", "text": response["output"][1]["content"][0]["text"]}],
    }
    result = invoke(ledger, config, response)
    assert result["status"] == "completed" and result["provider"] == "claude"
    assert result["actual_cost_usd"] == "0.002150"
    assert result["provider_usage"]["input_tokens"] == 100


def test_missing_codex_key_never_falls_back_to_claude_or_reserves(ledger, config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "available-wrong-provider-key")
    with pytest.raises(ValueError, match="OPENAI_API_KEY is not configured"):
        invoke(ledger, config, None)
    assert ledger[0].snapshot()["reservations"] == []


@pytest.mark.parametrize("fields", [
    {"provider": "openai"}, {"provider": []}, {"model": "claude-fixture"},
    {"model": "https://other-origin.invalid"}, {"cached_input_usd_per_million": "NaN"},
    {"cached_input_usd_per_million": "0"}, {"cache_write_usd_per_million": "-1"},
    {"cache_write_usd_per_million": float("inf")}, {"reasoning_effort": "unbounded"},
    {"reasoning_effort": []},
])
def test_provider_and_cache_config_fail_closed(config, fields):
    with pytest.raises(ValueError):
        replace(config, **fields)


@pytest.mark.parametrize("path,value", [
    (("model",), "gpt-unverified-model"), (("status",), "in_progress"),
    (("service_tier",), "priority"), (("service_tier",), None),
    (("usage",), None), (("usage", "input_tokens"), True),
    (("usage", "output_tokens"), -1), (("usage", "total_tokens"), 301),
    (("usage", "input_tokens_details"), None),
    (("usage", "input_tokens_details", "cached_tokens"), 100),
    (("usage", "input_tokens_details", "cached_tokens"), None),
    (("usage", "input_tokens_details", "cache_write_tokens"), 1.5),
    (("usage", "output_tokens_details"), None),
    (("usage", "output_tokens_details", "reasoning_tokens"), 201),
    (("usage", "output_tokens_details", "reasoning_tokens"), True),
    (("output",), [{"type": "web_search_call"}]),
])
def test_unverified_billing_holds_reservation_and_blocks_repeat(ledger, config, response, path, value):
    node = response
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    calls = []
    transport = lambda *args: calls.append(args) or response
    result = invoke(ledger, config, response, transport=transport)
    assert result["status"] == "blocked" and result["stop_wake"] is True
    assert result["billing_reconciliation_required"] is True
    assert result["actual_cost_usd"] is None
    assert ledger[0].snapshot()["active_wake_charged_usd"] == "0.620480"
    with pytest.raises(ValueError, match="duplicate paid request"):
        invoke(ledger, config, response, transport=transport)
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["incomplete", "failed", "refusal", "invalid_json", "unsupported_action"])
def test_unusable_advice_still_charges_known_tokens(ledger, config, response, mutation):
    message = response["output"][1]
    if mutation in {"incomplete", "failed"}:
        response["status"] = mutation
        response["incomplete_details"] = {"reason": "max_output_tokens"}
    elif mutation == "refusal":
        message["content"] = [{"type": "refusal", "refusal": "No advice"}]
    elif mutation == "invalid_json":
        message["content"][0]["text"] = "not JSON"
    else:
        advisory = json.loads(message["content"][0]["text"])
        advisory["recommended_actions"][0]["action"] = "execute_shell"
        message["content"][0]["text"] = json.dumps(advisory)
    result = invoke(ledger, config, response)
    assert result["status"] == "invalid_response" and result["stop_wake"] is True
    assert result["actual_cost_usd"] == "0.002150"
    assert result["billing_reconciliation_required"] is False
    assert "review" not in result
    assert ledger[0].snapshot()["active_wake_charged_usd"] == "0.002150"


def test_provider_overrun_is_settled_and_requires_caller_to_stop(ledger, config, response):
    response["usage"].update(input_tokens=1000000, output_tokens=3000, total_tokens=1003000)
    result = invoke(ledger, config, response)
    assert result["status"] == "budget_anomaly" and result["stop_wake"] is True
    assert Decimal(result["actual_cost_usd"]) > config.reservation_usd
    assert ledger[0].snapshot()["reservations"][0]["overrun_usd"] != "0.000000"
    assert result["billing_reconciliation_required"] is True
    assert "review" not in result


def test_unknown_codex_call_survives_restart_and_shares_budget_with_claude(ledger, config, monkeypatch):
    config = replace(config, input_usd_per_million="60", cached_input_usd_per_million=None,
                     cache_write_usd_per_million=None)
    calls = []

    def timeout(*args):
        calls.append(args)
        raise TimeoutError("fixture-openai-private-key echoed by upstream")

    result = invoke(ledger, config, None, transport=timeout)
    assert "fixture-openai-private-key" not in json.dumps(result)
    reopened = Store(ledger[0].path), ledger[1]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-fixture-key")
    claude_config = replace(config, provider="claude", model="claude-fixture")
    with pytest.raises(BudgetExceeded):
        invoke(reopened, claude_config, None, operation="child", transport=timeout)
    with pytest.raises(ValueError, match="duplicate paid request"):
        invoke(reopened, config, None, transport=timeout)
    assert len(calls) == 1
    assert reopened[0].snapshot()["active_wake_charged_usd"] == "12.020480"


def test_input_output_and_pricing_reference_scrub_keys(ledger, config, response):
    config = replace(config, pricing_reference="https://user:private-pass@example.invalid/pricing")
    advisory = json.loads(response["output"][1]["content"][0]["text"])
    advisory["summary"] = "fixture-openai-private-key sk-proj-privateValue Authorization: Bearer private-token"
    response["output"][1]["content"][0]["text"] = json.dumps(advisory)
    calls = []
    result = invoke(ledger, config, response,
                    snapshot={"OPENAI_API_KEY": "another-secret", "log": "sk-ant-privateValue password=hidden"},
                    transport=lambda payload, *args: calls.append(payload) or response)
    serialized = json.dumps({"sent": calls, "returned": result})
    for secret in ("fixture-openai-private-key", "sk-proj-privateValue", "private-token",
                   "another-secret", "sk-ant-privateValue", "hidden", "private-pass"):
        assert secret not in serialized


@pytest.mark.parametrize("status", [200, 302, 401, 500])
def test_direct_openai_transport_fixed_origin_no_retry_or_redirect(ledger, config, response, monkeypatch, status):
    requests, closed = [], []
    chunks = [json.dumps(response).encode(), b""]

    class Reply:
        def __init__(self):
            self.status = status

        def read1(self, size):
            assert status == 200  # Error bodies may contain echoed secrets.
            return chunks.pop(0)

    class Connection:
        sock = None

        def __init__(self, host, *, timeout, context):
            assert host == "api.openai.com" and timeout == 45

        def connect(self):
            pass

        def request(self, method, path, *, body, headers):
            assert method == "POST" and path == "/v1/responses"
            assert headers["Authorization"] == "Bearer fixture-openai-private-key"
            assert headers["Content-Type"] == "application/json"
            assert "x-api-key" not in headers
            requests.append(json.loads(body))

        def getresponse(self):
            return Reply()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(reviewer.http.client, "HTTPSConnection", Connection)
    result = review_once(ledger[0], ledger[1], "call", {}, config)
    assert len(requests) == len(closed) == 1
    assert result["status"] == ("completed" if status == 200 else "blocked")
    assert result["billing_reconciliation_required"] is (status != 200)
