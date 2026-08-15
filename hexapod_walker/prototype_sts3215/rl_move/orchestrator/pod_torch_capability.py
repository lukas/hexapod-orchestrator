#!/usr/bin/env python3
"""Durable, recorded CUDA-torch capability for mjx-train pods.

Named [code] wait (arch/STATUS.md, STATUS.md WAITING-ON, 08-15): every
mjx-train pod's SB3/torch stack is CPU-only (2.13.0+cpu) — fine for the
flatten-MLP champion (~5k fps) but ~18x too slow for attention/GRU
trunks whose PPO update cost lives in torch, not the warp/jax physics
step. `cw-arch-tf-r1b`/`cw-arch-tf-r1-hard1`/`cw-arch-tf-r1-hard2-r1`
proved a CUDA-torch install (`torch==2.11.0+cu128 --no-deps`, coexists
fine with the pod's jax/warp stack) gives ~120x on the PPO update — but
that fix was applied BY HAND on one pod (train-1) with nothing recorded:
lost on pod restart/recycle, invisible to snapshot.sh's code marker, and
every future transformer/attention arm would need the same manual
archaeology. This module is the durable version: a reproducible install
step, a light read-only coexistence smoke (safe to run against a pod
that is mid-training — no GPU memory allocation, no matmul), and a
recorded capability file the launcher gates `--device cuda` against.

Shared default is UNCHANGED: pods stay CPU-torch until explicitly
installed+recorded here; `--device cuda` without a recorded capability
is a clean launcher REFUSAL, not a silent CPU fallback (a silent
fallback would make a 40M "cuda" run actually be the 37h CPU run again,
undetected).

CLI:
  pod_torch_capability.py status
  pod_torch_capability.py verify --pod POD [--full-smoke]
  pod_torch_capability.py install --pod POD [--version 2.11.0+cu128]
  pod_torch_capability.py record --pod POD --version V --note "..."
      (manual/offline record — e.g. evidence from a run's own ledger
      log rather than a fresh probe; used for train-1's retroactive
      entry, whose install predates this module.)

Library API (used by launch_run.py's --device cuda gate):
  is_capable(pod) -> bool
  load() -> dict
"""
from __future__ import annotations

import argparse
import fcntl
import json
import shlex
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPFILE = HERE / "pod_torch_capability.json"
CAPFILE_LOCK = HERE / "pod_torch_capability.json.lock"
KUBECONFIG = str(Path.home() / ".kube" / "coreweave.yaml")
DEFAULT_VERSION = "2.11.0+cu128"
# +cuXXX local-version wheels only exist on PyTorch's own index, not
# plain PyPI (pods' default pip index has plain "torch==2.11.0" with no
# +cu128 suffix and 404s on the exact pin). train-1's original capable
# record came from an ad hoc BY-HAND install that happened to pass this
# index already; the durable `install` subcommand never actually
# exercised a fresh pod until cw-arch-tf-r1-hard3's prelaunch (08-15
# ~17:5x UTC) hit the bare 404 on train-0. --no-deps still protects the
# pod's jax/warp/nvidia-cu12 stack; only torch itself comes from here.
TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu128"
# torch==2.11.0+cu128 dynamically links a few CUDA-runtime .so's that
# --no-deps skips and that are NOT part of every pod's baseline image
# (jax pulls its own overlapping-but-not-identical nvidia-cu12 subset).
# Measured gap train-0 vs the already-capable train-1 (08-15, this
# cycle's cw-arch-tf-r1-hard3 prelaunch): missing cusparselt/cufile/
# curand/nvtx, discovered one ImportError at a time. Pinned to
# train-1's exact working versions and installed ONLY if the pod can't
# already import them — this never touches/upgrades a package the pod
# already has, so it can't disturb jax's pinned stack.
EXTRA_CUDA_LIBS = {
    "nvidia-cusparselt-cu12": "0.8.1",
    "nvidia-cufile-cu12": "1.14.1.1",
    "nvidia-curand-cu12": "10.3.10.19",
    "nvidia-nvtx-cu12": "12.9.79",
}

