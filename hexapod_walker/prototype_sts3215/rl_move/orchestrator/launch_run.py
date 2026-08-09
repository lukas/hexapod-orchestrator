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
import fcntl
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
GUARDRAILS = HERE / "guardrails.yaml"
LEDGER = HERE / "experiments.json"
LEDGER_LOCK = HERE / "experiments.json.lock"
# Concurrent decision cycles both run this launcher; the live capacity
# check -> process start window must not interleave or two cycles can
# double-book a pod/node that looked free to both.
LAUNCH_LOCK = HERE / "launch.lock"
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


def pod_node(pod: str) -> str:
    """Physical node hosting the pod (live — pods can be rescheduled)."""
    return sh(["kubectl", "--kubeconfig", KUBECONFIG, "get", "pod", pod,
               "-o", "jsonpath={.spec.nodeName}"]).strip()


def node_host_load(pod: str) -> dict:
    """Host-wide load and core count as seen from `pod`.

    /proc/loadavg and nproc are NOT cgroup-scoped: they see the whole
    ~128-core node, including OTHER tenants' pods (the operator runs
    other projects on these machines, e.g. mujoco-jax tests). The
    trainer-count checks elsewhere only see our own runs; this is the
    check that notices someone else actually using the machine.
    """
    out = kexec(pod, "cat /proc/loadavg && nproc").split()
    return {"load1": float(out[0]), "load5": float(out[1]),
            "cores": int(out[-1])}


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


@contextmanager
def file_lock(path: Path):
    path.touch(exist_ok=True)
    with path.open("r+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def ledger_lock():
    return file_lock(LEDGER_LOCK)


def upsert_entry(entry: dict) -> None:
    """Write `entry` into the ledger under the file lock, keyed on
    (run, created).

    The launch flow mutates its entry across minutes of verification
    sleeps while the watcher's async checkups write the same file from
    another process; an unlocked read-modify-write would lose whichever
    update finished first.
    """
    with ledger_lock():
        led = load_ledger()
        key = (entry.get("run"), entry.get("created"))
        for i, e in enumerate(led):
            if (e.get("run"), e.get("created")) == key:
                led[i] = entry
                break
        else:
            led.append(entry)
        save_ledger(led)


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
    print(f"{'POD':22s} {'NODE':8s} {'CPU':>4s} {'FREE':>5s}  "
          "TRAINERS (wandb global_step)")
    node_counts: dict[str, int] = {}
    node_loads: dict[str, dict | None] = {}
    for pod in g["compute"]["pods"]:
        try:
            limit = pod_cpu_limit(pod)
            trainers = pod_trainers(pod)
            node = pod_node(pod)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"{pod:22s}  unreachable (node may have spun down): {e}")
            continue
        node_counts[node] = node_counts.get(node, 0) + len(trainers)
        if node not in node_loads:
            try:
                node_loads[node] = node_host_load(pod)
            except Exception:
                node_loads[node] = None
        free = limit - CORES_PER_RUN * len(trainers)
        desc = ", ".join(
            f"{t}@{running.get(t, {}).get('global_step', '?')}"
            for t in trainers) or "-"
        print(f"{pod:22s} {node:8s} {limit:4d} {max(free, 0):5d}  {desc}")
    cap = g["compute"].get("max_heavy_per_node", 2)
    for node, n in sorted(node_counts.items()):
        hl = node_loads.get(node)
        load = (f"host load1 {hl['load1']:.1f} / {hl['cores']} cores "
                "(ALL tenants)" if hl else "host load unknown")
        print(f"node {node}: {n} trainer(s) / cap {cap} | {load}")
    return 0


def refuse(entry: dict, reason: str) -> int:
    print(f"REFUSED: {reason}")
    entry["status"] = "REFUSED"
    entry["refused_reason"] = reason
    upsert_entry(entry)
    return 1


def cmd_launch(g: dict, a: argparse.Namespace, extra: list[str]) -> int:
    """One launch at a time across all concurrent decision cycles.

    The lock deliberately covers the verification sleeps too — simple
    beats optimal here: a concurrent cycle's launch waits a few minutes
    at worst, while an unlocked check->start window could double-book a
    pod/node that looked free to both launchers.
    """
    with file_lock(LAUNCH_LOCK):
        return _launch_locked(g, a, extra)


