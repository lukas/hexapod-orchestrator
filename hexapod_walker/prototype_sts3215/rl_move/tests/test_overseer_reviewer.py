"""Advisory request admission, accounting and parsing; no live provider calls."""

from copy import deepcopy
from decimal import Decimal
import json

import pytest

from rl_move.overseer.reviewer import ReviewConfig, review_once
from rl_move.overseer import reviewer


class FakeStore:
    def __init__(self, remaining="20"):
        self.remaining = Decimal(remaining)
        self.operations = {}
        self.settlements = []

    def reserve(self, wake_id, operation_id, max_cost_usd, now=None):
        if operation_id in self.operations:
            return {"reused": True}
        maximum = Decimal(max_cost_usd)
        if maximum > self.remaining:
            raise ValueError("Budget exceeded")
        self.remaining -= maximum
        self.operations[operation_id] = {"wake_id": wake_id, "maximum": maximum, "actual": None}
        return {"reused": False}

    def settle(self, operation_id, actual_cost_usd, now=None):
        actual = Decimal(actual_cost_usd)
        operation = self.operations[operation_id]
        operation["actual"] = actual
        self.remaining += operation["maximum"] - actual
        self.settlements.append((operation_id, actual))
        return {"overrun_usd": str(max(Decimal(0), actual - operation["maximum"]))}


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-private-key")
    return ReviewConfig(
        model="claude-fixture-model", input_usd_per_million="2", output_usd_per_million="10",
        model_context_tokens=200000, pricing_verified=True,
        pricing_reference="Fixture rates and context only; not production pricing",
        max_output_tokens=2048,
    )


@pytest.fixture
def response(config):
    review = {
        "summary": "Authentication has failed repeatedly without new evidence.",
        "risks": ["Usage from one task is unknown."],
        "recommended_actions": [{
            "action": "repair_auth", "target": "cloud-controller", "reason": "Resolve the observed blocker once",
            "evidence": ["snapshot:controller/authentication"],
        }],
        "goal_assessment": {
            "any_means": {"sim": "No fresh demo evidence", "physical": "Unknown", "next_step": "Inspect pinned demo"},
            "rl_only": {"sim": "No fresh demo evidence", "physical": "Unknown", "next_step": "Inspect policy lineage"},
        },
    }
    return {
        "model": config.model, "stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 200},
        "content": [{"type": "text", "text": json.dumps(review)}],
    }


def test_request_reserved_before_call_and_charges_only_reported_tokens(config, response):
    store = FakeStore()
    calls = []

    def transport(payload, key, timeout):
        assert store.operations["review-1"]["maximum"] == Decimal("0.420480")
        assert payload["model"] == config.model
        assert payload["max_tokens"] == config.max_output_tokens
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["service_tier"] == "standard_only"
        assert "tools" not in payload and "cache_control" not in payload
        assert key == "fixture-private-key"
        assert timeout == 45
        calls.append(payload)
        return response

    result = review_once(store, "wake-1", "review-1", {"running": []}, config, transport=transport)
    assert len(calls) == 1
    assert result["status"] == "completed"
    assert result["advisory_only"] is True
    assert result["actual_cost_usd"] == "0.002200"
    assert store.settlements == [("review-1", Decimal("0.002200"))]
    assert result["review"]["recommended_actions"][0]["action"] == "repair_auth"


def test_budget_exhausted_or_duplicate_operation_never_dispatches(config, response):
    calls = []
    transport = lambda *args: calls.append(args) or response
    with pytest.raises(ValueError, match="Budget exceeded"):
        review_once(FakeStore("0.4"), "wake-1", "review-1", {}, config, transport=transport)
    store = FakeStore()
    review_once(store, "wake-1", "review-1", {}, config, transport=transport)
    with pytest.raises(ValueError, match="duplicate paid request"):
        review_once(store, "wake-1", "review-1", {}, config, transport=transport)
    assert len(calls) == 1


def test_subreviews_draw_from_same_wake_reservations(config):
    store = FakeStore("0.5")
    calls = []

    def transport(*args):
        calls.append(args)
        raise TimeoutError("Uncertain provider completion")

    result = review_once(store, "wake-1", "parent-review", {}, config, transport=transport)
    assert result["status"] == "blocked"
    with pytest.raises(ValueError, match="Budget exceeded"):
        review_once(store, "wake-1", "child-review", {}, config, transport=transport)
    assert store.operations["parent-review"]["wake_id"] == "wake-1"
    assert len(calls) == 1


def test_timeout_preserves_reservation_and_does_not_echo_secret(config):
    store = FakeStore()
    calls = []

    def transport(*args):
        calls.append(args)
        raise TimeoutError("fixture-private-key leaked in upstream error")

    result = review_once(store, "wake-1", "review-1", {}, config, transport=transport)
    assert result["billing_reconciliation_required"] is True
    assert result["actual_cost_usd"] is None
    assert not store.settlements
    assert "fixture-private-key" not in json.dumps(result)
    with pytest.raises(ValueError, match="duplicate paid request"):
        review_once(store, "wake-1", "review-1", {}, config, transport=transport)
    assert len(calls) == 1