# Light, read-only smoke: import + version/availability checks only, NO
# tensor allocation or matmul. Safe to run against a pod mid-training —
# it costs a python process start and a few ms of import time, nothing
# that competes for GPU memory with a live trainer. --full-smoke adds a
# real (tiny) CUDA matmul + a jax device-array roundtrip AFTER it, for
# use on a freshly-installed, still-IDLE pod only (never on a busy pod).
_LIGHT_SMOKE_PY = (
    "import json,sys\n"
    "out={}\n"
    "try:\n"
    "    import torch\n"
    "    out['torch_version']=torch.__version__\n"
    "    out['torch_cuda_available']=bool(torch.cuda.is_available())\n"
    "except Exception as e:\n"
    "    out['torch_error']=str(e)\n"
    "try:\n"
    "    import jax\n"
    "    out['jax_version']=jax.__version__\n"
    "    out['jax_import_ok']=True\n"
    "except Exception as e:\n"
    "    out['jax_import_ok']=False\n"
    "    out['jax_error']=str(e)\n"
    "print('CAPPROBE_JSON:'+json.dumps(out))\n"
)
_FULL_SMOKE_PY = (
    "import json\n"
    "out={}\n"
    "import torch\n"
    "x=torch.randn(256,256,device='cuda')\n"
    "y=(x@x).sum().item()\n"
    "out['cuda_matmul_ok']=(y==y)  # NaN-safe finite check below\n"
    "import math\n"
    "out['cuda_matmul_finite']=math.isfinite(y)\n"
    "del x\n"
    "torch.cuda.empty_cache()\n"
    "import jax, jax.numpy as jnp\n"
    "z=jnp.asarray([1.0,2.0,3.0])\n"
    "out['jax_roundtrip_ok']=bool((z*2).sum()==12.0)\n"
    "print('FULLPROBE_JSON:'+json.dumps(out))\n"
)


@contextmanager
def _file_lock(path: Path):
    path.touch(exist_ok=True)
    with open(path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load() -> dict:
    if not CAPFILE.exists():
        return {}
    return json.loads(CAPFILE.read_text())


def _save(data: dict) -> None:
    with _file_lock(CAPFILE_LOCK):
        CAPFILE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def is_capable(pod: str) -> bool:
    """True only for a pod with a recorded, coexistence-verified install.

    A record with a torch_error / jax_import_ok=False / no smoke block
    at all does NOT count — half-verified is not durable."""
    rec = load().get(pod)
    if not rec:
        return False
    smoke = rec.get("smoke", {})
    return bool(
        smoke.get("torch_cuda_available")
        and smoke.get("jax_import_ok")
        and not smoke.get("torch_error")
    )


def _kexec(pod: str, script: str, timeout: int = 120) -> str:
    return subprocess.run(
        ["kubectl", "--kubeconfig", KUBECONFIG, "exec", pod, "--",
         "bash", "-c", script],
        capture_output=True, text=True, timeout=timeout, check=True,
    ).stdout


def _ensure_extra_cuda_libs(pod: str) -> list[str]:
    """Install any of EXTRA_CUDA_LIBS the pod can't already import.

    Never reinstalls/upgrades a package already present (idempotent,
    additive-only — see EXTRA_CUDA_LIBS comment). Returns the list of
    packages actually installed this call (empty on an already-full
    pod, e.g. train-1)."""
    mod_of = {
        "nvidia-cusparselt-cu12": "nvidia.cusparselt.lib",
        "nvidia-cufile-cu12": "nvidia.cufile.lib",
        "nvidia-curand-cu12": "nvidia.curand.lib",
        "nvidia-nvtx-cu12": "nvidia.nvtx.lib",
    }
    installed = []
    for pkg, ver in EXTRA_CUDA_LIBS.items():
        probe = f"import {mod_of[pkg]}" if pkg in mod_of else f"import {pkg}"
        try:
            _kexec(pod, f"python3 -c {shlex.quote(probe)}", timeout=30)
            continue  # already importable, leave it alone
        except subprocess.CalledProcessError:
            pass
        _kexec(pod, f"pip install {pkg}=={ver} --no-deps", timeout=300)
        installed.append(f"{pkg}=={ver}")
    return installed


def _parse_probe(stdout: str, marker: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker):])
    return {"probe_error": f"no {marker} line in output", "raw": stdout[-2000:]}


