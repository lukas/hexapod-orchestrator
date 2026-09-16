"""Provider output contracts and private diagnostics, using synthetic responses."""
from dataclasses import replace
import json

import pytest

from rl_move.overseer.reviewer import ReviewConfig, _validate_review, bundled_reviewer_config, review_once
from rl_move.overseer.store import Store


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-private-provider-key")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-private-provider-key")
    config = ReviewConfig(model="claude-fixture", input_usd_per_million="2",
                          output_usd_per_million="10", model_context_tokens=200000,
                          pricing_verified=True, pricing_reference="Synthetic fixture prices")
    store = Store(tmp_path / "ledger.sqlite3")
    wake = store.start_wake("Synthetic output contract review")["wake_id"]
    return store, wake, config


def advice():
    return {"summary": "Inspect current walking evidence", "risks": ["No current physical observation"],
            "recommended_actions": [{"action": "inspect", "target": "demo",
                                     "reason": "Verify current evidence", "evidence": ["snapshot:demo"]}],
            "goal_assessment": {goal: {"sim": "Unknown", "physical": "Unknown", "next_step": "Inspect demo"}
                                for goal in ("any_means", "rl_only")},
            "strategic_assessment": {topic: {"diagnosis": "Unknown", "evidence": [],
                                              "decision": "Inspect evidence",
                                              "next_review_trigger": "New measured result"}
                                     for topic in ("robot_lab_throughput", "rl_experiment_portfolio",
                                                   "integrated_policy")}}


