import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "orchestrator" / "blocker_state.py"
)
SPEC = importlib.util.spec_from_file_location("blocker_state", MODULE_PATH)
blocker_state = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(blocker_state)


def test_report_deduplicates_open_blocker_and_resolves(tmp_path):
    ledger = tmp_path / "blockers.json"
    first = blocker_state.report_blocker("watcher", "Needs operator", "why", ledger)
    again = blocker_state.report_blocker("watcher", "Needs operator", "new", ledger)
    assert again["id"] == first["id"]
    assert blocker_state.list_blockers(ledger) == [first]

    resolved = blocker_state.resolve_blocker(first["id"], "operator answered", ledger)
    assert resolved["resolved_at"]
    assert blocker_state.list_blockers(ledger) == []
    assert blocker_state.list_blockers(ledger, include_resolved=True)[0]["resolution"] == (
        "operator answered"
    )


def test_report_validates_and_unknown_resolution_fails(tmp_path):
    ledger = tmp_path / "blockers.json"
    with pytest.raises(ValueError):
        blocker_state.report_blocker("", "missing source", path=ledger)
    with pytest.raises(KeyError):
        blocker_state.resolve_blocker("blk_missing", path=ledger)
