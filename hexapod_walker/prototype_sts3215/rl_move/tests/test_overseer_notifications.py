"""Manual outbox submissions using fake senders; no real messages are sent."""
from pathlib import Path
import subprocess

import pytest

from rl_move.overseer.journal import Journal
from rl_move.overseer import notifications
from rl_move.overseer.notifications import send_notification


@pytest.fixture
def journal(tmp_path):
    result = Journal(tmp_path / "journal.sqlite")
    result.record("review-1", {
        "generated_at": "2026-09-08T20:00:00+00:00",
        "findings": [{
            "incident_id": "auth-1", "code": "authentication_failure", "severity": "warning",
            "notify": True, "detail": "The controller cannot authenticate.",
            "proposed_action": "Inspect the configured authentication integration once.",
            "evidence": ["PRIVATE RAW LOGS"], "raw_logs": "PRIVATE RAW LOGS",
        }],
    }, "succeeded")
    return result


def test_send_claims_before_dispatch_and_records_submission(journal):
    calls = []

    def sender(recipient, message):
        assert journal.actions()[0]["notification_status"] == "sending"
        calls.append((recipient, message))

    result = send_notification(journal, "auth-1", "+1 (555) 555-0123", sender=sender)
    assert result["submitted"] is True
    assert result["notification_status"] == "submitted"
    assert "delivery is not confirmed" in result["receipt"]
    assert calls[0][0] == "+15555550123"
    assert "cannot authenticate" in calls[0][1]
    assert "Suggested next step" in calls[0][1]
    assert "PRIVATE RAW LOGS" not in calls[0][1]
    assert journal.actions()[0]["notification_status"] == "submitted"
    with pytest.raises(ValueError, match="already submitted"):
        send_notification(journal, "auth-1", "+15555550123", sender=sender)
    assert len(calls) == 1


def test_ambiguous_submission_retained_without_secret_error_or_retry(journal):
    calls = []

    def sender(*args):
        calls.append(args)
        raise subprocess.TimeoutExpired("private message password=secret", 15)

    result = send_notification(journal, "auth-1", "operator@example.test", sender=sender)
    assert result["notification_status"] == "uncertain"
    assert "private message" not in result["receipt"]
    assert "password" not in result["receipt"]
    assert journal.actions()[0]["notification_status"] == "uncertain"
    with pytest.raises(ValueError, match="outcome uncertain"):
        send_notification(journal, "auth-1", "operator@example.test", sender=sender)
    assert len(calls) == 1


@pytest.mark.parametrize("recipient", [None, "", " ", "look up Lukas", "bad\n@example.test", "55", "@example.test"])
def test_recipient_must_be_explicit_and_valid_before_claim(journal, recipient):
    with pytest.raises(ValueError, match="recipient|Recipient"):
        send_notification(journal, "auth-1", recipient, sender=lambda *args: pytest.fail("must not send"))
    assert journal.actions()[0]["notification_status"] == "not_sent"


@pytest.mark.parametrize("platform,available", [("linux", True), ("darwin", False)])
def test_platform_preflight_does_not_claim_outbox(journal, monkeypatch, platform, available):
    monkeypatch.setattr(notifications.sys, "platform", platform)
    monkeypatch.setattr(notifications.os, "access", lambda *args: available)
    with pytest.raises(RuntimeError, match="requires macOS"):
        send_notification(journal, "auth-1", "operator@example.test")
    assert journal.actions()[0]["notification_status"] == "not_sent"


def test_unknown_or_non_notifying_findings_cannot_be_sent(journal):
    with pytest.raises(ValueError, match="unknown incident"):
        send_notification(journal, "preview-only-id", "operator@example.test", sender=lambda *args: pytest.fail("must not send"))
    journal.record("review-2", {
        "generated_at": "2026-09-08T20:01:00+00:00",
        "findings": [{"incident_id": "review-only", "severity": "review", "notify": False}],
    }, "succeeded")
    with pytest.raises(ValueError, match="does not request"):
        send_notification(journal, "review-only", "operator@example.test", sender=lambda *args: pytest.fail("must not send"))


def test_recovery_notice_is_a_distinct_queued_message(journal):
    journal.record("review-2", {
        "generated_at": "2026-09-08T20:01:00+00:00",
        "findings": [{
            "incident_id": "auth-1-recovered", "severity": "review", "notify": True,
            "code": "recovery", "summary": "Authentication recovered after credential reload.",
            "proposed_action": "No operator action is required.",
        }],
    }, "succeeded")
    messages = []
    send_notification(journal, "auth-1-recovered", "operator@example.test", sender=lambda recipient, message: messages.append(message))
    assert messages[0].startswith("Hexapod overseer recovery")
    assert "No operator action" in messages[0]


def test_summary_redacts_credentials_links_and_omits_raw_logs(journal):
    journal.record("review-2", {
        "generated_at": "2026-09-08T20:01:00+00:00",
        "findings": [{
            "incident_id": "auth-secret", "severity": "warning", "notify": True,
            "summary": 'Failure api_key="secret value" ANTHROPIC_API_KEY=anothersecret Bearer abc.def sk-ant-private. View https://status.test/now?key=private#token',
            "proposed_action": "Reload once; password=hunter2 https://user:private@status.test/logs",
            "evidence": ["RAW LOG SECRETS"],
        }],
    }, "succeeded")
    messages = []
    send_notification(journal, "auth-secret", "operator@example.test", sender=lambda recipient, message: messages.append(message))
    message = messages[0]
    for private in ["secret value", "anothersecret", "abc.def", "sk-ant-private", "?key=", "#token", "hunter2", "user:private", "RAW LOG SECRETS"]:
        assert private not in message
    assert "https://status.test/now" in message
    assert len(message) < 950


def test_native_sender_uses_private_files_fixed_script_and_bounded_timeout(journal, monkeypatch):
    monkeypatch.setattr(notifications.sys, "platform", "darwin")
    monkeypatch.setattr(notifications.os, "access", lambda *args: True)
    observed = []

    def fake_run(args, **kwargs):
        assert args[:2] == ["/usr/bin/osascript", "-"]
        recipient_path, message_path = Path(args[2]), Path(args[3])
        assert recipient_path.read_text() == "operator@example.test"
        message = message_path.read_text()
        assert "cannot authenticate" in message
        assert recipient_path.stat().st_mode & 0o777 == 0o600
        assert message_path.stat().st_mode & 0o777 == 0o600
        assert "operator@example.test" not in " ".join(args)
        assert message not in " ".join(args)
        assert "cannot authenticate" not in kwargs["input"]
        assert kwargs["input"] == notifications._APPLE_SCRIPT
        assert kwargs["timeout"] == 15
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        observed.append((recipient_path, message_path))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    result = send_notification(journal, "auth-1", "operator@example.test")
    assert result["submitted"] is True
    assert all(not path.exists() for path in observed[0])


def test_native_sender_failure_is_uncertain(journal, monkeypatch):
    monkeypatch.setattr(notifications.sys, "platform", "darwin")
    monkeypatch.setattr(notifications.os, "access", lambda *args: True)
    monkeypatch.setattr(notifications.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 1))
    result = send_notification(journal, "auth-1", "operator@example.test")
    assert result["notification_status"] == "uncertain"
    assert journal.actions()[0]["notification_status"] == "uncertain"
