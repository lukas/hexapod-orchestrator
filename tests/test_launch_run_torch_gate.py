"""launch_run.py's --device cuda capability gate (08-15).

Closes the [code] WAITING-ON entry (STATUS.md / arch/STATUS.md): the
launcher must refuse an explicit `--device cuda` launch on a GPU pod
with no recorded pod_torch_capability.py capability, so a transformer/
attention-trunk arm can never silently fall back to the ~18x-slower
stock CPU-torch PPO update on GPU-priced hardware. `--device auto` (the
trainer default) is untouched — this only gates an EXPLICIT cuda ask.

These tests exercise `_launch_locked` with every external call
(kubectl, W&B, the ledger file) monkeypatched to canned/no-op values,
so nothing here touches a real pod or experiments.json.
"""
import argparse
import contextlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parents[1] / "orchestrator"

_spec = importlib.util.spec_from_file_location("launch_run", _HERE / "launch_run.py")
lr = importlib.util.module_from_spec(_spec)
sys.modules["launch_run"] = lr
_spec.loader.exec_module(lr)


def _ns(**kw):
    base = dict(run="cw-arch-tf-gatecheck", pod="hexapod-mjx-train-1",
                steps=2_000_000, smoke=False, hypothesis="h", gate="g",
                parent=None, allow_slow=False, dry_run=True,
                phase="discovery", evidence=None, trainer="ppo",
                track="arch", operator_override=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _patch_common(monkeypatch):
    # No live kubectl/W&B/ledger writes from this test, ever.
    local_sha = lr.sh(["git", "-C", str(lr.HEXAPOD_REPO), "rev-parse", "HEAD"]).strip()

    def _kexec(pod, script, timeout=60):
        if "code_sha" in script:
            return local_sha
        if "nvidia-smi" in script:
            return "GPU 0: NVIDIA H200\n"
        if "torch.cuda.is_available" in script:
            return "2.11.0+cu128 NVIDIA H200\n"
        if "command -v uv" in script:
            return "/usr/local/bin/python\n"
        if "wandb.env" in script:
            return "OK"
        return ""

    monkeypatch.setattr(lr, "pod_cpu_limit", lambda pod: 56)
    monkeypatch.setattr(lr, "pod_trainers", lambda pod: [])
    monkeypatch.setattr(lr, "kexec", _kexec)
    monkeypatch.setattr(lr, "wandb_name_exists", lambda run: False)
    monkeypatch.setattr(lr, "wandb_running_runs", lambda: {})
    monkeypatch.setattr(lr, "upsert_entry", lambda entry: None)
    monkeypatch.setattr(lr, "load_ledger", lambda: [])   # explicit empty ledger

    class _NeverExists:
        def exists(self):
            return False

    monkeypatch.setattr(lr, "LAUNCH_HOLD", _NeverExists())
    return _kexec


def _guardrails():
    return {"compute": {
        "pods": ["hexapod-sweep-friction"],
        "gpu_pods": ["hexapod-mjx-train-1"],
        "gpu": {"n_envs": 4096, "min_eval_every": 1_000_000,
                "min_video_every": 2_000_000,
                "max_steps_per_run": 40_000_000, "host_workers": 24,
                "impl": "warp"},
        "n_envs": 256, "min_eval_every": 100_000, "min_video_every": 500_000,
        "max_steps_per_run": 6_000_000,
        "max_concurrent_runs": 16,
        "phases": {"discovery_max_steps": 2_000_000},
    }}


def test_explicit_device_cuda_refused_on_uncapable_pod(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(lr._torch_cap, "is_capable", lambda pod: False)
    a = _ns()
    rc = lr._launch_locked(_guardrails(), a, ["--device", "cuda"])
    assert rc == 1


def test_explicit_device_cuda_passes_on_recorded_pod(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(lr._torch_cap, "is_capable", lambda pod: True)
    a = _ns()
    rc = lr._launch_locked(_guardrails(), a, ["--device", "cuda"])
    # dry_run=True -> a clean pass returns 0 (DRY-RUN print), not a refusal
    assert rc == 0


def test_device_auto_default_is_never_gated(monkeypatch):
    _patch_common(monkeypatch)
    # is_capable would refuse if consulted; it must NOT be consulted for
    # the trainer's own "auto" default (no explicit cuda ask at all).
    monkeypatch.setattr(lr._torch_cap, "is_capable", lambda pod: False)
    a = _ns()
    rc = lr._launch_locked(_guardrails(), a, [])
    assert rc == 0


def test_canary_and_acquisition_are_distinct_phase_contracts(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(lr._torch_cap, "is_capable", lambda pod: True)

    assert lr._launch_locked(
        _guardrails(), _ns(phase="canary"), ["--device", "cuda"]) == 0
    assert lr._launch_locked(
        _guardrails(), _ns(phase="canary", steps=2_000_001),
        ["--device", "cuda"]) == 1
    assert lr._launch_locked(
        _guardrails(), _ns(phase="acquisition", steps=38_000_000,
                           evidence=None), ["--device", "cuda"]) == 1
    assert lr._launch_locked(
        _guardrails(), _ns(phase="acquisition", steps=38_000_000,
                           evidence="healthy 2M canary; matched family 40M"),
        ["--device", "cuda"]) == 0


def test_canary_verdict_guard_blocks_behavioral_category_error():
    base = {"phase": "canary", "hardware_ready": False}
    assert lr.canary_update_error({
        **base, "verdict": "CANARY PASS - optimizer and telemetry healthy"}) == ""
    assert lr.canary_update_error({
        **base, "verdict": "CANARY FAIL - MECHANISM - NaN at step 10"}) == ""
    assert "invalid" in lr.canary_update_error({
        **base, "verdict": "FAIL - KNOWN EXPLOIT; reward recipe closed"})
    assert "hardware_ready" in lr.canary_update_error({
        **base, "hardware_ready": True, "verdict": "CANARY PASS"})


def test_dynrep_uses_recorded_capability_and_live_runtime_probe(monkeypatch):
    # A recorded capability lets dynrep consider uv's Python after the private
    # CUDA venv; the live CUDA probe still has to succeed before launch.
    _patch_common(monkeypatch)
    calls = []
    monkeypatch.setattr(lr._torch_cap, "is_capable",
                        lambda pod: calls.append(pod) or True)
    a = _ns(run="cw-dynrep-gatecheck", trainer="dynrep")
    rc = lr._launch_locked(
        _guardrails(), a,
        ["--device", "cuda", "--data", "ds1", "--arch", "transformer"])
    assert calls == ["hexapod-mjx-train-1"]
    assert rc == 0


def test_dynrep_launch_timeout_recovers_anchored_trainer_pid(monkeypatch):
    base_kexec = _patch_common(monkeypatch)
    monkeypatch.setattr(lr._torch_cap, "is_capable", lambda pod: True)

    def timeout_on_launch(pod, script, timeout=60):
        if "nohup" in script and " -m rl_move.dynamics.train" in script:
            raise lr.subprocess.TimeoutExpired("kubectl exec", timeout)
        return base_kexec(pod, script, timeout)

    recovered = []
    monkeypatch.setattr(lr, "kexec", timeout_on_launch)
    monkeypatch.setattr(
        lr, "_pod_trainer_pid",
        lambda pod, run: recovered.append((pod, run)) or "4184935")
    a = _ns(run="cw-dynrep-timeout", trainer="dynrep", dry_run=False)
    ctx = lr._launch_locked(
        _guardrails(), a,
        ["--device", "cuda", "--data", "ds1", "--arch", "transformer"])
    assert recovered == [("hexapod-mjx-train-1", "cw-dynrep-timeout")]
    assert ctx["pid"] == "4184935"


def test_dynrep_fresh_uses_gpu_data_pipeline(monkeypatch, capsys):
    _patch_common(monkeypatch)
    monkeypatch.setattr(lr._torch_cap, "is_capable", lambda pod: True)
    a = _ns(run="cw-dynrep-fresh-gatecheck", trainer="dynrep-fresh")
    rc = lr._launch_locked(
        _guardrails(), a,
        ["--device", "cuda", "--data", "fresh_ds",
         "--arch", "transformer", "--collect-n-envs", "2048"])
    command = capsys.readouterr().out
    assert rc == 0
    assert "-m rl_move.dynamics.fresh_pipeline" in command
    assert "--collect-n-envs 2048" in command
    assert "--arch transformer" in command


def test_respec_now_preserves_dynrep_fresh_trainer(monkeypatch):
    source = {
        "run": "cw-dynrep-source", "trainer": "dynrep-fresh",
        "steps": 40_000, "track": "dynrep", "phase": "discovery",
        "extra_args": ["--data", "old_ds", "--device", "cuda"],
        "checks": {"pid": "123"},
    }
    monkeypatch.setattr(lr, "load_ledger", lambda: [source])
    monkeypatch.setattr(
        lr.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="snapshot ok", stderr=""))
    monkeypatch.setattr(lr, "_self_repair_pod", lambda pod, args: None)
    captured = {}

    def fake_launch(g, ns, args):
        captured.update(ns=ns, args=args)
        return 0

    monkeypatch.setattr(lr, "cmd_launch", fake_launch)
    args = argparse.Namespace(
        source="cw-dynrep-source", run="cw-dynrep-copy", seed=None,
        steps=None, parent="", hypothesis="h", gate="g", phase="",
        evidence="", arg=["--data=new_ds"], cfg=None,
        init_from_source=False, now=True, pod="hexapod-mjx-train-1",
        operator_override="", track="")
    assert lr.cmd_respec({}, args) == 0
    assert captured["ns"].trainer == "dynrep-fresh"
    assert captured["args"][captured["args"].index("--data") + 1] == "new_ds"
    # 08-15 regression: respec used to append --out-name unconditionally
    # (a ppo-only convention) — rl_move.dynamics.train/fresh_pipeline has
    # no such flag and argparse crashes on it (cw-dynrep-tf-state2-fresh3
    # burned a full stage-1 recollection before hitting this on stage 2).
    assert "--out-name" not in captured["args"]


def test_respec_init_from_source_refused_for_dynrep(monkeypatch):
    source = {
        "run": "cw-dynrep-source", "trainer": "dynrep-fresh",
        "steps": 40_000, "track": "dynrep", "phase": "discovery",
        "extra_args": ["--data", "old_ds", "--device", "cuda"],
        "checks": {"pid": "123"},
    }
    monkeypatch.setattr(lr, "load_ledger", lambda: [source])
    args = argparse.Namespace(
        source="cw-dynrep-source", run="cw-dynrep-copy", seed=None,
        steps=None, parent="", hypothesis="h", gate="g", phase="",
        evidence="", arg=None, cfg=None,
        init_from_source=True, now=False, pod=None,
        operator_override=None, track="")
    assert lr.cmd_respec({}, args) == 1


def test_dynrep_checkup_floor_is_not_the_ppo_physics_fps_floor(monkeypatch):
    """Regression (found 08-15 on cw-dynrep-tf-state2-recovered1, and
    reproduced retroactively in the ledger on cw-dynrep-tf-state1):
    dynrep/dynrep-fresh's W&B "global_step" is a GRADIENT step over a
    fixed pre-collected window dataset, not a PPO physics env-step —
    a completely different unit from the ~19-20k-fps GPU-MJX floor
    calibrated for MJX rollout throughput. Both real runs steady-state
    at ~41 step/s and both false-SUSPECTed against the flat 5000 floor.
    A healthy ~41 step/s dynrep trainer must read HEALTHY."""
    entry = {
        "run": "cw-dynrep-gatecheck-checkup", "pod": "hexapod-mjx-train-1",
        "created": "2026-08-15T00:00:00+00:00", "status": "RUNNING",
        "trainer": "dynrep", "log": "/tmp/train_cw-dynrep-gatecheck-checkup.log",
    }
    monkeypatch.setattr(lr, "load_ledger", lambda: [entry])
    monkeypatch.setattr(lr, "save_ledger", lambda entries: None)
    monkeypatch.setattr(lr, "ledger_lock", lambda: contextlib.nullcontext())
    monkeypatch.setattr(lr, "pod_trainers",
                        lambda pod: ["cw-dynrep-gatecheck-checkup"])
    monkeypatch.setattr(lr, "pod_cpu_limit", lambda pod: 26)
    monkeypatch.setattr(lr, "kexec", lambda pod, script, timeout=60: "0")
    monkeypatch.setattr(lr.time, "sleep", lambda s: None)
    steps = iter([27750, 27750 + 41 * 45])  # matches recovered1's steady-state
    monkeypatch.setattr(
        lr, "wandb_running_runs",
        lambda: {"cw-dynrep-gatecheck-checkup": {"global_step": next(steps)}})
    a = SimpleNamespace(run="cw-dynrep-gatecheck-checkup")
    g = {"compute": {"gpu_pods": ["hexapod-mjx-train-1"]}}
    assert lr.cmd_checkup(g, a) == 0


def test_recover_population_waiting_detects_only_unreleased_ready_bucket():
    ready = '{"population_id":"recover-test-pop3","bucket":0}'
    summary = {"recover_population/ready_B00": ready}
    assert lr._recover_population_waiting(summary) == {
        "bucket": 0,
        "ready_key": "recover_population/ready_B00",
        "start_key": "recover_population/start_B00",
    }
    summary["recover_population/start_B00"] = '{"bucket":0}'
    assert lr._recover_population_waiting(summary) is None


def test_recover_population_barrier_is_healthy_during_checkup(monkeypatch):
    run = "cw-recover-barrier-checkup"
    entry = {
        "run": run,
        "pod": "hexapod-mjx-train-1",
        "created": "2026-08-18T00:00:00+00:00",
        "status": "RUNNING",
        "trainer": "ppo",
        "log": f"/tmp/train_{run}.log",
    }
    saved = []
    monkeypatch.setattr(lr, "load_ledger", lambda: [entry])
    monkeypatch.setattr(lr, "save_ledger", lambda entries: saved.extend(entries))
    monkeypatch.setattr(lr, "ledger_lock", lambda: contextlib.nullcontext())
    monkeypatch.setattr(lr, "pod_trainers", lambda pod: [run])
    monkeypatch.setattr(lr.time, "sleep", lambda seconds: None)

    def fake_kexec(pod, script, timeout=60):
        if "grep -c 'Traceback'" in script:
            return "0"
        if "stat -c %s" in script:
            return "1234"
        raise AssertionError(f"unexpected command while barrier is healthy: {script}")

    monkeypatch.setattr(lr, "kexec", fake_kexec)
    barrier = {"bucket": 0, "ready_key": "recover_population/ready_B00",
               "start_key": "recover_population/start_B00"}
    monkeypatch.setattr(
        lr, "wandb_running_runs",
        lambda: {run: {"id": "abc12345", "state": "running",
                       "global_step": 655_360,
                       "recover_population_barrier": barrier}})

    a = SimpleNamespace(run=run)
    g = {"compute": {"gpu_pods": ["hexapod-mjx-train-1"]}}
    assert lr.cmd_checkup(g, a) == 0
    checkup = saved[-1]["checkups"][-1]
    assert checkup["verdict"] == "HEALTHY"
    assert checkup["recover_population_barrier"] == barrier
    assert "intentionally waiting" in checkup["note"]


def test_checkup_finds_completion_marker_past_2000_bytes(monkeypatch):
    """Regression (08-27, anchor10-percoreclip false DEAD): a fast MJX
    canary's own post-completion W&B postamble (artifact upload lines
    + the full Run history/Run summary key dump) can push the
    "[mjx-train] done" completion banner more than 2000 bytes before
    the end of the log -- this exact run measured 2107 bytes after the
    marker, missing the previously-widened-once-already 2000-byte tail
    window by 107 bytes and reporting DEAD on a cleanly finished run.
    The tail must now be wide enough to still see the marker."""
    run = "cw-checkup-tailwidth-regress"
    entry = {
        "run": run, "pod": "hexapod-mjx-train-4",
        "created": "2026-08-27T00:00:00+00:00", "status": "RUNNING",
        "trainer": "ppo", "log": f"/tmp/train_{run}.log", "steps": 2000000,
    }
    monkeypatch.setattr(lr, "load_ledger", lambda: [entry])
    monkeypatch.setattr(lr, "save_ledger", lambda entries: None)
    monkeypatch.setattr(lr, "ledger_lock", lambda: contextlib.nullcontext())
    monkeypatch.setattr(lr, "pod_trainers", lambda pod: [])  # process exited
    # Fabricate the exact shape: the completion marker, then >2000
    # bytes of wandb postamble (a synthetic Run summary key dump).
    postamble = "\n".join(f"wandb:   canary/k{i} 0" for i in range(120))
    log_text = (
        "[mjx-train] done: 2,000,000 steps in 906s (2,207 env-steps/s "
        "incl. setup) -> ckpt.zip\n" + postamble)
    assert len(log_text.encode()) - log_text.index(
        "[mjx-train] done") > 2000, "fixture must exceed the old window"

    def _kexec(pod, script, timeout=60):
        if "tail -c" in script:
            n = int(script.split("tail -c", 1)[1].split()[0])
            return log_text[-n:]
        return "0"

    monkeypatch.setattr(lr, "kexec", _kexec)
    a = SimpleNamespace(run=run)
    g = {"compute": {"gpu_pods": ["hexapod-mjx-train-4"]}}
    assert lr.cmd_checkup(g, a) == 0, (
        "still reporting DEAD -- the tail window did not actually widen")
