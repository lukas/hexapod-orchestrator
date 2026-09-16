"""Durable proposal/delivery history without inferred operational success."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
import threading

import pytest

from rl_move.overseer.journal import Journal, read_history
from rl_move.overseer.policy import evaluate


NOW = "2026-09-08T12:00:00+00:00"


def auth_report():
    return evaluate({"agents": [], "services": [{
        "service_id": "controller", "status": "running", "desired_state": "running",
        "observed_at": NOW, "auth_failure_count": 3, "auth_failure": True,
        "evidence": ["AuthenticationError: API key verification failed"],
    }]}, now=NOW)


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path / "journal.sqlite3")


def test_report_replay_is_idempotent_and_conflicts_do_not_overwrite(journal):
    report = auth_report()
    journal.record("review-1", report, "blocked")
    journal.record("review-1", deepcopy(report), "blocked")
    assert len(journal.actions()) == 1
    with journal.connect() as db:
        assert db.execute("SELECT count(*) FROM overseer_reports").fetchone()[0] == 1
    altered = deepcopy(report)
    altered["notes"].append("different result")
    with pytest.raises(ValueError, match="different content"):
        journal.record("review-1", altered, "blocked")
    with pytest.raises(ValueError):
        journal.record("review-1", report, "succeeded")
    assert journal.history()["last_outcome"] == "blocked"


def test_successful_review_does_not_execute_proposals_or_send_notifications(journal):
    journal.record("review", auth_report(), "succeeded")
    action = journal.actions()[0]
    assert action["status"] == "proposed"
    assert action["notification_status"] == "not_sent"
    assert action["body"]["executed"] is False
    assert action["receipt"] is None


@pytest.mark.parametrize("submitted,status", [(True, "submitted"), (False, "uncertain")])
def test_delivery_uncertainty_and_confirmed_submission_both_prevent_retries(journal, submitted, status):
    journal.record("review", auth_report(), "blocked")
    incident = journal.actions()[0]["incident_id"]
    journal.begin_notification(incident)
    journal.end_notification(incident, submitted=submitted, receipt="transport receipt")
    reopened = Journal(journal.path)
    assert reopened.actions()[0]["notification_status"] == status
    assert reopened.actions()[0]["status"] == "proposed"
    assert incident in read_history(journal.path)["notified_incidents"]
    with pytest.raises(ValueError):
        reopened.begin_notification(incident)
    with pytest.raises(ValueError):
        reopened.end_notification(incident, submitted=True, receipt="retry")


def test_crash_during_notification_is_not_automatically_retried(journal):
    report = auth_report()
    journal.record("review", report, "blocked")
    incident = journal.actions()[0]["incident_id"]
    journal.begin_notification(incident)
    reopened = Journal(journal.path)
    assert reopened.actions()[0]["notification_status"] == "sending"
    assert incident in reopened.history()["notified_incidents"]
    assert read_history(journal.path) == reopened.history()
    with pytest.raises(ValueError):
        reopened.begin_notification(incident)
    journal.record("review-2", report, "no_change")
    assert journal.actions()[0]["notification_status"] == "sending"


def test_concurrent_notification_claims_authorize_only_one_sender(journal):
    journal.record("review", auth_report(), "blocked")
    incident = journal.actions()[0]["incident_id"]
    instances = [Journal(journal.path) for _ in range(4)]
    barrier = threading.Barrier(4)

    def begin(instance):
        barrier.wait()
        try:
            return instance.begin_notification(incident)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(begin, instances))
    assert sum(result is not None for result in results) == 1


def test_unknown_or_nonnotifying_findings_cannot_send(journal):
    with pytest.raises(ValueError, match="unknown incident"):
        journal.begin_notification("not-recorded")
    report = auth_report()
    report["findings"][0]["notify"] = False
    journal.record("review", report, "succeeded")
    with pytest.raises(ValueError, match="does not request"):
        journal.begin_notification(journal.actions()[0]["incident_id"])


def test_owner_evidence_is_required_to_change_action_status(journal):
    journal.record("review", auth_report(), "blocked")
    incident = journal.actions()[0]["incident_id"]
    for receipt in [{"outcome": "resolved", "exit_code": 0},
                    {"owner": "service", "outcome": "resolved"},
                    {"owner": "service", "evidence": ["fresh status"], "outcome": "success"}]:
        with pytest.raises(ValueError):
            journal.acknowledge_action(incident, receipt)
    assert journal.actions()[0]["status"] == "proposed"
    journal.acknowledge_action(incident, {"owner": "service", "evidence": ["fresh healthy status"], "outcome": "resolved"})
    assert journal.actions()[0]["status"] == "resolved"
    assert journal.actions()[0]["notification_status"] == "not_sent"


def test_readonly_preview_history_never_creates_a_database_or_parent_directory(tmp_path):
    path = tmp_path / "missing" / "journal.sqlite3"
    assert read_history(path) == {}
    assert not path.parent.exists()


def test_readonly_history_preserves_database_and_existing_schema(journal):
    journal.record("review", auth_report(), "no_change")
    before = journal.path.read_bytes()
    before_stat = journal.path.stat()
    history = read_history(journal.path)
    assert history["last_outcome"] == "no_change"
    assert journal.path.read_bytes() == before
    assert journal.path.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert journal.path.stat().st_mode & 0o777 == 0o600


def test_readonly_history_does_not_add_tables_to_unrelated_store(tmp_path):
    path = tmp_path / "registry.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE registry (id TEXT PRIMARY KEY)")
    before = path.read_bytes()
    assert read_history(path) == {}
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")] == ["registry"]


def test_invalid_report_rolls_back_history_and_partial_outbox(journal):
    report = auth_report()
    report["findings"].append({"severity": "warning"})
    with pytest.raises(KeyError):
        journal.record("invalid", report, "blocked")
    assert journal.history() == {}
    assert journal.actions() == []


@pytest.mark.parametrize('outcome', ['resolved', 'declined'])
def test_closed_incident_recurs_as_new_episode_without_rewriting_history(journal, outcome):
    first = auth_report()
    original = first['findings'][0]
    journal.record('review-1', first, 'blocked')
    journal.begin_notification(original['incident_id'])
    journal.end_notification(original['incident_id'], submitted=True, receipt='original submission')
    owner_receipt = {'owner': 'controller', 'evidence': ['verified current state'], 'outcome': outcome}
    journal.acknowledge_action(original['incident_id'], owner_receipt)
    history = read_history(journal.path)
    assert history == journal.history()
    base = original['base_incident_id']
    assert history['incident_episodes'][base] == {
        'episode': 1, 'incident_id': original['incident_id'], 'status': outcome}
    assert original['incident_id'] not in history['reviewed_incidents']
    assert original['incident_id'] not in history['notified_incidents']
    next_report = evaluate({'agents': first['agents'], 'services': first['services']}, history=history, now=NOW)
    next_incident = next_report['findings'][0]
    assert next_incident['episode'] == 2
    assert next_incident['base_incident_id'] == base
    assert next_incident['incident_id'] != original['incident_id']
    assert next_incident['incident_id'] in next_report['wake']['new_incidents']
    journal.record('review-2', next_report, 'blocked')
    rows = {item['incident_id']: item for item in journal.actions()}
    assert rows[original['incident_id']]['status'] == outcome
    assert rows[original['incident_id']]['notification_receipt'] == 'original submission'
    assert json.loads(rows[original['incident_id']]['action_receipt']) == owner_receipt
    assert rows[next_incident['incident_id']]['status'] == 'proposed'
    assert rows[next_incident['incident_id']]['notification_status'] == 'not_sent'
    assert journal.history()['incident_episodes'][base]['episode'] == 2


def test_resolution_queues_one_recovery_proposal_only_after_submitted_alert(journal):
    journal.record('review', auth_report(), 'blocked')
    incident = journal.actions()[0]['incident_id']
    journal.begin_notification(incident)
    journal.end_notification(incident, submitted=True, receipt='alert submission')
    receipt = {'owner': 'controller', 'evidence': ['fresh healthy status'], 'outcome': 'resolved'}
    journal.acknowledge_action(incident, receipt)
    journal.acknowledge_action(incident, receipt)
    recovery = [item for item in journal.actions() if item['body']['code'] == 'incident_recovered']
    assert len(recovery) == 1
    assert recovery[0]['body']['recovered_incident_id'] == incident
    assert recovery[0]['status'] == 'proposed'
    assert recovery[0]['notification_status'] == 'not_sent'
    assert recovery[0]['body']['notify'] is True
    assert recovery[0]['body']['executed'] is False
    with pytest.raises(ValueError, match='different owner receipt'):
        journal.acknowledge_action(incident, {**receipt, 'outcome': 'declined'})


@pytest.mark.parametrize('delivery', ['not_sent', 'uncertain'])
def test_unsent_or_uncertain_alert_does_not_generate_recovery_message(journal, delivery):
    journal.record('review', auth_report(), 'blocked')
    incident = journal.actions()[0]['incident_id']
    if delivery == 'uncertain':
        journal.begin_notification(incident)
        journal.end_notification(incident, submitted=False, receipt='timeout')
    journal.acknowledge_action(incident, {'owner': 'controller', 'evidence': ['fresh status'], 'outcome': 'resolved'})
    assert len(journal.actions()) == 1
    with pytest.raises(ValueError, match='closed'):
        journal.begin_notification(incident)


def test_resolution_during_submission_preserves_both_receipts(journal):
    journal.record('review', auth_report(), 'blocked')
    incident = journal.actions()[0]['incident_id']
    journal.begin_notification(incident)
    receipt = {'owner': 'controller', 'evidence': ['fresh status'], 'outcome': 'resolved'}
    journal.acknowledge_action(incident, receipt)
    assert len(journal.actions()) == 1
    journal.end_notification(incident, submitted=True, receipt='late transport confirmation')
    rows = {item['incident_id']: item for item in journal.actions()}
    assert len(rows) == 2
    assert json.loads(rows[incident]['receipt']) == receipt
    assert json.loads(rows[incident]['action_receipt']) == receipt
    assert rows[incident]['notification_receipt'] == 'late transport confirmation'


def test_old_report_cannot_overwrite_closed_episode_evidence(journal):
    report = auth_report()
    journal.record('first', report, 'blocked')
    incident = journal.actions()[0]['incident_id']
    journal.acknowledge_action(incident, {'owner': 'controller', 'evidence': ['fresh status'], 'outcome': 'resolved'})
    before = journal.actions()[0]
    report['findings'][0]['detail'] = 'late old review with changed wording'
    journal.record('late-review', report, 'blocked')
    assert journal.actions()[0] == before
