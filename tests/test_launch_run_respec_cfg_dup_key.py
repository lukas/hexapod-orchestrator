"""Respec --cfg override must win even when the inherited source args
already carry a LATER duplicate --cfg-set for the same key.

cfg-set application is last-wins per key (rl_move/sim/cfg_set.py builds
a dict by iterating the list in order). The old respec logic replaced
only the FIRST matching --cfg-set occurrence it found, in place. If a
respec chain's inherited args already had a stale duplicate of that key
sitting LATER in the list (e.g. an ancestor's "disable this axis" ask
appended on top of the original recipe value), the in-place edit at the
earlier position was silently defeated -- the untouched later duplicate
kept winning. Root cause of the safewiden6-backdose-s0 /
safewiden7-acq1 pair training with backlash/stickslip still fully
disabled despite their ledger hypothesis asking for half-dose
(found 2026-09-21). Fixed: drop EVERY existing occurrence of the key,
then append the new ask at the end, so it always wins regardless of
how many stale duplicates the lineage carries."""
from __future__ import annotations
import argparse
from types import SimpleNamespace
import pytest

import launch_run as lr


def setup_respec(monkeypatch, source_args, cfg=None):
    source = {"run": "cw-src", "extra_args": list(source_args),
              "steps": 2_000_000, "phase": "canary", "track": "walkcurr",
              "wandb_id": "existing", "trainer": "ppo"}
    monkeypatch.setattr(lr, "load_ledger", lambda: [source])
    monkeypatch.setattr(lr, "naming_correction", lambda name: None)
    calls = []

    def capture(kind, ns, args):
        calls.append((kind, ns, list(args)))
        return 0
    monkeypatch.setattr(lr, "cmd_backlog", lambda ns, args: capture("queue", ns, args))
    monkeypatch.setattr(lr, "cmd_launch", lambda g, ns, args: capture("launch", ns, args))
    monkeypatch.setattr(lr, "_self_repair_pod", lambda pod, args: None)
    monkeypatch.setattr(lr.subprocess, "run",
                         lambda *a, **k: SimpleNamespace(returncode=0, stdout="snapshot", stderr=""))
    a = argparse.Namespace(source=source["run"], run="cw-src-follow",
        seed=None, steps=None, parent="", hypothesis="h", gate="g",
        phase="acquisition", evidence="e", arg=None, cfg=cfg,
        init_from_source=False, now=False, pod="hexapod-mjx-train-7",
        operator_override="", track="")
    return source, a, calls


def _cfg_values(args, key):
    out = []
    for i, v in enumerate(args):
        if v == "--cfg-set" and args[i + 1].split("=", 1)[0] == key:
            out.append(args[i + 1])
    return out


def test_respec_cfg_override_wins_over_inherited_later_duplicate(monkeypatch):
    # Inherited args mimic the real bug: an EARLY original-recipe value
    # for dr.foot_stickslip_gain, then a LATER "disable" duplicate for
    # the same key appended by an ancestor respec -- last-wins means
    # 0,0 is the effective value BEFORE this respec's edit.
    source_args = [
        "--task", "joint_walk", "--out-name", "ppo_goal_cw_src",
        "--cfg-set", "dr.foot_stickslip_gain=0.0,0.4",
        "--cfg-set", "dr.mass_scale=0.8,1.2",
        "--cfg-set", "dr.foot_stickslip_gain=0,0",
    ]
    _, a, calls = setup_respec(monkeypatch, source_args,
                                cfg=["dr.foot_stickslip_gain=0.0,0.2"])
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    vals = _cfg_values(args, "dr.foot_stickslip_gain")
    # exactly one occurrence left, and it's the newly requested value --
    # under last-wins that is unambiguously the effective one.
    assert vals == ["dr.foot_stickslip_gain=0.0,0.2"]


def test_respec_cfg_override_still_works_with_single_occurrence(monkeypatch):
    source_args = ["--task", "joint_walk", "--out-name", "ppo_goal_cw_src",
                    "--cfg-set", "reward.k_action_delta=0.01"]
    _, a, calls = setup_respec(monkeypatch, source_args,
                                cfg=["reward.k_action_delta=0.03"])
    assert lr.cmd_respec({}, a) == 0
    args = calls[0][2]
    assert _cfg_values(args, "reward.k_action_delta") == ["reward.k_action_delta=0.03"]
