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
import os
import pathlib
import shlex
import subprocess
import sys

# Same convention as launch_run.py / ops.sh: the controller's default
# in-cluster serviceaccount cannot exec pods.
os.environ.setdefault(
    "KUBECONFIG", str(pathlib.Path.home() / ".kube" / "coreweave.yaml"))

HERE = pathlib.Path(__file__).resolve().parent
PROTO = HERE.parent.parent
LEDGER = HERE / "experiments.json"
POD_PROTO = "/workspace/prototype_sts3215"
PASS_TIMEOUT_S = 2700

# WISHLIST 8e (landed 08-13): every finished stance/walk candidate also
# gets the interactive SESSION gate (rl_move.sim.eval_session — the
# play.py protocol: belly -> auto stand -> drive -> sit -> stand ->
# hold) in the pre-staged evals. Seat rule: stance candidates pair with
# the DEPLOYED walk, walk candidates with the DEPLOYED stance (source
# of truth: linux_control/rl_policy.py — update BOTH on promotion). The
# session result is INFORMATIONAL in the prestage: printed + logged +
# artifacts synced, but never folded into pod_eval's exit code —
# exotic-obs candidates (phase-clock, history stacks, ...) are EXPECTED
# to be incompatible with the deployed session env and exit loudly.
DEPLOYED_STANCE = "ppo_goal_cw_stand_holdbc1_hard1.zip"
DEPLOYED_WALK = "ppo_goal_cw_dep_vref1_r1.zip"
STANCE_MODES = ("rise", "hold", "lower")
SESSION_TIMEOUT_S = 900


def kexec(pod: str, cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "exec", pod, "--", "bash", "-c", cmd],
                          capture_output=True, text=True, timeout=timeout)


def push_local(pod: str, name: str) -> str | None:
    """Ensure policies/<name> exists on the pod; push the controller's
    copy when the pod lost it (pods are recreated on infra fixes and
    /workspace checkpoints go with them). ~2 MB, seconds."""
    p = f"{POD_PROTO}/rl_move/sim/policies/{name}"
    if kexec(pod, f"test -s {shlex.quote(p)}").returncode == 0:
        return p
    local = PROTO / "rl_move/sim/policies" / name
    if local.is_file() and local.stat().st_size:
        kexec(pod, f"mkdir -p {POD_PROTO}/rl_move/sim/policies")
        subprocess.run(["kubectl", "cp", str(local), f"{pod}:{p}"],
                       capture_output=True, text=True, timeout=300)
        if kexec(pod, f"test -s {shlex.quote(p)}").returncode == 0:
            print(f"(pushed controller copy of {name} to {pod})")
            return p
    return None


def find_checkpoint(pod: str, run: str, task: str) -> str | None:
    names = ["ppo_goal_" + run.replace("-", "_") + ".zip"]
    names += [f"ppo_mjx_{t}_{run}.zip"
              for t in (task, "joint_walk", "joint_goal", "goal")]
    names = list(dict.fromkeys(names))
    for n in names:
        p = f"{POD_PROTO}/rl_move/sim/policies/{n}"
        if kexec(pod, f"test -s {shlex.quote(p)}").returncode == 0:
            return p
    for n in names:
        p = push_local(pod, n)
        if p is not None:
            return p
    return None


