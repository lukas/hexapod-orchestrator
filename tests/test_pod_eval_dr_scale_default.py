"""A launch that omits --dr-scale trains at the TRAINER's own default
(train_ppo_mjx.py: default=1.0, full DR), not DR=0.

2026-09-11 (cw-walk50hz-amp-mesh-m2plain-styleoff-pushcurr-canary2m
triage): pod_eval.py used to fall back to dr=0 whenever a launch's
extra_args omitted --dr-scale, silently skipping the own-DR eval pass
for any such run -- even though the trainer itself defaults to full DR.
This run's own pre-registered gate required a push-survival read only
obtainable at DR>0 (push is a DR mechanism, zeroed at dr_scale=0), so
the missing own-DR pass left the gate's own criterion unverifiable.
Pin: omitting --dr-scale must schedule the owncfg pass at dr=1.0;
--no-dr must still force dr=0 (the one flag that genuinely means no
DR); an explicit --dr-scale value must still win over both defaults.
"""
import importlib.util
import io
import json
import pathlib
import shlex
import subprocess
import sys

import pytest

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_spec = importlib.util.spec_from_file_location("pod_eval_dr_default", _ORCH / "pod_eval.py")
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)


def _fixture(state_ledger, monkeypatch, tmp_path, extra_args):
    run = "dr-default-test-" + tmp_path.name
    state_ledger([{
        "run": run, "pod": "target-pod", "wandb_id": "test-id",
        "extra_args": ["--task", "joint_walk", "--cfg-set", "control.hz=50",
                       *extra_args],
    }])
    monkeypatch.setattr(pod_eval, "PROTO", tmp_path)
    monkeypatch.setattr(pod_eval, "find_checkpoint", lambda *a, **k: "policy.zip")
    monkeypatch.setattr(pod_eval, "session_side", lambda *a: None)
    monkeypatch.setattr(pod_eval, "core_synced", lambda *a: None)
    monkeypatch.setattr(pod_eval, "core_pass_synced", lambda *a: False)
    monkeypatch.setattr(pod_eval, "remote_eval_running", lambda *a: False)
    monkeypatch.setattr(pod_eval, "remote_report_exists", lambda *a: False)
    monkeypatch.setattr(pod_eval, "eval_video_args", lambda *a: "")
    monkeypatch.setattr(pod_eval, "open", lambda *a: io.StringIO(), raising=False)
    monkeypatch.setattr(sys, "argv", ["pod_eval.py", run])
    return run


def _run_and_collect_drv(state_ledger, monkeypatch, tmp_path, extra_args):
    _fixture(state_ledger, monkeypatch, tmp_path, extra_args)
    launches = []

    def launch(args, **kwargs):
        launches.append(shlex.split(args[-1]))

        class _Done:
            def wait(self, timeout):
                return 0
        return _Done()

    def copy(args, **kwargs):
        destination = pathlib.Path(args[-1])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "report.json").write_text("{}")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(pod_eval.subprocess, "Popen", launch)
    monkeypatch.setattr(pod_eval.subprocess, "run", copy)
    assert pod_eval.main() == 0
    tags = set()
    for cmd in launches:
        drv = cmd[cmd.index("--dr-scale") + 1]
        out = cmd[cmd.index("--out") + 1]
        tags.add((("owncfg" if "_owncfg" in out else "gate"), drv))
    return tags


def test_omitted_dr_scale_schedules_owncfg_at_trainer_default(state_ledger, monkeypatch, tmp_path):
    tags = _run_and_collect_drv(state_ledger, monkeypatch, tmp_path, [])
    assert ("gate", "0.0") in tags
    assert ("owncfg", "1.0") in tags


def test_no_dr_flag_forces_dr_zero_and_skips_owncfg(state_ledger, monkeypatch, tmp_path):
    tags = _run_and_collect_drv(state_ledger, monkeypatch, tmp_path, ["--no-dr"])
    assert tags == {("gate", "0.0")}


def test_explicit_dr_scale_still_wins(state_ledger, monkeypatch, tmp_path):
    tags = _run_and_collect_drv(state_ledger, monkeypatch, tmp_path, ["--dr-scale", "0.35"])
    assert ("gate", "0.0") in tags
    assert ("owncfg", "0.35") in tags
