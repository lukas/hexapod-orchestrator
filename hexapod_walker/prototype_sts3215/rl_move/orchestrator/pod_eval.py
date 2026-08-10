#!/usr/bin/env python3
"""Run a finished run's standard post-training evals ON ITS OWN POD.

    python3 rl_move/orchestrator/pod_eval.py <run> [tag-suffix]

Operator directive 2026-08-10: eval compute must not pile up on the
controller (measured: 5 concurrent triage evals at ~4.5 cores each on a
box already at load ~240/128, everything ~2x slow) and must not wait
for an LLM cycle to claim the run. Train pods have ~100 idle CPUs and
already hold the checkpoint, so the harness runs there.

What it does, synchronously (caller backgrounds it — the watcher runs
it in the prestage worker thread):

  1. Reads the run's ledger entry (pod, task, cfg-sets, dr-scale).
  2. Locates the checkpoint on the pod (launch_run --out-name
     convention, with the trainer-default ppo_mjx_* fallbacks).
  3. Starts the DR-0 gate eval and — when the run trained at DR>0 —
     the own-DR eval, IN PARALLEL on the pod. Output streams to
     controller-local /tmp/eval_<run>.log / /tmp/eval_<run>_owncfg.log
     so the cycle's existing `ops.sh waitlog` workflow keeps working.
  4. When each pass finishes, copies its artifact dir back to the
     controller's logs/ckpt_eval/ (same paths as before) and appends a
     final "SYNCED ..." line to the pass's log. Wait on THAT line, not
     on eval_checkpoint's own "artifacts" line — that prints on the
     pod before the copy-back.

Idempotent: a pass whose controller-side artifact dir already exists
is skipped (protects historical eval artifacts from being clobbered).
The eval harness also pushes its summary to the training run's W&B
page by itself (eval_checkpoint --wandb, default on; pods carry
wandb.env).
"""
from __future__ import annotations

import json
import pathlib
import shlex
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PROTO = HERE.parent.parent
LEDGER = HERE / "experiments.json"
POD_PROTO = "/workspace/prototype_sts3215"
PASS_TIMEOUT_S = 2700


def kexec(pod: str, cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "exec", pod, "--", "bash", "-c", cmd],
                          capture_output=True, text=True, timeout=timeout)


def find_checkpoint(pod: str, run: str, task: str) -> str | None:
    names = ["ppo_goal_" + run.replace("-", "_") + ".zip"]
    names += [f"ppo_mjx_{t}_{run}.zip"
              for t in (task, "joint_walk", "joint_goal", "goal")]
    seen = set()
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        p = f"{POD_PROTO}/rl_move/sim/policies/{n}"
        if kexec(pod, f"test -s {shlex.quote(p)}").returncode == 0:
            return p
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    run, suffix = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    entry = None
    for e in json.loads(LEDGER.read_text()):
        if isinstance(e, dict) and e.get("run") == run and e.get("extra_args"):
            entry = e
    if entry is None:
        print(f"no ledger entry with extra_args for {run}")
        return 1
    pod = entry["pod"]
    args = list(entry["extra_args"])

    def val(flag: str, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    task = val("--task", "joint_walk")
    ep = val("--episode-seconds", "15" if task == "joint_walk" else None)
    dr = float(val("--dr-scale", "0") or 0)
    cfgs = [args[i + 1] for i, a in enumerate(args) if a == "--cfg-set"]
    modes = "--modes walk" if task == "joint_walk" else ""

    ckpt = find_checkpoint(pod, run, task)
    if ckpt is None:
        print(f"no checkpoint for {run} on {pod} — nothing to eval")
        return 1

    run_us = run.replace("-", "_")
    passes = [("gate", "0.0", f"/tmp/eval_{run}.log")]
    if dr > 0:
        passes.append(("owncfg", str(dr), f"/tmp/eval_{run}_owncfg.log"))

    jobs = []
    for tag, drv, logpath in passes:
        out_rel = f"logs/ckpt_eval/{run_us}_{tag}{suffix}"
        local_out = PROTO / out_rel
        if local_out.exists():
            print(f"{tag}: {out_rel} already on controller — skipping")
            continue
        cmd = (f"cd {POD_PROTO} && set -a && "
               f". rl_move/sim/wandb.env 2>/dev/null; set +a; "
               f"python3 -m rl_move.sim.eval_checkpoint {shlex.quote(ckpt)}"
               f" --task {task} {modes} --per-mode 6 --dr-scale {drv}"
               f" --seed 0 --stochastic"
               + (f" --episode-seconds {ep}" if ep else "")
               + "".join(f" --cfg-set {shlex.quote(c)}" for c in cfgs)
               + f" --video-every 1 --out {out_rel}")
        fh = open(logpath, "w")
        p = subprocess.Popen(["kubectl", "exec", pod, "--", "bash", "-c", cmd],
                             stdout=fh, stderr=subprocess.STDOUT, text=True)
        print(f"{tag}: started on {pod} (dr {drv}) -> {logpath}")
        jobs.append((tag, out_rel, logpath, p, fh))

    worst = 0
    for tag, out_rel, logpath, p, fh in jobs:
        try:
            rc = p.wait(timeout=PASS_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p.kill()
            rc = -1
        note = ""
        if rc == 0:
            (PROTO / out_rel).parent.mkdir(parents=True, exist_ok=True)
            cp = subprocess.run(
                ["kubectl", "cp", f"{pod}:{POD_PROTO}/{out_rel}",
                 str(PROTO / out_rel)],
                capture_output=True, text=True, timeout=600)
            # kubectl cp exits 0 on missing remote paths — check the file
            if not (PROTO / out_rel / "report.json").is_file():
                rc, note = 1, " (copy-back missing report.json)"
                cp_err = (cp.stderr or "").strip()
                if cp_err:
                    note += f": {cp_err[-200:]}"
        fh.write(f"\nSYNCED rc={rc}{note}: {out_rel}\n")
        fh.close()
        print(f"{tag}: rc={rc}{note} artifacts -> {out_rel}")
        worst = max(worst, abs(rc))
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
