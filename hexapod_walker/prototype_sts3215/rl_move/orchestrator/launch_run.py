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
# Operator launch hold: while this file exists every launch path
# (launch, drain, auto-continue — they all come through here) refuses.
# Triage/verdict/eval work is unaffected. Remove the file to resume.
LAUNCH_HOLD = HERE / "LAUNCH_HOLD"
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
TRAIN_MODULE_DYNREP = "rl_move.dynamics.train"
TRAIN_MODULE_DYNREP_FRESH = "rl_move.dynamics.fresh_pipeline"
GPU_TORCH_PYTHON = "/workspace/venv_torchgpu/bin/python"
WANDB_PROJECT = "l2k2/hexapod-balance"
# Research tracks (operator, 08-11): every launch belongs to one of
# tracks.json's tracks; the run gets W&B tag `track:<id>` and the
# ledger entry a "track" field. tracks.py is the single accessor.
import tracks as _tracks
import pod_torch_capability as _torch_cap

# One 48-env run wants ~50-60 cores. Assumed footprint per already-running
# trainer when computing free capacity, and minimum free cores required.
CORES_PER_RUN = 55
MIN_FREE_FULL = 40   # full experiment below this = refused (--allow-slow overrides)
MIN_FREE_SMOKE = 8
SMOKE_MAX_STEPS = 1_000_000
# CANARY and DISCOVERY are intentionally distinct: a canary asks only
# whether training machinery is healthy, while discovery asks whether
# correct behavior appears in a short budget. ACQUISITION gives a healthy
# from-scratch lineage its honest learning budget before hardening.
PHASES = ("canary", "discovery", "acquisition", "hardening",
          "composition", "transfer")
SHORT_PHASES = ("canary", "discovery")
DISCOVERY_MAX_STEPS_DEFAULT = 2_000_000

PHASE_SCOPES = {
    "canary": "mechanism_health",
    "discovery": "short_behavior_discovery",
    "acquisition": "full_budget_skill_acquisition",
    "hardening": "behavior_hardening",
    "composition": "skill_composition",
    "transfer": "deployment_transfer",
}

CANARY_GATE_PREFIX = (
    "MECHANISM-HEALTH CANARY ONLY: do not judge skill acquisition, close a "
    "behavior/reward class, or require mature gait at this checkpoint. "
)


def canary_update_error(entry: dict) -> str:
    """Reject category-error verdicts for mechanism-only canaries."""
    if entry.get("phase") != "canary":
        return ""
    if entry.get("hardware_ready") is True:
        return "canary runs cannot be marked hardware_ready"
    verdict = str(entry.get("verdict", "")).strip().upper()
    if not verdict:
        return ""
    allowed = (
        verdict.startswith("CANARY PASS"),
        verdict.startswith("CANARY FAIL - INFRASTRUCTURE"),
        verdict.startswith("CANARY FAIL - MECHANISM"),
    )
    if not any(allowed):
        return ("canary verdict must begin CANARY PASS, CANARY FAIL - "
                "INFRASTRUCTURE, or CANARY FAIL - MECHANISM; behavioral "
                "FAIL/exploit/reward-closure verdicts are invalid at "
                "mechanism-health scope")
    return ""


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


# Module invocations counted as "a trainer is running" by pod_trainers()
# (2026-08-09 c37: anchored on literal `-m <module> ` prefixes, never a
# loose `*train_ppo_*` glob — that matched cycle-agent processes whose
# cmdline embeds the standing prompt, 371 phantom trainers on the
# controller node would have refused every smoke launch there).
# 2026-08-15 (dynrep triage cycle): `rl_move.dynamics.train_ppo_transfer`
# (the condition A/B/C PPO-transfer cohorts, e.g. risewalk-single2/
# futurewalk-C) was MISSING — capacity.py/ops.sh census/the launcher's
# own pre-launch free-pod check all read those pods as free while they
# were genuinely busy (confirmed live via direct kubectl exec /proc
# reads on train-4/5/6/7/8/9 while capacity.py reported them FREE).
# Not just a cosmetic report bug: launch_run.py's own pod_trainers()
# call gates real launches (line ~1159/1567) and dedup (line ~683) —
# added here so a future launch/dedupe check sees these pods correctly.
TRAINER_MODULES = [
    "rl_move.sim.train_ppo_",  # prefix: train_ppo_sim / train_ppo_mjx
    "rl_move.dynamics.train ",  # exact module, trailing space
    "rl_move.dynamics.fresh_pipeline ",
    "rl_move.dynamics.train_ppo_transfer ",
]

# {proc} defaults to /proc; tests substitute a fabricated directory tree
# (numeric-named dirs each holding a NUL-separated `cmdline` file) so the
# real glob/case logic is exercised without touching a live pod.
_TRAINER_SCAN_SCRIPT = (
    "for p in {proc}/[0-9]*; do c=$(tr '\\0' ' ' < $p/cmdline 2>/dev/null); "
    "case \"$c\" in " +
    "|".join(
        f"python*' -m {m}'*|*/python*' -m {m}'*" for m in TRAINER_MODULES
    ) +
    ") case \"$c\" in *' -c '*) ;; *) echo \"$c\";; esac;; esac; done | sort -u"
)


def pod_trainers(pod: str) -> list[str]:
    """Names (--run-name/--name values) of main trainer processes on the pod.

    Matches main trainers of every stack (TRAINER_MODULES above); the
    forkserver/spawn workers have -c or empty cmdlines and are excluded,
    as is this scan's own bash wrapper.
    """
    script = _TRAINER_SCAN_SCRIPT.format(proc="/proc")
    names = []
    for line in kexec(pod, script).splitlines():
        toks = line.split()
        name = "unnamed"
        for i, t in enumerate(toks):
            if t == "--run-name" and i + 1 < len(toks):
                name = toks[i + 1]
            if t == "--name" and i + 1 < len(toks):
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


def _recover_population_waiting(summary: object) -> dict | None:
    """Return the newest unreleased recovery-population start barrier."""
    try:
        keys = list(summary.keys())
    except (AttributeError, TypeError):
        return None
    ready = []
    for key in keys:
        match = re.fullmatch(r"recover_population/ready_B(\d+)", str(key))
        if match:
            ready.append((int(match.group(1)), str(key)))
    for bucket, key in sorted(ready, reverse=True):
        start_key = f"recover_population/start_B{bucket:02d}"
        try:
            is_ready = bool(summary.get(key))
            is_started = bool(summary.get(start_key))
        except (AttributeError, TypeError):
            return None
        if is_ready and not is_started:
            return {"bucket": bucket, "ready_key": key,
                    "start_key": start_key}
    return None


def wandb_running_runs() -> dict[str, dict]:
    """Name -> liveness fields for runs currently reported as running."""
    import wandb
    api = wandb.Api()
    out = {}
    for r in api.runs(WANDB_PROJECT, order="-created_at")[:25]:
        if r.state == "running":
            step = r.summary.get("global_step") or r.summary.get("_step")
            out[r.name] = {"id": r.id, "state": r.state,
                           "global_step": step}
            barrier = _recover_population_waiting(r.summary)
            if barrier is not None:
                out[r.name]["recover_population_barrier"] = barrier
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


