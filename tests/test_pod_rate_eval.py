"""pod_rate_eval: pure helpers (no kubectl, no ledger)."""
from __future__ import annotations

import pod_rate_eval as pre


def test_split_episodes_even_and_remainder():
    assert pre.split_episodes(96, 16) == [6] * 16
    s = pre.split_episodes(100, 16)
    assert sum(s) == 100 and len(s) == 16 and max(s) - min(s) == 1
    assert pre.split_episodes(4, 16) == [1, 1, 1, 1]        # never an empty worker


def test_worker_seeds_skip_the_fixed_reference_panel_by_default():
    assert pre.worker_seeds(3) == [1, 2, 3]
    assert pre.worker_seeds(3, include_seed0=True) == [0, 1, 2]


def test_eval_cfgs_drops_trainer_only_keys_and_the_ramp():
    args = ["--cfg-set", "dr.joint_zero_bias_deg=2.25", "--cfg-set", "env.dr_stage_ramp_steps=0",
            "--cfg-set", "goal.mode_seq=rise,walk", "--cfg-set", "sched.key=x",
            "--cfg-set", "reward.k_park_duty=8.0", "--cfg-set", "goal.walk_residual_x=1"]
    assert pre.eval_cfgs(args, 1.0) == ["dr.joint_zero_bias_deg=2.25", "reward.k_park_duty=8.0"]


def test_parent_refused_when_child_widens_obs():
    child = ["--obs-pad-transplant", "18", "--cfg-set", "obs.current_sense=1"]
    ok, why = pre.parent_compatible(child, ["--cfg-set", "x=1"])
    assert not ok and "transplant" in why
    child2 = ["--cfg-set", "obs.current_sense=1", "--cfg-set", "dr.joint_zero_bias_deg=2.25"]
    ok, why = pre.parent_compatible(child2, ["--cfg-set", "dr.joint_zero_bias_deg=2.0"])
    assert not ok and "obs.current_sense" in why
    ok, _ = pre.parent_compatible(["--cfg-set", "obs.history_frames=16", "--cfg-set", "dr.x=1"],
                                  ["--cfg-set", "obs.history_frames=16"])
    assert ok


def test_worker_cmd_and_script_shape():
    cmd = pre.build_worker_cmd("rl_move/sim/policies/a.zip", ["dr.x=1"], per_mode=6, seed=3,
                               episode_s="20", out_rel="logs/ckpt_eval/r/child/seed3", dr_scale=1.0)
    assert "--per-mode 6 --dr-scale 1 --seed 3 --episode-seconds 20" in cmd
    assert "--cfg-set dr.x=1" in cmd and "--no-video --no-wandb" in cmd and "compose" not in cmd
    sc = pre.build_worker_cmd("a.zip", [], per_mode=6, seed=1, episode_s=None,
                              out_rel="o", dr_scale=1.0, scripted=True)
    assert "--stall-substitute-every-s 0.02" in sc
    script = pre.build_pod_script([(cmd, "/tmp/a.log"), (sc, "/tmp/b.log")])
    assert script.count(") > ") == 2 and script.rstrip().endswith("RATE-EVAL-DONE")
    assert "\nwait\n" in script


def _report(flags, progs=None):
    eps = []
    for i, ok in enumerate(flags):
        eps.append({"gait_valid": ok, "progress_ratio": (progs[i] if progs else 0.3),
                    "sacrificed_legs": [] if ok else [i % 6],
                    "duty_cycle": [0.5] * 6 if ok else [0.5, 0.5, 0.0, 0.5, 0.5, 0.5]})
    return {"episodes": {"walk/det": eps}}


def test_merge_and_compare_reproduce_known_counts():
    child = pre.merge_reports([_report([1, 1, 0]), _report([1, 0, 0])])
    parent = pre.merge_reports([_report([1, 1, 0]), _report([1, 1, 0])])
    assert (child["n"], child["k"]) == (6, 3) and (parent["n"], parent["k"]) == (6, 4)
    assert child["hard_eps"] == 3 and child["hard_with_parked_leg"] == 3
    assert child["sacrifice_hist"] == {"1": 1, "2": 2}
    res = pre.compare(child, parent)
    assert abs(res["child"]["rate"] - 0.5) < 1e-9 and res["child"]["ci95"][0] < 0.5 < res["child"]["ci95"][1]
    assert abs(res["delta_pp"] - (-100 / 6)) < 1e-6
    assert res["episode_identity"] == {"same": 5, "of": 6, "frac": 5 / 6}
    line = pre.summary_line("run-x", res)
    assert "child 3/6" in line and "parent zero-shot 4/6" in line and "episode identity 5/6" in line
