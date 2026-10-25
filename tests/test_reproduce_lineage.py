import copy

import pytest

import reproduce_lineage as repro


def plan():
    root = dict(source_code_sha="a" * 40, steps=2000000,
                checkpoint_out="old_root", initialization_run=None,
                status="FAIL-MECHANISM", phase="canary",
                argv=["--run-name", "old-root", "--steps", "2000000",
                      "--out-name", "old_root", "--host-workers", "24",
                      "--n-envs", "4096", "--batch-size", "131072"])
    child = dict(root, checkpoint_out="old_child", initialization_run="root",
                 argv=[*root["argv"], "--init-from", "rl_move/sim/policies/old_root.zip"])
    return dict(prefix="cw-test", roles={"walk": ["root", "child"]},
                stages={"root": root, "child": child})


def test_reproduction_uses_new_ancestors_and_preserves_optimizer_batches():
    stages = repro.stages(plan())
    args = repro.training_args(stages[1], {"root": stages[0]["output"]})
    assert repro.option(args, "--init-from") == "rl_move/sim/policies/ppo_goal_cw_test_walk_01.zip"
    assert repro.option(args, "--n-envs") == "4096"
    assert repro.option(args, "--batch-size") == "131072"
    assert repro.option(args, "--host-workers") == "12"
    assert "--run-name" not in args and "--steps" not in args
    assert "--no-defer-final-artifacts" in args
    assert repro.option(repro.training_args(stages[0], {}), "--init-from") is None
    # A historically failing intermediate is still an ancestor of the champion.
    assert stages[0]["status"] == "FAIL-MECHANISM"


@pytest.mark.parametrize("mutation", ["external", "forward", "artifact", "budget", "teacher"])
def test_untrusted_or_inconsistent_initialization_is_rejected(mutation):
    p = copy.deepcopy(plan())
    child = p["stages"]["child"]
    if mutation == "external":
        child["initialization_run"] = "frozen-champion"
    elif mutation == "forward":
        p["roles"]["walk"].reverse()
    elif mutation == "artifact":
        child["argv"][-1] = "rl_move/sim/policies/champion.zip"
    elif mutation == "budget":
        child["steps"] = 4000000
    else:
        child["argv"] += ["--teacher", "demonstration.zip"]
    with pytest.raises(ValueError):
        repro.stages(p)


def test_partial_checkpoint_and_nonfinite_weights_cannot_advance_curriculum():
    good = dict(finite=True, timesteps=2097152)
    repro.completion("[mjx-train] done 2,000,000 steps in 100s", 2000000, good)
    repro.completion("[mjx-train] done 2000000 steps in 100s", 2000000, good)
    with pytest.raises(RuntimeError):
        repro.completion("saved periodic checkpoint", 2000000, good)
    for checkpoint in [dict(good, finite=False), dict(good, timesteps=1000000)]:
        with pytest.raises(RuntimeError):
            repro.completion("[mjx-train] done 2,000,000 steps", 2000000, checkpoint)


def test_source_sync_refuses_to_replace_code_used_by_a_live_trainer(monkeypatch, tmp_path):
    monkeypatch.setattr(repro.launch_run, "pod_trainers", lambda pod: ["owned-run+finalizer"])
    monkeypatch.setattr(repro, "command", lambda *a, **k: pytest.fail("must not mutate code"))
    with pytest.raises(RuntimeError, match="cannot replace"):
        repro.sync_source("pod", "a" * 40, tmp_path)
