"""`launch_run.py update` stamps the canonical fields from rl_index.

Every verdict path (ops.sh verdict -> launch_run update) writes `outcome`
(one closed vocabulary over the ~200 raw `status` spellings) and coerces
hardware_ready to a bool when it is one of the historical spellings
("yes"/"no"/"True"/"False"); anything else is kept verbatim, never dropped.
The raw `status` is untouched. Mechanics-only: temp ledger, no W&B (no
--set verdict=), run story rendering and the real lock file patched out.
"""
from __future__ import annotations

import argparse
import contextlib
import json

import launch_run
import rl_index
import state_dir


def _update(monkeypatch, tmp_path, run, *sets):
    monkeypatch.setattr(launch_run, "render_run_md", lambda entry: None)
    monkeypatch.setattr(launch_run, "ledger_lock",
                        lambda: contextlib.nullcontext())
    ns = argparse.Namespace(run=run, set=list(sets), create=False, created=None)
    assert launch_run.cmd_update(ns) == 0
    return {e["run"]: e for e in state_dir.load_ledger()}[run]


def test_update_stamps_outcome_and_coerces_hardware_ready(state_ledger, tmp_path, monkeypatch):
    state_ledger([{"run": "cw-x", "status": "RUNNING", "phase": "acquisition",
                   "created": "2026-09-20T10:00:00+00:00", "wandb_id": "abc"}])
    e = _update(monkeypatch, tmp_path, "cw-x", "status=ACQ PASS", "hardware_ready=yes")
    assert e["status"] == "ACQ PASS"            # raw spelling kept
    assert e["outcome"] == "PASS"
    assert e["hardware_ready"] is True
    assert rl_index.outcome(e) == e["outcome"]


def test_update_keeps_uncoercible_hardware_ready_note(state_ledger, tmp_path, monkeypatch):
    state_ledger([{"run": "cw-y", "status": "FINISHED", "phase": "hardening",
                   "created": "2026-09-20T10:00:00+00:00", "wandb_id": "abd"}])
    note = "no, leg4 sacrificed past 40M"
    e = _update(monkeypatch, tmp_path, "cw-y", "status=HARDENING FAIL",
                f"hardware_ready={json.dumps(note)}")
    assert e["hardware_ready"] == note          # kept verbatim
    assert e["outcome"] == "FAIL"


def test_update_outcome_follows_the_canary_canonicalizer(state_ledger, tmp_path, monkeypatch):
    state_ledger([{"run": "cw-z-canary2m", "status": "RUNNING", "phase": "canary",
                   "created": "2026-09-20T10:00:00+00:00", "wandb_id": "abe"}])
    e = _update(monkeypatch, tmp_path, "cw-z-canary2m", "status=FAIL-MECHANISM")
    assert e["outcome"] == "CANARY_FAIL"
