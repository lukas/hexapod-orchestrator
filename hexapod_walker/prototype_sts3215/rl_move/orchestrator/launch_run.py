#!/usr/bin/env python3
"""Deterministic launch gate for training runs on the CoreWeave pods.

Every training launch MUST go through this script (guardrails:
require_launcher). It exists because placement and launch verification
cannot be left to an LLM's memory: it reads real pod CPU limits live,
refuses placements that would starve runs, blocks duplicates, writes a
two-phase INTENT -> RUNNING entry to the experiment ledger, and only
reports success after mechanically verifying the run is alive and
advancing (process + log growth + W&B).

Usage:
  launch_run.py status
  launch_run.py launch --pod POD --run NAME --steps N \
      --hypothesis "..." --gate "..." [--parent CKPT] \
      [--smoke] [--allow-slow] [--dry-run] -- <extra train_ppo_sim.py args>

Exit code 0 = launched and verified (or dry-run passed). Anything else =
NOT launched; never record the run as running if this script failed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
GUARDRAILS = HERE / "guardrails.yaml"
LEDGER = HERE / "experiments.json"
KUBECONFIG = str(Path.home() / ".kube" / "coreweave.yaml")
# Established launch pattern on the training pods: module invocation from
# the project root (NOT `python3 train_ppo_sim.py` from the sim dir).
WORKDIR = "/workspace/prototype_sts3215"
TRAIN_MODULE = "rl_move.sim.train_ppo_sim"
WANDB_PROJECT = "l2k2/hexapod-balance"

# One 48-env run wants ~50-60 cores. Assumed footprint per already-running
# trainer when computing free capacity, and minimum free cores required.
CORES_PER_RUN = 55
MIN_FREE_FULL = 40   # full experiment below this = refused (--allow-slow overrides)
MIN_FREE_SMOKE = 8
SMOKE_MAX_STEPS = 1_000_000


def sh(cmd: list[str], timeout: int = 60) -> str:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, check=True).stdout


def kexec(pod: str, script: str, timeout: int = 60) -> str:
    return sh(["kubectl", "--kubeconfig", KUBECONFIG, "exec", pod, "--",
               "bash", "-c", script], timeout=timeout)


def pod_cpu_limit(pod: str) -> int:
    out = sh(["kubectl", "--kubeconfig", KUBECONFIG, "get", "pod", pod,
              "-o", "jsonpath={.spec.containers[0].resources.limits.cpu}"])
    return int(out.strip().rstrip("m") or 0)


def pod_trainers(pod: str) -> list[str]:
    """Names (--run-name values) of main trainer processes on the pod.

    Matches only main trainers (`python* ... train_ppo_sim ...`); the
    forkserver/spawn workers have -c or empty cmdlines and are excluded,
    as is this scan's own bash wrapper.
    """
    script = (
        "for p in /proc/[0-9]*; do c=$(tr '\\0' ' ' < $p/cmdline "
        "2>/dev/null); case \"$c\" in python*train_ppo_sim*|"
        "*/python*train_ppo_sim*) case \"$c\" in *' -c '*) ;; *) "
        "echo \"$c\";; esac;; esac; done | sort -u"
    )
    names = []
    for line in kexec(pod, script).splitlines():
        toks = line.split()
        name = "unnamed"
        for i, t in enumerate(toks):
            if t == "--run-name" and i + 1 < len(toks):
                name = toks[i + 1]
        names.append(name)
    return names


def load_guardrails() -> dict:
    return yaml.safe_load(GUARDRAILS.read_text())


def load_ledger() -> list[dict]:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return []


def save_ledger(entries: list[dict]) -> None:
    LEDGER.write_text(json.dumps(entries, indent=2) + "\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def wandb_running_runs() -> dict[str, dict]:
    """name -> {id, state, global_step} for runs currently 'running'."""
    import wandb
    api = wandb.Api()
    out = {}
    for r in api.runs(WANDB_PROJECT, order="-created_at")[:25]:
        if r.state == "running":
            step = r.summary.get("global_step") or r.summary.get("_step")
            out[r.name] = {"id": r.id, "state": r.state, "global_step": step}
    return out


def wandb_name_exists(name: str) -> bool:
    import wandb
    api = wandb.Api()
    return any(True for _ in api.runs(WANDB_PROJECT, {"display_name": name}))


def cmd_status(g: dict) -> int:
    running = {}
    try:
        running = wandb_running_runs()
    except Exception as e:  # W&B down should not hide pod state
        print(f"(W&B query failed: {e})")
    print(f"{'POD':22s} {'CPU':>4s} {'FREE':>5s}  TRAINERS (wandb global_step)")
    for pod in g["compute"]["pods"]:
        try:
            limit = pod_cpu_limit(pod)
            trainers = pod_trainers(pod)
        except subprocess.CalledProcessError as e:
            print(f"{pod:22s}  unreachable: {e}")
            continue
        free = limit - CORES_PER_RUN * len(trainers)
        desc = ", ".join(
            f"{t}@{running.get(t, {}).get('global_step', '?')}"
            for t in trainers) or "-"
        print(f"{pod:22s} {limit:4d} {max(free, 0):5d}  {desc}")
    return 0


def refuse(entry: dict, reason: str) -> int:
    print(f"REFUSED: {reason}")
    entry["status"] = "REFUSED"
    entry["refused_reason"] = reason
    led = load_ledger()
    led.append(entry)
    save_ledger(led)
    return 1


def cmd_launch(g: dict, a: argparse.Namespace, extra: list[str]) -> int:
    comp = g["compute"]
    entry = {
        "run": a.run, "pod": a.pod, "steps": a.steps, "smoke": a.smoke,
        "hypothesis": a.hypothesis, "gate": a.gate, "parent": a.parent,
        "extra_args": extra, "created": now(), "status": "INTENT",
        "checks": {},
    }
    checks = entry["checks"]

    # --- static checks -----------------------------------------------------
    if a.pod not in comp["pods"]:
        return refuse(entry, f"pod {a.pod} not in guardrails pod list")
    if a.smoke:
        if a.run.startswith("cw-"):
            return refuse(entry, "smoke runs must NOT use the cw- prefix "
                                 "(the watcher treats cw- as experiments)")
        if a.steps > SMOKE_MAX_STEPS:
            return refuse(entry, f"smoke capped at {SMOKE_MAX_STEPS} steps")
    else:
        if not a.run.startswith("cw-"):
            return refuse(entry, "experiments must use the cw- prefix")
        if a.steps > comp["max_steps_per_run"]:
            return refuse(entry, f"steps {a.steps} > max_steps_per_run "
                                 f"{comp['max_steps_per_run']}")
        if not a.hypothesis or not a.gate:
            return refuse(entry, "experiments require --hypothesis and "
                                 "--gate (guardrails)")
    for flag in ("--run-name", "--steps"):
        if flag in extra:
            return refuse(entry, f"{flag} belongs to the launcher, not the "
                                 "passthrough args")
    for flag, key in (("--eval-every", "min_eval_every"),
                      ("--video-every", "min_video_every")):
        if flag in extra:
            v = int(extra[extra.index(flag) + 1])
            if v < comp[key]:
                return refuse(entry, f"{flag} {v} < guardrails {key} "
                                     f"{comp[key]}")
    if "--n-envs" not in extra:
        extra = [*extra, "--n-envs", str(comp["n_envs"])]
        entry["extra_args"] = extra

    # --- live capacity checks (never trust remembered facts) ---------------
    limit = pod_cpu_limit(a.pod)
    trainers = pod_trainers(a.pod)
    free = limit - CORES_PER_RUN * len(trainers)
    checks["cpu_limit"] = limit
    checks["existing_trainers"] = trainers
    checks["free_cores_estimate"] = free
    need = MIN_FREE_SMOKE if a.smoke else MIN_FREE_FULL
    if free < need and not a.allow_slow:
        return refuse(entry, f"{a.pod} has ~{free} free cores "
                             f"(limit {limit}, {len(trainers)} trainer(s) "
                             f"x ~{CORES_PER_RUN}); need >= {need}. "
                             "Pick another pod or pass --allow-slow and "
                             "record why.")
    if free < need:
        checks["allow_slow_override"] = True

    # --- duplicate + concurrency checks -------------------------------------
    for pod in comp["pods"]:
        try:
            if a.run in pod_trainers(pod):
                return refuse(entry, f"a process for {a.run} already exists "
                                     f"on {pod}")
        except subprocess.CalledProcessError:
            pass
    if not a.smoke:
        if wandb_name_exists(a.run):
            return refuse(entry, f"W&B already has a run named {a.run} "
                                 "(names are append-only; pick a new one)")
        n_running = sum(1 for n in wandb_running_runs() if n.startswith("cw-"))
        if n_running >= comp["max_concurrent_runs"]:
            return refuse(entry, f"{n_running} experiments already running "
                                 f">= cap {comp['max_concurrent_runs']}")
        checks["running_experiments_before"] = n_running

    # --- build command ------------------------------------------------------
    log = f"/tmp/train_{a.run}.log"
    if "--subproc" not in extra:
        extra = [*extra, "--subproc"]
        entry["extra_args"] = extra
    train = (f"python -m {TRAIN_MODULE} "
             f"--run-name {a.run} --steps {a.steps} "
             + " ".join(extra))
    envp = "WANDB_MODE=disabled " if a.smoke else ""
    remote = (f"cd {WORKDIR} && {envp}nohup {train} > {log} 2>&1 & echo $!")
    entry["command"] = remote
    entry["log"] = log

    if a.dry_run:
        print("DRY-RUN: all checks passed. Would run on", a.pod)
        print(" ", remote)
        return 0

    led = load_ledger()
    led.append(entry)
    save_ledger(led)

    # --- launch + mechanical verification -----------------------------------
    pid = kexec(a.pod, remote).strip().splitlines()[-1]
    checks["pid"] = pid
    print(f"launched pid {pid}; verifying...")

    def fail(reason: str) -> int:
        print(f"VERIFICATION FAILED: {reason}")
        kexec(a.pod, f"kill {pid} 2>/dev/null; pkill -f 'run-name {a.run}' "
                     "2>/dev/null; true")
        entry["status"] = "FAILED"
        entry["failed_reason"] = reason
        save_ledger(led)
        return 1

    time.sleep(20)
    try:
        size1 = int(kexec(a.pod, f"stat -c %s {log}").strip())
        alive = kexec(a.pod, f"kill -0 {pid} 2>/dev/null && echo yes || "
                             "echo no").strip()
    except subprocess.CalledProcessError:
        return fail("log file missing after 20s")
    if alive != "yes":
        tail = kexec(a.pod, f"tail -c 800 {log}")
        return fail(f"process died; log tail:\n{tail}")
    time.sleep(40)
    size2 = int(kexec(a.pod, f"stat -c %s {log}").strip())
    if size2 <= size1:
        return fail(f"log not growing ({size1} -> {size2} bytes)")
    checks["log_growth_bytes"] = [size1, size2]

    if not a.smoke:
        deadline = time.time() + 240
        wb = None
        while time.time() < deadline:
            wb = wandb_running_runs().get(a.run)
            if wb:
                break
            time.sleep(20)
        if not wb:
            return fail("run never appeared as 'running' in W&B within 240s")
        checks["wandb_id"] = wb["id"]
        entry["wandb_id"] = wb["id"]
        s1 = wb.get("global_step") or 0
        time.sleep(90)
        s2 = (wandb_running_runs().get(a.run) or {}).get("global_step") or 0
        if s2 <= s1:
            return fail(f"W&B global_step not advancing ({s1} -> {s2})")
        checks["global_step_window"] = [s1, s2]
        checks["fps_estimate"] = round((s2 - s1) / 90.0, 1)
        print(f"fps estimate: {checks['fps_estimate']}")

    entry["status"] = "RUNNING"
    entry["verified"] = now()
    save_ledger(led)
    print(f"VERIFIED RUNNING: {a.run} on {a.pod} (ledger updated)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    lp = sub.add_parser("launch")
    lp.add_argument("--pod", required=True)
    lp.add_argument("--run", required=True)
    lp.add_argument("--steps", type=int, required=True)
    lp.add_argument("--hypothesis", default="")
    lp.add_argument("--gate", default="")
    lp.add_argument("--parent", default="")
    lp.add_argument("--smoke", action="store_true",
                    help="short validation run: W&B disabled, non-cw name")
    lp.add_argument("--allow-slow", action="store_true",
                    help="override the free-cores check (record why!)")
    lp.add_argument("--dry-run", action="store_true")
    argv = sys.argv[1:]
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    g = load_guardrails()
    if a.cmd == "status":
        return cmd_status(g)
    return cmd_launch(g, a, extra)


if __name__ == "__main__":
    sys.exit(main())
