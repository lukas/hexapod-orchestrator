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
import re
import shlex
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
# Mechanical experiment queue (operator, 2026-08-09: "a free slot plus a
# non-empty backlog is a bug"). Items are full launch specs; `drain`
# pushes them onto free GPU pods, self-repairing code-sync and missing
# checkpoints instead of refusing. The watcher calls drain continuously.
BACKLOG = HERE / "backlog.json"
BACKLOG_LOCK = HERE / "backlog.json.lock"
BACKLOG_FAILED = HERE / "backlog_failed.json"
KUBECONFIG = str(Path.home() / ".kube" / "coreweave.yaml")
# Established launch pattern on the training pods: module invocation from
# the project root (NOT `python3 train_ppo_sim.py` from the sim dir).
WORKDIR = "/workspace/prototype_sts3215"
TRAIN_MODULE = "rl_move.sim.train_ppo_sim"      # CPU sweep pods (legacy)
TRAIN_MODULE_GPU = "rl_move.sim.train_ppo_mjx"  # GPU-MJX pods (default)
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

    Matches main trainers of BOTH stacks (`train_ppo_sim` on CPU pods,
    `train_ppo_mjx` on GPU pods); the forkserver/spawn workers have -c
    or empty cmdlines and are excluded, as is this scan's own bash
    wrapper. Anchored on the literal `-m rl_move.sim.train_ppo_`
    module invocation (2026-08-09 c37: the loose `*train_ppo_*` glob
    matched cycle-agent processes whose cmdline embeds the standing
    prompt — 371 phantom trainers on the controller node would have
    refused every smoke launch there).
    """
    script = (
        "for p in /proc/[0-9]*; do c=$(tr '\\0' ' ' < $p/cmdline "
        "2>/dev/null); case \"$c\" in python*' -m rl_move.sim.train_ppo_'*|"
        "*/python*' -m rl_move.sim.train_ppo_'*) case \"$c\" in *' -c '*) ;; *) "
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
    try:
        render_run_md(entry)
    except OSError:
        pass  # docs mirror is best-effort; the ledger already has the facts


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
    gpu_pods = g["compute"].get("gpu_pods", [])
    for pod in g["compute"]["pods"] + gpu_pods:
        is_gpu = pod in gpu_pods
        try:
            limit = pod_cpu_limit(pod)
            trainers = pod_trainers(pod)
            node = pod_node(pod)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"{pod:22s}  unreachable (node may have spun down): {e}")
            continue
        # GPU trainers don't count against CPU-node co-tenancy caps.
        if not is_gpu:
            node_counts[node] = node_counts.get(node, 0) + len(trainers)
        if node not in node_loads:
            try:
                node_loads[node] = node_host_load(pod)
            except Exception:
                node_loads[node] = None
        if is_gpu:
            free_s = "free" if not trainers else "BUSY"
        else:
            free_s = str(max(limit - CORES_PER_RUN * len(trainers), 0))
        desc = ", ".join(
            f"{t}@{running.get(t, {}).get('global_step', '?')}"
            for t in trainers) or "-"
        tag = " [GPU]" if is_gpu else ""
        print(f"{pod:22s} {node:8s} {limit:4d} {free_s:>5s}  {desc}{tag}")
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
    """Checks + process start are serialized; verification is NOT.

    The lock covers the live-capacity-check -> trainer-start window (an
    unlocked window could double-book a pod that looked free to two
    launchers). It used to cover the multi-minute verification sleeps
    too, which serialized every launch into ~5 min of wall clock each
    (operator, 2026-08-09: 3 repaired launches took 12+ min to appear).
    Once the trainer process exists on the pod, pod_trainers() sees it,
    so concurrent capacity checks are already correct — verify outside
    the lock.
    """
    with file_lock(LAUNCH_LOCK):
        res = _launch_locked(g, a, extra)
    if isinstance(res, int):
        return res
    return _verify_started(g, a, res)


def _launch_locked(g: dict, a: argparse.Namespace,
                   extra: list[str]) -> int | dict:
    """All gates + trainer start, under LAUNCH_LOCK.

    Returns an exit code on refusal/dry-run/start-failure, or a context
    dict for _verify_started() once the trainer process exists."""
    comp = g["compute"]
    gpu_pods = comp.get("gpu_pods", [])
    gpu = comp.get("gpu", {})
    is_gpu = a.pod in gpu_pods
    entry = {
        "run": a.run, "pod": a.pod, "steps": a.steps, "smoke": a.smoke,
        "hypothesis": a.hypothesis, "gate": a.gate, "parent": a.parent,
        "extra_args": extra, "created": now(), "status": "INTENT",
        "checks": {}, "stack": "gpu-mjx" if is_gpu else "cpu",
    }
    checks = entry["checks"]

    # --- static checks -----------------------------------------------------
    if a.pod not in comp["pods"] and not is_gpu:
        return refuse(entry, f"pod {a.pod} not in guardrails pod list")
    # STACK SWITCH-OVER (operator, 2026-08-09): every training run
    # (anything with W&B, i.e. non-smoke) runs on the GPU-MJX stack.
    # CPU pods keep serving the controller, eval harness work, and
    # W&B-disabled smokes only. Enforced here mechanically so a stale
    # prompt/ledger entry (e.g. watcher auto-continue of an old CPU
    # segment) cannot quietly land a CPU run.
    if not is_gpu and not a.smoke:
        return refuse(entry, "CPU training launches are retired "
                             "(2026-08-09 GPU-MJX switch-over): launch on "
                             "a gpu_pods entry instead; CPU pods take "
                             "only --smoke runs.")
    if a.smoke:
        if a.run.startswith("cw-"):
            return refuse(entry, "smoke runs must NOT use the cw- prefix "
                                 "(the watcher treats cw- as experiments)")
        if a.steps > SMOKE_MAX_STEPS:
            return refuse(entry, f"smoke capped at {SMOKE_MAX_STEPS} steps")
    else:
        if not a.run.startswith("cw-"):
            return refuse(entry, "experiments must use the cw- prefix")
        max_steps = (gpu.get("max_steps_per_run", comp["max_steps_per_run"])
                     if is_gpu else comp["max_steps_per_run"])
        if a.steps > max_steps:
            return refuse(entry, f"steps {a.steps} > max_steps_per_run "
                                 f"{max_steps}")
        if not a.hypothesis or not a.gate:
            return refuse(entry, "experiments require --hypothesis and "
                                 "--gate (guardrails)")
    for flag in ("--run-name", "--steps"):
        if flag in extra:
            return refuse(entry, f"{flag} belongs to the launcher, not the "
                                 "passthrough args")
    mins = gpu if is_gpu else comp
    for flag, key in (("--eval-every", "min_eval_every"),
                      ("--video-every", "min_video_every")):
        if flag in extra:
            v = int(extra[extra.index(flag) + 1])
            if v < mins[key]:
                return refuse(entry, f"{flag} {v} < guardrails {key} "
                                     f"{mins[key]}")
    if "--n-envs" not in extra:
        n_envs = gpu["n_envs"] if is_gpu else comp["n_envs"]
        extra = [*extra, "--n-envs", str(n_envs)]
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
    checks["cpu_limit"] = limit
    checks["existing_trainers"] = trainers
    if is_gpu:
        # GPU pods: the H200 is the unit — exactly ONE trainer per pod,
        # no sharing, no core math. cgroup requests partition the node,
        # so a busy neighbor GPU pod is expected, not contention.
        if trainers:
            return refuse(entry, f"{a.pod} already runs "
                                 f"{', '.join(trainers)} — GPU pods host "
                                 "exactly one run; pick a free GPU pod.")
        try:
            gpus = kexec(a.pod, "nvidia-smi -L").strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return refuse(entry, f"{a.pod}: nvidia-smi failed ({e}) — GPU "
                                 "not visible; pod may need recreation")
        checks["gpu"] = gpus.splitlines()[0]
    else:
        free = limit - CORES_PER_RUN * len(trainers)
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
    # a clump). Applies to CPU experiments only; smokes are short and
    # small, and GPU pods partition their node by cgroup REQUESTS (all
    # four busy at once is the design point, not starvation).
    if not a.smoke and not is_gpu:
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
    # GPU pods skip this: their node legitimately runs near 104/128 cores
    # when all four are training, and cgroup requests reserve their share.
    if not is_gpu:
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
                                 f"a {'smoke' if a.smoke else 'full run'} "
                                 f"needs ~{need_host}. Pick another pod, "
                                 "wait for the node to free up, or pass "
                                 "--allow-slow and record why.")

    # --- duplicate + concurrency checks -------------------------------------
    for pod in comp["pods"] + gpu_pods:
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

    # --- code-version gate (2026-08-09) -------------------------------------
    # Pods have no git; the only record of what code a pod runs is the
    # .code_sha marker snapshot.sh --sync writes. cw-walk-lowent-dr03
    # trained 4M steps on long5m with PRE-AUDIT code (its cfg-set
    # step-event reward package silently ignored, no target_kl) because
    # nothing verified the sync. Missing marker or mismatch vs local
    # HEAD = refuse: run snapshot.sh <run> then snapshot.sh --sync <pod>.
    try:
        local_sha = sh(["git", "-C", str(HERE), "rev-parse", "HEAD"]).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return refuse(entry, f"cannot resolve local git HEAD: {e}")
    try:
        pod_sha = kexec(a.pod, "cat /workspace/prototype_sts3215/.code_sha "
                               "2>/dev/null || true").strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return refuse(entry, f"{a.pod} unreachable reading .code_sha: {e}")
    checks["code_sha_local"] = local_sha
    checks["code_sha_pod"] = pod_sha or None
    if pod_sha != local_sha:
        return refuse(entry, f"{a.pod} code marker "
                             f"{pod_sha or 'MISSING'} != local HEAD "
                             f"{local_sha}. Sync first: snapshot.sh "
                             f"--sync {a.pod} (and snapshot/commit before "
                             "that if the tree is dirty).")

    # --- init-from checkpoint preflight (2026-08-09) -------------------------
    # snapshot.sh --sync deliberately EXCLUDES rl_move/sim/policies, so a
    # warm-start checkpoint only exists on pods that already trained the
    # lineage. cw-walk-longdist crashed at startup on a fresh pod because
    # nothing checked this. Refuse early with the fix spelled out.
    if "--init-from" in extra:
        ckpt = extra[extra.index("--init-from") + 1]
        pod_ckpt = f"/workspace/prototype_sts3215/{ckpt}"
        try:
            found = kexec(a.pod, f"test -f '{pod_ckpt}' && echo OK || true").strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return refuse(entry, f"{a.pod} unreachable checking init-from: {e}")
        checks["init_from_on_pod"] = found == "OK"
        if found != "OK":
            return refuse(entry, f"init-from checkpoint missing on {a.pod}: "
                                 f"{pod_ckpt}. Push it first: "
                                 f"ops.sh pushckpt {a.pod} {ckpt}")

    # --- W&B credentials preflight (2026-08-09) -------------------------------
    # rl_move/sim/wandb.env is a gitignored secret, so code sync never
    # carries it to a fresh pod. Without it the trainer prints "no API key
    # — logging skipped" and trains BLIND: 4 runs burned GPU-hours
    # invisible to W&B before anyone noticed. Refuse up front.
    if not a.smoke:
        wenv = f"{WORKDIR}/rl_move/sim/wandb.env"
        try:
            has_env = kexec(a.pod, f"test -s '{wenv}' && echo OK || true").strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return refuse(entry, f"{a.pod} unreachable checking wandb.env: {e}")
        checks["wandb_env_on_pod"] = has_env == "OK"
        if has_env != "OK":
            return refuse(entry, f"wandb.env missing on {a.pod} — the run "
                                 "would train blind (no W&B). Push it: "
                                 f"kubectl cp rl_move/sim/wandb.env "
                                 f"{a.pod}:{wenv}")

    # --- build command ------------------------------------------------------
    log = f"/tmp/train_{a.run}.log"
    if is_gpu:
        # train_ppo_mjx owns its parallelism (sharded host workers), and
        # --subproc does not exist there.
        if "--impl" not in extra:
            extra = [*extra, "--impl", str(gpu.get("impl", "warp"))]
        if "--host-workers" not in extra:
            extra = [*extra, "--host-workers",
                     str(gpu.get("host_workers", 24))]
        entry["extra_args"] = extra
    elif "--subproc" not in extra:
        extra = [*extra, "--subproc"]
        entry["extra_args"] = extra
    # Operator directive 08-09: a run's W&B notes must LEAD with a human
    # paragraph — what is being tested and why — with the trainer's
    # auto-generated env spec below it. If the caller didn't pass --notes,
    # compose that paragraph from the hypothesis/gate/parent this launcher
    # already requires (cw-walk-step0-lowent shipped spec-only notes).
    if "--notes" not in extra and (a.hypothesis or a.gate):
        human = a.hypothesis or ""
        if a.parent:
            human += f" Parent: {a.parent}."
        if a.gate:
            human += f" Gate: {a.gate}"
        extra = [*extra, "--notes", human.strip()]
        entry["extra_args"] = extra
    module = TRAIN_MODULE_GPU if is_gpu else TRAIN_MODULE
    # shlex.quote every passthrough token: notes/cfg values with shell
    # metacharacters (parens, semicolons) used to splice raw into the
    # remote bash -c and kill the launch (2026-08-09: cw-walk-parkstart
    # and cw-stance-bellyrest each burned a FAILED attempt on this).
    train = (f"python -m {module} "
             f"--run-name {a.run} --steps {a.steps} "
             + " ".join(shlex.quote(t) for t in extra))
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
    return {"entry": entry, "checks": checks, "pid": pid,
            "log": log, "is_gpu": is_gpu}


def _verify_started(g: dict, a: argparse.Namespace, ctx: dict) -> int:
    """Mechanical liveness verification of a just-started trainer.

    Runs OUTSIDE the launch lock: the process already exists on the pod,
    so concurrent capacity checks count it. Parallel drains/launches can
    verify simultaneously instead of queueing ~5 min each."""
    entry, checks = ctx["entry"], ctx["checks"]
    pid, log, is_gpu = ctx["pid"], ctx["log"], ctx["is_gpu"]

    def fail(reason: str) -> int:
        print(f"VERIFICATION FAILED: {reason}")
        # pkill pattern MUST be anchored to the python trainer: an
        # unanchored 'run-name X' also matches the bash -c wrapper running
        # this very cleanup, so pkill killed its own shell (exit 143) and
        # the "failure" bubbled up as a crashed launch attempt (2026-08-09:
        # cw-walk-highgait burned 2 backlog attempts on cleanup suicide).
        try:
            kexec(a.pod, f"kill {pid} 2>/dev/null; "
                         f"pkill -f '^python -m rl_move[.]sim[.]train_ppo.*"
                         f"--run-name {a.run} ' 2>/dev/null; true")
        except subprocess.CalledProcessError:
            pass  # cleanup best-effort; the verdict below is what matters
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
    if size2 <= size1 and not is_gpu:
        # GPU runs sit quiet for ~2-3 min while JAX/Warp compiles the
        # batched tick; a static log with a live process is normal there.
        # The W&B step-advance check below is the real GPU liveness gate.
        return fail(f"log not growing ({size1} -> {size2} bytes)")
    checks["log_growth_bytes"] = [size1, size2]

    if not a.smoke:
        deadline = time.time() + (480 if is_gpu else 240)
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
    # Reconstructed entries (operator raw launches) may lack "log";
    # fall back to the guardrails pattern instead of crashing the
    # watcher (KeyError 'log' on cw-walk-step0-c2, 2026-08-09).
    pod = entry["pod"]
    log = entry.get("log") or f"/tmp/train_{a.run}.log"
    created = entry.get("created")
    problems, facts = [], {"time": now()}

    def record(verdict: str, _status: str | None = None,
               **extra: object) -> None:
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
            if _status:
                e["status"] = _status
            save_ledger(led)

    trainers = pod_trainers(pod)
    facts["process_alive"] = a.run in trainers
    if not facts["process_alive"]:
        tail = kexec(pod, f"tail -c 600 {log} 2>/dev/null || true")
        # A missing process is NOT necessarily a death: short runs and
        # canary auto-stops complete before/within the checkup window.
        # The trainer's completion marker is "[train] N steps in Ts → ckpt"
        # (cw-walk-step0-c1 false-positive DEAD, 2026-08-09: run had
        # finished, saved its checkpoint, and been verdicted already).
        if re.search(r"\[train\] \d+ steps in .*→", tail):
            record("FINISHED_BEFORE_CHECKUP", _status="FINISHED",
                   log_tail=tail[-600:])
            print(f"FINISHED: {a.run} completed before checkup on {pod} "
                  f"(completion marker in log; status set FINISHED). "
                  f"Log tail:\n{tail}")
            return 0
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
            # Expected floor by placement: GPU-MJX pods run ~19-20k fps
            # solo; solo on a 56-core CPU pod ~1000+; sharing or a
            # 30-core pod runs slower but should beat 60.
            limit = pod_cpu_limit(pod)
            solo = len(trainers) == 1
            if pod in g["compute"].get("gpu_pods", []):
                floor = 5000.0
                facts["placement"] = "solo on GPU-MJX pod"
            else:
                floor = 500.0 if (solo and limit >= 48) else 60.0
                facts["placement"] = (
                    f"{'solo' if solo else f'{len(trainers)} runs'} "
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


def _read_backlog() -> list[dict]:
    if BACKLOG.exists():
        return json.loads(BACKLOG.read_text())
    return []


def _write_backlog(items: list[dict]) -> None:
    BACKLOG.write_text(json.dumps(items, indent=2) + "\n")


def cmd_backlog(a: argparse.Namespace, extra: list[str]) -> int:
    """Append/list mechanical launch specs (operator queue)."""
    if a.action == "list":
        for i, it in enumerate(_read_backlog()):
            print(f"{i}: {it['run']} steps={it['steps']} "
                  f"attempts={it.get('attempts', 0)}")
        return 0
    if not (a.run and a.steps and a.hypothesis and a.gate):
        print("backlog add needs --run --steps --hypothesis --gate -- <args>")
        return 1
    with file_lock(BACKLOG_LOCK):
        items = _read_backlog()
        if any(it["run"] == a.run for it in items):
            print(f"{a.run} already queued")
            return 1
        # Near-duplicate tripwire: concurrent cycles queued velsag AND
        # velsag30 minutes apart (08-09) and only noticed post-launch.
        # Same alpha-stem (digits/suffix stripped) as a queued or
        # RUNNING run = probably the same axis; WARN, don't block.
        stem = re.sub(r"[-_]?\d+[a-z]?$", "", a.run)
        near = {it["run"] for it in items
                if re.sub(r"[-_]?\d+[a-z]?$", "", it["run"]) == stem}
        near |= {e.get("run") for e in load_ledger()
                 if isinstance(e, dict) and e.get("status") == "RUNNING"
                 and re.sub(r"[-_]?\d+[a-z]?$", "", e.get("run", "")) == stem}
        near.discard(a.run)
        if near:
            print(f"WARNING: same-axis run(s) already queued/RUNNING: "
                  f"{sorted(near)} — is {a.run} a duplicate? "
                  "(queued anyway; remove via backlog.json if so)")
        items.append({"run": a.run, "steps": a.steps, "parent": a.parent,
                      "hypothesis": a.hypothesis, "gate": a.gate,
                      "extra_args": extra, "attempts": 0, "added": now()})
        _write_backlog(items)
    print(f"queued {a.run} ({len(items)} item(s) in backlog)")
    return 0


def _free_gpu_pods(g: dict) -> list[str]:
    free = []
    for pod in g["compute"]["gpu_pods"]:
        try:
            # A pod without the .bootstrapped marker is schedulable but
            # not training-ready (deps mid-install); it is NOT a slot
            # yet — bootstrap_train_pod.sh writes the marker last.
            ready = kexec(pod, "test -f /workspace/prototype_sts3215/"
                               ".bootstrapped && echo OK || true").strip()
            if ready == "OK" and not pod_trainers(pod):
                free.append(pod)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue  # Pending/unreachable pod: not a free slot right now
    return free


def cmd_drain(g: dict, a: argparse.Namespace) -> int:
    """Push backlog items onto free GPU pods until one side is empty.

    SELF-REPAIRING (operator, 2026-08-09 — root cause of the idle
    fleet was gates that refuse and wait for an intelligent actor):
    before each launch this syncs the pod's code and pushes a missing
    --init-from checkpoint instead of refusing. Launches run as child
    processes; verifications overlap since the launch lock only covers
    check->start. A free slot plus a non-empty backlog is a bug.
    """
    import concurrent.futures

    def take_next() -> dict | None:
        with file_lock(BACKLOG_LOCK):
            items = _read_backlog()
            if not items:
                return None
            it = items.pop(0)
            _write_backlog(items)
            return it

    def requeue(it: dict, err: str) -> None:
        it["attempts"] = it.get("attempts", 0) + 1
        it["last_error"] = err[-400:]
        with file_lock(BACKLOG_LOCK):
            if it["attempts"] >= 3:
                dead = (json.loads(BACKLOG_FAILED.read_text())
                        if BACKLOG_FAILED.exists() else [])
                dead.append(it)
                BACKLOG_FAILED.write_text(json.dumps(dead, indent=2) + "\n")
                print(f"PARKED {it['run']} after 3 failed attempts "
                      f"(backlog_failed.json) — needs a human/cycle look")
            else:
                _write_backlog([*_read_backlog(), it])

    def launch_one(pod: str, it: dict) -> None:
        run = it["run"]
        # Dedupe: a requeued item whose run meanwhile made it to W&B (e.g.
        # a parallel drain's attempt succeeded after this one's cleanup
        # failure) must be DROPPED, not retried into refusal-parking.
        try:
            if wandb_name_exists(run):
                print(f"drain: {run} already exists in W&B — dropping "
                      "backlog item (duplicate)")
                return
        except Exception:
            pass  # W&B flake: fall through, cmd_launch's gate still holds
        # Self-repair 1: pod code marker -> current HEAD.
        sync = subprocess.run(["bash", str(HERE / "snapshot.sh"),
                               "--sync", pod],
                              capture_output=True, text=True, timeout=600)
        if sync.returncode != 0:
            requeue(it, f"sync {pod}: {sync.stderr or sync.stdout}")
            return
        # Self-repair 2: warm-start checkpoint present on the pod.
        xa = it.get("extra_args") or []
        if "--init-from" in xa:
            ckpt = xa[xa.index("--init-from") + 1]
            subprocess.run(["bash", str(HERE / "ops.sh"), "pushckpt",
                            pod, ckpt],
                           capture_output=True, text=True, timeout=600)
        # Self-repair 3: W&B secret (gitignored, never in code sync).
        wenv = HERE.parent / "sim" / "wandb.env"
        if wenv.is_file():
            subprocess.run(["kubectl", "--kubeconfig", KUBECONFIG, "cp",
                            str(wenv),
                            f"{pod}:{WORKDIR}/rl_move/sim/wandb.env"],
                           capture_output=True, text=True, timeout=120)
        cmd = [sys.executable, str(HERE / "launch_run.py"), "launch",
               "--pod", pod, "--run", run, "--steps", str(it["steps"]),
               "--parent", it.get("parent", ""),
               "--hypothesis", it["hypothesis"], "--gate", it["gate"],
               "--", *xa]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=1800)
        out = (r.stdout or "") + (r.stderr or "")
        print(f"drain {run} -> {pod}: rc={r.returncode}\n{out[-600:]}")
        if r.returncode != 0:
            requeue(it, out)

    free = _free_gpu_pods(g)
    if not free:
        print("drain: no free GPU slots")
        return 0
    jobs = []
    for pod in free:
        it = take_next()
        if it is None:
            break
        jobs.append((pod, it))
    if not jobs:
        print("drain: backlog empty")
        return 0
    print(f"drain: {len(jobs)} launch(es): "
          + ", ".join(f"{it['run']}->{pod}" for pod, it in jobs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda j: launch_one(*j), jobs))
    return 0


RUNS_DIR = HERE.parent.parent / "rl_docs" / "runs"


def render_run_md(entry: dict) -> None:
    """Write rl_docs/runs/<run>.md from a ledger entry.

    One generated file per run (operator ask, 2026-08-09): a browsable
    directory of past runs instead of everyone appending to one big
    RL_LOG.md and merge-conflicting. NEVER hand-edit these — they are
    overwritten from experiments.json on every ledger update. Narrative
    goes in the ledger's hypothesis/verdict fields (or W&B notes)."""
    run = entry.get("run")
    if not run:
        return
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# {run}", "",
             "<!-- GENERATED from experiments.json by launch_run.py — "
             "do not edit -->", ""]
    order = ["status", "created", "pod", "steps", "parent", "git_sha",
             "wandb_id", "checkpoint", "hardware_ready", "hypothesis",
             "gate", "verdict", "failed_reason", "refused_reason", "note"]
    for k in order:
        v = entry.get(k)
        if v in (None, "", []):
            continue
        lines.append(f"**{k}**: {v}")
        lines.append("")
    (RUNS_DIR / f"{run}.md").write_text("\n".join(lines) + "\n")


