"""Read-only current-attempt selection for public ledger views.

The ledger is append-ordered, and launch/update writes identify attempts by
(run, created). A rejected duplicate is a different attempt, not a status
transition of the process already launched under that run name.
"""
from __future__ import annotations

from collections.abc import Iterable


def current_entries(entries: Iterable[object]) -> dict[str, dict]:
    """Select each run's latest substantive attempt without hiding failures.

    Only an unexecuted REFUSED row for a distinct attempt can be skipped.
    Later INTENT, FAILED, KILLED, or recovered attempts still replace earlier
    rows regardless of execution evidence. All-refused runs retain their
    latest refusal; an explicit same-attempt status update remains authoritative.
    The input and its full attempt history are never modified.
    """
    latest: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("run"):
            continue
        run = entry["run"]
        previous = latest.get(run)
        checks = entry.get("checks") or {}
        launch_evidence = (entry.get("wandb_id")
                           or checks.get("wandb_id")
                           or checks.get("pid")
                           or checks.get("trainer_pid"))
        same_attempt = (previous is not None and entry.get("created")
                        and entry.get("created") == previous.get("created"))
        if (entry.get("status") == "REFUSED" and not launch_evidence
                and previous is not None
                and previous.get("status") != "REFUSED"
                and not same_attempt):
            continue
        latest[run] = entry
    return latest
