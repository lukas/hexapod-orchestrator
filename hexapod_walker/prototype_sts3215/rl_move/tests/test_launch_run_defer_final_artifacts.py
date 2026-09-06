"""Unit tests for launch_run.py's `_with_defer_final_artifacts`
(2026-09-06 routine adoption of the deferred-artifact handoff,
operator focus note + fb_20260906T064159_b11605: live verification
completed on cw-walkscratch-easy0905-medhead-widenfwd-c2-acq1).

Contract pinned here (pure function — no I/O, no subprocess, no pod):
  * compatible launches (GPU MJX trainer, not smoke, not dynrep) get
    --defer-final-artifacts injected and the decision recorded in
    entry["checks"]["defer_final_artifacts"];
  * smokes / dynrep / CPU launches are bit-exact untouched;
  * the launcher-level opt-out sentinel --no-defer-final-artifacts is
    stripped on EVERY path (no trainer ever sees it) and suppresses
    injection;
  * guardrails gpu.defer_final_artifacts: false is a fleet-wide
    rollback; a MISSING key means ON (adoption is the new normal);
  * an explicit --defer-final-artifacts already present (respec clone
    of a post-adoption parent) is left alone — no duplicate token.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "rl_move" / "orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

import launch_run as lr  # noqa: E402

GPU_CFG_ON = {"defer_final_artifacts": True}
GPU_CFG_OFF = {"defer_final_artifacts": False}
BASE = ["--task", "joint_walk", "--eval-every", "2000000"]


def _call(extra, *, is_gpu=True, is_dynrep=False, smoke=False,
          gpu_cfg=None):
    entry: dict = {}
    out = lr._with_defer_final_artifacts(
        list(extra), entry, is_gpu=is_gpu, is_dynrep=is_dynrep,
        smoke=smoke, gpu_cfg=GPU_CFG_ON if gpu_cfg is None else gpu_cfg)
    return out, entry["checks"]["defer_final_artifacts"]


def test_compatible_gpu_wandb_launch_gets_flag_injected():
    out, state = _call(BASE)
    assert out == [*BASE, "--defer-final-artifacts"]
    assert state == "injected"


def test_missing_guardrails_key_means_on():
    out, state = _call(BASE, gpu_cfg={})
    assert out == [*BASE, "--defer-final-artifacts"]
    assert state == "injected"


def test_guardrails_false_is_fleet_wide_rollback():
    out, state = _call(BASE, gpu_cfg=GPU_CFG_OFF)
    assert out == BASE
    assert state == "off-guardrails"


def test_smoke_is_untouched():
    out, state = _call(BASE, smoke=True)
    assert out == BASE
    assert state == "off-smoke"


def test_dynrep_is_untouched():
    out, state = _call(BASE, is_dynrep=True)
    assert out == BASE
    assert state == "not-applicable"


def test_cpu_launch_is_untouched():
    out, state = _call(BASE, is_gpu=False)
    assert out == BASE
    assert state == "not-applicable"


def test_opt_out_sentinel_suppresses_injection_and_is_stripped():
    out, state = _call([*BASE, lr.DEFER_OPT_OUT_FLAG])
    assert out == BASE
    assert state == "opt-out"
    assert lr.DEFER_OPT_OUT_FLAG not in out


def test_opt_out_sentinel_stripped_even_on_incompatible_paths():
    # The trainer has no such flag — every path must strip it or the
    # launch argparse-crashes (the 08-18 bare-flag lesson).
    for kw in ({"smoke": True}, {"is_dynrep": True}, {"is_gpu": False},
               {"gpu_cfg": GPU_CFG_OFF}):
        out, _ = _call([*BASE, lr.DEFER_OPT_OUT_FLAG], **kw)
        assert lr.DEFER_OPT_OUT_FLAG not in out


def test_explicit_flag_left_alone_no_duplicate():
    out, state = _call([*BASE, "--defer-final-artifacts"])
    assert out.count("--defer-final-artifacts") == 1
    assert state == "explicit"


def test_provenance_recorded_in_entry_checks():
    entry: dict = {}
    lr._with_defer_final_artifacts(
        list(BASE), entry, is_gpu=True, is_dynrep=False, smoke=False,
        gpu_cfg=GPU_CFG_ON)
    assert entry["checks"]["defer_final_artifacts"] == "injected"


def test_live_guardrails_file_has_adoption_on():
    """The shipped guardrails.yaml carries the adoption key ON — the
    documented rollback is flipping it to false, not deleting it."""
    import yaml
    g = yaml.safe_load((ORCH / "guardrails.yaml").read_text())
    assert g["compute"]["gpu"].get("defer_final_artifacts", True) is True
