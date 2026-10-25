import copy
import subprocess
import sys

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
    repro.completion("[mjx-train] done: 2,000,000 steps in 100s", 2000000, good)
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


def test_matched_evaluation_replays_lower_actuator_contract_for_arbitrary_paths():
    args = repro.evaluation_args({"lower": "/restored/champion.zip", "walk": "/new/walker.zip"})
    overrides = [args[i+1] for i, value in enumerate(args) if value == "--lower-cfg"]
    assert overrides == ["motor.thermal_derate_enable=1", "motor.thermal_derate_max_frac=0.5"]
    assert "--rot60" in args


def test_original_deferred_recipe_uses_cooperative_post_training_drain():
    stage = repro.stages(plan())[0]
    stage["argv"] += ["--defer-final-artifacts"]
    args = repro.training_args(stage, {})
    assert "--defer-final-artifacts" not in args
    assert args.count("--no-defer-final-artifacts") == 1


def test_marker_recovery_requires_integrity_and_confirmed_artifact_publication():
    good = dict(finite=True, timesteps=2097152, marker_verified=True, artifact_phase="evaluated")
    repro.completion("", 2000000, good)
    for bad in [dict(good, marker_verified=False), dict(good, artifact_phase="artifacts_pending")]:
        with pytest.raises(RuntimeError):
            repro.completion("", 2000000, bad)


def test_revision_sync_preserves_generated_outputs_at_unexpected_paths(monkeypatch, tmp_path):
    repo = tmp_path / "source"
    proto = repo / "hexapod_walker/prototype_sts3215"
    proto.mkdir(parents=True)

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Mechanical Test")
    git("config", "user.email", "test@example.invalid")
    (proto / "old.py").write_text("old source")
    git("add", ".")
    git("commit", "-qm", "initial source")
    first = git("rev-parse", "HEAD")
    (proto / "old.py").unlink()
    (proto / "new.py").write_text("new source")
    git("add", "-u")
    git("add", "hexapod_walker/prototype_sts3215/new.py")
    git("commit", "-qm", "replace source")
    second = git("rev-parse", "HEAD")
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / ".code_sha").write_text(first)
    (worker / "old.py").write_text("old source")
    generated = worker / "wandb/run/files/video.mp4"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"training video")
    checkpoint = worker / "rl_move/sim/policies/new.zip"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"newly trained model")
    monkeypatch.setattr(repro, "HEXAPOD_REPO", repo)
    monkeypatch.setattr(repro, "PROTO", proto)
    monkeypatch.setattr(repro.launch_run, "pod_trainers", lambda _: [])
    repro.sync_source("pod", second, worker)
    assert not (worker / "old.py").exists()
    assert (worker / "new.py").read_text() == "new source"
    assert generated.read_bytes() == b"training video"
    assert checkpoint.read_bytes() == b"newly trained model"


def test_behavioral_miss_is_collected_but_stale_report_cannot_hide_a_crash(tmp_path):
    report = tmp_path / "result.json"
    validation = f"import json; print(json.load(open({str(report)!r}))['zero_fall'])"
    args = [sys.executable, "-c", f"import pathlib; pathlib.Path({str(report)!r}).write_text('{{\"zero_fall\": false}}'); raise SystemExit(1)"]
    shell = repro.report_shell(args, str(tmp_path / "log"), str(report), validation, sys.executable)
    result = subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "False"
    # The previous valid miss must not mask an infrastructure failure on retry.
    shell = repro.report_shell([sys.executable, "-c", "raise RuntimeError('failed before output')"],
        str(tmp_path / "log"), str(report), validation, sys.executable)
    assert subprocess.run(["bash", "-c", shell], capture_output=True).returncode != 0
    assert len(list(tmp_path.glob("result.json.previous-*"))) == 1


def test_throughput_excludes_first_rollout_startup_and_requires_advancement():
    log = "| time_elapsed | 100 |\n| total_timesteps | 524288 |\n| time_elapsed | 120 |\n| total_timesteps | 1048576 |"
    assert repro.steady_throughput(log) == 524288 / 20
    with pytest.raises(RuntimeError):
        repro.steady_throughput("| time_elapsed | 100 |\n| total_timesteps | 524288 |")


def test_worker_selection_requires_gain_larger_than_repeat_noise():
    trials = [dict(workers=12, steady_steps_s=100), dict(workers=24, steady_steps_s=108),
              dict(workers=16, steady_steps_s=105), dict(workers=12, steady_steps_s=102)]
    assert repro.worker_choice(trials)["selected_workers"] == 12
    trials[1]["steady_steps_s"] = 130
    assert repro.worker_choice(trials)["selected_workers"] == 24
    trials[-1]["steady_steps_s"] = 120
    assert repro.worker_choice(trials)["selected_workers"] == 12


def test_tuned_parallelism_does_not_change_small_sac_roles_or_optimizer_batches():
    stage = repro.stages(plan())[0]
    progress = {"worker_benchmark": {"selected_workers": 24}}
    count = repro.runtime_workers(stage, progress)
    assert count == 24
    args = repro.training_args(stage, {}, count)
    assert repro.option(args, "--host-workers") == "24"
    assert repro.option(args, "--n-envs") == "4096"
    assert repro.option(args, "--batch-size") == "131072"
    stage["argv"][stage["argv"].index("--n-envs") + 1] = "256"
    assert repro.runtime_workers(stage, progress) == 12