def session_side(mix_modes: list[str], task: str) -> str | None:
    """Which seat the candidate takes in the interactive session gate.

    Returns "stance", "walk", or None (no seat: track/quad/etc-only
    runs, or tasks outside the deployment protocol). Walk wins when a
    run trains both families: a walk-training policy is (by the
    deployment contract) walk-env-width, and eval_session requires the
    stance seat's obs to be a strict PREFIX of the walk env obs — so a
    both-family checkpoint can only take the walk seat, partnered with
    the deployed stance.
    """
    has_stance = any(m in STANCE_MODES for m in mix_modes)
    has_walk = ("walk" in mix_modes
                or (not mix_modes and task == "joint_walk"))
    if has_walk:
        return "walk"
    if has_stance:
        return "stance"
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    run, suffix = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    # 08-13 fix: a run name can appear MULTIPLE times in the ledger (a
    # REFUSED re-launch/respec attempt after the real run finished, e.g.
    # "GPU pods host exactly one run") and a plain last-match-wins scan
    # picks that REFUSED stub (thin extra_args, no --cfg-set) instead of
    # the entry that actually trained — silently evaluating with the
    # wrong reward/goal cfg (obs-width mismatches, voided verdicts).
    # Prefer an entry that actually ran (has a wandb_id/pid), falling
    # back to last-match only if none did.
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
    pod = entry["pod"]
    args = list(entry["extra_args"])

    def val(flag: str, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    task = val("--task", "joint_walk")
    ep = val("--episode-seconds", "15" if task == "joint_walk" else None)
    dr = float(val("--dr-scale", "0") or 0)
    cfgs = [args[i + 1] for i, a in enumerate(args) if a == "--cfg-set"]
    # 08-11 (cw-uni-flag-a1-r1/h2 triage): a joint_walk task with an
    # explicit --goal-mix (e.g. "hold=0.2,rise=0.4,lower=0.4") may never
    # train walk at all — hardcoding "--modes walk" silently evals a mode
    # the run never learned and reports nothing about its actual gate.
    # Derive the eval mode list from --goal-mix's keys when present;
    # only fall back to the walk-only default for plain walk tasks.
    goal_mix = val("--goal-mix")
    mix_modes: list[str] = []
    if goal_mix:
        for kv in goal_mix.split(","):
            if not kv.strip():
                continue
            k, _, v = kv.partition("=")
            if float(v or 0) > 0:
                mix_modes.append(k.strip())
        modes = "--modes " + " ".join(mix_modes) if mix_modes else "--modes walk"
    elif task == "joint_walk":
        modes = "--modes walk"
    else:
        modes = ""

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

    # SESSION gate (WISHLIST 8e — see the constants' comment block).
    session = None  # (side, partner_name, out_rel, logpath, proc, fh)
    side = session_side(mix_modes, task)
    if side:
        partner_name = DEPLOYED_WALK if side == "stance" else DEPLOYED_STANCE
        s_out_rel = f"logs/ckpt_eval/{run_us}_session{suffix}"
        # Key on report.json, not the dir: a failed/incompatible session
        # leaves an empty dir behind and must stay retryable.
        if (PROTO / s_out_rel / "report.json").is_file():
            print(f"session: {s_out_rel} already on controller — skipping")
        else:
            partner = push_local(pod, partner_name)
            if partner is None:
                print(f"session: partner {partner_name} unavailable on "
                      f"{pod}/controller — skipped")
            else:
                st, wk = ((ckpt, partner) if side == "stance"
                          else (partner, ckpt))
                s_log = f"/tmp/eval_{run}_session.log"
                s_cmd = (f"cd {POD_PROTO} && mkdir -p {s_out_rel} && "
                         f"python3 -m rl_move.sim.eval_session"
                         f" --stance {shlex.quote(st)}"
                         f" --walk {shlex.quote(wk)}"
                         f" --out {s_out_rel}/report.json"
                         f" --strips {s_out_rel}")
                s_fh = open(s_log, "w")
                s_p = subprocess.Popen(
                    ["kubectl", "exec", pod, "--", "bash", "-c", s_cmd],
                    stdout=s_fh, stderr=subprocess.STDOUT, text=True)
                print(f"session: started on {pod} ({side} seat vs "
                      f"{partner_name}) -> {s_log}")
                session = (side, partner_name, s_out_rel, s_log, s_p, s_fh)

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

    if session:
        side, partner_name, out_rel, logpath, p, fh = session
        try:
            rc = p.wait(timeout=SESSION_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p.kill()
            rc = -1
        if rc in (0, 1):
            # eval_session writes report.json on both PASS (0) and
            # hard-gate FAIL (1); rc 1 with NO report = the loud
            # obs-contract SystemExit (incompatible candidate).
            (PROTO / out_rel).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["kubectl", "cp", f"{pod}:{POD_PROTO}/{out_rel}",
                 str(PROTO / out_rel)],
                capture_output=True, text=True, timeout=600)
        has_rep = (PROTO / out_rel / "report.json").is_file()
        if rc == 0 and has_rep:
            status = "HARD GATES PASS"
        elif rc == 1 and has_rep:
            status = "HARD GATES FAIL"
        elif rc == 1:
            status = ("INCOMPATIBLE (no report — obs contract mismatch "
                      "with the deployed session env; expected for "
                      "exotic-obs candidates)")
        else:
            status = f"ERROR rc={rc}"
        line = (f"SESSION ({side} seat vs {partner_name}): {status} "
                f"artifacts -> {out_rel}")
        fh.write(f"\nSYNCED {line}\n")
        fh.close()
        print(line)
        # Informational only: never folds into pod_eval's exit code.
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