# Operator naming corrections (08-15, fb_20260815T114937_f9078d): run
# names must name the operator-visible BEHAVIOR (joystick translate,
# stop, rise, lower), never the internal mechanism/sampler geometry.
# Enforced here because cycle prompts are frozen at spawn: a cycle
# started before a correction landed would otherwise launch under the
# superseded name, and the launcher is the one mechanical interception
# point every launch/queue/respec path shares. Map: banned name (or
# substring rule below) -> (required name, correction id).
RENAMED_RUNS = {
    "cw-mt-c2-fullcircle1": ("cw-joystick-translate1",
                             "fb_20260815T114937_f9078d"),
}
BANNED_NAME_SUBSTRINGS = {
    # "fullcircle" is a misleading implementation-centric label for
    # joystick-commanded translation (uniform [-pi,pi] heading is just
    # sampler coverage, not the behavior, and must not suggest yaw).
    "fullcircle": ("cw-joystick-translate1", "fb_20260815T114937_f9078d"),
}


def _joystick_metric_block(run: str) -> str | None:
    """Operator metric simplification (08-15, fb_20260815T115650_47010c):
    the joystick-translation TRAINING contract is only raw signed
    joystick/v_along_m_s (+ _cumulative + active_ticks; cross/wrong-way
    may stay as secondary train/ diagnostics). Per-heading binned
    training series are REMOVED — uniform [-pi,pi] heading sampling plus
    the signed average already zeroes out command-ignorant motion, and
    fixed 8/12-direction panels belong in held-out EVAL only. Enforced
    at the launcher for the same reason as the naming table above: the
    executing cycle's prompt was frozen before the simplification
    landed. Self-clearing — refuses only while the sim tree still emits
    the binned series."""
    if "joystick" not in run:
        return None
    marker = "v_along_" + "hbin"   # split so this file never self-matches
    sim = Path(__file__).resolve().parent.parent / "sim"
    for fn in ("walk_task.py", "train_ppo_mjx.py"):
        try:
            src = (sim / fn).read_text(encoding="utf-8")
        except OSError:
            continue
        if marker in src:
            return (f"operator metric simplification "
                    f"fb_20260815T115650_47010c not applied: sim/{fn} "
                    f"still emits per-heading '{marker}*' training "
                    "series. Training headline is ONLY "
                    "joystick/v_along_m_s + joystick/v_along_m_s_"
                    "cumulative + joystick/active_ticks (raw signed m/s "
                    "along the requested direction, active ticks only); "
                    "remove the bins — fixed-direction panels are "
                    "held-out EVAL tools — then relaunch. See "
                    "/workspace/llm_feedback/"
                    "fb_20260815T115650_47010c.json")
    return None


