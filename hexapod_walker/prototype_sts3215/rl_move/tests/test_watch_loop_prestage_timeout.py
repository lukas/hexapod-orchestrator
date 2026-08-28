"""Prestage wrapper timeout scaling (standwalk Next -1.86, 2026-08-27):
`watch_loop.py`'s subprocess wrapper around `pod_eval.py` used a flat
7500s timeout regardless of the run's own control.hz/episode-seconds,
so a control.hz=100/30s-episode 4-mode joint panel (measured ~1h35-
1h50m of legitimate wait, plus a joygate rider) could get killed by the
WRAPPER before the still-healthy remote eval finished, losing the
whole pass's copy-back. `_prestage_wrapper_timeout` reuses `pod_eval`'s
own `eval_timeout_scale` so the two budgets stay consistent, with a
floor that never shrinks the pre-fix behavior for legacy/unreadable
runs.
"""
import importlib.util
import json
import pathlib
import sys

_ORCH_DIR = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))
_P = _ORCH_DIR / "watch_loop.py"
_spec = importlib.util.spec_from_file_location("watch_loop", _P)
watch_loop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch_loop)


def test_unknown_run_falls_back_to_flat_floor():
    assert (watch_loop._prestage_wrapper_timeout("no-such-run-ever-xyz")
            == watch_loop.PRESTAGE_WRAPPER_TIMEOUT_S)


def test_legacy_run_stays_at_or_above_old_flat_floor(tmp_path, monkeypatch):
    ledger = tmp_path / "experiments.json"
    ledger.write_text(json.dumps([
        {"run": "legacy-run", "extra_args": ["--task", "walk"]},
    ]))
    monkeypatch.setattr(watch_loop, "LEDGER", ledger)
    t = watch_loop._prestage_wrapper_timeout("legacy-run")
    assert t >= watch_loop.PRESTAGE_WRAPPER_TIMEOUT_S


def test_control_hz100_episode30_scales_up(tmp_path, monkeypatch):
    ledger = tmp_path / "experiments.json"
    ledger.write_text(json.dumps([
        {"run": "hz100-run", "extra_args": [
            "--task", "joint_walk",
            "--episode-seconds", "30",
            "--cfg-set", "control.hz=100",
        ]},
    ]))
    monkeypatch.setattr(watch_loop, "LEDGER", ledger)
    t = watch_loop._prestage_wrapper_timeout("hz100-run")
    # scale = (100/25)*(30/15) = 8x; must exceed the old flat 7500s floor
    # by a wide margin (the exact regression this fix closes).
    assert t > watch_loop.PRESTAGE_WRAPPER_TIMEOUT_S * 4


def test_never_shrinks_below_flat_floor_even_at_1x_scale(tmp_path,
                                                          monkeypatch):
    ledger = tmp_path / "experiments.json"
    ledger.write_text(json.dumps([
        {"run": "baseline-run", "extra_args": [
            "--task", "joint_walk",
            "--episode-seconds", "15",
            "--cfg-set", "control.hz=25",
        ]},
    ]))
    monkeypatch.setattr(watch_loop, "LEDGER", ledger)
    t = watch_loop._prestage_wrapper_timeout("baseline-run")
    assert t >= watch_loop.PRESTAGE_WRAPPER_TIMEOUT_S


def test_budget_covers_pod_evals_own_mixedsession_wait(tmp_path,
                                                        monkeypatch):
    # BUG (2026-08-28, long-s1-cont1 triage): the `worst` sum never
    # included the mixedsession rider's own (now-scaled) internal wait
    # budget, so at this recipe's real 100 Hz/60 s scale (16x) the
    # OUTER wrapper here (~29.5h before this fix) was smaller than
    # pod_eval.py's OWN inner `MIXEDSESSION_TIMEOUT_S * scale` wait
    # (32h) -- the outer wrapper would truncate a still-healthy remote
    # mixedsession eval before the inner wait ever got the chance to.
    # The wrapper's budget must be strictly >= pod_eval's own scaled
    # mixedsession timeout for every recipe it covers.
    import pod_eval
    ledger = tmp_path / "experiments.json"
    ledger.write_text(json.dumps([
        {"run": "hz100-mixedsession-run", "extra_args": [
            "--task", "joint_walk",
            "--episode-seconds", "60",
            "--cfg-set", "control.hz=100",
        ]},
    ]))
    monkeypatch.setattr(watch_loop, "LEDGER", ledger)
    t = watch_loop._prestage_wrapper_timeout("hz100-mixedsession-run")
    scale = pod_eval.eval_timeout_scale(100.0, 60.0)
    assert t >= pod_eval.MIXEDSESSION_TIMEOUT_S * scale
