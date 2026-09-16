"""Regression test (2026-08-25, gaitgate-cont1 launch dig-in): the
duplicate-run-name scan in `_launch_locked` iterates every configured
pod (`comp["pods"] + gpu_pods`) calling `pod_trainers(pod)`, and only
caught `subprocess.CalledProcessError` -- every OTHER `kexec`/
`pod_trainers` call site in this file already catches
`(CalledProcessError, TimeoutExpired)` together. When
`hexapod-sweep-friction` went briefly slow/unresponsive under its own
CPU sweep load, `kexec`'s 60s timeout raised `TimeoutExpired`
uncaught, crashing EVERY launch/respec attempt fleet-wide (not a
refusal scoped to that one pod -- a hard Python traceback with no
ledger entry written at all), reproduced live 3x in a row before the
fix. This test pins the fix: a pod that times out during the
duplicate-name scan must be skipped, exactly like `status`'s already-
graceful "unreachable (node may have spun down)" handling, not crash
the launch.
"""
import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parents[1] / "orchestrator"

_spec = importlib.util.spec_from_file_location("launch_run", _HERE / "launch_run.py")
lr = importlib.util.module_from_spec(_spec)
sys.modules["launch_run"] = lr
_spec.loader.exec_module(lr)


def _ns(**kw):
    base = dict(run="cw-arch-gaitgate-dupecheck", pod="hexapod-mjx-train-1",
                steps=2_000_000, smoke=False, hypothesis="h", gate="g",
                parent=None, allow_slow=False, dry_run=True,
                phase="discovery", evidence=None, trainer="ppo",
                track="arch", operator_override=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _patch_common(monkeypatch):
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
    monkeypatch.setattr(lr, "kexec", _kexec)
    monkeypatch.setattr(lr, "wandb_name_exists", lambda run: False)
    monkeypatch.setattr(lr, "wandb_running_runs", lambda: {})
    monkeypatch.setattr(lr, "upsert_entry", lambda entry: None)
    monkeypatch.setattr(lr, "load_ledger", lambda: [])   # explicit empty ledger
    monkeypatch.setattr(lr, "_torch_cap",
                        SimpleNamespace(is_capable=lambda pod: True))

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


def test_timeout_expired_pod_is_skipped_not_fatal(monkeypatch):
    _patch_common(monkeypatch)

    def flaky_pod_trainers(pod):
        if pod == "hexapod-sweep-friction":
            raise subprocess.TimeoutExpired("kubectl exec", 60)
        return []

    monkeypatch.setattr(lr, "pod_trainers", flaky_pod_trainers)
    a = _ns()
    # Must reach the dry-run print path (rc 0), not raise.
    rc = lr._launch_locked(_guardrails(), a, [])
    assert rc == 0


def test_calledprocesserror_pod_still_skipped(monkeypatch):
    """Unchanged prior behavior: a pod that errors (rather than times
    out) while being scanned is still skipped, not fatal."""
    _patch_common(monkeypatch)

    def erroring_pod_trainers(pod):
        if pod == "hexapod-sweep-friction":
            raise subprocess.CalledProcessError(1, "kubectl")
        return []

    monkeypatch.setattr(lr, "pod_trainers", erroring_pod_trainers)
    a = _ns()
    rc = lr._launch_locked(_guardrails(), a, [])
    assert rc == 0


def test_duplicate_name_on_a_healthy_pod_still_refuses(monkeypatch):
    """The fix must not swallow a REAL duplicate-name refusal on a pod
    that responds fine."""
    _patch_common(monkeypatch)

    def dupe_pod_trainers(pod):
        if pod == "hexapod-mjx-train-1":
            return ["cw-arch-gaitgate-dupecheck"]
        return []

    monkeypatch.setattr(lr, "pod_trainers", dupe_pod_trainers)
    a = _ns()
    rc = lr._launch_locked(_guardrails(), a, [])
    assert rc == 1