def cmd_runsmd() -> int:
    """Backfill/refresh rl_docs/runs/ for every ledger entry."""
    led = load_ledger()
    newest = {}
    for e in led:
        if e.get("run"):
            newest[e["run"]] = e
    for e in newest.values():
        render_run_md(e)
    print(f"rendered {len(newest)} run file(s) -> {RUNS_DIR}")
    return 0


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
        matches = [e for e in led if e.get("run") == a.run
                   and (not a.created or e.get("created") == a.created)]
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
        if entry.get("verdict"):
            # a verdict closes the analysis pipeline for this run
            entry["triage"] = "done"
        save_ledger(led)
    render_run_md(entry)
    keys = [kv.partition("=")[0] for kv in a.set or []]
    print(f"updated {a.run}: set {keys}")
    # Mechanical W&B mirror (operator, 08-09): a verdict that only lives
    # in the ledger looks like an ignored result on the W&B page. Push
    # it to the run's notes immediately; ops.sh wandbnote may later
    # replace it with a richer paragraph (same OUTCOME marker). Also
    # package the run's ANALYSIS (ledger entry, rendered run page,
    # harness eval outputs incl. report.json/frames/videos) as an
    # `analysis-<run>` artifact attached to the W&B run.
    if "verdict" in keys and entry.get("verdict"):
        try:
            import wandb
            api = wandb.Api()
            runs = sorted(api.runs("l2k2/hexapod-balance",
                                   filters={"display_name": a.run}),
                          key=lambda r: r.created_at)
            if runs:
                r = runs[-1]
                marker = "--- OUTCOME"
                base = (r.notes or "").split(marker)[0].rstrip()
                r.notes = (f"{base}\n\n{marker} ---\n"
                           f"{str(entry['verdict']).strip()}\n")
                r.update()
                print(f"verdict mirrored to W&B notes: {r.url}")
                try:
                    _publish_analysis_artifact(r, a.run, entry)
                except Exception as ex:
                    print(f"WARN: analysis artifact failed: {ex}")
        except Exception as ex:  # never fail the ledger update over W&B
            print(f"WARN: could not mirror verdict to W&B notes: {ex}")
    return 0


