"""Eval pass timeout scaling for non-baseline control cadences/episode
lengths (found 08-24 on cw-arch-hist16-dep1-c1-joyfullcurr13-v7-hz100-r2:
PASS_TIMEOUT_S=2700 was calibrated for the 25 Hz / 15s-episode baseline;
a control.hz=100 / episode-seconds=60 run needs 16x the sim ticks per
episode and got silently killed (rc=-1, no report.json copy-back at
all -- pod_eval only copies back on rc==0) 6 episodes short of the
full 12-episode gate panel).
"""
import importlib.util
import pathlib

_ORCH_DIR = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_P = _ORCH_DIR / "pod_eval.py"
_spec = importlib.util.spec_from_file_location("pod_eval", _P)
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)

eval_timeout_scale = pod_eval.eval_timeout_scale


def test_baseline_is_1x():
    assert eval_timeout_scale(25.0, 15.0) == 1.0


def test_defaults_to_baseline_when_missing():
    assert eval_timeout_scale(None, None) == 1.0


def test_100hz_60s_scales_16x():
    # the exact regression case: (100/25) * (60/15) = 4 * 4 = 16
    assert eval_timeout_scale(100.0, 60.0) == 16.0


def test_100hz_15s_scales_4x():
    assert eval_timeout_scale(100.0, 15.0) == 4.0


def test_never_shrinks_below_1x():
    # a cheaper-than-baseline config (e.g. shorter episodes) must not
    # get LESS time than the calibrated baseline
    assert eval_timeout_scale(25.0, 3.0) == 1.0
    assert eval_timeout_scale(10.0, 15.0) == 1.0
