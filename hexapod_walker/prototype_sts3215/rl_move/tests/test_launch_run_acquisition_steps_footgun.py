"""Unit tests for launch_run.py's `_acquisition_steps_footgun`
(2026-09-06): five independent respec launches this cycle window
(gains1x/geom1x/fault1x/extpush1x/zerobiasframe1x-c1-acq1) warm-started
an "-acqN"-named run off its own 2M canary via --init-from-source
without passing --steps, and each one silently finished in minutes at
the canary's 2M budget instead of the intended 40M acquisition read --
`respec` inherits --steps from the source entry when --steps is
omitted. This guard REFUSES that specific shape and requires an
explicit --steps. Pure-function tests only (no ledger/subprocess I/O).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "rl_move" / "orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

import launch_run as lr  # noqa: E402


def test_flags_the_exact_bug_shape():
    # extpush1x-c1-acq1 off extpush1x-c1's 2M canary, --init-from-source,
    # no --steps given.
    msg = lr._acquisition_steps_footgun(
        run="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-extpush1x-c1-acq1",
        source="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-extpush1x-c1",
        explicit_steps=None, inherited_steps=2_000_000,
        init_from_source=True)
    assert msg is not None
    assert "REFUSED" in msg
    assert "--steps" in msg


def test_explicit_steps_passes_through_clear():
    msg = lr._acquisition_steps_footgun(
        run="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-extpush1x-c1-acq1",
        source="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-extpush1x-c1",
        explicit_steps=40_000_000, inherited_steps=2_000_000,
        init_from_source=True)
    assert msg is None


def test_non_init_from_source_is_untouched():
    msg = lr._acquisition_steps_footgun(
        run="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-extpush1x-c1-acq1",
        source="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-extpush1x-c1",
        explicit_steps=None, inherited_steps=2_000_000,
        init_from_source=False)
    assert msg is None


def test_real_cont40m_chain_off_an_already_acq_source_is_silent():
    # medhead-widenfwd-c1-acq1-cont40m off medhead-widenfwd-c1-acq1
    # (already 40M) -- the source already carries -acq1, and its own
    # inherited steps is large, so this must stay silent either way.
    msg = lr._acquisition_steps_footgun(
        run="cw-walkscratch-easy0905-medhead-widenfwd-c1-acq1-cont40m",
        source="cw-walkscratch-easy0905-medhead-widenfwd-c1-acq1",
        explicit_steps=None, inherited_steps=40_000_000,
        init_from_source=True)
    assert msg is None


def test_non_acquisition_named_target_is_untouched():
    msg = lr._acquisition_steps_footgun(
        run="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-newaxis1x-c1",
        source="cw-walkscratch-easy0905-headset-crossgrav-medhead-abrupt-c1-acq1-cont40m",
        explicit_steps=None, inherited_steps=2_000_000,
        init_from_source=True)
    assert msg is None


def test_large_inherited_steps_is_untouched():
    # a canary source that happens to already be large-budget (>=10M):
    # no real footgun, don't nag.
    msg = lr._acquisition_steps_footgun(
        run="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-someaxis1x-c1-acq1",
        source="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-someaxis1x-c1",
        explicit_steps=None, inherited_steps=10_000_000,
        init_from_source=True)
    assert msg is None


def test_no_inherited_steps_is_untouched():
    msg = lr._acquisition_steps_footgun(
        run="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-someaxis1x-c1-acq1",
        source="cw-walkscratch-easy0905-headset-crossgrav-medhead-dr-someaxis1x-c1",
        explicit_steps=None, inherited_steps=None,
        init_from_source=True)
    assert msg is None
