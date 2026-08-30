"""Unit tests for launch_run.py's `_with_default_log_std_final`
(2026-08-30): three independent from-scratch acquisition runs on the
cw-walk-allheading-{mlp,tf,mlp-singleframe}-acq1 recipe family hit the
identical bug (no --log-std-final -> unbounded train/std -> crashed
back-half reward + collapsed sto-mode eval), fixed by hand three
separate times. This defaults --log-std-final -3.0 (frac 1.0) onto
new acquisition-phase PPO launches, narrowly, mirroring the
control.hz=100 default-injection precedent. Pure-function tests only.
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
    monkeypatch.setattr(lr, "upsert_entry", lambda entry: None)


def test_acquisition_with_no_log_std_final_gets_the_default_injected():
    entry: dict = {}
    out = lr._with_default_log_std_final([], entry, phase="acquisition")
    assert out == ["--log-std-final", "-3", "--log-std-anneal-frac", "1"]
    assert entry["checks"]["log_std_final_defaulted"] == "-3"


def test_non_acquisition_phases_are_untouched():
    for phase in ("canary", "discovery", "hardening", "composition",
                  "transfer", ""):
        entry: dict = {}
        out = lr._with_default_log_std_final([], entry, phase=phase)
        assert out == []
        assert entry == {}


def test_explicit_log_std_final_passes_through_unchanged():
    entry: dict = {}
    extra = ["--log-std-final", "-4.0"]
    out = lr._with_default_log_std_final(
        list(extra), entry, phase="acquisition")
    assert out == extra
    assert entry == {}


def test_explicit_log_std_anneal_core_is_left_alone():
    """An explicit per-core target (dual-core standwalk lineage) is a
    deliberate choice this default must never override or duplicate."""
    entry: dict = {}
    extra = ["--log-std-anneal-core", "stance"]
    out = lr._with_default_log_std_final(
        list(extra), entry, phase="acquisition")
    assert out == extra
    assert entry == {}


def test_gru_dual_is_excluded():
    """The standwalk anchor4/6b lineage found annealing one SHARED
    log_std across a dual walk+stance core taxes walk while fixing
    stance -- must never be silently defaulted for --gru-dual."""
    entry: dict = {}
    extra = ["--gru-dual"]
    out = lr._with_default_log_std_final(
        list(extra), entry, phase="acquisition")
    assert out == extra
    assert entry == {}


def test_gru_experts_is_excluded():
    entry: dict = {}
    extra = ["--gru-experts"]
    out = lr._with_default_log_std_final(
        list(extra), entry, phase="acquisition")
    assert out == extra
    assert entry == {}


def test_sac_algo_is_excluded():
    """train_ppo_mjx hard-refuses --log-std-final for --algo sac."""
    entry: dict = {}
    extra = ["--algo", "sac"]
    out = lr._with_default_log_std_final(
        list(extra), entry, phase="acquisition")
    assert out == extra
    assert entry == {}


def test_algo_ppo_explicit_still_gets_the_default():
    entry: dict = {}
    extra = ["--algo", "ppo"]
    out = lr._with_default_log_std_final(
        list(extra), entry, phase="acquisition")
    assert out == extra + ["--log-std-final", "-3",
                           "--log-std-anneal-frac", "1"]


def test_allow_off_disables_the_default():
    entry: dict = {}
    out = lr._with_default_log_std_final(
        [], entry, phase="acquisition", allow_off=True)
    assert out == []
    assert entry == {}


def test_transformer_and_plain_gru_and_decleg_still_get_the_default():
    """Only --gru-dual/--gru-experts are excluded; the three already-
    confirmed-buggy architectures (plain MLP, --transformer, and any
    other single-core architecture such as --gru or --decleg) must
    still get the fix."""
    for flag in ([], ["--transformer"], ["--gru"], ["--decleg"]):
        entry: dict = {}
        out = lr._with_default_log_std_final(
            list(flag), entry, phase="acquisition")
        assert out == flag + ["--log-std-final", "-3",
                              "--log-std-anneal-frac", "1"]
