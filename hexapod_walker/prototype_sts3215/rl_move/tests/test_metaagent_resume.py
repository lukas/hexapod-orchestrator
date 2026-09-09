"""Manual continuation retains one durable wake; all model requests are mocked."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import threading

import pytest

from rl_move.overseer import reviewer
from rl_move.overseer.__main__ import main
from rl_move.overseer.journal import Journal
from rl_move.overseer.policy import evaluate
from rl_move.overseer.store import BudgetExceeded, Store, WakeConflict


NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)


def blocked_wake(store, *, amount="10.153600", wake_id="blocked", operation="old-call"):
    wake = store.start_wake("Original manual review", NOW, wake_id=wake_id)
    store.reserve(wake_id, operation, amount, NOW)
    store.finish_wake(wake_id, "blocked", now=NOW)
    return wake


def test_resume_retains_identity_pending_charge_and_original_cutoff(tmp_path):
    store = Store(tmp_path / "ledger.sqlite3")
    store.register_agent({"agent_id": "agent", "cost_status": "known"})
    store.record_spend("agent", "first-receipt", 101, NOW)
    original = blocked_wake(store)
    old_reservation = store.snapshot(NOW)["reservations"][0]
    store.record_spend("agent", "late-receipt", 5, NOW + timedelta(seconds=1))
    later = NOW + timedelta(days=2)
    resumed = Store(store.path).resume_wake("blocked", "new-call", later)
    for key in ("wake_id", "reason", "started_at", "review_seq"):
        assert resumed[key] == original[key]
    assert resumed["previous_finished_at"] == NOW.isoformat(timespec="microseconds")
    assert resumed["operation_id"] == "new-call" and resumed["status"] == "active"
    assert store.snapshot(later)["reservations"][0] == old_reservation
    assert store.snapshot(later)["daily_charged_usd"] == "10.153600"
    store.reserve("blocked", "new-call", "4.040960", later)
    store.settle("new-call", "0.5", later)
    store.finish_wake("blocked", "succeeded", reviewed_agent_ids=["agent"], now=later)
    assert store.spending_since_review("agent")["amount_usd"] == "5.000000"
    assert store.snapshot(later)["daily_charged_usd"] == "10.653600"
    assert len(store.snapshot(later)["wakes"]) == 1


def test_resumed_requests_share_cumulative_wake_cap(tmp_path):
    store = Store(tmp_path / "ledger.sqlite3")
    blocked_wake(store)
    store.resume_wake("blocked", "new-call", NOW)
    with pytest.raises(BudgetExceeded, match="wake budget"):
        store.reserve("blocked", "new-call", "9.846401", NOW)
    assert store.reserve("blocked", "new-call", "9.846400", NOW)["reused"] is False
    assert store.snapshot(NOW)["active_wake_charged_usd"] == "20.000000"
    assert store.reserve("blocked", "old-call", "10.153600", NOW)["reused"] is True


def test_resumed_requests_share_daily_cap(tmp_path):
    store = Store(tmp_path / "ledger.sqlite3")
    blocked_wake(store)
    for index in range(3):
        blocked_wake(store, amount="20", wake_id=f"other-{index}", operation=f"other-call-{index}")
    blocked_wake(store, amount="8", wake_id="last", operation="last-call")
    store.resume_wake("blocked", "new-call", NOW)
    with pytest.raises(BudgetExceeded, match="24-hour"):
        store.reserve("blocked", "new-call", "2", NOW)
    assert store.snapshot(NOW)["daily_charged_usd"] == "78.153600"


@pytest.mark.parametrize("outcome", ["succeeded", "no_change", "idle"])
def test_only_finished_blocked_wake_can_be_resumed(tmp_path, outcome):
    store = Store(tmp_path / "ledger.sqlite3")
    store.start_wake("Original review", NOW, wake_id="wake")
    store.finish_wake("wake", outcome, now=NOW)
    before = store.snapshot(NOW)
    with pytest.raises(WakeConflict, match="finished blocked"):
        store.resume_wake("wake", "new-call", NOW)
    assert store.snapshot(NOW) == before


@pytest.mark.parametrize("active_id", ["blocked", "another"])
def test_active_wake_rejects_continuation_without_changing_target(tmp_path, active_id):
    store = Store(tmp_path / "ledger.sqlite3")
    blocked_wake(store)
    if active_id == "blocked":
        store.resume_wake("blocked", "first-resume", NOW)
    else:
        store.start_wake("Other manual review", NOW, wake_id=active_id)
    before = store.snapshot(NOW)
    with pytest.raises(WakeConflict, match="still active"):
        store.resume_wake("blocked", "second-resume", NOW)
    assert store.snapshot(NOW) == before


def test_wrap_threshold_counts_settled_and_pending_charges(tmp_path):
    store = Store(tmp_path / "ledger.sqlite3")
    store.start_wake("Original review", NOW, wake_id="wake")
    store.reserve("wake", "known", "14", NOW)
    store.settle("known", "14", NOW)
    store.reserve("wake", "unknown", "1", NOW)
    store.finish_wake("wake", "blocked", now=NOW)
    with pytest.raises(BudgetExceeded, match="Wrap-up"):
        store.resume_wake("wake", "new-call", NOW)
    assert store.snapshot(NOW)["active_wake"] is None
    assert store.snapshot(NOW)["daily_charged_usd"] == "15.000000"


def test_continuation_identity_cannot_be_replayed_even_before_reservation(tmp_path):
    store = Store(tmp_path / "ledger.sqlite3")
    blocked_wake(store)
    with pytest.raises(ValueError, match="already used"):
        store.resume_wake("blocked", "old-call", NOW)
    store.resume_wake("blocked", "new-call", NOW)
    store.finish_wake("blocked", "blocked", now=NOW)
    reopened = Store(store.path)
    with pytest.raises(ValueError, match="already used"):
        reopened.resume_wake("blocked", "new-call", NOW)
    assert reopened.snapshot(NOW)["active_wake"] is None
    assert len(reopened.snapshot(NOW)["reservations"]) == 1


def test_concurrent_resume_claims_exactly_one_manual_attempt(tmp_path):
    store = Store(tmp_path / "ledger.sqlite3")
    blocked_wake(store)
    instances = [Store(store.path), Store(store.path)]
    barrier = threading.Barrier(2)

    def resume(pair):
        index, instance = pair
        barrier.wait()
        try:
            return instance.resume_wake("blocked", f"new-{index}", NOW)
        except WakeConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resume, enumerate(instances)))
    assert sum(result is not None for result in results) == 1


@pytest.fixture
def cli_case(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    state = tmp_path / "state"
    store = Store(state / "overseer.sqlite3")
    agent = {"agent_id": "terminal", "task_id": "task", "status": "completed", "cost_status": "known"}
    store.register_agent(agent)
    store.record_spend("terminal", "original-spend", 101, NOW)
    blocked_wake(store)
    original = evaluate({"agents": [{**agent, "unreviewed_cost_usd": "101"}]}, now=NOW.isoformat(), force=True)
    original["wake"]["wake_id"] = "blocked"
    original["llm_review"] = {"status": "blocked", "provider": "claude", "model": "claude-old",
                              "operation_id": "old-call", "reserved_usd": "10.153600",
                              "actual_cost_usd": None, "billing_reconciliation_required": True}
    Journal(store.path).record("blocked", original, "blocked")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"agents": [agent]}))
    config = tmp_path / "reviewer.json"
    config.write_text(json.dumps({"model": "claude-fixture", "input_usd_per_million": "2",
                                 "output_usd_per_million": "10", "cache_write_usd_per_million": "4",
                                 "model_context_tokens": 1000000, "max_output_tokens": 4096,
                                 "pricing_verified": True, "pricing_reference": "Synthetic test rates"}))
    output = tmp_path / "report"
    args = ["--state-dir", str(state), "review", "--resume-wake", "blocked",
            "--project-root", str(tmp_path), "--snapshot", str(snapshot),
            "--reviewer-config", str(config), "--output", str(output)]
    return store, original, output, args


def completed_response():
    advisory = {"summary": "Inspect the next walking demo", "risks": [], "recommended_actions": [],
                "goal_assessment": {goal: {"sim": "Unknown", "physical": "Unknown", "next_step": "Inspect evidence"}
                                    for goal in ("any_means", "rl_only")}}
    return {"model": "claude-fixture", "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "content": [{"type": "text", "text": json.dumps(advisory)}]}


def test_cli_resume_makes_one_new_call_preserves_audit_and_late_receipts(cli_case, monkeypatch):
    store, original, output, args = cli_case
    store.record_spend("terminal", "late-spend", 5, NOW + timedelta(seconds=1))
    old_reservation = store.snapshot()["reservations"][0]
    calls = []

    def transport(payload, key, timeout):
        calls.append(payload)
        sent = json.loads(payload["messages"][0]["content"])
        assert [agent["agent_id"] for agent in sent["agents"]] == ["terminal"]
        assert store.snapshot()["active_wake_charged_usd"] == "14.194560"
        return completed_response()

    monkeypatch.setattr(reviewer, "_post_messages", transport)
    assert main(args) == 0
    assert len(calls) == 1
    state = store.snapshot()
    assert len(state["wakes"]) == 1 and state["active_wake"] is None
    assert state["wakes"][0]["outcome"] == "succeeded"
    assert state["reservations"][0] == old_reservation
    assert state["reservations"][1]["operation_id"] != "old-call"
    assert state["daily_charged_usd"] == "10.155800"
    assert store.spending_since_review("terminal")["amount_usd"] == "5.000000"
    report = json.loads((output / "report.json").read_text())
    assert report["wake"]["wake_id"] == "blocked"
    assert report["budget"]["additional_model_cost_usd"] == "0.002200"
    assert report["budget"]["wake_charged_usd"] == "10.155800"
    assert report["prior_attempts"] == [{"report_id": "blocked", "generated_at": original["generated_at"],
                                         "outcome": "blocked", "llm_review": original["llm_review"]}]
    with sqlite3.connect(store.path) as db:
        reports = dict(db.execute("SELECT report_id,body FROM overseer_reports"))
    assert json.loads(reports["blocked"]) == original
    assert report["report_id"] in reports and len(reports) == 2
    # A successful wake cannot purchase another call by replaying the command.
    assert main(args) == 2
    assert len(calls) == 1


def test_cli_manual_second_failure_retains_both_charges_and_reports(cli_case, monkeypatch):
    store, _, output, args = cli_case
    calls = []

    def timeout(*args):
        calls.append(True)
        raise TimeoutError("fixture-key")

    monkeypatch.setattr(reviewer, "_post_messages", timeout)
    assert main(args) == 0
    assert len(calls) == 1
    assert store.snapshot()["daily_charged_usd"] == "14.194560"
    assert store.snapshot()["active_wake"] is None
    assert store.snapshot()["wakes"][0]["outcome"] == "blocked"
    assert len(store.snapshot()["reservations"]) == 2
    report = json.loads((output / "report.json").read_text())
    assert report["prior_attempts"][0]["report_id"] == "blocked"
    assert report["budget"]["additional_model_cost_usd"] == "4.040960"
    assert report["budget"]["wake_charged_usd"] == "14.194560"


def test_cli_resume_requires_configuration_without_reopening(cli_case, monkeypatch):
    store, _, _, args = cli_case
    index = args.index("--reviewer-config")
    del args[index:index + 2]
    monkeypatch.setattr(reviewer, "review_once", lambda *a, **k: pytest.fail("unexpected call"))
    assert main(args) == 2
    assert store.snapshot()["active_wake"] is None
    assert len(store.snapshot()["reservations"]) == 1
