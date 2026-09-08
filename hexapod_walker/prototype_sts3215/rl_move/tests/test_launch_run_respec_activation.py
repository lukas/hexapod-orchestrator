"""Respec fresh-only activation inheritance; no pod, checkpoint or ledger I/O."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ORCH = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCH))
import launch_run as lr


def setup_respec(monkeypatch, *, activation=None, now=False, explicit=None,
                 init_from_source=True, transplant=None):
    source_args = ["--task", "joint_walk", "--seed", "10", "--out-name",
                   "ppo_goal_cw_easy_seed10", "--net-arch", "256,256,128",
                   "--log-std-final", "-2", "--cfg-set", "reward.k_action_delta=0.01"]
    source_args += activation if activation is not None else ["--activation-fn", "elu"]
    if transplant:
        source_args.append(transplant)
    source = {"run": "cw-easy-seed10", "extra_args": source_args,
              "steps": 2_000_000, "phase": "canary", "track": "walkcurr",
              "wandb_id": "existing", "trainer": "ppo"}
    monkeypatch.setattr(lr, "load_ledger", lambda: [source])
    monkeypatch.setattr(lr, "naming_correction", lambda name: None)
    calls = []
    def capture(kind, ns, args):
        calls.append((kind, ns, list(args)))
        return 0
    monkeypatch.setattr(lr, "cmd_backlog", lambda ns,args:capture("queue",ns,args))
    monkeypatch.setattr(lr, "cmd_launch", lambda g,ns,args:capture("launch",ns,args))
    monkeypatch.setattr(lr, "_self_repair_pod", lambda pod,args:None)
    snapshots = []
    def snapshot(*args, **kwargs):
        snapshots.append(args)
        return SimpleNamespace(returncode=0, stdout="snapshot", stderr="")
    monkeypatch.setattr(lr.subprocess, "run", snapshot)
    a = argparse.Namespace(source=source["run"], run="cw-easy-seed10-acq1",
        seed=None, steps=40_000_000, parent="", hypothesis="matched continuation",
        gate="original acquisition gate", phase="acquisition", evidence="healthy source",
        arg=explicit, cfg=None, init_from_source=init_from_source, now=now,
        pod="hexapod-mjx-train-7", operator_override="", track="")
    return source, a, calls, snapshots


@pytest.mark.parametrize("now", [False, True])
@pytest.mark.parametrize("activation", [["--activation-fn", "elu"], ["--activation-fn=elu"]])
def test_plain_warm_respec_drops_only_inherited_activation(monkeypatch, now, activation):
    source, a, calls, snapshots = setup_respec(monkeypatch, now=now, activation=activation)
    original = list(source["extra_args"])
    assert lr.cmd_respec({}, a) == 0
    kind, ns, args = calls[0]
    assert kind == ("launch" if now else "queue")
    assert not any(x == "--activation-fn" or x.startswith("--activation-fn=") for x in args)
    assert args[args.index("--init-from")+1] == "rl_move/sim/policies/ppo_goal_cw_easy_seed10.zip"
    for flag, value in [("--net-arch", "256,256,128"), ("--log-std-final", "-2"),
                        ("--seed", "10"), ("--cfg-set", "reward.k_action_delta=0.01")]:
        assert args[args.index(flag)+1] == value
    assert ns.steps == 40_000_000
    assert source["extra_args"] == original
    assert len(snapshots) == int(now)


@pytest.mark.parametrize("now", [False, True])
@pytest.mark.parametrize("activation", ["elu", "relu"])
def test_explicit_nonempty_activation_refused_before_queue_or_snapshot(monkeypatch, capsys, now, activation):
    _, a, calls, snapshots = setup_respec(monkeypatch, now=now,
                                         explicit=[f"--activation-fn={activation}"])
    assert lr.cmd_respec({}, a) == 1
    assert not calls and not snapshots
    output = capsys.readouterr().out
    assert "REFUSED" in output and "activation" in output and "checkpoint" in output


def test_explicit_empty_activation_keeps_existing_workaround_valid(monkeypatch):
    _, a, calls, _ = setup_respec(monkeypatch, explicit=["--activation-fn="])
    assert lr.cmd_respec({}, a) == 0
    assert "--activation-fn" not in calls[0][2]


def test_fresh_respec_retains_requested_activation(monkeypatch):
    _, a, calls, _ = setup_respec(monkeypatch, init_from_source=False,
                                 explicit=["--activation-fn=relu"])
    assert lr.cmd_respec({}, a) == 0
    args=calls[0][2]
    assert args[args.index("--activation-fn")+1] == "relu"
    assert "--init-from" not in args


@pytest.mark.parametrize("transplant", ["--init-from-actor-only", "--init-from-policy-backbone"])
@pytest.mark.parametrize("explicit", [None, ["--activation-fn=relu"]])
def test_supported_transplant_keeps_activation(monkeypatch, transplant, explicit):
    _, a, calls, _ = setup_respec(monkeypatch, transplant=transplant, explicit=explicit)
    assert lr.cmd_respec({}, a) == 0
    args=calls[0][2]
    assert args[args.index("--activation-fn")+1] == ("relu" if explicit else "elu")
    assert transplant in args and "--init-from" in args


def test_other_transplant_flag_does_not_override_trainers_activation_contract(monkeypatch):
    _, a, calls, snapshots = setup_respec(monkeypatch,
        explicit=["--obs-pad-transplant=2", "--activation-fn=elu"])
    assert lr.cmd_respec({}, a) == 1
    assert not calls and not snapshots


def test_missing_inherited_activation_value_is_not_silently_repaired(monkeypatch):
    _, a, calls, snapshots = setup_respec(monkeypatch, activation=["--activation-fn"])
    assert lr.cmd_respec({}, a) == 1
    assert not calls and not snapshots