@pytest.mark.parametrize("usage", [
    {}, {"input_tokens": -1, "output_tokens": 1}, {"input_tokens": 1.5, "output_tokens": 1},
    {"input_tokens": True, "output_tokens": 1}, {"input_tokens": 1, "output_tokens": float("inf")},
    {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": False},
    {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 12},
    {"input_tokens": 1, "output_tokens": 1, "server_tool_use": {"web_search_requests": 1}},
    {"input_tokens": 1, "output_tokens": 1, "service_tier": "priority"},
])
def test_uncertain_usage_never_refunds(config, response, usage):
    response["usage"] = usage
    store = FakeStore()
    result = review_once(store, "wake-1", "review-1", {}, config, transport=lambda *args: response)
    assert result["status"] == "blocked"
    assert result["billing_reconciliation_required"] is True
    assert not store.settlements


def test_unexpected_model_keeps_reservation(config, response):
    response["model"] = "claude-different-prices"
    store = FakeStore()
    result = review_once(store, "wake-1", "review-1", {}, config, transport=lambda *args: response)
    assert result["status"] == "blocked"
    assert not store.settlements


def test_provider_overrun_is_accounted_before_stopping(config, response):
    response["usage"]["input_tokens"] = config.model_context_tokens + 1000000
    store = FakeStore()
    result = review_once(store, "wake-1", "review-1", {}, config, transport=lambda *args: response)
    assert result["status"] == "budget_anomaly"
    assert Decimal(result["actual_cost_usd"]) > Decimal(result["reserved_usd"])
    assert store.settlements == [("review-1", Decimal("2.402000"))]
    assert "review" not in result


@pytest.mark.parametrize("mutation", ["json", "truncated", "tool", "schema", "goals", "action"])
def test_invalid_paid_advice_is_charged_and_never_executed(config, response, mutation):
    if mutation == "json":
        response["content"][0]["text"] = "not JSON"
    elif mutation == "truncated":
        response["stop_reason"] = "max_tokens"
    elif mutation == "tool":
        response["content"] = [{"type": "tool_use", "name": "run_shell", "input": {"cmd": "stop robot"}}]
    else:
        content = json.loads(response["content"][0]["text"])
        if mutation == "schema":
            content["execute"] = "touch /tmp/something"
        elif mutation == "goals":
            del content["goal_assessment"]["rl_only"]["physical"]
        else:
            content["recommended_actions"][0]["action"] = "run_shell"
        response["content"][0]["text"] = json.dumps(content)
    store = FakeStore()
    result = review_once(store, "wake-1", "review-1", {}, config, transport=lambda *args: response)
    assert result["status"] == "invalid_response"
    assert len(store.settlements) == 1
    assert "review" not in result


def test_input_and_output_redact_secrets(config, response):
    seen = []
    content = json.loads(response["content"][0]["text"])
    content["summary"] = "fixture-private-key Authorization: Bearer other-private-token"
    response["content"][0]["text"] = json.dumps(content)

    def transport(payload, *args):
        seen.append(payload)
        return response

    result = review_once(FakeStore(), "wake-1", "review-1", {
        "api_key": "another-secret", "log": "credential fixture-private-key sk-ant-abc123 password=hunter2",
    }, config, transport=transport)
    serialized = json.dumps({"sent": seen, "result": result})
    for secret in ["fixture-private-key", "another-secret", "sk-ant-abc123", "hunter2", "other-private-token"]:
        assert secret not in serialized
    assert "[REDACTED]" in serialized


def test_prompt_limit_and_missing_key_fail_before_reserving(config, monkeypatch):
    store = FakeStore()
    with pytest.raises(ValueError, match="prompt byte limit"):
        review_once(store, "wake-1", "review-1", {"logs": "x" * 65536}, config)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(ValueError, match="not configured"):
        review_once(store, "wake-1", "review-1", {}, config)
    assert not store.operations


@pytest.mark.parametrize("change", [
    {"model": ""}, {"input_usd_per_million": "0"}, {"input_usd_per_million": "NaN"},
    {"output_usd_per_million": "Infinity"}, {"output_usd_per_million": "-1"},
    {"model_context_tokens": True}, {"model_context_tokens": 0}, {"max_output_tokens": 9000},
    {"pricing_verified": False}, {"pricing_verified": "true"}, {"pricing_reference": " "},
    {"timeout_seconds": float("nan")}, {"timeout_seconds": 301},
])
def test_missing_or_invalid_pricing_and_limit_metadata_fail_closed(config, change):
    fields = deepcopy(config.__dict__)
    fields.update(change)
    with pytest.raises(ValueError):
        ReviewConfig(**fields)


@pytest.mark.parametrize("http_status", [200, 302, 401, 500])
def test_default_transport_fixed_host_no_redirects_or_retry(config, response, monkeypatch, http_status):
    requests = []
    closed = []
    response_bytes = [json.dumps(response).encode(), b""]

    class Reply:
        status = http_status

        def read1(self, size):
            assert http_status == 200  # Do not read/echo provider error bodies.
            return response_bytes.pop(0)

    class Connection:
        sock = None

        def __init__(self, host, *, timeout, context):
            assert host == "api.anthropic.com"
            assert timeout == 45

        def connect(self):
            pass

        def request(self, method, path, *, body, headers):
            assert method == "POST" and path == "/v1/messages"
            assert headers["x-api-key"] == "fixture-private-key"
            requests.append(json.loads(body))

        def getresponse(self):
            return Reply()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(reviewer.http.client, "HTTPSConnection", Connection)
    store = FakeStore()
    result = review_once(store, "wake-1", "review-1", {}, config)
    assert len(requests) == 1
    assert closed == [True]
    if http_status == 200:
        assert result["status"] == "completed"
    else:
        assert result["status"] == "blocked"
        assert result["stop_wake"] is True
        assert not store.settlements