def naming_correction(run: str) -> str | None:
    """Refusal message if this run name was renamed by the operator."""
    hit = RENAMED_RUNS.get(run)
    if not hit:
        for sub, h in BANNED_NAME_SUBSTRINGS.items():
            if sub in run:
                hit = h
                break
    if not hit:
        return _joystick_metric_block(run)
    new, ref = hit
    return (f"run name '{run}' superseded by operator naming correction "
            f"{ref} — use --run {new} (same spec otherwise; name the "
            f"operator-visible behavior, keep mechanism/sampler details "
            f"in config/tags/notes; see /workspace/llm_feedback/{ref}.json)")


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
    trainer = getattr(a, "trainer", "ppo")
    is_dynrep = trainer in ("dynrep", "dynrep-fresh")
    is_dynrep_fresh = trainer == "dynrep-fresh"
    track = getattr(a, "track", "") or _tracks.infer(a.run)
    entry = {
        "run": a.run, "pod": a.pod, "steps": a.steps, "smoke": a.smoke,
        "hypothesis": a.hypothesis, "gate": a.gate, "parent": a.parent,
        "track": track,
        "extra_args": extra, "created": now(), "status": "INTENT",
        "checks": {}, "trainer": trainer,
        "stack": ("gpu-transformer-fresh-data" if is_dynrep_fresh else
                  "gpu-transformer") if is_dynrep else (
            "gpu-mjx" if is_gpu else "cpu"),
    }
    if LAUNCH_HOLD.exists():
        # Operator-ordered single launch during a hold. Before this flag
        # (08-10) the operator's assistant had to mv the hold file away
        # and restore it — a race against the watcher and a throwaway
        # script every time. The bypass is recorded in the ledger entry;
        # every AUTOMATIC path (drain, auto-continue, backlog retries)
        # never passes it, so the hold still parks the fleet. Agents:
        # this flag is operator-only (guardrails OPERATOR HOLD note).
        override = getattr(a, "operator_override", "")
        if override:
            entry["operator_override"] = override
        else:
            return refuse(entry, "operator LAUNCH_HOLD in effect — triage/"
                                 "verdict only, no new launches; do NOT retry "
                                 "or requeue, the hold clears when the operator "
                                 "removes rl_move/orchestrator/LAUNCH_HOLD")
    checks = entry["checks"]

    # --- static checks -----------------------------------------------------
    nc = naming_correction(a.run)
    if nc:
        return refuse(entry, nc)
    if a.pod not in comp["pods"] and not is_gpu:
        return refuse(entry, f"pod {a.pod} not in guardrails pod list")
    if is_dynrep and not is_gpu:
        return refuse(entry, "dynrep pretraining is CUDA-only and must run "
                             "on a gpu_pods entry")
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
        # CANARY checks machinery only; DISCOVERY asks whether behavior
        # appears cheaply; ACQUISITION gives a healthy from-scratch lineage
        # its comparable full budget. Later phases require evidence.
        phase = getattr(a, "phase", "") or _lineage_field(a.parent, "phase")
        if not phase and a.hypothesis.startswith("AUTO-CONTINUE"):
            # Pre-phase-system lineage being segment-stitched by the
            # watcher: a continuation of a still-climbing run is by
            # definition hardening behavior already seen.
            phase = "hardening"
            entry["evidence"] = (f"auto-continue of {a.parent} "
                                 "(watcher; pre-phase lineage)")
        if phase not in PHASES:
            return refuse(entry, "experiments require --phase "
                                 f"{{{'|'.join(PHASES)}}} (operator 08-10). "
                                 "SPECIFICATION work never trains. If this "
                                 "continues an existing lineage, pass "
                                 "--parent and the phase is inherited.")
        entry["phase"] = phase
        entry["assessment_scope"] = PHASE_SCOPES[phase]
        if phase == "canary":
            entry["gate"] = CANARY_GATE_PREFIX + a.gate
        if phase in SHORT_PHASES:
            cap = int(g.get("phases", {}).get("discovery_max_steps",
                                              DISCOVERY_MAX_STEPS_DEFAULT))
            if a.steps > cap:
                question = ("is the training mechanism healthy?"
                            if phase == "canary" else
                            "did qualitatively correct behavior emerge?")
                next_phase = ("acquisition" if phase == "canary" else
                              "hardening")
                return refuse(entry, f"{phase} runs cap at {cap} steps "
                                     f"(asked {a.steps}): the question is "
                                     f"'{question}' - continue as --phase "
                                     f"{next_phase} with --evidence.")
        else:
            evidence = (entry.get("evidence")
                        or getattr(a, "evidence", "")
                        or _lineage_field(a.parent, "evidence"))
            if not evidence:
                required = (
                    "name the healthy canary and a comparable full-budget "
                    "learning precedent" if phase == "acquisition" else
                    "name the run/video where intended behavior was already "
                    "seen, or the test_task_semantics/preflight PASS")
                return refuse(entry, f"{phase} runs require --evidence: "
                                     f"{required}.")
            entry["evidence"] = evidence
    owned_name_flag = "--name" if is_dynrep else "--run-name"
    for flag in (owned_name_flag, "--steps"):
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
    if not is_dynrep and "--n-envs" not in extra:
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
        # CUDA-torch capability gate (08-15 wait, closed this cycle):
        # --device cuda only pays off (~120x on the PPO update for
        # attention/GRU trunks) on a pod whose torch stack was
        # installed+recorded (pod_torch_capability.py) — every
        # mjx-train pod otherwise ships stock CPU-torch, so an
        # unrecorded --device cuda would silently run the ~18x-slower
        # CPU path on GPU-priced hardware, invisible until someone reads
        # the fps. Does NOT touch --device auto (the trainer's default):
        # auto degrades safely by letting the process detect cuda
        # itself, so ordinary flatten-MLP launches are unaffected.
        # is_dynrep is exempt: it already runs its own live
        # cuda_torch_runtime probe above (kexec, this call) which is at
        # least as strict.
        if not is_dynrep and "--device" in extra:
            dev = extra[extra.index("--device") + 1]
            if dev == "cuda" and not _torch_cap.is_capable(a.pod):
                return refuse(
                    entry,
                    f"{a.pod}: --device cuda requested but has no "
                    "recorded CUDA-torch capability (pod_torch_capability.py "
                    "install/verify + record first, or drop --device cuda "
                    "to keep the pod's default CPU-torch)")
            checks["torch_device"] = dev
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
        if is_dynrep_fresh and wandb_name_exists(f"{a.run}-data"):
            return refuse(entry, f"W&B already has a run named "
                                 f"{a.run}-data (fresh-pipeline data runs "
                                 "are append-only; pick a new run name)")
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
    # Default --out-name the same way `respec` already does (gotcha 6:
    # dash->underscore, "ppo_goal_" prefix) if the caller forgot it. Without
    # this, train_ppo_mjx falls back to its OWN default
    # f"ppo_mjx_{task}_{run_name}" (e.g. task=joint_goal -> a checkpoint
    # named ppo_mjx_joint_goal_<run>.zip, not ppo_goal_<run>.zip), which
    # `ops.sh pullckpt`/eval tooling never look for. Hit twice now (08-10):
    # cw-walk-wander60-dr05-s1 (silent, caught by a later cycle) and
    # cw-stance-riseproof1 (this cycle: pullckpt rc=1, no such file — pulled
    # manually under its real trainer-default name once diagnosed).
    if not is_dynrep and "--out-name" not in extra:
        extra = [*extra, "--out-name", "ppo_goal_" + a.run.replace("-", "_")]
        entry["extra_args"] = extra
    log = f"/tmp/train_{a.run}.log"
    if is_gpu and not is_dynrep:
        # train_ppo_mjx owns its parallelism (sharded host workers), and
        # --subproc does not exist there.
        if "--impl" not in extra:
            extra = [*extra, "--impl", str(gpu.get("impl", "warp"))]
        if "--host-workers" not in extra:
            extra = [*extra, "--host-workers",
                     str(gpu.get("host_workers", 24))]
        entry["extra_args"] = extra
    elif not is_dynrep and "--subproc" not in extra:
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
    if is_dynrep:
        python = GPU_TORCH_PYTHON
        if not _torch_cap.is_capable(a.pod):
            runtime_candidates = [GPU_TORCH_PYTHON]
        else:
            runtime_candidates = [GPU_TORCH_PYTHON, "python3"]
        runtime = ""
        runtime_error = None
        for candidate in runtime_candidates:
            try:
                info = kexec(
                    a.pod,
                    f"test -x $(command -v {candidate} 2>/dev/null || "
                    f"echo {candidate}) && {candidate} -c "
                    "'import torch; assert torch.cuda.is_available(); "
                    "print(torch.__version__, torch.cuda.get_device_name())'"
                ).strip()
                if info:
                    python, runtime = candidate, f"{candidate}: {info}"
                    break
            except (subprocess.CalledProcessError,
                    subprocess.TimeoutExpired) as e:
                runtime_error = e
        if not runtime:
            return refuse(entry, f"{a.pod} lacks a working recorded CUDA "
                                 f"PyTorch runtime ({runtime_candidates}): "
                                 f"{runtime_error}")
        checks["cuda_torch_runtime"] = runtime
        if "--data" not in extra:
            return refuse(entry, "dynrep launches require --data DATASET")
        if "--arch" in extra and extra[extra.index("--arch") + 1] != "transformer":
            return refuse(entry, "orchestrated dynrep pretraining requires "
                                 "--arch transformer")
        if "--arch" not in extra:
            extra = [*extra, "--arch", "transformer"]
        if "--device" in extra and extra[extra.index("--device") + 1] != "cuda":
            return refuse(entry, "orchestrated dynrep pretraining requires "
                                 "--device cuda")
        if "--device" not in extra:
            extra = [*extra, "--device", "cuda"]
        if "--input-set" not in extra:
            extra = [*extra, "--input-set", "obs"]
        if "--allow-cpu" in extra or "--allow-legacy-priv" in extra:
            return refuse(entry, "production dynrep launches may not bypass "
                                 "CUDA or full-label dataset requirements")
        entry["extra_args"] = extra
        module = (TRAIN_MODULE_DYNREP_FRESH if is_dynrep_fresh
                  else TRAIN_MODULE_DYNREP)
        name_flag = "--name"
    else:
        module = TRAIN_MODULE_GPU if is_gpu else TRAIN_MODULE
        python = "python"
        name_flag = "--run-name"
    # shlex.quote every passthrough token: notes/cfg values with shell
    # metacharacters (parens, semicolons) used to splice raw into the
    # remote bash -c and kill the launch (2026-08-09: cw-walk-parkstart
    # and cw-stance-bellyrest each burned a FAILED attempt on this).
    train = (f"{python} -m {module} "
             f"{name_flag} {a.run} --steps {a.steps} "
             + " ".join(shlex.quote(t) for t in extra))
    envp = "WANDB_MODE=disabled " if a.smoke else ""
    # Track tagging (operator, 08-11: tags, not separate projects —
    # nothing moves). wandb.init picks WANDB_TAGS up natively; the W&B
    # UI then filters per track on tag `track:<id>`.
    if not a.smoke:
        envp += f"WANDB_TAGS={shlex.quote(_tracks.tag(track))} "
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
        # Reuse the anchored scanner used by checkup. The old inline
        # pattern embedded `--name <run>` in its own bash command line,
        # matched that wrapper, and returned the short-lived scan PID
        # instead of the live dynrep trainer.
        pid = _pod_trainer_pid(a.pod, a.run)
        if not pid:
            entry["status"] = "FAILED"
            entry["failed_reason"] = ("launch kexec timed out and no "
                                      "trainer process found on pod")
            upsert_entry(entry)
            print("VERIFICATION FAILED: kexec timeout and no trainer process")
            return 1
    checks["pid"] = pid
    print(f"launched pid {pid}; verifying...")
    return {"entry": entry, "checks": checks, "pid": pid,
            "log": log, "is_gpu": is_gpu}


