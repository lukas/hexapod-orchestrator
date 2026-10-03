"""goal.lower_hold_only_frac (and sibling episode-sampling-curriculum
keys) must NEVER be replayed into the lifecycle composed gate's
--lower-cfg delta, even though they ARE part of a candidate's own
training --cfg-set.

2026-10-03 (lowerrole_holdonly100_evalcfg_confound): these keys change
which TASK is sampled at env reset (e.g. frac=1.0 = every lower episode
starts already crouched at the target depth, skipping the descent
entirely — a strictly easier start distribution), not physics/reward/
safety. Auto-replaying a candidate's OWN training cfg at eval time is
correct for the latter (the hippitchmax precedent this function was
built for) but silently makes the composed gate an easier task for any
checkpoint trained with one of these on, confounding it against a
baseline (delta=[]) scored on the true harder task — concretely, this
bug produced the holdonly100-s3 "33/36 (92%)" number that backed a
PASS-MECHANISM verdict and an ADOPTED-recipe decision, later reversed
(see rl_docs/tracks/walkcurr/lowerrole_holdonly100_evalcfg_confound_
2026-10-03/SUMMARY.md) once a byte-for-byte repro pinned the cause to
exactly this auto-replay.
"""
import importlib.util
import pathlib

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_spec = importlib.util.spec_from_file_location(
    "pod_eval_lifecycle_curriculum_strip", _ORCH / "pod_eval.py")
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)


def test_lower_hold_only_frac_never_replayed():
    cfgs = ["control.hz=50", "goal.lower_hold_only_frac=1.0"]
    delta = pod_eval.lifecycle_lower_cfg_delta(cfgs)
    assert "goal.lower_hold_only_frac=1.0" not in delta
    assert not any(c.startswith("goal.lower_hold_only_frac")
                   for c in delta)


def test_sibling_curriculum_keys_never_replayed():
    cfgs = [
        "goal.lower_partial_frac=0.5",
        "goal.lower_belly_start_frac=0.3",
        "goal.lower_start_bank=some_bank",
        "goal.lower_start_bank_frac=0.2",
        "reward.k_novel_test_only=1.0",  # not in base -> would survive
    ]
    delta = pod_eval.lifecycle_lower_cfg_delta(cfgs)
    assert delta == ["reward.k_novel_test_only=1.0"]


def test_unrelated_goal_keys_not_in_base_still_pass_through():
    # Only the exact named curriculum keys are stripped — a goal.* key
    # NOT in the exclusion tuple (and not already in the recipe's own
    # base CFG_ARGS) must survive untouched.
    cfgs = ["goal.walk_yaw_cmd=1"]
    assert pod_eval.lifecycle_lower_cfg_delta(cfgs) == cfgs
