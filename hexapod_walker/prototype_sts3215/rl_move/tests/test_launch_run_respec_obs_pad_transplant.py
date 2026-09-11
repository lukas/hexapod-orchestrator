"""Respec fresh-only obs-widening-transplant inheritance; no pod, checkpoint
or ledger I/O.

Root cause covered: cw-walk50hz-amp-mesh-m2plain-styleoff-pushfaultcurr-
rampacq15m (2026-09-11) inherited --obs-pad-transplant 18 verbatim from its
source's own build recipe via --init-from-source, but the source's own
checkpoint is ALREADY widened -- the plain warm start into a same-shaped
parent/child pair made train_ppo_sim.pad_obs_transplant's own width-mismatch
guard raise SystemExit before any training step (dead pod, zero training).
"""
from __future__ import annotations
import argparse
from types import SimpleNamespace
import pytest

import launch_run as lr


def setup_respec(monkeypatch, *, transplant=None, now=False, explicit=None,
                 init_from_source=True):
    source_args = ["--task", "joint_walk", "--seed", "10", "--out-name",
                   "ppo_goal_cw_easy_seed10", "--net-arch", "256,256,128",
                   "--log-std-final", "-2", "--cfg-set", "reward.k_action_delta=0.01"]
    source_args += transplant if transplant is not None else ["--obs-pad-transplant", "18"]
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
@pytest.mark.parametrize("transplant", [["--obs-pad-transplant", "18"],
                                        ["--obs-pad-transplant=18"]])
def test_plain_warm_respec_drops_inherited_obs_pad_transplant(monkeypatch, now, transplant):
    source, a, calls, snapshots = setup_respec(monkeypatch, now=now, transplant=transplant)
    original = list(source["extra_args"])
    assert lr.cmd_respec({}, a) == 0
    kind, ns, args = calls[0]
    assert kind == ("launch" if now else "queue")
    assert not any(x == "--obs-pad-transplant"
                  or x.startswith("--obs-pad-transplant=") for x in args)
    assert args[args.index("--init-from")+1] == "rl_move/sim/policies/ppo_goal_cw_easy_seed10.zip"
    assert source["extra_args"] == original
    assert len(snapshots) == int(now)


def test_plain_warm_respec_drops_inherited_hist_stride_transplant(monkeypatch):
    _, a, calls, _ = setup_respec(monkeypatch,
        transplant=["--hist-stride-transplant", "4"])
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    assert "--hist-stride-transplant" not in args


def test_explicit_obs_pad_transplant_is_kept(monkeypatch):
    _, a, calls, _ = setup_respec(monkeypatch,
        explicit=["--obs-pad-transplant=6"])
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    assert args[args.index("--obs-pad-transplant")+1] == "6"


def test_fresh_respec_retains_requested_obs_pad_transplant(monkeypatch):
    _, a, calls, _ = setup_respec(monkeypatch, init_from_source=False,
                                 explicit=["--obs-pad-transplant=6"])
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    assert args[args.index("--obs-pad-transplant")+1] == "6"
    assert "--init-from" not in args


def test_no_transplant_in_source_is_a_noop(monkeypatch):
    _, a, calls, _ = setup_respec(monkeypatch, transplant=[])
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    assert "--obs-pad-transplant" not in args