def _pod_trainer_pid(pod: str, run: str) -> str | None:
    """PID of the main trainer process for --run-name <run> on a pod
    (None if absent). Same /proc scan + anchoring rules as
    pod_trainers(); run names are [a-z0-9-] so direct interpolation
    into the case pattern is safe."""
    script = (
        "for p in /proc/[0-9]*; do c=$(tr '\\0' ' ' < $p/cmdline "
        "2>/dev/null); case \"$c\" in *' -m rl_move.sim.train_ppo_'*"
        f"'--run-name {run} '*|*' -m rl_move.dynamics.train '*"
        f"'--name {run} '*|*' -m rl_move.dynamics.fresh_pipeline '*"
        f"'--name {run} '*|*' -m rl_move.dynamics.train_ppo_transfer '*"
        f"'--name {run} '*) case \"$c\" in *' -c '*) ;; *) "
        "echo ${p#/proc/};; esac;; esac; done"
    )
    try:
        out = kexec(pod, script).strip().splitlines()
        return out[0] if out else None
    except subprocess.CalledProcessError:
        return None


def _pod_pid_cputime(pod: str, pid: str) -> int | None:
    """Cumulative CPU-centiseconds (utime+stime, /proc/<pid>/stat fields
    14+15) for a process on a remote pod, or None if it's gone/unreadable.
    Used as a "genuinely still computing" signal independent of any
    single iteration's wall-clock budget (see _verify_started)."""
    try:
        out = kexec(pod, f"awk '{{print $14+$15}}' /proc/{pid}/stat "
                          f"2>/dev/null || echo ''").strip()
        return int(out) if out else None
    except (subprocess.CalledProcessError, ValueError):
        return None


def _extra_int(extra_args: list, flag: str, default: int) -> int:
    """Read an integer value passed as `--flag value` in an extra_args list."""
    if flag in extra_args:
        try:
            return int(extra_args[extra_args.index(flag) + 1])
        except (ValueError, IndexError):
            return default
    return default


