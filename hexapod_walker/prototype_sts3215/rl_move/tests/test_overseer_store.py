"""Fast, synthetic accounting/ownership checks; no model, network or robot."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import threading

import pytest

from rl_move.overseer.store import BudgetExceeded, Store, WakeConflict


NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "overseer.sqlite3")


def agent(store, name="parent", **kwargs):
    return store.register_agent({"agent_id": name, "name": name, **kwargs})


@pytest.mark.parametrize("amount", ["-0.01", -1, float("nan"), float("inf"),
                                  "NaN", "sNaN", "Infinity", "nope", None,
                                  True, [], "1000000001"])
def test_invalid_money_never_creates_reservations(store, amount):
    wake = store.start_wake("manual review", NOW)
    with pytest.raises(ValueError):
        store.reserve(wake["wake_id"], "invalid", amount, NOW)
    assert store.snapshot(NOW)["reservations"] == []


def test_exact_decimal_accounting_and_round_up(store):
    wake = store.start_wake("review", NOW)["wake_id"]
    store.reserve(wake, "parent", Decimal("19.70"), NOW)
    store.reserve(wake, "child1", 0.1, NOW)
    store.reserve(wake, "child2", "0.2", NOW)
    assert store.snapshot(NOW)["active_wake_charged_usd"] == "20.000000"
    with pytest.raises(BudgetExceeded):
        store.reserve(wake, "tiny-child", "0.00000001", NOW)
    assert len(store.snapshot(NOW)["reservations"]) == 3


def test_reservation_idempotence_prevents_duplicate_dispatch_after_restart(store):
    wake = store.start_wake("review", NOW, wake_id="wake")
    assert not wake["reused"]
    first = store.reserve("wake", "parent", "12", NOW)
    assert first["reused"] is False
    reopened = Store(store.path)
    assert reopened.start_wake("review", NOW, wake_id="wake")["reused"] is True
    reused = reopened.reserve("wake", "parent", Decimal("12.0"), NOW)
    assert reused["reused"] is True
    assert reused["status"] == "reserved"
    assert reopened.snapshot(NOW)["active_wake_charged_usd"] == "12.000000"
    with pytest.raises(ValueError, match="different reservation"):
        reopened.reserve("wake", "parent", "8", NOW)
    with pytest.raises(ValueError, match="different reason"):
        reopened.start_wake("new purpose", NOW, wake_id="wake")
    with pytest.raises(WakeConflict):
        reopened.start_wake("another wake", NOW)


def test_unknown_requests_remain_charged_after_finish_restart_and_a_day(store):
    for i in range(4):
        wake = store.start_wake(f"review {i}", NOW)["wake_id"]
        store.reserve(wake, f"unknown-{i}", 20, NOW)
        store.finish_wake(wake, "failed", now=NOW)
    reopened = Store(store.path)
    tomorrow = NOW + timedelta(days=2)
    wake = reopened.start_wake("new day", tomorrow)["wake_id"]
    assert reopened.snapshot(tomorrow)["daily_charged_usd"] == "80.000000"
    with pytest.raises(BudgetExceeded, match="24-hour"):
        reopened.reserve(wake, "new-call", "0.01", tomorrow)
    assert reopened.reserve(wake, "free-preview", 0, tomorrow)["charged_usd"] == "0.000000"


def test_settled_costs_follow_rolling_window_not_calendar_day(store):
    for i in range(4):
        wake = store.start_wake(f"review {i}", NOW)["wake_id"]
        store.reserve(wake, f"call-{i}", 20, NOW)
        store.settle(f"call-{i}", 20, NOW)
        store.finish_wake(wake, "succeeded", now=NOW)
    tomorrow = NOW + timedelta(hours=23, minutes=59)
    wake = store.start_wake("later review", tomorrow)["wake_id"]
    with pytest.raises(BudgetExceeded):
        store.reserve(wake, "later-call", 1, tomorrow)
    boundary = NOW + timedelta(hours=24)
    assert store.reserve(wake, "later-call", 20, boundary)["reused"] is False
    assert store.snapshot(boundary)["daily_charged_usd"] == "20.000000"


def test_delayed_settlement_is_charged_at_settlement_time(store):
    wake = store.start_wake("review", NOW)["wake_id"]
    store.reserve(wake, "call", 20, NOW)
    store.finish_wake(wake, "failed", now=NOW)
    later = NOW + timedelta(days=3)
    store.settle("call", 15, later)
    assert store.snapshot(later)["daily_charged_usd"] == "15.000000"
    assert store.snapshot(later + timedelta(hours=23))["daily_charged_usd"] == "15.000000"
    assert store.snapshot(later + timedelta(hours=24))["daily_charged_usd"] == "0.000000"


def test_settlement_refunds_only_known_unused_reserve_and_records_overrun(store):
    wake = store.start_wake("review", NOW)["wake_id"]
    store.reserve(wake, "call", 20, NOW)
    store.settle("call", "3.25", NOW)
    assert store.settle("call", Decimal("3.250"), NOW)["reused"] is True
    with pytest.raises(ValueError, match="different cost"):
        store.settle("call", 3, NOW)
    store.reserve(wake, "child", "16.75", NOW)
    settled = store.settle("child", 18, NOW)
    assert settled["overrun_usd"] == "1.250000"
    snapshot = store.snapshot(NOW)
    assert snapshot["active_wake_charged_usd"] == "21.250000"
    assert snapshot["active_wake_remaining_usd"] == "0.000000"
    with pytest.raises(BudgetExceeded):
        store.reserve(wake, "extra", "0.01", NOW)


def test_parallel_reservations_are_atomic_across_store_instances(store):
    wake = store.start_wake("review", NOW)["wake_id"]
    instances = [Store(store.path) for _ in range(8)]
    barrier = threading.Barrier(len(instances))

    def reserve(item):
        index, instance = item
        barrier.wait()
        try:
            return instance.reserve(wake, f"child-{index}", 4, NOW)
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=len(instances)) as pool:
        results = list(pool.map(reserve, enumerate(instances)))
    assert len([result for result in results if result]) == 5
    assert store.snapshot(NOW)["active_wake_charged_usd"] == "20.000000"


def test_parallel_start_only_grants_one_wake(store):
    instances = [Store(store.path) for _ in range(4)]
    barrier = threading.Barrier(len(instances))

    def start(instance):
        barrier.wait()
        try:
            return instance.start_wake("concurrent review", NOW)
        except WakeConflict:
            return None

    with ThreadPoolExecutor(max_workers=len(instances)) as pool:
        results = list(pool.map(start, instances))
    assert len([result for result in results if result]) == 1
    assert len(store.snapshot(NOW)["wakes"]) == 1


def test_parallel_retry_grants_dispatch_only_once(store):
    wake = store.start_wake("review", NOW)["wake_id"]
    instances = [Store(store.path) for _ in range(4)]
    barrier = threading.Barrier(len(instances))

    def reserve(instance):
        barrier.wait()
        return instance.reserve(wake, "one-request", 7, NOW)

    with ThreadPoolExecutor(max_workers=len(instances)) as pool:
        results = list(pool.map(reserve, instances))
    assert [result["reused"] for result in results].count(False) == 1
    assert store.snapshot(NOW)["daily_charged_usd"] == "7.000000"


def test_tiny_positive_money_never_rounds_to_free(store):
    wake = store.start_wake("review", NOW)["wake_id"]
    reservation = store.reserve(wake, "tiny", Decimal("1e-1000000"), NOW)
    assert reservation["reserved_usd"] == "0.000001"


def test_reported_agent_spend_does_not_consume_overseer_budget(store):
    registered = agent(store, "child", parent_id="parent", task_id="task", goals=["rl_only"], cost_status="reported")
    assert registered["last_reviewed_at"] is None
    first = store.record_spend("child", "api-1", "350.21", NOW)
    assert not first["reused"]
    assert store.record_spend("child", "api-1", "350.210000", NOW)["reused"]
    assert store.spending_since_review("child")["amount_usd"] == "350.210000"
    assert store.snapshot(NOW)["daily_charged_usd"] == "0.000000"
    agent(store, "other")
    with pytest.raises(ValueError):
        store.record_spend("other", "api-1", "350.21", NOW)
    with pytest.raises(ValueError):
        store.record_spend("child", "api-1", "350.22", NOW)
    with pytest.raises(ValueError):
        store.record_spend("child", "api-1", "350.21", NOW, source="estimated")


def test_review_ack_is_success_only_and_never_swallows_late_costs(store):
    agent(store)
    store.record_spend("parent", "initial", 1, NOW)
    wake = store.start_wake("review fails", NOW)["wake_id"]
    store.finish_wake(wake, "failed", ["parent"], NOW)
    assert store.spending_since_review("parent")["amount_usd"] == "1.000000"
    wake = store.start_wake("review works", NOW)["wake_id"]
    store.record_spend("parent", "arrived-late", 2, NOW - timedelta(hours=1))
    store.finish_wake(wake, "succeeded", ["parent"], NOW)
    assert store.spending_since_review("parent")["amount_usd"] == "2.000000"
    assert store.finish_wake(wake, "succeeded", ["parent"], NOW)["reused"]
    with pytest.raises(ValueError):
        store.finish_wake(wake, "failed", now=NOW)
    wake = store.start_wake("no explicit review", NOW)["wake_id"]
    store.finish_wake(wake, "succeeded", now=NOW)
    assert store.spending_since_review("parent")["amount_usd"] == "2.000000"


def test_invalid_ack_rolls_back_entire_wake_finish(store):
    agent(store)
    store.record_spend("parent", "cost", 1, NOW)
    wake = store.start_wake("review", NOW)["wake_id"]
    with pytest.raises(ValueError, match="Unknown agent"):
        store.finish_wake(wake, "succeeded", ["parent", "zzz-unknown"], NOW)
    assert store.snapshot(NOW)["active_wake"]["wake_id"] == wake
    assert store.spending_since_review("parent")["amount_usd"] == "1.000000"


def test_agent_upsert_and_heartbeat_preserve_evidence_costs_and_review(store):
    agent(store, "worker", provider="claude", goals=["any_means"], started_at=NOW)
    store.record_spend("worker", "cost", 1, NOW)
    wake = store.start_wake("review", NOW)["wake_id"]
    store.finish_wake(wake, "succeeded", ["worker"], NOW)
    store.register_agent({"agent_id": "worker", "status": "running"})
    result = store.heartbeat("worker", {"progress_evidence": ["commit:abc"], "last_progress_at": NOW}, NOW)
    assert result["provider"] == "claude"
    assert result["last_reviewed_at"] == "2026-09-08T12:00:00.000000+00:00"
    assert result["last_heartbeat_at"] == result["last_progress_at"]
    assert result["progress_evidence"] == ["commit:abc"]
    assert Store(store.path).spending_since_review("worker")["event_count"] == 0
    with pytest.raises(ValueError):
        store.heartbeat("worker", {"agent_id": "someone-else"}, NOW)
    with pytest.raises(ValueError):
        store.register_agent({"agent_id": "worker", "last_reviewed_at": NOW.isoformat()})


@pytest.mark.parametrize("record", [{}, {"agent_id": ""}, {"agent_id": "a", "goals": "rl_only"},
                                    {"agent_id": "a", "cost_usd": float("nan")},
                                    {"agent_id": "a", "started_at": "2026-09-08T12:00:00"}])
def test_invalid_agent_metadata_rejected(store, record):
    with pytest.raises(ValueError):
        store.register_agent(record)
    assert store.list_agents() == []


def test_configured_limits_cannot_reset_existing_budget(tmp_path):
    path = tmp_path / "limits.sqlite3"
    store = Store(path, wake_limit_usd=5, daily_limit_usd=10)
    store.start_wake("review", NOW, "wake")
    store.reserve("wake", "call", 5, NOW)
    with pytest.raises(ValueError, match="Existing store limits"):
        Store(path)
    with pytest.raises(ValueError, match="cannot exceed"):
        Store(tmp_path / "too-high.sqlite3", wake_limit_usd=21)
    assert Store(path, wake_limit_usd=5, daily_limit_usd=10).snapshot(NOW)["daily_charged_usd"] == "5.000000"


def test_timestamps_normalize_utc_and_reject_backdated_operations(store):
    local = "2026-09-08T05:00:00-07:00"
    wake = store.start_wake("review", local)
    assert wake["started_at"] == "2026-09-08T12:00:00.000000+00:00"
    with pytest.raises(ValueError):
        store.reserve(wake["wake_id"], "call", 1, NOW - timedelta(seconds=1))
    store.reserve(wake["wake_id"], "call", 1, NOW)
    with pytest.raises(ValueError):
        store.settle("call", 1, NOW - timedelta(seconds=1))
    with pytest.raises(ValueError):
        store.finish_wake(wake["wake_id"], "failed", now=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError):
        store.start_wake("naive timestamp", datetime(2026, 9, 8))