def response(config, text=None):
    text = json.dumps(advice()) if text is None else text
    if config.provider == "codex":
        return {"id": "resp_synthetic", "model": config.model, "status": "completed", "service_tier": "default",
                "usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 25}},
                "output": [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "private-reasoning"}]},
                           {"type": "message", "status": "completed", "role": "assistant",
                            "content": [{"type": "output_text", "text": text}]}]}
    return {"id": "msg_synthetic", "model": config.model, "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "content": [{"type": "text", "text": text}]}


def invoke(harness, reply, *, config=None, transport=None):
    store, wake, default_config = harness
    return review_once(store, wake, "call", {}, config or default_config,
                       transport=transport or (lambda *args: reply))


def assert_closed_object(schema, required):
    assert schema["type"] == "object"
    assert set(schema["properties"]) == set(schema["required"]) == set(required)
    assert schema["additionalProperties"] is False


def test_claude_requests_closed_json_schema_and_retains_bounded_single_call(harness):
    _, _, config = harness
    reply = response(config)
    calls = []

    def transport(payload, key, timeout):
        calls.append(payload)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["max_tokens"] == config.max_output_tokens
        assert payload["stream"] is False and "tools" not in payload
        output_format = payload["output_config"]["format"]
        assert output_format["type"] == "json_schema"
        schema = output_format["schema"]
        assert_closed_object(schema, {"summary", "risks", "recommended_actions", "goal_assessment",
                                      "strategic_assessment"})
        assert schema["properties"]["summary"]["type"] == "string"
        assert schema["properties"]["risks"]["type"] == "array"
        assert schema["properties"]["risks"]["items"]["type"] == "string"
        actions = schema["properties"]["recommended_actions"]
        assert actions["type"] == "array"
        assert_closed_object(actions["items"], {"action", "target", "reason", "evidence"})
        assert set(actions["items"]["properties"]["action"]["enum"]) == {
            "continue", "inspect", "change_strategy", "pause_agent", "repair_auth", "notify", "automate",
            "stop_review"}
        assert actions["items"]["properties"]["evidence"]["items"]["type"] == "string"
        goals = schema["properties"]["goal_assessment"]
        assert_closed_object(goals, {"any_means", "rl_only"})
        for goal in goals["properties"].values():
            assert_closed_object(goal, {"sim", "physical", "next_step"})
            assert all(field["type"] == "string" for field in goal["properties"].values())
        strategy = schema["properties"]["strategic_assessment"]
        assert_closed_object(strategy, {"robot_lab_throughput", "rl_experiment_portfolio", "integrated_policy"})
        for topic in strategy["properties"].values():
            assert_closed_object(topic, {"diagnosis", "evidence", "decision", "next_review_trigger"})
        return reply

    result = invoke(harness, reply, transport=transport)
    assert len(calls) == 1
    assert result["status"] == "completed" and result["provider_response_id"] == "msg_synthetic"
    assert "invalid_advisory_excerpt" not in result


def test_fable_uses_adaptive_effort_and_accepts_private_thinking_blocks(harness):
    config = replace(harness[2], model="claude-fable-5-1", reasoning_effort="high")
    reply = response(config)
    reply["content"].insert(0, {"type": "thinking", "thinking": "private reasoning",
                                "signature": "opaque-signature"})

    def transport(payload, key, timeout):
        assert "thinking" not in payload
        assert payload["output_config"]["effort"] == "high"
        return reply

    result = invoke(harness, reply, config=config, transport=transport)
    assert result["status"] == "completed"
    assert "private reasoning" not in json.dumps(result)


def test_bundled_claude_profile_is_fable_and_fits_wrap_up_gate():
    config = ReviewConfig(**json.loads(bundled_reviewer_config("claude").read_text()))
    assert config.model == "claude-fable-5-1"
    assert config.adaptive_thinking is True
    assert config.reservation_usd < 15


def test_new_calls_require_strategy_but_historical_advice_remains_readable():
    legacy = advice()
    legacy.pop("strategic_assessment")
    with pytest.raises(ValueError, match="schema"):
        _validate_review(legacy)
    assert _validate_review(legacy, allow_legacy=True) is legacy


@pytest.mark.parametrize("effort", ["none", "minimal", "xhigh"])
def test_fable_rejects_unsupported_effort_values(harness, effort):
    with pytest.raises(ValueError, match="Claude Fable"):
        replace(harness[2], model="claude-fable-5-1", reasoning_effort=effort)


@pytest.mark.parametrize("mutation", ["malformed-json", "unsupported-action", "missing-goal-field", "oversized-string", "too-many-risks"])
def test_invalid_advice_still_charges_and_reports_validation_reason(harness, mutation):
    value = advice()
    if mutation == "unsupported-action":
        value["recommended_actions"][0]["action"] = "run_shell"
    elif mutation == "missing-goal-field":
        del value["goal_assessment"]["rl_only"]["physical"]
    elif mutation == "oversized-string":
        value["summary"] = "x" * 4001
    elif mutation == "too-many-risks":
        value["risks"] = ["unknown"] * 21
    text = "malformed advice fixture-private-provider-key password=private-password" if mutation == "malformed-json" else json.dumps(value)
    result = invoke(harness, response(harness[2], text))
    assert result["status"] == "invalid_response" and result["stop_wake"] is True
    assert result["actual_cost_usd"] == "0.002200"
    assert result["billing_reconciliation_required"] is False
    assert harness[0].snapshot()["daily_charged_usd"] == "0.002200"
    assert "review" not in result and result["advisory_only"] is True
    assert result["validation_error"] and len(result["validation_error"]) <= 500
    assert result["provider_stop_reason"] == "end_turn"
    assert result["provider_response_id"] == "msg_synthetic"
    assert result["invalid_advisory_excerpt"]
    serialized = json.dumps(result)
    assert "fixture-private-provider-key" not in serialized
    assert "private-password" not in serialized


def test_diagnostics_exclude_thinking_and_tool_input(harness):
    reply = response(harness[2], "visible advisory prefix")
    reply["content"] += [
        {"type": "thinking", "thinking": "private-thought", "text": "thinking-must-not-export"},
        {"type": "redacted_thinking", "data": "private-encrypted-thought"},
        {"type": "tool_use", "name": "shell", "input": {"command": "private-tool-input"},
         "text": "tool-must-not-export"},
    ]
    result = invoke(harness, reply)
    assert result["status"] == "invalid_response"
    assert result["invalid_advisory_excerpt"] == "visible advisory prefix"
    assert result["validation_error"]
    serialized = json.dumps(result)
    for private in ("private-thought", "thinking-must-not-export", "private-encrypted-thought",
                    "private-tool-input", "tool-must-not-export"):
        assert private not in serialized


def test_excerpt_is_sanitized_before_clipping_and_stop_reason_is_bounded(harness):
    text = "visible " + "x" * 15980 + "fixture-private-provider-key " + "tail " * 4000
    reply = response(harness[2], text)
    reply["stop_reason"] = "max_tokens " + "fixture-private-provider-key " * 50
    result = invoke(harness, reply)
    assert result["status"] == "invalid_response"
    assert len(result["invalid_advisory_excerpt"]) == 16000
    assert "fixture-private" not in result["invalid_advisory_excerpt"]
    assert "[REDACTED]" in result["invalid_advisory_excerpt"]
    assert len(result["provider_stop_reason"]) <= 200
    assert "fixture-private" not in result["provider_stop_reason"]


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("container", [None, "wrong-container", {"text": "wrong-container"}])
def test_malformed_content_still_returns_accounted_diagnostic(harness, provider, container):
    config = replace(harness[2], provider=provider,
                     model="claude-fixture" if provider == "claude" else "gpt-fixture-codex")
    reply = response(config)
    if provider == "claude":
        reply["content"] = container
    else:
        reply["output"][1]["content"] = container
    result = invoke(harness, reply, config=config)
    assert result["status"] == "invalid_response"
    assert result["actual_cost_usd"] == "0.002200"
    assert result["invalid_advisory_excerpt"] == ""
    assert result["validation_error"]


@pytest.mark.parametrize("provider_id", [None, 123, "msg_optional_receipt"])
def test_provider_response_id_is_optional_receipt(harness, provider_id):
    reply = response(harness[2])
    reply["id"] = provider_id
    result = invoke(harness, reply)
    assert result["status"] == "completed"
    if isinstance(provider_id, str):
        assert result["provider_response_id"] == provider_id
    else:
        assert "provider_response_id" not in result


def test_response_id_is_sanitized_before_clipping(harness):
    reply = response(harness[2])
    reply["id"] = "r" * 185 + "fixture-private-provider-key"
    result = invoke(harness, reply)
    assert len(result["provider_response_id"]) <= 200
    assert "fixture-private" not in result["provider_response_id"]
    assert "[REDACTED]" in result["provider_response_id"]


def test_codex_request_contract_unchanged_and_diagnostics_ignore_reasoning(harness):
    config = replace(harness[2], provider="codex", model="gpt-fixture-codex")
    reply = response(config, "visible invalid JSON sk-proj-hidden")

    def transport(payload, key, timeout):
        assert "output_config" not in payload
        assert payload["text"] == {"format": {"type": "json_object"}}
        assert payload["max_output_tokens"] == config.max_output_tokens
        assert payload["tools"] == [] and payload["tool_choice"] == "none"
        assert payload["background"] is False and payload["store"] is False
        return reply

    result = invoke(harness, reply, config=config, transport=transport)
    assert result["status"] == "invalid_response"
    assert result["provider_stop_reason"] == "completed"
    assert result["provider_response_id"] == "resp_synthetic"
    assert result["invalid_advisory_excerpt"] == "visible invalid JSON [REDACTED]"
    assert result["actual_cost_usd"] == "0.002200"
    assert "private-reasoning" not in json.dumps(result)