def _verify_started(g: dict, a: argparse.Namespace, ctx: dict) -> int:
    """Mechanical liveness verification of a just-started trainer.

    Runs OUTSIDE the launch lock: the process already exists on the pod,
    so concurrent capacity checks count it. Parallel drains/launches can
    verify simultaneously instead of queueing ~5 min each."""
    entry, checks = ctx["entry"], ctx["checks"]
    pid, log, is_gpu = ctx["pid"], ctx["log"], ctx["is_gpu"]
    is_dynrep = entry.get("trainer") in ("dynrep", "dynrep-fresh")
    is_dynrep_fresh = entry.get("trainer") == "dynrep-fresh"
    wb_name = f"{a.run}-data" if is_dynrep_fresh else a.run

    def fail(reason: str) -> int:
        print(f"VERIFICATION FAILED: {reason}")
        # pkill pattern MUST be anchored to the python trainer: an
        # unanchored 'run-name X' also matches the bash -c wrapper running
        # this very cleanup, so pkill killed its own shell (exit 143) and
        # the "failure" bubbled up as a crashed launch attempt (2026-08-09:
        # cw-walk-highgait burned 2 backlog attempts on cleanup suicide).
        try:
            pattern = (f"rl_move[.]dynamics[.](train|fresh_pipeline).*"
                       f"--name {a.run} "
                       if is_dynrep else
                       f"rl_move[.]sim[.]train_ppo.*--run-name {a.run} ")
            kexec(a.pod, f"kill {pid} 2>/dev/null; "
                         f"pkill -f '{pattern}' 2>/dev/null; true")
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
            running = wandb_running_runs()
            wb = running.get(a.run) or running.get(wb_name)
            if wb:
                break
            time.sleep(20)
        if not wb:
            return fail("run never appeared as 'running' in W&B within 240s")
        checks["wandb_id"] = wb["id"]
        entry["wandb_id"] = wb["id"]
        active_wb_id = wb["id"]
        s1 = wb.get("global_step") or 0
        # A single PPO iteration's wall time is floored by its rollout
        # (n_envs * n_steps). A fixed 90s window false-killed
        # cw-arch-gru-r4 TWICE (2026-08-11, --n-steps 256 / 10.24s BPTT):
        # a first attempt to fix this by scaling the wait with --n-steps
        # (90s * n_steps/64, capped 600s) was STILL too short — direct
        # /proc CPU-time sampling on the pod during the retry showed the
        # process burning ~25 cores flat out (real PPO update work: the
        # GRU policy trains on CPU per the trainer's own "Using cpu
        # device" log line, so a big BPTT backward pass has no GPU signal
        # at all) for 360s+ with iteration 2 still not done -- a live,
        # correctly-working run, killed anyway. Replaced the fixed sleep
        # with a poll loop: keep waiting past the nominal budget as long
        # as the process's cumulative CPU time (utime+stime) is still
        # climbing (proof of real work, not a hang); only fail once BOTH
        # global_step has not advanced AND CPU time has gone flat for two
        # consecutive samples, or an outer safety cap (20 min) elapses.
        n_steps = _extra_int(entry.get("extra_args", []), "--n-steps", 64)
        # The fresh dynrep parent waits while a child process compiles the
        # 2k-world MJX/Warp collector. Its own /proc CPU clock can stay flat
        # even though the child and H200 are busy, so allow the full compile
        # window before applying the parent-CPU stall heuristic.
        base_wait = (900 if is_dynrep_fresh else
                     min(600, max(90, int(90 * n_steps / 64))))
        poll = 30
        outer_cap = 1200.0  # absolute safety net regardless of CPU signal
        elapsed = 0.0
        prev_cpu = _pod_pid_cputime(a.pod, pid)
        flat_streak = 0
        s2 = s1
        while elapsed < outer_cap:
            time.sleep(poll)
            elapsed += poll
            running = wandb_running_runs()
            current_wb = running.get(a.run) or running.get(wb_name) or {}
            if current_wb.get("id") not in (None, active_wb_id):
                checks.setdefault("wandb_stage_transitions", []).append(
                    [active_wb_id, current_wb["id"]])
                active_wb_id = current_wb["id"]
                checks["wandb_id"] = active_wb_id
                entry["wandb_id"] = active_wb_id
                s1 = current_wb.get("global_step") or 0
                s2 = s1
                prev_cpu = _pod_pid_cputime(a.pod, pid)
                flat_streak = 0
                continue
            s2 = current_wb.get("global_step") or 0
            if s2 > s1:
                break
            cur_cpu = _pod_pid_cputime(a.pod, pid)
            still_computing = (cur_cpu is not None and prev_cpu is not None
                                and cur_cpu > prev_cpu + 50)  # >0.5 CPU-s
            prev_cpu = cur_cpu
            if elapsed >= base_wait:
                if still_computing:
                    flat_streak = 0  # genuinely busy; keep extending
                else:
                    flat_streak += 1
                    if flat_streak >= 2:
                        break  # two flat samples past budget = real stall
        if s2 <= s1:
            # Fast short runs FINISH before/during this window (a 0.5-1M
            # step GPU run completes in ~90-200 s): the run leaves W&B's
            # 'running' set, s2 reads 0, CPU goes flat — and a healthy
            # completed run was marked FAILED ("global_step not advancing
            # (1048576 -> 0)"), which also stops the watcher from staging
            # its evals. Hit cw-arch-noslipphase1-r3/-r4/-dr0 (08-13).
            # If the last observed global_step already reached the
            # requested budget, that is a clean finish, not a stall.
            target = int(entry.get("steps") or 0)
            if target and s1 >= target:
                checks["finished_during_verification"] = [s1, target]
                entry["status"] = "FINISHED"
                entry["verified"] = now()
                upsert_entry(entry)
                print(f"VERIFIED FINISHED (run completed during "
                      f"verification window): {a.run} on {a.pod}")
                return 0
            return fail(f"W&B global_step not advancing ({s1} -> {s2}) "
                        f"after {elapsed:.0f}s (n_steps={n_steps}, "
                        f"cpu-time flat for {flat_streak} polls)")
        checks["global_step_window"] = [s1, s2]
        checks["fps_estimate"] = round((s2 - s1) / max(elapsed, 1.0), 1)
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
    wb_names = ([a.run, f"{a.run}-data"]
                if entry.get("trainer") == "dynrep-fresh" else [a.run])

    def live_wandb() -> dict:
        running = wandb_running_runs()
        # Script-owned cohorts (pod_tfwalk.sh / pod_risewalk.sh, 08-15):
        # their W&B run names carry per-attempt/per-phase suffixes that
        # never equal the ledger run name (dynrep-tfwalk-A-s5.0815-2221Z,
        # rw_rise_C_s5) — three false checkup alarms 08-15 22:37. An
        # optional `wandb_match` regex on the entry matches any running
        # W&B name; absent field = old exact-name behavior, bit-exact.
        wm = entry.get("wandb_match")
        if wm:
            for name in running:
                if re.search(wm, name):
                    return running[name]
            return {}
        return next((running[name] for name in wb_names if name in running),
                    {})

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
    # Optional `proc_match` regex (script-owned cohorts whose trainer
    # --name is per-phase, e.g. rw_rise_C_s5 for ledger run
    # risewalk-single2-s5 — false DEAD x3 on 08-15). Absent field =
    # old exact-membership behavior, bit-exact.
    pm = entry.get("proc_match")
    live_names = ([t for t in trainers if re.search(pm, t)] if pm
                  else [t for t in trainers if t == a.run])
    facts["process_alive"] = bool(live_names)
    if not facts["process_alive"]:
        tail = kexec(pod, f"tail -c 2000 {log} 2>/dev/null || true")
        # A missing process is NOT necessarily a death: short runs and
        # canary auto-stops complete before/within the checkup window.
        # Completion markers: CPU trainer "[train] N steps in Ts → ckpt"
        # (cw-walk-step0-c1 false-positive DEAD, 2026-08-09) and MJX/GPU
        # trainer "[mjx-train] done: N steps in Ts ... -> ckpt" (three
        # false DEADs on sub-7-min discovery runs 2026-08-11: 01:55
        # cycle, cw-stand-rsi1, cw-stand-rsi2 — the old regex only knew
        # the CPU banner). Tail widened 600->2000 bytes because post-
        # completion wandb-artifact lines can push the banner out.
        if re.search(r"\[train\] \d+ steps in .*→", tail) or \
                re.search(r"\[mjx-train\] done: [\d,]+ steps in", tail):
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
    wb1 = live_wandb()
    s1 = wb1.get("global_step") or 0
    time.sleep(45)
    size2 = int(kexec(pod, f"stat -c %s {log}").strip())
    wb2 = live_wandb()
    s2 = wb2.get("global_step") or 0
    facts["log_growth_bytes"] = size2 - size1
    log_stalled = size2 <= size1
    # A stalled log alone is NOT suspect when W&B global_step is
    # advancing: the MJX trainer writes nothing to stdout after its
    # startup banner (false SUSPECT on healthy cw-arch-gru-anchor2,
    # 2026-08-12 — steps 131k->720k, fps ~1.5k, log frozen at 1519 B).
    # Smokes run with W&B off, so there the log is the only signal.
    if entry.get("smoke") and log_stalled:
        problems.append("log stopped growing")
    if not entry.get("smoke"):
        if not wb2:
            problems.append("W&B no longer reports the run as running")
            if log_stalled:
                problems.append("log stopped growing")
        elif s2 <= s1 and wb2.get("recover_population_barrier"):
            barrier = wb2["recover_population_barrier"]
            facts["recover_population_barrier"] = barrier
            facts["placement"] = "recovery-population start barrier"
            facts["note"] = (
                f"intentionally waiting at recovery-population B"
                f"{int(barrier['bucket'])} start barrier at global_step "
                f"{s2}; ready is published and start is not yet released")
        elif s2 <= s1:
            # W&B logs once per PPO iteration, and an iteration's wall
            # time is floored by its rollout (n_envs * n_steps). Small-
            # env configs legitimately exceed the 45 s sample window
            # (false SUSPECT on healthy cw-arch-modeexperts-scratch1-r1,
            # 2026-08-15: 256 envs x 256 n_steps at ~225 fps = ~380 s
            # per iteration; both W&B and the log were between writes).
            # Before calling a stall, require the same proof-of-no-work
            # signal the launch verifier uses (_verify_started, the
            # 08-11 cw-arch-gru-r4 fix): cumulative CPU time flat across
            # two 30 s samples. A genuinely hung/starved process goes
            # CPU-flat; a slow-cadence healthy one keeps burning cores.
            pid = _pod_trainer_pid(
                pod, live_names[0] if live_names else a.run)
            cpu = [_pod_pid_cputime(pod, pid) if pid else None]
            for _ in range(2):
                time.sleep(30)
                cpu.append(_pod_pid_cputime(pod, pid) if pid else None)
            deltas = [b - a2 for a2, b in zip(cpu, cpu[1:])
                      if a2 is not None and b is not None]
            computing = bool(deltas) and all(d > 50 for d in deltas)
            facts["cpu_centisec_deltas"] = deltas
            if computing:
                facts["note"] = ("global_step flat in 45s window but "
                                 "trainer CPU busy — long-rollout "
                                 "iteration cadence, not a stall")
            else:
                problems.append(f"W&B global_step stalled at {s2}")
                if log_stalled:
                    problems.append("log stopped growing")
        else:
            fps = (s2 - s1) / 45.0
            facts["fps"] = round(fps, 1)
            # Expected floor by placement: GPU-MJX pods run ~19-20k fps
            # solo; solo on a 56-core CPU pod ~1000+; sharing or a
            # 30-core pod runs slower but should beat 60.
            limit = pod_cpu_limit(pod)
            solo = len(trainers) == 1
            # train_ppo_transfer added 08-15: the dynamics-track transfer
            # PPO runs 8 SB3 envs (measured healthy 49 fps risewalk_s5,
            # ~560 fps tfwalk-A) — nothing like MJX's 19-20k rollout fps;
            # the 5000 floor false-SUSPECTed healthy risewalk-single2-s5.
            # A genuine stall still lands near zero, under the 5.0 floor.
            # 08-15 23:xx: the gpu1 tfwalk relaunch entries were
            # registered without the `trainer` field, so all three
            # healthy CUDA runs (fps 228-401, steps advancing) fell
            # through to the 5000 MJX floor — false SUSPECT x3 at
            # 22:59. Fall back to the entry's command/args/log blob so
            # a script-owned dynamics-track entry missing the field
            # still classifies; entries WITH the field are unchanged.
            _tblob = (" ".join(str(x) for x in entry.get("extra_args", []))
                      + " " + str(entry.get("command", ""))
                      + " " + str(entry.get("log", "")))
            is_dynrep_trainer = (
                entry.get("trainer") in (
                    "dynrep", "dynrep-fresh", "train_ppo_transfer")
                or "train_ppo_transfer" in _tblob
                or "rl_move/dynamics/logs/" in _tblob)
            if is_dynrep_trainer and pod in g["compute"].get("gpu_pods", []):
                # dynrep/dynrep-fresh's "global_step" is a GRADIENT step
                # over pre-collected windows, not a PPO physics env-step —
                # a completely different unit from the ~19-20k fps floor
                # below, which is calibrated for MJX rollout throughput.
                # Two independent healthy runs (cw-dynrep-tf-state1,
                # cw-dynrep-tf-state2-recovered1 — both the same 13.6M
                # CUDA transformer) steady-state at ~41-42 step/s and both
                # false-SUSPECTed against the 5000 floor (found 08-15,
                # recovered1 checkup). Floor calibrated well below that
                # steady-state so a genuine stall/starvation (CPU-flat or
                # near-zero step/s) still catches, healthy training doesn't.
                floor = 5.0
                facts["placement"] = "solo on GPU-MJX pod (dynrep trainer)"
            elif pod in g["compute"].get("gpu_pods", []):
                floor = 5000.0
                facts["placement"] = "solo on GPU-MJX pod"
                # Scale the floor for configs that are legitimately
                # slower (08-10: the flat 5k floor false-alarmed
                # cw-arch-hist16-dep1-s1r1, a healthy run). Two known
                # causes: fewer envs (the /dev/shm-mandated 3072
                # shrink for deep-history runs, COMMANDS gotcha 13c)
                # and deep obs-history stacks. Measured healthy
                # steady-state on a full node (4 trainers): plain@4096
                # ~7.7-8.3k fps, hist16@3072 ~3.9-4.6k, hist24@3072
                # ~2.0k. Genuine starvation (4-5x, the 08-08 CPU
                # incident class) still lands well below these floors.
                blob = " ".join(str(x) for x in entry.get(
                    "extra_args", [])) + " " + entry.get("command", "")
                m = re.search(r"--n-envs\s+(\d+)", blob)
                if m:
                    floor *= min(1.0, int(m.group(1)) / 4096.0)
                m = re.search(r"history_frames=(\d+)", blob)
                if m and int(m.group(1)) > 8:
                    floor *= 8.0 / int(m.group(1))
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


