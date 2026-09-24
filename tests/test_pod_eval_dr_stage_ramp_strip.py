"""env.dr_stage_ramp_steps must not leak into a DR=0 eval pass.

2026-09-24 (lowerrole/walkyaw SAC drramp triage): sim_env.py's
``env.dr_stage_ramp_steps > 0`` construction-time check deliberately
raises when ``randomize=False`` ("nothing to stage") -- a fail-closed
guard against a MISCONFIGURED TRAINING run. But every gate/probe eval
pass forces ``--dr-scale 0.0`` (randomize=False) regardless of what the
checkpoint trained with, so any run whose ledger extra_args still
carry an inherited ``env.dr_stage_ramp_steps`` cfg-set crashes its own
DR=0 gate pass outright (FAIL-INFRASTRUCTURE for a harness gap, not a
training defect) -- confirmed on
cw-stance50hz-rlonly-lowerrole-scratch-sac-{s0,s1}-drramp-acq1's own
gate pass this cycle. The key is moot with DR off anyway (nothing to
interpolate toward), so a DR=0 pass should silently drop it while a
DR>0 (owncfg) pass keeps it untouched.
"""
import importlib.util
import io
import pathlib
import shlex
import subprocess
import sys

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_spec = importlib.util.spec_from_file_location(
    "pod_eval_drramp_strip", _ORCH / "pod_eval.py")
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)


def test_strip_helper_pure():
    cfgs = ["env.dr_stage_ramp_steps=5000000", "goal.walk_yaw_cmd=1"]
    assert pod_eval.strip_dr_stage_ramp_for_dr0(cfgs, 0.0) == [
        "goal.walk_yaw_cmd=1"]
    # DR>0 pass: untouched, order preserved.
    assert pod_eval.strip_dr_stage_ramp_for_dr0(cfgs, 0.2) == cfgs


def test_strip_helper_noop_when_key_absent():
    cfgs = ["goal.walk_yaw_cmd=1", "control.hz=50"]
    assert pod_eval.strip_dr_stage_ramp_for_dr0(cfgs, 0.0) == cfgs


def test_gate_pass_drops_ramp_key_owncfg_keeps_it(
        state_ledger, monkeypatch, tmp_path):
    run = "drramp-strip-test-" + tmp_path.name
    state_ledger([{
        "run": run, "pod": "target-pod", "wandb_id": "test-id",
        "extra_args": [
            "--task", "joint_walk", "--dr-scale", "0.2",
            "--cfg-set", "control.hz=50",
            "--cfg-set", "env.dr_stage_ramp_steps=5000000",
        ],
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

    by_out = {}
    for cmd in launches:
        out = cmd[cmd.index("--out") + 1]
        by_out["owncfg" if "_owncfg" in out else "gate"] = " ".join(cmd)

    assert "env.dr_stage_ramp_steps" not in by_out["gate"]
    assert "env.dr_stage_ramp_steps=5000000" in by_out["owncfg"]
    assert "control.hz=50" in by_out["gate"]  # unrelated key untouched
