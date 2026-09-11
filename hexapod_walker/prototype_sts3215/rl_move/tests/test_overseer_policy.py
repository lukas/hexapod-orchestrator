"""Decision boundaries for a manual, advisory project overseer."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from rl_move.overseer.policy import evaluate
from rl_move.overseer.report import markdown


NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


def stamp(hours=0):
    return (NOW + timedelta(hours=hours)).isoformat()


def snapshot(*agents, services=()):
    return {"collected_at": stamp(), "agents": list(agents), "services": list(services)}


def worker(agent_id="worker", **updates):
    return {"agent_id": agent_id, "status": "running", "goals": ["any_means"],
            "started_at": stamp(-8), "last_progress_at": stamp(-7),
            "observed_at": stamp(), "cost_status": "known",
            "unreviewed_cost_usd": "0", **updates}


def recent_history():
    return {"last_review_at": stamp(-1)}


def codes(report):
    return {finding["code"] for finding in report["findings"]}


def auth_service(**updates):
    return {"service_id": "rl-controller", "status": "running",
            "desired_state": "running", "observed_at": stamp(),
            "auth_failure_count": 3, "auth_failure": True,
            "evidence": ["AuthenticationError: invalid API key"], **updates}


def test_idle_sessions_and_empty_snapshot_do_not_request_a_paid_wake():
    for data in [snapshot(), snapshot(worker(status="idle")),
                 snapshot(worker(status="paused"))]:
        result = evaluate(data, now=stamp())
        assert result["wake"]["eligible"] is False
        assert result["proposed_notifications"] == []
        assert result["actions_executed"] == []
        assert result["notifications_sent"] == []
        assert result["scheduler_enabled"] is False


def test_active_review_timer_boundary_and_stale_observations():
    data = snapshot(worker())
    early = evaluate(data, history={"last_review_at": stamp(-5.99)}, now=stamp())
    due = evaluate(data, history={"last_review_at": stamp(-6)}, now=stamp())
    assert early["wake"]["eligible"] is False
    assert due["wake"]["eligible"] is True
    assert "progress_review" in codes(due)
    stale = evaluate(snapshot(worker(observed_at=stamp(-1))), now=stamp())
    assert stale["wake"]["eligible"] is False
    assert "stale_observation" in codes(stale)


def test_unknown_cost_remains_explicit_and_never_fabricates_spend():
    result = evaluate(snapshot(worker(status="idle", cost_status="unknown",
                                      unreviewed_cost_usd=None)), now=stamp())
    assert result["wake"]["eligible"] is False
    assert result["wake"]["spend_due_agents"] == []
    assert result["budget"]["unknown_cost_agents"] == ["worker"]
    assert any("Unknown is not zero" in note for note in result["notes"])
    assert "unknown" in markdown(result)


@pytest.mark.parametrize("amount,due", [("99.999999", False), ("100", True),
                                        ("100.01", True), ("NaN", False),
                                        ("-1", False)])
def test_new_spend_trigger_uses_valid_money_and_exact_threshold(amount, due):
    result = evaluate(snapshot(worker(status="idle", unreviewed_cost_usd=amount)), now=stamp())
    assert result["wake"]["eligible"] is due
    assert bool(result["wake"]["spend_due_agents"]) is due


@pytest.mark.parametrize("identity", [{"is_overseer": True}, {"overseer_wake_id": "wake-1"}])
def test_overseer_and_paid_children_do_not_fund_their_own_wake(identity):
    result = evaluate(snapshot(worker(unreviewed_cost_usd="1000", **identity)), now=stamp())
    assert result["wake"]["eligible"] is False
    assert result["wake"]["active_agent_count"] == 0
    assert result["wake"]["spend_due_agents"] == []


def test_unchanged_blocked_state_does_not_purchase_another_timer_review():
    data = snapshot(worker())
    first = evaluate(data, now=stamp())
    history = {"last_review_at": stamp(-7), "last_outcome": "blocked",
               "fingerprint": first["wake"]["fingerprint"]}
    repeated = evaluate(data, history=history, now=stamp())
    assert repeated["wake"]["eligible"] is False
    changed = deepcopy(data)
    changed["agents"][0]["progress_evidence"] = ["new measured result"]
    assert evaluate(changed, history=history, now=stamp())["wake"]["eligible"] is True


def test_descendant_progress_does_not_change_external_work_fingerprint():
    data = snapshot(worker(), worker("review-child", overseer_wake_id="wake-1"))
    first = evaluate(data, now=stamp())
    history = {"last_review_at": stamp(-7), "last_outcome": "blocked",
               "fingerprint": first["wake"]["fingerprint"]}
    data["agents"][1]["progress_evidence"] = ["review report written"]
    assert evaluate(data, history=history, now=stamp())["wake"]["eligible"] is False


def test_inventory_order_does_not_reopen_an_unchanged_review():
    data = snapshot(worker("one"), worker("two"))
    first = evaluate(data, now=stamp())
    history = {"last_review_at": stamp(-7), "last_outcome": "no_change",
               "fingerprint": first["wake"]["fingerprint"]}
    data["agents"].reverse()
    assert evaluate(data, history=history, now=stamp())["wake"]["eligible"] is False


def loop_evidence(**updates):
    return {"same_failure_count": 3, "window_seconds": 1800,
            "unchanged_progress": True, "no_progressing_children": True,
            "failure_signature": "same timeout", "operation": "same replay",
            **updates}


@pytest.mark.parametrize("missing", ["unchanged_progress", "no_progressing_children",
                                      "failure_signature", "operation"])
def test_loop_requires_independent_evidence_and_child_progress_check(missing):
    evidence = loop_evidence()
    evidence.pop(missing)
    result = evaluate(snapshot(worker(loop_evidence=evidence)), history=recent_history(), now=stamp())
    assert "suspected_loop" not in codes(result)
    assert result["proposed_notifications"] == []


def test_repeated_tools_idle_or_short_failures_are_not_loop_proof():
    cases = [worker(loop_evidence=loop_evidence(same_failure_count=2)),
             worker(loop_evidence=loop_evidence(window_seconds=1799)),
             worker(status="idle", loop_evidence=loop_evidence()),
             worker(loop_evidence={"operation": "poll", "same_failure_count": 100})]
    for case in cases:
        assert "suspected_loop" not in codes(evaluate(snapshot(case), history=recent_history(), now=stamp()))


@pytest.mark.parametrize("invalid", [{"same_failure_count": "many"},
                                      {"window_seconds": None}])
def test_invalid_loop_counters_do_not_crash_or_establish_a_loop(invalid):
    data = snapshot(worker(loop_evidence=loop_evidence(**invalid)))
    result = evaluate(data, history=recent_history(), now=stamp())
    assert "suspected_loop" not in codes(result)


def test_verified_repetition_proposes_owner_review_never_executes_stop():
    data = snapshot(worker(loop_evidence=loop_evidence(), evidence=["log digest"]))
    result = evaluate(data, history=recent_history(), now=stamp())
    finding = next(item for item in result["findings"] if item["code"] == "suspected_loop")
    assert finding["executed"] is False
    assert finding["execution_owner"] == "registered execution owner"
    assert "healthy trainers" in finding["proposed_action"]
    assert result["wake"]["eligible"] is True
    assert result["actions_executed"] == []
    assert result["notifications_sent"] == []


def test_known_incident_and_uncertain_notification_stay_deduplicated():
    data = snapshot(services=[auth_service()])
    first = evaluate(data, now=stamp())
    incident = first["wake"]["new_incidents"][0]
    history = {"reviewed_incidents": [incident], "notified_incidents": [incident]}
    data["services"][0]["evidence"] = ["AuthenticationError: another poll of same failure"]
    again = evaluate(data, history=history, now=stamp())
    assert again["wake"]["eligible"] is False
    assert again["proposed_notifications"] == []


@pytest.mark.parametrize("observed", [stamp(-1), stamp(1), "bad timestamp", None])
def test_stale_or_undated_auth_errors_cannot_open_a_new_incident(observed):
    service = auth_service(observed_at=observed)
    result = evaluate(snapshot(services=[service]), now=stamp())
    assert "stale_authentication_report" in codes(result)
    assert "authentication_failure" not in codes(result)
    assert result["wake"]["eligible"] is False


@pytest.mark.parametrize("pause_signal", [{"desired_state": "disabled", "status": "stopped"},
                                           {"desired_state": "unknown", "status": "paused"}])
def test_any_explicit_pause_signal_prevents_recovery_proposal(pause_signal):
    result = evaluate(snapshot(services=[auth_service(**pause_signal)]), now=stamp())
    assert "intentional_pause" in codes(result)
    proposed = next(item["proposed_action"] for item in result["findings"] if item["code"] == "authentication_failure")
    assert "Read-only" in proposed
    assert "do not restart" in proposed
    assert "try only its documented credential refresh/reload" not in proposed


def test_report_keeps_proposals_separate_from_executed_results():
    result = evaluate(snapshot(services=[auth_service()]), now=stamp(), force=True)
    result["mode"] = "preview"
    rendered = markdown(result)
    assert "manual preview" in rendered
    assert "Scheduling is off" in rendered
    assert "Proposed actions" in rendered
    assert "does not certify a walking policy" in rendered
    assert result["actions_executed"] == result["notifications_sent"] == []


def test_evaluation_does_not_mutate_collected_data_or_history():
    data = snapshot(worker(loop_evidence=loop_evidence()), services=[auth_service()])
    history = recent_history()
    original = deepcopy((data, history))
    evaluate(data, history=history, now=stamp())
    assert (data, history) == original


def lab_experiments(**counts):
    """The Robot Lab experiment-count service the collector exports."""
    return {"service_id": "lab:experiments", "name": "Robot Lab experiments",
            "status": "observed", "observed_at": stamp(), "counts": counts}


def test_an_empty_robot_lab_queue_requests_a_review():
    """Ten experiments then eight idle hours must be an eligible trigger.

    Every other trigger keys off activity, and an empty queue has none, so
    the campaign could go quiet indefinitely without anyone asking why.
    """
    report = evaluate(
        snapshot(services=[lab_experiments(succeeded=51, failed=21)]),
        now=stamp(), history={"last_review_at": stamp(-7)})
    assert report["wake"]["eligible"] is True
    assert any("no queued, running or waiting experiment" in reason
               for reason in report["wake"]["reasons"])
    assert any("only path that queues or executes" in note
               for note in report["notes"])


@pytest.mark.parametrize("pending", ["queued", "building", "running"])
def test_work_still_pending_is_not_an_empty_queue(pending):
    report = evaluate(
        snapshot(services=[lab_experiments(succeeded=51, **{pending: 1})]),
        now=stamp(), history={"last_review_at": stamp(-7)})
    assert report["wake"]["eligible"] is False, report["wake"]["reasons"]


def test_an_empty_queue_still_obeys_the_six_hour_interval():
    """The new trigger must not buy a review the old ones could not."""
    report = evaluate(
        snapshot(services=[lab_experiments(succeeded=51)]),
        now=stamp(), history={"last_review_at": stamp(-1)})
    assert report["wake"]["eligible"] is False, report["wake"]["reasons"]


def test_an_absent_lab_queue_service_is_not_treated_as_empty():
    """Missing source coverage is not evidence of an idle campaign."""
    report = evaluate(snapshot(), now=stamp(),
                      history={"last_review_at": stamp(-7)})
    assert report["wake"]["eligible"] is False, report["wake"]["reasons"]


def test_changed_portfolio_evidence_requests_strategy_review_without_live_agent():
    data = snapshot()
    data["portfolio_evidence"] = {"rl_campaign": {"recent_runs": "run-a failed the same gate"}}
    first = evaluate(data, now=stamp(), history={"last_review_at": stamp(-7)})
    assert first["wake"]["eligible"] is True
    assert "six-hour project strategy review due" in first["wake"]["reasons"]
    unchanged = evaluate(data, now=stamp(), history={"last_review_at": stamp(-7),
                         "last_outcome": "blocked", "fingerprint": first["wake"]["fingerprint"]})
    assert unchanged["wake"]["eligible"] is False
    data["portfolio_evidence"]["rl_campaign"]["observed_at"] = stamp(1)
    assert evaluate(data, now=stamp(), history={"last_review_at": stamp(-7),
                    "last_outcome": "blocked", "fingerprint": first["wake"]["fingerprint"]})["wake"]["eligible"] is False
    data["portfolio_evidence"]["rl_campaign"]["recent_runs"] = "run-b tested exploration"
    assert evaluate(data, now=stamp(), history={"last_review_at": stamp(-7),
                    "last_outcome": "blocked", "fingerprint": first["wake"]["fingerprint"]})["wake"]["eligible"]


def test_robot_lab_v2_plan_queue_supersedes_legacy_history():
    services = [lab_experiments(succeeded=51),
                {"service_id": "lab2:plans", "counts": {"running": 1}}]
    report = evaluate(snapshot(services=services), now=stamp(), history={"last_review_at": stamp(-7)})
    assert report["wake"]["eligible"] is False
    services[1]["counts"] = {"done": 3}
    assert evaluate(snapshot(services=services), now=stamp(),
                    history={"last_review_at": stamp(-7)})["wake"]["eligible"] is True