def _lineage_field(parent: str, field: str) -> str:
    """Inherit phase/evidence from the parent's newest ledger entry, so
    auto-continues and respecs of an already-phased lineage need no
    re-declaration (the watcher passes --parent on every continuation)."""
    if not parent:
        return ""
    vals = [e.get(field, "") for e in load_ledger()
            if isinstance(e, dict) and e.get("run") == parent]
    return next((v for v in reversed(vals) if v), "")


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
    nc = naming_correction(a.run)
    if nc:
        print(f"REFUSED: {nc}")
        return 1
    # Fail fast at queue time: a phase-less, parent-less item would only
    # refuse at drain time (3 retries, then parked — noise for nothing).
    if not getattr(a, "phase", "") and not a.parent:
        print(f"backlog add needs --phase ({'|'.join(PHASES)}) - or "
              "--parent, to inherit the lineage's phase at "
              "launch (operator 08-10; see RESEARCH_RULES.md)")
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
                      "trainer": getattr(a, "trainer", "ppo"),
                      "phase": getattr(a, "phase", ""),
                      "evidence": getattr(a, "evidence", ""),
                      "track": (getattr(a, "track", "")
                                or _tracks.infer(a.run)),
                      "extra_args": extra, "attempts": 0, "added": now()})
        _write_backlog(items)
    print(f"queued {a.run} ({len(items)} item(s) in backlog)")
    return 0


