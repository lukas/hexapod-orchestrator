#!/usr/bin/env python3
"""Run the AMP M5 cross-engine suite (eval_amp_m5) for a checkpoint ON
A POD, with the SAME extra_args-derived cfg-set list `ops.sh evalcmd`
prints (so a run's "own training cfg" -- phase obs, servo profile,
whatever dr.fault_prob/ext_push_prob it trained WITH always-on -- is
what the m5 suite judges, exactly matching how its own DR-0 gate was
read). Not part of the automatic prestage (m5 is a track-DONE-gate
tool, not a per-run standard eval); run it by hand when a verdict names
it as the next step.

    python3 rl_move/orchestrator/m5_pod_eval.py <run> [pod] [--skip=a,b]
        [--per-mode=N] [--suffix=name]

--per-mode overrides the suite's episodes per mode (default 6; the
q_20260823T0700Z sampling amendment uses 12 so the walk section's
translating-episode count reaches n>=4 per pass). --suffix writes to
logs/ckpt_eval/<run>_m5<suffix> so a resample never clobbers the
original per-mode-6 read.

pod defaults to the run's own ledger pod; pass an idle pod explicitly
to run on free capacity instead of waiting for that pod to free up.
Code on the target pod is synced first (snapshot.sh --sync) so a pod
that never trained this run still has the eval harness.
"""
from __future__ import annotations

import json
import pathlib
import shlex
import subprocess
import sys

import pod_eval  # same directory: reuse kexec/push_local/find_checkpoint

HERE = pathlib.Path(__file__).resolve().parent
PROTO = HERE.parent.parent
LEDGER = HERE / "experiments.json"
POD_PROTO = "/workspace/prototype_sts3215"
TIMEOUT_S = 3600


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    run = sys.argv[1]
    pod = None
    skip = ""
    rest = sys.argv[2:]
    if rest and not rest[0].startswith("--"):
        pod = rest[0]
        rest = rest[1:]
    per_mode = "6"
    suffix = ""
    for a in rest:
        if a.startswith("--skip="):
            skip = a.split("=", 1)[1]
        elif a.startswith("--per-mode="):
            per_mode = a.split("=", 1)[1]
        elif a.startswith("--suffix="):
            suffix = a.split("=", 1)[1]

    entry = None
    fallback = None
    for e in json.loads(LEDGER.read_text()):
        if isinstance(e, dict) and e.get("run") == run and e.get("extra_args"):
            fallback = e
            if e.get("wandb_id") or e.get("checks", {}).get("pid"):
                entry = e
    entry = entry or fallback
    if entry is None:
        print(f"no ledger entry with extra_args for {run}")
        return 1
    pod = pod or entry["pod"]
    args = list(entry["extra_args"])

    def val(flag, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    task = val("--task", "joint_walk")
    ep = val("--episode-seconds", "15" if task == "joint_walk" else None)
    cfgs = [args[i + 1] for i, a in enumerate(args) if a == "--cfg-set"]

    print(f"syncing current code to {pod} ...")
    sync = subprocess.run(["bash", str(HERE / "snapshot.sh"), "--sync", pod],
                          capture_output=True, text=True, timeout=300)
    if sync.returncode != 0:
        print("WARNING: code sync failed, proceeding anyway:\n",
              sync.stdout[-2000:], sync.stderr[-2000:])

    ckpt = pod_eval.find_checkpoint(pod, run, task)
    if ckpt is None:
        print(f"no checkpoint for {run} on {pod} or controller -- abort")
        return 1

    run_us = run.replace("-", "_")
    out_rel = f"logs/ckpt_eval/{run_us}_m5{suffix}"
    logpath = f"/tmp/eval_{run}_m5{suffix}.log"
    cmd = (f"cd {POD_PROTO} && set -a && "
           f". rl_move/sim/wandb.env 2>/dev/null; set +a; "
           f"python3 -m rl_move.sim.eval_amp_m5 {shlex.quote(ckpt)}"
           f" --out-dir {out_rel} --per-mode {shlex.quote(per_mode)} --seed 0"
           + (f" --episode-seconds {ep}" if ep else "")
           + (f" --skip {shlex.quote(skip)}" if skip else "")
           + "".join(f" --cfg-set {shlex.quote(c)}" for c in cfgs))
    print(f"m5: starting on {pod} -> {logpath}\n+ {cmd}")
    with open(logpath, "w") as fh:
        p = subprocess.run(["kubectl", "exec", pod, "--", "bash", "-c", cmd],
                           stdout=fh, stderr=subprocess.STDOUT, timeout=TIMEOUT_S)
    (PROTO / out_rel).parent.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["kubectl", "cp", f"{pod}:{POD_PROTO}/{out_rel}",
                         str(PROTO / out_rel)],
                        capture_output=True, text=True, timeout=600)
    verdict_path = PROTO / out_rel / "m5_verdict.json"
    with open(logpath, "a") as fh:
        fh.write(f"\nSYNCED rc={p.returncode} artifacts -> {out_rel}\n")
    if verdict_path.is_file():
        v = json.loads(verdict_path.read_text())
        print(json.dumps({k: v["sections"][k].get("pass")
                          for k in v["sections"]} | {"m5_pass": v["m5_pass"]},
                         indent=1))
    else:
        print(f"m5: no verdict written (rc={p.returncode}); "
              f"cp stderr: {(cp.stderr or '')[-500:]}")
    print(f"m5 artifacts: {out_rel}")
    return 0 if verdict_path.is_file() else 1


if __name__ == "__main__":
    raise SystemExit(main())