def _publish_analysis_artifact(api_run, run_name: str, entry: dict) -> None:
    """Attach `analysis-<run>` (type run-analysis) to the W&B run:
    the ledger entry, rl_docs/runs/<run>.md, logs/experiments/<run>/,
    and every logs/ckpt_eval/<run>_* harness output directory. Skips
    single files >100 MB (an eval reel gone wrong must not hang the
    verdict cycle)."""
    import tempfile
    import wandb
    proto = HERE.parent.parent
    art = wandb.Artifact(f"analysis-{run_name}", type="run-analysis",
                         metadata={"verdict": str(entry.get("verdict"))[:500],
                                   "status": entry.get("status")})
    with tempfile.NamedTemporaryFile("w", suffix=".json",
                                     delete=False) as tf:
        json.dump(entry, tf, indent=2, default=str)
    art.add_file(tf.name, name="ledger_entry.json")
    md = RUNS_DIR / f"{run_name}.md"
    if md.exists():
        art.add_file(str(md), name=f"{run_name}.md")
    n_files = 0
    dirs = [proto / "logs" / "experiments" / run_name]
    dirs += sorted((proto / "logs" / "ckpt_eval").glob(
        run_name.replace("-", "_") + "_*"))
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.stat().st_size < 100 * 1024 * 1024:
                art.add_file(str(f), name=f"{d.name}/{f.relative_to(d)}")
                n_files += 1
    # The public API can't create-and-link artifacts on a finished run;
    # briefly resume the run so the artifact lands on ITS page/DAG.
    w = wandb.init(entity="l2k2", project="hexapod-balance",
                   id=api_run.id, resume="allow", reinit=True,
                   settings=wandb.Settings(silent=True))
    w.log_artifact(art)
    w.finish()
    print(f"analysis artifact analysis-{run_name} attached "
          f"({n_files} eval files)")


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
    up.add_argument("--created", default=None, metavar="TIMESTAMP",
                    help="select a specific duplicate by its 'created' "
                         "field (default: newest entry for --run; needed "
                         "to mark stale duplicates, e.g. from the "
                         "2026-08-09 shadow-ledger import)")
    dp = sub.add_parser("drain", help="push backlog items onto free "
                                      "GPU pods (self-repairing)")
    sub.add_parser("runsmd", help="backfill rl_docs/runs/ summaries "
                                  "from the ledger")
    bp = sub.add_parser("backlog", help="queue mechanical launch specs")
    bp.add_argument("action", choices=["add", "list"])
    bp.add_argument("--run")
    bp.add_argument("--steps", type=int)
    bp.add_argument("--hypothesis", default="")
    bp.add_argument("--gate", default="")
    bp.add_argument("--parent", default="")
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
    if a.cmd == "backlog":
        return cmd_backlog(a, extra)
    if a.cmd == "runsmd":
        return cmd_runsmd()
    if a.cmd == "drain":
        return cmd_drain(g, a)
    return cmd_launch(g, a, extra)


if __name__ == "__main__":
    sys.exit(main())