def cmd_respec(g: dict, a: argparse.Namespace) -> int:
    """Queue (or directly launch) a follow-up run by CLONING a ledger
    entry's trainer args with targeted overrides — the mechanical form of
    the most-repeated cycle task (seed panels, ladder rungs, DR variants,
    continuations). Agents re-typed the ~800-char arg vector for every
    follow-up and typo'd it more than once (operator, 08-09 evening: 'if
    the models keep doing the same thing, give them more scripts').

        launch_run.py respec --from cw-walk-joyjit-dr05-c1 \
            --run cw-walk-joyjit-dr05-s3 --seed 3 \
            --hypothesis '…' --gate '…' \
            [--steps N] [--arg='--episode-seconds=120'] [--cfg k=v] \
            [--init-from-source] [--now [--pod POD]] \
            [--operator-override 'why']

    --arg overrides/adds a trainer flag (use the = form, the value
    starts with --); --cfg overrides/adds a --cfg-set KEY=V pair.
    --out-name is derived from --run; --notes is replaced by the
    hypothesis (pass --arg='--notes=…' to override).
    --init-from-source warm-starts from the source run's checkpoint
    (its --out-name; encodes the dash->underscore rule of gotcha 6).
    Default is queue-to-backlog (drain launches it). --now skips the
    backlog: snapshot -> pick pod (source run's pod if free, else any
    free slot, or --pod) -> self-repair -> launch + verify, in one
    command — previously hand-assembled from snapshot.sh + pushckpt +
    a hand-typed launch (operator continuation, 08-10).
    --operator-override (requires --now) is the OPERATOR-ONLY audited
    LAUNCH_HOLD bypass; agents must never pass it.
    """
    if a.operator_override and not a.now:
        print("--operator-override requires --now (a queued item would be "
              "launched later by drain, which never bypasses the hold)")
        return 1
    nc = naming_correction(a.run)
    if nc:
        print(f"REFUSED: {nc}")
        return 1
    src = [e for e in load_ledger() if isinstance(e, dict)
           and e.get("run") == a.source and e.get("extra_args")]
    if not src:
        print(f"no ledger entry with extra_args for {a.source}")
        return 1
    # 08-13 fix: a source run name can carry a LATER, unrelated REFUSED
    # entry (e.g. a same-pod-busy re-launch attempt after the real run
    # already finished) whose thin extra_args ("--n-envs 4096" only, no
    # --init-from/--cfg-set) still pass the truthiness check above.
    # Blindly taking src[-1] (list/creation order) picked that stub
    # instead of the real training entry and silently respec'd from a
    # near-empty arg vector (root cause of the cw-arch-noslipphase1-r2
    # corruption: no --init-from, default task). Prefer an entry that
    # actually ran; fall back to the last match only if none did.
    ran = [e for e in src if e.get("wandb_id") or e.get("checks", {}).get("pid")]
    entry = ran[-1] if ran else src[-1]
    args = list(entry["extra_args"])

    def set_flag(flag: str, val: str) -> None:
        if flag in args:
            args[args.index(flag) + 1] = val
        else:
            args.extend([flag, val])

    def set_bare_flag(flag: str) -> None:
        # store_true-style flag: takes no value. Adding [flag, ""]
        # (the old set_flag behavior for a missing '=') crashed
        # train_ppo_mjx.py's argparse with a trailing empty
        # "unrecognized arguments" (found the hard way, 08-18:
        # --arg='--best-ckpt' launched, argparse-crashed pre-boot,
        # zero GPU-seconds lost, fixed here). Idempotent: a bare flag
        # already present is left alone.
        if flag not in args:
            args.append(flag)

    if a.seed is not None:
        set_flag("--seed", str(a.seed))
    for spec in a.arg or []:
        flag, eq, val = spec.partition("=")
        if not flag.startswith("--"):
            print(f"bad --arg (need --flag=value or bare --flag): {spec}")
            return 1
        if eq:
            set_flag(flag, val)
        else:
            set_bare_flag(flag)
    for spec in a.cfg or []:
        key = spec.split("=", 1)[0]
        # replace an existing --cfg-set for the same key, else append
        for i, v in enumerate(args):
            if v == "--cfg-set" and args[i + 1].split("=", 1)[0] == key:
                args[i + 1] = spec
                break
        else:
            args.extend(["--cfg-set", spec])
    # dynrep/dynrep-fresh trainers (rl_move.dynamics.train /
    # fresh_pipeline) have no --out-name / --init-from flags at all --
    # they derive their own checkpoint name from --name and don't warm
    # -start from a PPO-style zip. respec used to add --out-name
    # unconditionally (mirroring the ppo-only convention the `launch`
    # command already guards with `is_dynrep`), which crashed
    # argparse the first time it respec'd a dynrep-fresh run (08-15,
    # `cw-dynrep-tf-state2-fresh3`: "unrecognized arguments: --out-name
    # ..." after burning a full stage-1 data-collection cycle first).
    is_dynrep_source = entry.get("trainer") in ("dynrep", "dynrep-fresh")
    if a.init_from_source:
        if is_dynrep_source:
            print("REFUSED: --init-from-source has no meaning for a "
                  "dynrep/dynrep-fresh source (no --out-name checkpoint "
                  "to warm-start from)")
            return 1
        xa = entry["extra_args"]
        src_out = (xa[xa.index("--out-name") + 1] if "--out-name" in xa
                   else "ppo_goal_" + a.source.replace("-", "_"))
        set_flag("--init-from", f"rl_move/sim/policies/{src_out}.zip")
    if not is_dynrep_source:
        set_flag("--out-name", "ppo_goal_" + a.run.replace("-", "_"))
    if "--notes" not in (a.arg or []) and not any(
            s.startswith("--notes=") for s in a.arg or []):
        set_flag("--notes", f"respec of {a.source}: {a.hypothesis}")
    print(f"respec {a.source} -> {a.run} "
          f"(changed: seed={a.seed}, args={a.arg or []}, cfg={a.cfg or []}"
          f"{', init-from source ckpt' if a.init_from_source else ''})")
    steps = a.steps or entry.get("steps")
    # Track containment (operator, 08-11): a respec inherits the source
    # run's track unless explicitly overridden.
    track = (getattr(a, "track", "") or entry.get("track", "")
             or _tracks.infer(a.run))
    trainer = entry.get("trainer", "ppo")
    if not a.now:
        ns = argparse.Namespace(
            action="add", run=a.run, steps=steps,
            parent=a.parent or a.source, hypothesis=a.hypothesis,
            gate=a.gate, phase=a.phase or entry.get("phase", ""),
            evidence=a.evidence or entry.get("evidence", ""),
            track=track, trainer=trainer)
        return cmd_backlog(ns, args)

    # --now: direct launch, skipping the backlog. snapshot -> sync ->
    # launch, in that order, same command (gotcha 5, mechanized).
    snap = subprocess.run(["bash", str(HERE / "snapshot.sh"), a.run],
                          capture_output=True, text=True, timeout=600)
    if snap.returncode != 0:
        print(f"snapshot failed (commit/tag/push):\n"
              f"{snap.stdout}{snap.stderr}")
        return 1
    pod = a.pod
    if not pod:
        free = _free_gpu_pods(g)
        # Prefer the source run's pod: its checkpoint is already there,
        # so an --init-from-source launch needs zero copies.
        src_pod = entry.get("pod", "")
        pod = src_pod if src_pod in free else (free[0] if free else "")
    if not pod:
        print("no free GPU pod and no --pod given; nothing launched")
        return 1
    err = _self_repair_pod(pod, args)
    if err:
        print(f"self-repair failed: {err}")
        return 1
    ns = argparse.Namespace(
        pod=pod, run=a.run, steps=steps, parent=a.parent or a.source,
        hypothesis=a.hypothesis, gate=a.gate, smoke=False,
        allow_slow=False, dry_run=False,
        phase=a.phase or entry.get("phase", ""),
        evidence=a.evidence or entry.get("evidence", ""),
        track=track, trainer=trainer,
        operator_override=a.operator_override)
    return cmd_launch(g, ns, args)


