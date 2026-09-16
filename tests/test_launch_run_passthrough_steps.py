"""Queue-budget regressions: exercise real backlog writes in a temporary directory."""
from __future__ import annotations

import argparse
import json

import pytest

import launch_run as lr


@pytest.fixture
def queue(monkeypatch, tmp_path):
    backlog = tmp_path / "backlog.json"
    lock = tmp_path / "backlog.json.lock"
    backlog.write_text('[{"run": "cw-other", "steps": 2000000}]\n')
    source = {
        "run": "cw-easy-s10-acq1", "steps": 40_000_000,
        "phase": "acquisition", "track": "walkcurr", "wandb_id": "source",
        "extra_args": ["--task", "joint_walk", "--seed", "10",
                       "--out-name", "ppo_goal_cw_easy_s10_acq1",
                       "--init-from", "rl_move/sim/policies/canary_2m.zip"],
    }
    monkeypatch.setattr(lr, "BACKLOG", backlog)
    monkeypatch.setattr(lr, "BACKLOG_LOCK", lock)
    monkeypatch.setattr(lr, "load_ledger", lambda: [source])
    monkeypatch.setattr(lr, "naming_correction", lambda name: None)
    def unexpected(*args, **kwargs):
        pytest.fail("invalid respec reached snapshot or launch")
    monkeypatch.setattr(lr.subprocess, "run", unexpected)
    monkeypatch.setattr(lr, "cmd_launch", unexpected)
    return source, backlog, lock


def respec_args(source, **updates):
    a = argparse.Namespace(
        source=source["run"], run="cw-easy-s10-acq1-cont10m", seed=None,
        steps=None, parent="", hypothesis="bounded continuation",
        gate="original acquisition criterion", phase="acquisition",
        evidence="healthy source", arg=None, cfg=None,
        init_from_source=False, now=False, pod="", operator_override="", track="",
    )
    vars(a).update(updates)
    return a


@pytest.mark.parametrize("now", [False, True])
@pytest.mark.parametrize("inherited,explicit", [
    ([], ["--steps=10000000"]),  # actual queued regression
    ([], ["--steps"]),
    (["--steps", "10000000"], None),
    (["--steps=10000000"], None),
])
def test_respec_rejects_before_queue_or_snapshot(queue, capsys, now, inherited, explicit):
    source, backlog, lock = queue
    source["extra_args"].extend(inherited)
    before_source = json.dumps(source, sort_keys=True)
    before_backlog = backlog.read_bytes()
    a = respec_args(source, now=now, arg=explicit)
    assert lr.cmd_respec({}, a) == 1
    assert backlog.read_bytes() == before_backlog
    assert not lock.exists()
    assert json.dumps(source, sort_keys=True) == before_source
    output = capsys.readouterr().out
    assert "top-level --steps N" in output
    assert "--init-from-source" in output
    assert "preserves" in output and "replicas" in output


@pytest.mark.parametrize("extra", [["--steps", "10000000"], ["--steps=10000000"]])
def test_direct_backlog_rejects_budget_before_any_write(queue, capsys, extra):
    _, backlog, lock = queue
    before = backlog.read_bytes()
    a = argparse.Namespace(action="add", run="cw-queued", steps=40_000_000,
                           hypothesis="test", gate="test", phase="acquisition", parent="")
    assert lr.cmd_backlog(a, extra) == 1
    assert backlog.read_bytes() == before
    assert not lock.exists()
    assert "top-level --steps N" in capsys.readouterr().out


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("fresh_source", [False, True])
def test_valid_respec_keeps_budget_and_explicit_initialization_semantics(queue, warm, fresh_source):
    source, backlog, _ = queue
    if fresh_source:
        del source["extra_args"][-2:]
    original = list(source["extra_args"])
    a = respec_args(source, steps=10_000_000, init_from_source=warm,
                   arg=["--n-steps=128", "--notes=budget mentions --steps=50 as text"])
    assert lr.cmd_respec({}, a) == 0
    item = json.loads(backlog.read_text())[-1]
    assert item["steps"] == 10_000_000
    args = item["extra_args"]
    assert "--steps" not in args and "--steps=10000000" not in args
    assert args[args.index("--n-steps") + 1] == "128"
    assert args[args.index("--notes") + 1] == "budget mentions --steps=50 as text"
    if warm:
        assert args[args.index("--init-from") + 1] == (
            "rl_move/sim/policies/ppo_goal_cw_easy_s10_acq1.zip")
    elif fresh_source:
        assert "--init-from" not in args
    else:
        assert args[args.index("--init-from") + 1] == "rl_move/sim/policies/canary_2m.zip"
    assert source["extra_args"] == original


def test_valid_replica_can_still_inherit_top_level_budget(queue):
    source, backlog, _ = queue
    assert lr.cmd_respec({}, respec_args(source)) == 0
    item = json.loads(backlog.read_text())[-1]
    assert item["steps"] == 40_000_000
    args = item["extra_args"]
    assert args[args.index("--init-from") + 1] == "rl_move/sim/policies/canary_2m.zip"
