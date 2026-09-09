"""Explicit manual iMessage delivery from the durable overseer outbox.

No scheduler, polling, automatic retry, or import-time delivery. The native
Messages transport follows experiment_lab.hexapod_lab.blocker_monitor's private
file/argv pattern, with a shorter timeout. An accepted AppleScript submission is
not proof that the recipient received the message.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit


_OSASCRIPT = "/usr/bin/osascript"
_TIMEOUT_SECONDS = 15
_APPLE_SCRIPT = r'''
on run argv
    set targetAddress to read POSIX file (item 1 of argv) as «class utf8»
    set messageText to read POSIX file (item 2 of argv) as «class utf8»
    tell application "Messages"
        set targetService to first service whose service type = iMessage
        set targetBuddy to buddy targetAddress of targetService
        send messageText to targetBuddy
    end tell
end run
'''


class NotificationJournal(Protocol):
    def begin_notification(self, incident_id: str) -> dict[str, Any]: ...

    def end_notification(self, incident_id: str, *, submitted: bool, receipt: str) -> None: ...


def _recipient(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("An explicit iMessage recipient is required")
    recipient = value.strip()
    if not recipient or len(recipient) > 254 or any(ord(char) < 32 for char in recipient):
        raise ValueError("An explicit phone number or email recipient is required")
    if re.fullmatch(r"\+?[0-9][0-9 ()-]{5,30}", recipient):
        return re.sub(r"[ ()-]", "", recipient)
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient):
        return recipient
    raise ValueError("Recipient must be an explicit phone number or email")


def _preflight_messages() -> None:
    if sys.platform != "darwin" or not os.access(_OSASCRIPT, os.X_OK):
        raise RuntimeError("Manual iMessage delivery requires macOS with osascript available")


def _send_messages_text(recipient: str, message: str) -> None:
    _preflight_messages()
    with tempfile.TemporaryDirectory(prefix="hexapod-overseer-alert-") as temporary:
        paths = []
        for name, value in (("recipient", recipient), ("message", message)):
            path = Path(temporary) / name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(value)
            paths.append(str(path))
        result = subprocess.run(
            [_OSASCRIPT, "-", *paths], input=_APPLE_SCRIPT, text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS, check=False,
        )
    if result.returncode:
        raise RuntimeError("Messages did not confirm submission")


def _summary_text(value: Any, fallback: str, limit: int) -> str:
    """Only selected summary fields; never serialize evidence or raw logs."""
    if not isinstance(value, str) or not value.strip():
        return fallback
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"\b(?:gh[pousr]_|github_pat_|glpat-)[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[REDACTED]", text)
    text = re.sub(
        r'''(?ix)\b((?:[A-Za-z0-9]+[_-])*(?:api[_\s-]?key|access[_\s-]?token|refresh[_\s-]?token|password|secret|authorization|token|key))
            \s*[=:]\s*(?:"[^"]*"|'[^']*'|[^\s,;&]+)''',
        r"\1=[REDACTED]", text,
    )

    def safe_url(match: re.Match) -> str:
        try:
            parsed = urlsplit(match.group(0))
            if parsed.username or parsed.password:
                return "[private link omitted]"
            # Status URLs commonly put tokens in ?key= or fragments.
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        except ValueError:
            return "[private link omitted]"

    text = re.sub(r"https?://[^\s<>]+", safe_url, text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _message(finding: dict[str, Any]) -> str:
    recovery = (finding.get("recovered") is True or finding.get("resolved") is True
                or finding.get("status") == "resolved"
                or str(finding.get("code", "")).startswith(("recovery", "recovered", "resolved")))
    label = "Hexapod overseer recovery" if recovery else "Hexapod overseer alert"
    summary = _summary_text(finding.get("summary", finding.get("detail")), "An incident needs review.", 420)
    action = _summary_text(finding.get("proposed_action"), "Inspect the recorded overseer report.", 420)
    return f"{label}\n{summary}\nSuggested next step: {action}"


def send_notification(
    journal: NotificationJournal,
    incident_id: str,
    recipient: str,
    *,
    sender: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Manually submit one queued incident or recovery notice at most once.

    recipient is always explicit; the CLI may supply its explicit environment
    setting. No contacts/config/keychain discovery is performed. Preflight errors
    leave the outbox untouched. Once claimed, any uncertain send is journaled as
    uncertain and is not eligible for another automatic submission.
    """
    address = _recipient(recipient)
    if not isinstance(incident_id, str) or not incident_id.strip():
        raise ValueError("An explicit queued incident ID is required")
    if sender is None:
        _preflight_messages()
    finding = journal.begin_notification(incident_id)
    try:
        message = _message(finding)
        outcome = (sender or _send_messages_text)(address, message)
        if outcome is not None:
            raise RuntimeError("Sender did not return its submission contract")
    except Exception as exc:
        # No raw exception/message/recipient details enter the durable receipt.
        receipt = f"{type(exc).__name__}: submission outcome uncertain; do not retry without reconciliation"
        journal.end_notification(incident_id, submitted=False, receipt=receipt)
        return {"incident_id": incident_id, "submitted": False,
                "notification_status": "uncertain", "receipt": receipt}
    receipt = "Messages submission accepted; recipient delivery is not confirmed"
    journal.end_notification(incident_id, submitted=True, receipt=receipt)
    return {"incident_id": incident_id, "submitted": True,
            "notification_status": "submitted", "receipt": receipt}