def _self_repair_pod(pod: str, extra_args: list[str]) -> str | None:
    """Make <pod> launchable: sync code, push a missing --init-from
    checkpoint (best-effort; the launcher's preflight still gates), copy
    the gitignored W&B secret. Shared by drain and respec --now — this
    exact three-step dance used to be hand-assembled per launch.
    Returns an error string on hard failure, else None."""
    sync = subprocess.run(["bash", str(HERE / "snapshot.sh"), "--sync", pod],
                          capture_output=True, text=True, timeout=600)
    if sync.returncode != 0:
        return f"sync {pod}: {sync.stderr or sync.stdout}"
    if "--init-from" in extra_args:
        ckpt = extra_args[extra_args.index("--init-from") + 1]
        subprocess.run(["bash", str(HERE / "ops.sh"), "pushckpt", pod, ckpt],
                       capture_output=True, text=True, timeout=600)
    wenv = HERE.parent / "sim" / "wandb.env"
    if wenv.is_file():
        subprocess.run(["kubectl", "--kubeconfig", KUBECONFIG, "cp",
                        str(wenv),
                        f"{pod}:{WORKDIR}/rl_move/sim/wandb.env"],
                       capture_output=True, text=True, timeout=120)
    return None


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
    if LAUNCH_HOLD.exists():
        print("drain: operator LAUNCH_HOLD in effect; backlog left queued, "
              "nothing launched")
        return 0
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
        # Bug found live (cycle 2026-08-10 ~02:0x, groundtilt8-s1r2 and
        # groundtilt5-payload-r4 vanished with no science AND no park):
        # if training itself started before crashing (e.g. the gotcha
        # 13/13b launch-collision EOFError), a W&B run already exists
        # under this name. Requeueing the SAME name means the next
        # attempt's cmd_launch append-only-name check refuses it, and
        # launch_one's own dedup guard then treats that refusal as
        # "already exists in W&B" and silently DROPS the item — no
        # requeue, no park, no trace. Rename before requeueing so a
        # real retry (not a name refusal) happens.
        try:
            if wandb_name_exists(it["run"]):
                base = it["run"]
                n = 1
                while wandb_name_exists(f"{base}-rr{n}"):
                    n += 1
                new_name = f"{base}-rr{n}"
                print(f"requeue: {base} already has a W&B run (started "
                      f"then crashed) — renaming retry to {new_name}")
                it["run"] = new_name
                # Keep --out-name (checkpoint filename) in sync so a
                # SUCCESSFUL renamed retry's checkpoint is findable
                # under the name that actually trained.
                xa = it.get("extra_args")
                if xa and "--out-name" in xa:
                    xa[xa.index("--out-name") + 1] = (
                        "ppo_goal_" + new_name.replace("-", "_"))
        except Exception as exc:
            print(f"requeue: wandb_name_exists check failed ({exc}); "
                  "requeueing under the same name anyway")
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
        # Self-repairs: code sync, warm-start checkpoint, W&B secret.
        xa = it.get("extra_args") or []
        err = _self_repair_pod(pod, xa)
        if err:
            requeue(it, err)
            return
        cmd = [sys.executable, str(HERE / "launch_run.py"), "launch",
               "--trainer", it.get("trainer", "ppo"),
               "--pod", pod, "--run", run, "--steps", str(it["steps"]),
               "--parent", it.get("parent", ""),
               "--hypothesis", it["hypothesis"], "--gate", it["gate"],
               "--phase", it.get("phase", ""),
               "--evidence", it.get("evidence", ""),
               "--track", it.get("track", ""),
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
        # 08-13 fix: without an explicit --created, prefer an entry that
        # actually ran (wandb_id/pid) over a LATER same-name REFUSED
        # stub (e.g. a busy-pod re-launch attempt after the real run
        # finished) — plain "newest by list order" silently attached
        # verdicts/notes to the wrong (unexecuted) entry.
        if not a.created:
            ran = [e for e in matches
                   if e.get("wandb_id") or e.get("checks", {}).get("pid")]
            if ran:
                matches = ran
        entry = matches[-1]  # newest (ran-preferred) entry for this run name
        for kv in a.set or []:
            key, _, val = kv.partition("=")
            if not _:
                print(f"bad --set (need key=value): {kv}")
                return 1
            try:
                entry[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                entry[key] = val
        err = canary_update_error(entry)
        if err:
            print(f"REFUSED: {err}")
            return 1
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
            r = _tracks.find_wandb_run(api, a.run)
            if r is not None:
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
    w = wandb.init(entity="l2k2", project=api_run.project,
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
    bp.add_argument("--phase", default="", choices=(*PHASES, ""),
                    help="experiment phase; "
                         "inherited from --parent's ledger entry if empty")
    bp.add_argument("--evidence", default="",
                    help="hardening/composition/transfer: where the "
                         "qualitatively correct behavior was already seen "
                         "(run/video) or the preflight PASS that licenses "
                         "this run")
    bp.add_argument("--track", default="", choices=(*_tracks.ids(), ""),
                    help="research track (tracks.json); default: inferred "
                         "from the run-name prefix, else hw")
    bp.add_argument("--trainer", choices=("ppo", "dynrep", "dynrep-fresh"),
                    default="ppo", help="trainer family to preserve through "
                         "the backlog drain")
    rp = sub.add_parser("respec", help="queue a follow-up by cloning a "
                                       "ledger entry's args with overrides")
    rp.add_argument("--from", dest="source", required=True,
                    metavar="RUN", help="run whose config to clone")
    rp.add_argument("--run", required=True, help="new run name")
    rp.add_argument("--seed", type=int, default=None)
    rp.add_argument("--steps", type=int, default=None,
                    help="default: same as source")
    rp.add_argument("--parent", default="", help="default: the source run")
    rp.add_argument("--hypothesis", required=True)
    rp.add_argument("--gate", required=True)
    rp.add_argument("--phase", default="", choices=(*PHASES, ""),
                    help="experiment phase; default: the source run's")
    rp.add_argument("--evidence", default="",
                    help="see launch --evidence; default: the source run's")
    rp.add_argument("--arg", action="append", default=None,
                    metavar="--FLAG=VALUE",
                    help="override/add a trainer flag (repeatable)")
    rp.add_argument("--cfg", action="append", default=None, metavar="K=V",
                    help="override/add a --cfg-set pair (repeatable)")
    rp.add_argument("--init-from-source", action="store_true",
                    help="warm-start from the source run's checkpoint")
    rp.add_argument("--now", action="store_true",
                    help="launch directly (snapshot+sync+repair+verify) "
                         "instead of queueing to the backlog")
    rp.add_argument("--pod", default="",
                    help="with --now: target pod (default: source run's "
                         "pod if free, else first free slot)")
    rp.add_argument("--operator-override", default="",
                    help="OPERATOR-ONLY, with --now: reason string that "
                         "bypasses LAUNCH_HOLD for this one launch "
                         "(recorded in the ledger); agents never pass this")
    rp.add_argument("--track", default="", choices=(*_tracks.ids(), ""),
                    help="research track; default: the SOURCE run's track "
                         "(containment rule) — override only for an "
                         "escalated cross-track insight")
    lp = sub.add_parser("launch")
    lp.add_argument("--trainer",
                    choices=("ppo", "dynrep", "dynrep-fresh"),
                    default="ppo",
                    help="trainer family; dynrep-fresh generates a "
                         "reuse-budgeted GPU dataset before CUDA Transformer "
                         "phase-1 pretraining")
    lp.add_argument("--pod", required=True)
    lp.add_argument("--run", required=True)
    lp.add_argument("--steps", type=int, required=True)
    lp.add_argument("--hypothesis", default="")
    lp.add_argument("--gate", default="")
    lp.add_argument("--parent", default="")
    lp.add_argument("--phase", default="", choices=(*PHASES, ""),
                    help="experiment phase: canary/discovery cap steps; "
                         "acquisition and later phases require --evidence; "
                         "inherited from "
                         "--parent's ledger entry if empty")
    lp.add_argument("--evidence", default="",
                    help="acquisition: healthy canary plus comparable "
                         "full-budget precedent; later phases: run/video "
                         "or preflight PASS that licenses this run")
    lp.add_argument("--smoke", action="store_true",
                    help="short validation run: W&B disabled, non-cw name")
    lp.add_argument("--allow-slow", action="store_true",
                    help="override the free-cores check (record why!)")
    lp.add_argument("--dry-run", action="store_true")
    lp.add_argument("--operator-override", default="",
                    help="OPERATOR-ONLY: reason string that bypasses "
                         "LAUNCH_HOLD for this one launch (recorded in "
                         "the ledger); agents never pass this")
    lp.add_argument("--track", default="", choices=(*_tracks.ids(), ""),
                    help="research track (tracks.json): sets the W&B "
                         "track:<id> tag and the status doc; default: "
                         "inferred from the run-name prefix, else hw")
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
    if a.cmd == "respec":
        return cmd_respec(g, a)
    if a.cmd == "runsmd":
        return cmd_runsmd()
    if a.cmd == "drain":
        return cmd_drain(g, a)
    return cmd_launch(g, a, extra)


if __name__ == "__main__":
    sys.exit(main())
