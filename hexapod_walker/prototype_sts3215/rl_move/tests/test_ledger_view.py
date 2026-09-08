from __future__ import annotations

import copy
import json

import pytest


import mcp_server
import status_server
from ledger_view import current_entries


RUN = "cw-walkscratch-easy0905-base-cartfoot-fresh-s10-c1b"


def _row(status: str, minute: int, **kwargs) -> dict:
    return {"run": RUN, "status": status, "track": "walkcurr",
            "created": f"2026-09-08T06:{minute:02d}:00+00:00", **kwargs}


def _live_and_duplicate() -> list[dict]:
    return [
        _row("RUNNING", 47, wandb_id="d9xbrnil", pod="train-7",
             checks={"pid": "2939170",
                     "global_step_window": [524288, 1048576]}),
        _row("REFUSED", 48, pod="train-1",
             refused_reason=f"a process for {RUN} already exists on train-7"),
    ]


def test_duplicate_refusal_does_not_mask_verified_launch_or_mutate_history():
    rows = _live_and_duplicate()
    before = copy.deepcopy(rows)
    assert current_entries(rows)[RUN] is rows[0]
    assert rows == before


@pytest.mark.parametrize("status", [
    "INTENT", "FAILED", "FAILED_BUG", "KILLED", "FINISHED", "RUNNING",
])
@pytest.mark.parametrize("evidence", [{}, {"wandb_id": "later-attempt"}])
def test_later_substantive_attempt_wins_even_without_pid(status, evidence):
    rows = _live_and_duplicate() + [_row(status, 49, **evidence)]
    assert current_entries(rows)[RUN] is rows[-1]


def test_failure_of_original_attempt_then_recovery_remains_authoritative():
    rows = _live_and_duplicate()
    rows[0].update(status="FAILED", stop_reason="trainer exited")
    assert current_entries(rows)[RUN]["status"] == "FAILED"

    rows.append(_row("INTENT", 50))
    assert current_entries(rows)[RUN] is rows[-1]
    rows[-1].update(status="FAILED", stop_reason="failed before PPO")
    rows.append(_row("REFUSED", 51, refused_reason="busy pod"))
    assert current_entries(rows)[RUN]["stop_reason"] == "failed before PPO"

    rows.append(_row("RUNNING", 52, wandb_id="recovered", checks={"pid": "4"}))
    rows.append(_row("REFUSED", 53, refused_reason="duplicate process"))
    assert current_entries(rows)[RUN]["wandb_id"] == "recovered"


@pytest.mark.parametrize("evidence", [
    {"wandb_id": "attempt"},
    {"checks": {"wandb_id": "attempt"}},
    {"checks": {"pid": "123"}},
    {"checks": {"trainer_pid": "123"}},
])
def test_refusal_with_launch_evidence_is_not_assumed_to_be_a_stub(evidence):
    rows = _live_and_duplicate() + [_row("REFUSED", 50, **evidence)]
    assert current_entries(rows)[RUN] is rows[-1]


def test_explicit_same_attempt_refusal_overrides_its_intent():
    rows = [_row("INTENT", 47), _row("REFUSED", 47)]
    assert current_entries(rows)[RUN] is rows[-1]


def test_only_refusals_keep_latest_and_invalid_rows_are_ignored():
    rows = [None, "noise", {}, _row("REFUSED", 47), _row("REFUSED", 48)]
    assert current_entries(rows)[RUN] is rows[-1]


def test_mcp_and_dashboard_select_same_attempt_and_expose_history(
        monkeypatch, tmp_path):
    rows = _live_and_duplicate()
    ledger = tmp_path / "experiments.json"
    encoded = json.dumps(rows)
    ledger.write_text(encoded)
    monkeypatch.setattr(mcp_server, "HERE", tmp_path)
    monkeypatch.setattr(mcp_server, "PROTO", tmp_path)
    monkeypatch.setattr(mcp_server, "feedback_for_run", lambda _: [])
    monkeypatch.setattr(status_server, "HERE", tmp_path)
    monkeypatch.setattr(status_server, "PROTO", tmp_path)
    monkeypatch.setattr(status_server, "_cycle_registry_entries", lambda: [])
    monkeypatch.setitem(status_server.SNAP, "fast", {
        "run_videos": {RUN: {"clips": [], "missing": []}},
    })

    result = mcp_server.t_get_run(RUN)
    # Keep the existing leading JSON entry interface.
    leading = result.split("# Ledger attempt history", 1)[0]
    entry = json.JSONDecoder().raw_decode(leading.split("\n", 1)[1])[0]
    assert entry["status"] == "RUNNING"
    assert entry["wandb_id"] == "d9xbrnil"
    assert "pod" not in entry
    assert "REFUSED" in result
    assert rows[1]["refused_reason"] in result

    listing = json.loads(mcp_server.t_list_runs().split("\n\n", 1)[1])
    assert listing[0]["status"] == "RUNNING"
    shown, counts, slim = status_server.ledger_rows()
    assert shown[0]["wandb_id"] == "d9xbrnil"
    assert counts == {"RUNNING": 1}
    assert slim[RUN]["status"] == "RUNNING"
    page = status_server.render_run_page(RUN)
    assert "[RUNNING]" in page.split("</h1>", 1)[0]
    assert "Ledger history" in page
    assert "REFUSED" in page
    assert ledger.read_text() == encoded

    # Both outward views must follow an actual failure of that attempt;
    # a later rejected duplicate must never keep it looking RUNNING.
    rows[0]["status"] = "FAILED"
    ledger.write_text(json.dumps(rows))
    assert mcp_server._ledger()[0]["status"] == "FAILED"
    assert status_server.ledger_rows()[1] == {"FAILED": 1}