def _launch_locked(g: dict, a: argparse.Namespace, extra: list[str]) -> int:
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
    # Machines spin up and down; an unreachable pod is a REFUSAL (pick
    # another pod / escalate), never a traceback.
    try:
        limit = pod_cpu_limit(a.pod)
        trainers = pod_trainers(a.pod)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return refuse(entry, f"{a.pod} unreachable during live checks "
                             f"(node may have spun down): {e}")
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

    # --- node-level co-tenancy check (08-08 evening: pod cgroup limits do
    # NOT protect against neighbor pods on the same ~128-core node; 8
    # "within-limits" experiments starved each other 4-5x and finished in
    # a clump). Applies to experiments only; smokes are short and small.
    if not a.smoke:
        try:
            node = pod_node(a.pod)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return refuse(entry, f"{a.pod} unreachable while resolving its "
                                 f"node (node may have spun down): {e}")
        node_trainers: list[str] = []
        for pod in comp["pods"]:
            try:
                if pod_node(pod) == node:
                    node_trainers.extend(pod_trainers(pod))
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
        cap = comp.get("max_heavy_per_node", 2)
        checks["node"] = node
        checks["node_trainers"] = node_trainers
        if len(node_trainers) >= cap and not a.allow_slow:
            return refuse(entry, f"node {node} already runs "
                                 f"{len(node_trainers)} trainer(s) "
                                 f"({', '.join(node_trainers)}); cap "
                                 f"{cap}/node. Pod limits lie — the node "
                                 "is the real budget. Pick a pod on the "
                                 "other node or wait.")

    # --- host-load check: the nodes are SHARED with other projects --------
    # The trainer counts above only see OUR runs; /proc/loadavg (host-wide,
    # not cgroup-scoped) sees every tenant — e.g. the operator's mujoco-jax
    # tests. Gate on what the machine is ACTUALLY doing right now.
    try:
        hl = node_host_load(a.pod)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            ValueError, IndexError) as e:
        return refuse(entry, f"cannot read host load via {a.pod} "
                             f"(node may have spun down): {e}")
    checks["host_load"] = hl
    host_free = hl["cores"] - hl["load1"]
    need_host = MIN_FREE_SMOKE if a.smoke else CORES_PER_RUN
    if host_free < need_host and not a.allow_slow:
        return refuse(entry, f"node hosting {a.pod} has only "
                             f"~{host_free:.0f} of {hl['cores']} cores "
                             f"actually free (load1 {hl['load1']:.1f}, "
                             f"load5 {hl['load5']:.1f} — includes OTHER "
                             f"projects' workloads, not just our runs); "
                             f"a {'smoke' if a.smoke else 'full run'} needs "
                             f"~{need_host}. Pick another pod, wait for the "
                             "node to free up, or pass --allow-slow and "
                             "record why.")

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
    # `< /dev/null` is load-bearing: without it the nohup'd trainer inherits
    # the kubectl-exec stream and `kubectl exec` hangs until the trainer
    # exits (observed cycle 10: launch verified fine but kexec timed out at
    # 60 s, leaving a healthy run stuck at INTENT).
    remote = (f"cd {WORKDIR} && {envp}nohup {train} > {log} 2>&1 "
              f"< /dev/null & echo $!")
    entry["command"] = remote
    entry["log"] = log

    if a.dry_run:
        print("DRY-RUN: all checks passed. Would run on", a.pod)
        print(" ", remote)
        return 0

    upsert_entry(entry)

    # --- launch + mechanical verification -----------------------------------
    try:
        pid = kexec(a.pod, remote).strip().splitlines()[-1]
    except subprocess.TimeoutExpired:
        # Known hang (cycle 10, twice, incl. with stdin redirected): the
        # kubectl exec stream can stay attached even though the remote
        # nohup command completed and the trainer started. Recover the
        # trainer pid via /proc scan and continue verification; only fail
        # if no process exists.
        print("kubectl exec timed out; recovering trainer pid via /proc scan")
        scan = ("for p in /proc/[0-9]*/cmdline; do "
                "c=$(tr '\\0' ' ' < \"$p\" 2>/dev/null); "
                'case "$c" in python*"--run-name ' + a.run + ' "*) '
                'basename "${p%/cmdline}";; esac; done')
        pids = kexec(a.pod, scan).split()
        if not pids:
            entry["status"] = "FAILED"
            entry["failed_reason"] = ("launch kexec timed out and no "
                                      "trainer process found on pod")
            upsert_entry(entry)
            print("VERIFICATION FAILED: kexec timeout and no trainer process")
            return 1
        pid = pids[0]
    checks["pid"] = pid
    print(f"launched pid {pid}; verifying...")

    def fail(reason: str) -> int:
        print(f"VERIFICATION FAILED: {reason}")
        kexec(a.pod, f"kill {pid} 2>/dev/null; pkill -f 'run-name {a.run}' "
                     "2>/dev/null; true")
        entry["status"] = "FAILED"
        entry["failed_reason"] = reason
        upsert_entry(entry)
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
    upsert_entry(entry)
    print(f"VERIFIED RUNNING: {a.run} on {a.pod} (ledger updated)")
    return 0


