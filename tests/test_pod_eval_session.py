"""Seat selection for the pre-staged interactive SESSION gate.

WISHLIST 8e (landed 08-13): the watcher's post-run evals (pod_eval.py)
add ``rl_move.sim.eval_session`` for every stance/walk candidate —
stance candidates pair with the deployed walk, walk candidates with
the deployed stance. These tests pin the pure seat-selection rule so
the wiring can't silently start sessioning quad/track-only runs or
seat a walk-width checkpoint on the stance side (eval_session requires
the stance obs to be a strict prefix of the walk env obs).
"""
import importlib.util
import pathlib

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_P = _ORCH / "pod_eval.py"
_spec = importlib.util.spec_from_file_location("pod_eval", _P)
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)

session_side = pod_eval.session_side
legacy_eval_cfgs = pod_eval.legacy_eval_cfgs


def test_stance_only_mix_takes_stance_seat():
    assert session_side(["rise", "hold", "lower"], "goal") == "stance"
    assert session_side(["hold"], "goal") == "stance"


def test_walk_only_takes_walk_seat():
    assert session_side(["walk"], "goal") == "walk"
    # plain joint_walk task with no --goal-mix is the walk default
    assert session_side([], "joint_walk") == "walk"


def test_both_families_take_walk_seat():
    # a walk-training policy is walk-env-width and can only sit in the
    # walk seat (stance seat must be a strict obs prefix)
    assert session_side(["walk", "rise", "hold", "lower"], "goal") == "walk"


def test_non_session_modes_get_no_seat():
    assert session_side(["track"], "goal") is None
    assert session_side(["quad"], "goal") is None
    assert session_side(["quadwalk"], "goal") is None
    assert session_side(["getup"], "goal") is None
    assert session_side([], "goal") is None


def test_legacy_eval_cfgs_pin_old_unstamped_rate_contract():
    assert legacy_eval_cfgs(["reward.foo=1"]) == [
        "reward.foo=1",
        "control.hz=25",
        "safety.max_delta_q_deg=1.5",
    ]


def test_legacy_eval_cfgs_preserve_explicit_rate_contract():
    assert legacy_eval_cfgs([
        "control.hz=100",
        "safety.max_delta_q_deg=0.375",
    ]) == [
        "control.hz=100",
        "safety.max_delta_q_deg=0.375",
    ]


def test_legacy_eval_cfgs_explicit_100hz_no_mdq_stays_untouched():
    # BUG (08-26, standheight-rung5-acq8m triage): explicit control.hz
    # present (the post-08-24 norm) but max_delta_q_deg NOT restated
    # (also the norm — 0.375 is config.yaml's own default for 100 Hz,
    # so launches correctly never repeat it) must NOT get the legacy
    # 1.5 deg/tick pin bolted on — that pin is only valid when
    # control.hz is ALSO missing (pre-flip). Regression test for the
    # independent-ifs bug that silently ran every 100 Hz run's
    # automated gate/owncfg/session/joygate passes under a 4x-looser
    # slew than they trained with.
    assert legacy_eval_cfgs(["control.hz=100"]) == ["control.hz=100"]


def test_legacy_eval_cfgs_missing_both_pins_both_together():
    assert legacy_eval_cfgs([]) == [
        "control.hz=25",
        "safety.max_delta_q_deg=1.5",
    ]