def _run_smoke(pod: str, full: bool) -> dict:
    out = _parse_probe(_kexec(pod, f"python3 -c {shlex.quote(_LIGHT_SMOKE_PY)}"),
                       "CAPPROBE_JSON:")
    if full and not out.get("torch_error") and out.get("torch_cuda_available"):
        out.update(_parse_probe(
            _kexec(pod, f"python3 -c {shlex.quote(_FULL_SMOKE_PY)}"),
            "FULLPROBE_JSON:"))
    return out


def cmd_status(_a) -> int:
    data = load()
    if not data:
        print("no pods recorded (rl_move/orchestrator/pod_torch_capability.json "
              "empty/missing) — every mjx-train pod is CPU-torch-only by "
              "default; run `install --pod POD` to opt one in.")
        return 0
    print(f"{'pod':<24} {'capable':<8} {'version':<14} verified_utc")
    for pod, rec in sorted(data.items()):
        print(f"{pod:<24} {'yes' if is_capable(pod) else 'no':<8} "
              f"{rec.get('torch_version', '?'):<14} "
              f"{rec.get('verified_utc', '?')}")
    return 0


def cmd_verify(a) -> int:
    smoke = _run_smoke(a.pod, full=a.full_smoke)
    data = load()
    rec = data.get(a.pod, {})
    rec["torch_version"] = smoke.get("torch_version", rec.get("torch_version", "?"))
    rec["smoke"] = smoke
    rec["verified_utc"] = datetime.now(timezone.utc).isoformat()
    data[a.pod] = rec
    _save(data)
    ok = is_capable(a.pod)
    print(f"{a.pod}: {'CAPABLE' if ok else 'NOT capable'} — {json.dumps(smoke)}")
    return 0 if ok else 1


def cmd_install(a) -> int:
    version = a.version or DEFAULT_VERSION
    print(f"installing torch=={version} (--no-deps, preserves the pod's "
          f"jax/warp/nvidia-cu12 stack) on {a.pod} ...")
    install_cmd = (f"pip install torch=={version} --no-deps "
                   f"--index-url {TORCH_INDEX_URL}")
    _kexec(a.pod, install_cmd, timeout=480)
    extras = _ensure_extra_cuda_libs(a.pod)
    smoke = _run_smoke(a.pod, full=a.full_smoke)
    data = load()
    rec = data.get(a.pod, {})
    rec.update({
        "torch_version": smoke.get("torch_version", version),
        "install_cmd": install_cmd,
        "extra_cuda_libs_installed": extras,
        "smoke": smoke,
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "note": rec.get("note", "installed + verified by "
                                 "pod_torch_capability.py install"),
    })
    data[a.pod] = rec
    _save(data)
    ok = is_capable(a.pod)
    print(f"{a.pod}: {'CAPABLE' if ok else 'INSTALL SUCCEEDED BUT SMOKE FAILED'} "
          f"— {json.dumps(smoke)}")
    return 0 if ok else 1


def cmd_record(a) -> int:
    """Manual/retroactive record (evidence from elsewhere, e.g. a run's
    own ledger/log, rather than a probe run here-and-now)."""
    data = load()
    rec = data.get(a.pod, {})
    rec.update({
        "torch_version": a.version,
        "smoke": {
            "torch_version": a.version,
            "torch_cuda_available": True,
            "jax_import_ok": True,
        },
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "note": a.note or "manually recorded",
    })
    data[a.pod] = rec
    _save(data)
    print(f"recorded {a.pod} as capable (manual, unprobed this session): "
          f"{a.note or ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    vp = sub.add_parser("verify")
    vp.add_argument("--pod", required=True)
    vp.add_argument("--full-smoke", action="store_true",
                     help="also run a tiny CUDA matmul + jax roundtrip — "
                          "only use this against an IDLE pod, never one "
                          "mid-training")
    ip = sub.add_parser("install")
    ip.add_argument("--pod", required=True)
    ip.add_argument("--version", default="")
    ip.add_argument("--full-smoke", action="store_true")
    rp = sub.add_parser("record")
    rp.add_argument("--pod", required=True)
    rp.add_argument("--version", required=True)
    rp.add_argument("--note", default="")
    a = ap.parse_args(argv)
    fn = {"status": cmd_status, "verify": cmd_verify, "install": cmd_install,
          "record": cmd_record}[a.action]
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
