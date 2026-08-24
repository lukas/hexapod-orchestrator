"""Unit tests for launch_run.py's `_with_default_control_hz` (2026-08-24,
certfreeze-v9 dig-in): CURRENT_TRUTHS documents an `--allow-legacy-
control-hz` escape hatch as already landed with the 08-24 100 Hz
ruling, but the function had no such parameter at all -- every
explicit non-100 `--cfg-set control.hz=...` was an unconditional
REFUSE, so the already-precedented legacy-rate isolation pattern
(certfreeze-v8's own control.hz=25 pin, OPERATOR_QUESTIONS.md 08-24
~20:0x) could not be reproduced through the normal launch/respec path.
These tests pin the pure-function contract directly (no I/O, no
subprocess, no pod).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "rl_move" / "orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

import launch_run as lr  # noqa: E402


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_ledger_writes(monkeypatch):
    """refuse() calls upsert_entry(), which writes the real
    experiments.json ledger under a file lock -- these are pure-
    function tests of the pre-refuse arg logic, not ledger-integration
    tests, and must never touch the real ledger file."""
    monkeypatch.setattr(lr, "upsert_entry", lambda entry: None)


def test_missing_control_hz_gets_the_100_default_injected():
    entry: dict = {}
    out = lr._with_default_control_hz([], entry, is_dynrep=False)
    assert out == ["--cfg-set", "control.hz=100"]
    assert entry["checks"]["control_hz_defaulted"] == "100"


def test_explicit_100_passes_through_unchanged():
    entry: dict = {}
    extra = ["--cfg-set", "control.hz=100"]
    out = lr._with_default_control_hz(list(extra), entry, is_dynrep=False)
    assert out == extra
    assert entry["checks"]["control_hz_defaulted"] == "explicit"


def test_explicit_non_100_refuses_by_default():
    entry: dict = {}
    extra = ["--cfg-set", "control.hz=25"]
    out = lr._with_default_control_hz(list(extra), entry, is_dynrep=False)
    assert isinstance(out, int) and out != 0
    assert "refused_reason" in entry
    assert "control.hz=100" in entry["refused_reason"]
    assert "allow_legacy_control_hz" not in entry.get("checks", {})


def test_allow_legacy_lets_an_explicit_non_100_value_through():
    entry: dict = {}
    extra = ["--cfg-set", "control.hz=25"]
    out = lr._with_default_control_hz(
        list(extra), entry, is_dynrep=False, allow_legacy=True)
    assert out == extra, "allow_legacy must not mutate the extra_args list"
    assert "refused_reason" not in entry
    assert "legacy" in entry["checks"]["control_hz_defaulted"]


def test_allow_legacy_is_a_no_op_when_control_hz_is_already_100():
    """allow_legacy must only change behavior for a non-100 EXPLICIT
    value -- it must never bypass or alter the ordinary 100 Hz path
    (bit-exact-when-100 guarantee)."""
    entry_a: dict = {}
    entry_b: dict = {}
    extra = ["--cfg-set", "control.hz=100"]
    out_a = lr._with_default_control_hz(
        list(extra), entry_a, is_dynrep=False, allow_legacy=False)
    out_b = lr._with_default_control_hz(
        list(extra), entry_b, is_dynrep=False, allow_legacy=True)
    assert out_a == out_b == extra
    assert entry_a["checks"] == entry_b["checks"] == {
        "control_hz_defaulted": "explicit"}


def test_allow_legacy_is_a_no_op_when_control_hz_is_missing():
    """allow_legacy must never change the no-key default-injection
    path either."""
    entry_a: dict = {}
    entry_b: dict = {}
    out_a = lr._with_default_control_hz(
        [], entry_a, is_dynrep=False, allow_legacy=False)
    out_b = lr._with_default_control_hz(
        [], entry_b, is_dynrep=False, allow_legacy=True)
    assert out_a == out_b
    assert entry_a["checks"] == entry_b["checks"]


def test_bad_control_hz_value_still_refuses_even_with_allow_legacy():
    entry: dict = {}
    extra = ["--cfg-set", "control.hz=not-a-number"]
    out = lr._with_default_control_hz(
        list(extra), entry, is_dynrep=False, allow_legacy=True)
    assert isinstance(out, int) and out != 0
    assert "bad control.hz cfg-set" in entry["refused_reason"]


def test_dynrep_trainer_is_untouched_regardless_of_allow_legacy():
    entry: dict = {}
    out = lr._with_default_control_hz(
        [], entry, is_dynrep=True, allow_legacy=True)
    assert out == []
    assert entry == {}