def cmd_checkup(g: dict, a: argparse.Namespace) -> int:
    """Post-launch health assessment (run by the WATCHER ~5 min after
    every verified launch; the agent acts on findings next cycle).
    Mechanical facts first; exit 0 HEALTHY, 2 SUSPECT, 1 DEAD.
    The agent decides keep / kill+retry / rebalance — this only reports.
    """
    entry = next((e for e in reversed(load_ledger())
                  if e.get("run") == a.run
                  and e.get("status") in ("RUNNING", "INTENT")), None)
    if entry is None:
        print(f"DEAD: no RUNNING/INTENT ledger entry for {a.run}")
        return 1
    pod, log = entry["pod"], entry["log"]
    created = entry.get("created")
    problems, facts = [], {"time": now()}

    def record(verdict: str, **extra: object) -> None:
        # Re-find the entry under the lock: 45+ s elapse while measuring
        # and the launch flow / other checkups may have written the ledger.
        with ledger_lock():
            led = load_ledger()
            e = next((x for x in reversed(led)
                      if x.get("run") == a.run
                      and x.get("created") == created), None)
            if e is None:
                led.append(entry)
                e = entry
            e.setdefault("checkups", []).append(
                {**facts, "verdict": verdict, **extra})
            save_ledger(led)

    trainers = pod_trainers(pod)
    facts["process_alive"] = a.run in trainers
    if not facts["process_alive"]:
        tail = kexec(pod, f"tail -c 600 {log} 2>/dev/null || true")
        record("DEAD", log_tail=tail[-600:])
        print(f"DEAD: no {a.run} trainer process on {pod}. Log tail:\n{tail}")
        return 1

    # Crashes inside workers often keep the parent alive; the traceback
    # in the log is the tell.
    tb = kexec(pod, f"tail -n 300 {log} | grep -c 'Traceback' || true")
    facts["tracebacks_in_tail"] = int(tb.strip() or 0)
    if facts["tracebacks_in_tail"]:
        problems.append(f"{facts['tracebacks_in_tail']} traceback(s) in "
                        "recent log — read the log before trusting this run")

    size1 = int(kexec(pod, f"stat -c %s {log}").strip())
    wb1 = wandb_running_runs().get(a.run) or {}
    s1 = wb1.get("global_step") or 0
    time.sleep(45)
    size2 = int(kexec(pod, f"stat -c %s {log}").strip())
    wb2 = wandb_running_runs().get(a.run) or {}
    s2 = wb2.get("global_step") or 0
    facts["log_growth_bytes"] = size2 - size1
    if size2 <= size1:
        problems.append("log stopped growing")
    if not entry.get("smoke"):
        if not wb2:
            problems.append("W&B no longer reports the run as running")
        elif s2 <= s1:
            problems.append(f"W&B global_step stalled at {s2}")
        else:
            fps = (s2 - s1) / 45.0
            facts["fps"] = round(fps, 1)
            # Expected floor by placement: solo on a 56-core pod ~1000+;
            # sharing or a 30-core pod runs slower but should beat 60.
            limit = pod_cpu_limit(pod)
            solo = len(trainers) == 1
            floor = 500.0 if (solo and limit >= 48) else 60.0
            facts["placement"] = (f"{'solo' if solo else f'{len(trainers)} runs'} "
                                  f"on {limit}-core pod")
            if fps < floor:
                problems.append(
                    f"fps {fps:.0f} below expected floor {floor:.0f} for "
                    f"{facts['placement']} — starved or misplaced; consider "
                    "rebalancing")

    verdict = "SUSPECT" if problems else "HEALTHY"
    record(verdict, problems=problems)
    print(f"{verdict}: {a.run} on {pod} "
          f"({facts.get('placement', 'smoke')}, fps={facts.get('fps', 'n/a')})")
    for p in problems:
        print(f"  - {p}")
    return 0 if verdict == "HEALTHY" else 2


def cmd_update(a: argparse.Namespace) -> int:
    """Locked field update on a ledger entry — the ONLY sanctioned way
    to edit experiments.json outside the launcher itself.

    Hand-editing the file (read whole file -> modify -> dump) clobbers
    concurrent writers: on 2026-08-09 a cycle's manual "reconstruction"
    of one entry silently erased another launch's entry that had landed
    in between (c1/lowent incident).
    """
    with ledger_lock():
        led = load_ledger()
        matches = [e for e in led if e.get("run") == a.run]
        if not matches:
            if not a.create:
                print(f"no ledger entry for {a.run} (use --create to add one)")
                return 1
            entry = {"run": a.run, "created": now(),
                     "note": "created via `update --create`"}
            led.append(entry)
            matches = [entry]
        entry = matches[-1]  # newest entry for this run name
        for kv in a.set or []:
            key, _, val = kv.partition("=")
            if not _:
                print(f"bad --set (need key=value): {kv}")
                return 1
            try:
                entry[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                entry[key] = val
        save_ledger(led)
    print(f"updated {a.run}: set {[kv.partition('=')[0] for kv in a.set or []]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    cp = sub.add_parser("checkup")
    cp.add_argument("--run", required=True)
    up = sub.add_parser("update", help="locked edit of a ledger entry")
    up.add_argument("--run", required=True)
    up.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="field to set; VALUE parsed as JSON when possible")
    up.add_argument("--create", action="store_true",
                    help="create a minimal entry if none exists (backfill)")
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
    if a.cmd == "checkup":
        return cmd_checkup(g, a)
    if a.cmd == "update":
        return cmd_update(a)
    return cmd_launch(g, a, extra)


if __name__ == "__main__":
    sys.exit(main())
