"""Respec fresh-only use-sde inheritance; no pod, checkpoint or ledger I/O."""
from __future__ import annotations
import argparse
from types import SimpleNamespace
import pytest

import launch_run as lr


def setup_respec(monkeypatch, *, use_sde=None, now=False, explicit=None,
                 init_from_source=True, transplant=None):
    source_args = ["--task", "joint_walk", "--seed", "10", "--out-name",
                   "ppo_goal_cw_easy_seed10", "--net-arch", "256,256,128",
                   "--log-std-final", "-2", "--cfg-set", "reward.k_action_delta=0.01"]
    source_args += use_sde if use_sde is not None else ["--use-sde", "--sde-sample-freq", "20"]
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
def test_plain_warm_respec_drops_inherited_use_sde(monkeypatch, now):
    source, a, calls, snapshots = setup_respec(monkeypatch, now=now)
    original = list(source["extra_args"])
    assert lr.cmd_respec({}, a) == 0
    kind, ns, args = calls[0]
    assert kind == ("launch" if now else "queue")
    assert "--use-sde" not in args
    assert "--sde-sample-freq" not in args
    assert args[args.index("--init-from")+1] == "rl_move/sim/policies/ppo_goal_cw_easy_seed10.zip"
    assert source["extra_args"] == original


def test_explicit_use_sde_refused_on_plain_warm_start(monkeypatch, capsys):
    _, a, calls, snapshots = setup_respec(monkeypatch, explicit=["--use-sde"])
    assert lr.cmd_respec({}, a) == 1
    assert not calls and not snapshots
    output = capsys.readouterr().out
    assert "REFUSED" in output and "use-sde" in output and "checkpoint" in output


def test_fresh_respec_retains_requested_use_sde(monkeypatch):
    _, a, calls, _ = setup_respec(monkeypatch, init_from_source=False,
                                 explicit=["--use-sde"])
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    assert "--use-sde" in args
    assert "--init-from" not in args


@pytest.mark.parametrize("transplant", ["--init-from-actor-only", "--init-from-policy-backbone"])
def test_supported_transplant_keeps_use_sde(monkeypatch, transplant):
    _, a, calls, _ = setup_respec(monkeypatch, transplant=transplant)
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    assert "--use-sde" in args and "--sde-sample-freq" in args
    assert transplant in args and "--init-from" in args


def test_no_use_sde_in_source_is_a_noop(monkeypatch):
    _, a, calls, _ = setup_respec(monkeypatch, use_sde=[])
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    assert "--use-sde" not in args
