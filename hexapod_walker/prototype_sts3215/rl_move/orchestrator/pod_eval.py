#!/usr/bin/env python3
"""Run a finished run's standard post-training evals ON ITS OWN POD.

    uv run python rl_move/orchestrator/pod_eval.py <run> [tag-suffix]

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

import datetime
import json
import os
import pathlib
import shlex
import subprocess
import sys

import tracks

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

# Joystick DONE-gate reading (operator 08-22: the longrun17 rung-A
# passer sat for hours before anyone thought to run the session gate
# on it, and unsticking it took a manual kick). Every joystick-track
# walk candidate now gets the randomized 60 s command-script gate
# (rl_move.sim.eval_joystick_gate: stress_mix commands, held-out
# seeds, det+sto x DR-0+own-DR, ONE PASS/FAIL vs the track's DONE
# numbers) fired mechanically here, in parallel with the standard
# passes, on the run's own pod. INFORMATIONAL like the session gate:
# printed + logged + synced, never folded into pod_eval's exit code —
# candidates are EXPECTED to fail it until the fine-tune stage closes
# the fixed-heading -> randomized-session gap.
JOYGATE_TIMEOUT_S = 3600
LEGACY_CONTROL_HZ = 25.0
LEGACY_MAX_DELTA_Q_DEG = 1.5

# MIXED-SESSION gate auto-launch (2026-08-28, standwalk unified1-mix
# gap): two independent triage cycles (04:4x on -long-s1, 04:5x on
# -long-s0) found the SAME hole by hand — a "unified command-
# following" recipe (env-native `goal.mode_seq>0`: chained rise/walk/
# lower/hold sessions with joystick-style resampled walk commands)
# needs `rl_move.sim.eval_mixed_session` for its OWN pre-registered
# gate (session terminations-per-episode / completion fraction), but
# that instrument was never wired into pod_eval's auto-prestage — only
# `eval_checkpoint`/`eval_session` were. Both cycles worked around it
# by hand-running `ops.sh sessioncmd` on the pod; this wires the same
# command in here so the NEXT arm in this lineage (there will be more
# — this is an active wave) doesn't need a human/agent to notice and
# re-derive it every time. Timeout matches `ops.sh sessioncmd`'s own
# documented `waitlog ... 7200` convention (60s+180s sessions, video,
# on the 100 Hz mesh contract this recipe always trains under).
MIXEDSESSION_TIMEOUT_S = 7200


def mode_seq_frac(cfgs: list[str]) -> float:
    """Value of ``goal.mode_seq`` in an UNSTRIPPED cfg-set list, else
    0.0 (pure/testable — the trigger for the mixed-session auto-launch
    below). A malformed/non-numeric value counts as unset (0.0) rather
    than crashing pod_eval on a bad ledger entry."""
    for c in cfgs:
        k, _, v = c.partition("=")
        if k.strip() == "goal.mode_seq":
            try:
                return float(v)
            except ValueError:
                return 0.0
    return 0.0


def _cfg_key(cfg: str) -> str:
    return cfg.split("=", 1)[0].strip()


def _has_cfg_key(cfgs: list[str], key: str) -> bool:
    return any(_cfg_key(c) == key for c in cfgs)


def legacy_eval_cfgs(cfgs: list[str]) -> list[str]:
    """Replay old unstamped runs under the 25 Hz contract they trained with.

    BUG FIX (08-26, standheight-rung5-acq8m triage): the two pins used
    to be independent ``if`` checks, so a ledger entry with an EXPLICIT
    ``control.hz=100`` (every post-08-24 launch) but no explicit
    ``safety.max_delta_q_deg`` (the overwhelmingly common case — the
    100 Hz contract's 0.375 already lives in config.yaml's own
    default, so launches correctly never restate it) still hit the
    second ``if`` alone and got the LEGACY 25 Hz slew (1.5 deg/tick =
    150 deg/s) force-added — 4x looser than the 0.375 deg/tick
    (37.5 deg/s) contract those policies actually trained under. This
    silently ran every automated gate/owncfg/session/joygate pass for
    every 100 Hz run since the flip (161 launches at last count) under
    the wrong motor contract instead of the config default that would
    otherwise have been correct. The two pins are only valid TOGETHER
    (a ledger entry with no control.hz key at all means "pre-flip,
    trained at 25 Hz" per the flip's own invariant) — gate the second
    pin on the SAME missing-control.hz condition as the first, so an
    explicit (non-legacy) control.hz leaves max_delta_q_deg for
    config.yaml's own default (or whatever the run itself set) instead
    of overriding it.
    """
    out = list(cfgs)
    if not _has_cfg_key(out, "control.hz"):
        out.append(f"control.hz={LEGACY_CONTROL_HZ:g}")
        if not _has_cfg_key(out, "safety.max_delta_q_deg"):
            out.append(f"safety.max_delta_q_deg={LEGACY_MAX_DELTA_Q_DEG:g}")
    return out

# 08-24 100 Hz CADENCE FIX (found on cw-arch-hist16-dep1-c1-
# joyfullcurr13-v7-hz100-r2): PASS_TIMEOUT_S/JOYGATE_TIMEOUT_S were
# calibrated for the 25 Hz / 15s-episode baseline. A run trained at
# control.hz=100 with 60s episodes needs (100/25)*(60/15) = 16x the
# sim-tick count per episode of that baseline — wall-clock scales with
# it (video-every-1 rendering dominates, ~5 min/episode observed at
# 100Hz/60s vs seconds at 25Hz/60s) and the fixed 2700s pass timeout
# silently kills the job with rc=-1 BEFORE all 12 (6 det + 6 sto)
# episodes finish. Worse: pod_eval's copy-back only runs in the
# rc==0 branch, so a timeout kill loses the ENTIRE pass (no
# report.json, no partial credit) even though most episodes had
# already rendered on the pod. Scale both timeouts by the actual
# control.hz/episode-seconds product vs this same 25Hz/15s baseline
# (floor of 1x — never SHRINKS the budget for cheaper configs).
BASELINE_HZ = 25.0
BASELINE_EP_S = 15.0


def eval_timeout_scale(control_hz: float | None, episode_s: float | None) -> float:
    """Pure, testable: timeout multiplier vs the 25Hz/15s baseline the
    pass timeouts were calibrated for. Never below 1.0."""
    hz = control_hz if control_hz else BASELINE_HZ
    ep_s = episode_s if episode_s else BASELINE_EP_S
    return max(1.0, (hz / BASELINE_HZ) * (ep_s / BASELINE_EP_S))


def core_pass_synced(local_out: pathlib.Path) -> bool:
    """Is a gate/owncfg pass's artifact dir a COMPLETE synced copy?

    Bug found 08-28 (unified1-mix triage): the pass loop used to check
    bare `local_out.exists()`, so a partial/interrupted copy-back (a
    hand `kubectl cp` grabbed mid-flight, a truncated sync) — a
    directory with videos but no `report.json` — was silently treated
    as "already on controller", which wrote the prestage sentinel and
    released a verdict cycle to judge an incomplete panel. Every other
    pass in this file (session/mixedsession/joygate) already keys on
    its own completion file for exactly this reason; key gate/owncfg
    on `report.json` too, consistently.
    """
    return (local_out / "report.json").is_file()


def core_synced(run: str) -> None:
    """Sentinel: the CORE prestage evals (gate + own-DR) are settled —
    synced, skipped, or impossible. The watcher defers a finished run's
    triage cycle until this file exists (operator 08-22: cycles spent
    ~5 min/run sleep-polling for eval artifacts, and verdicts written
    off half-synced reports caused the longrun17 premature-verdict
    race). Written BEFORE the informational session/joygate passes,
    which a verdict never waits on."""
    p = PROTO / "logs/ckpt_eval" / (run.replace("-", "_") + "_prestage.synced")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(datetime.datetime.now().isoformat(timespec="seconds"))
    except OSError as exc:
        print(f"prestage sentinel write failed: {exc!r}")


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


def remote_report_exists(pod: str, out_rel: str) -> bool:
    """Does the pod already hold a finished report.json for out_rel?

    Used to distinguish an ORPHANED finished pass (the process exited,
    result sitting on the pod, nobody copied it back) from a genuinely
    not-yet-attempted one — the former must be reaped (copy-back only),
    never relaunched (see the 08-28 orphaned-result comment at the call
    site: relaunching silently discards a finished result and burns
    another full eval's worth of pod compute)."""
    remote_report = f"{POD_PROTO}/{out_rel}/report.json"
    return kexec(pod, f"test -f {shlex.quote(remote_report)}").returncode == 0


def remote_eval_running(pod: str, out_rel: str, module: str = "rl_move.sim.eval_checkpoint") -> bool:
    """True if a live `module` process on `pod` already targets `out_rel`
    (matched on the `--out`/`--out-dir` token, whichever the caller's
    output path shows up under). 2026-08-27 (standwalk
    anchor14-rescue-acq8m idle-kick): pod_eval's old idempotency check
    only looked at whether the CONTROLLER-side artifact dir already
    exists (i.e. a finished pass already synced back) — a pass still
    mid-flight on the pod (the normal state for anything with per-mode
    video, 1-2h+) is invisible to that check, so re-invoking
    `ops.sh podeval`/pod_eval.py on the same run silently launched a
    SECOND eval process hammering the same GPU-pod CPUs and writing
    episode files into the same output dir concurrently (observed: two
    live 4-process eval_checkpoint trees on one pod, ~28 cores of
    contention, racing writes into logs/ckpt_eval/<run>_gate/). Grep
    the pod's own process table for the exact out-path token before
    starting a new one.

    SELF-MATCH FIX (2026-08-28, idle-kick, found while chasing the
    acq8m session pass's missing log): `kubectl exec pod -- bash -c
    "ps -eo args= | grep MODULE | grep -F -- OUT_REL"` runs as its OWN
    process on the pod with that exact pipeline text as its argv, so
    `ps -eo args=` lists the wrapper (and each intermediate `grep`
    child) alongside any real target — and since the wrapper's argv
    literally contains both search strings, it ALWAYS self-matches,
    making this function report "running" unconditionally regardless
    of whether anything is really running (confirmed live: `ps -eo
    args= | grep eval_session | grep -F -- totally-made-up-string`
    returned rc=0, matching only its own invocation). This is why the
    acq8m session pass silently never launched — no log, no crash, no
    real process, just a permanent false "already RUNNING". Every
    process in this pipeline (the `bash -c` wrapper and both `grep`
    children) has the literal word "grep" in its own argv; a genuine
    `eval_checkpoint`/`eval_session` target never does — so filter
    those lines out before deciding. (The prior fix's own unit tests
    mocked `kexec` entirely, which is why they passed despite this:
    they never exercised a real shell self-matching itself.) Also adds
    `ww` (unlimited width) to `ps`: some `ps` builds still truncate the
    `args=` column even though it's usually unbounded once
    stdout isn't a tty, which can silently cut a long out_rel/module
    match in half and hide a real running process — cheap belt-and-
    suspenders alongside the self-match fix, not required to fix the
    grep bug itself."""
    try:
        cp = kexec(pod, f"ps ww -eo args= | grep {shlex.quote(module)} | "
                         f"grep -F -- {shlex.quote(out_rel)} | "
                         f"grep -v grep",
                   timeout=30)
    except subprocess.TimeoutExpired:
        return False  # pod slow/unreachable; let the caller proceed as before
    return cp.returncode == 0 and bool(cp.stdout.strip())


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
        core_synced(run)  # nothing to wait for; don't stall the cycle
        return 1
    pod = entry["pod"]
    args = list(entry["extra_args"])

    def val(flag: str, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    task = val("--task", "joint_walk")
    ep = val("--episode-seconds", "15" if task == "joint_walk" else None)
    dr = float(val("--dr-scale", "0") or 0)
    cfgs = [args[i + 1] for i, a in enumerate(args) if a == "--cfg-set"]
    # Unstripped/unpinned copy for the MIXED-SESSION gate below — that
    # harness scores the run's own env-native mode_seq sequencing, so
    # (unlike eval_checkpoint's forced-single-mode `cfgs` right below)
    # it needs the FULL cfg stack, mode_seq keys included.
    all_cfgs = list(cfgs)
    # 08-14 (cw-arch-modeseq1-r1 dig-in): NEVER carry the sequence-diet
    # keys into the forced-single-mode harness eval. With
    # goal.mode_seq>0 the env samples sequence episodes BEFORE the
    # forced p_* mix applies, and a rise-first sequence still labels
    # itself "rise" — so the "single-mode" retention numbers are
    # silently measured on mislabeled multi-segment episodes. The
    # sequence half of such runs' gates is eval_modeseq's job, not
    # eval_checkpoint's.
    cfgs = [c for c in cfgs
            if not c.split("=", 1)[0].strip().startswith("goal.mode_seq")]
    # Rate-contract pin (2026-08-24 control.hz 25->100 default flip,
    # fb_20260824T174619_c49b7e): since the flip the launcher injects an
    # explicit control.hz cfg-set into EVERY PPO launch, so a ledger
    # entry with no control.hz key ALWAYS means "trained at the old
    # 25 Hz default". Pin it (plus the matching 1.5 deg/tick slew =
    # 37.5 deg/s) so a re-eval on a post-flip code deploy doesn't
    # silently step the env at 100 Hz under a 25 Hz checkpoint.
    cfgs = legacy_eval_cfgs(cfgs)
    control_hz = BASELINE_HZ
    for c in cfgs:
        k, _, v = c.partition("=")
        if k.strip() == "control.hz":
            try:
                control_hz = float(v)
            except ValueError:
                pass
    timeout_scale = eval_timeout_scale(control_hz, float(ep) if ep else None)
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
        core_synced(run)  # nothing to wait for; don't stall the cycle
        return 1

    run_us = run.replace("-", "_")
    passes = [("gate", "0.0", f"/tmp/eval_{run}.log")]
    if dr > 0:
        passes.append(("owncfg", str(dr), f"/tmp/eval_{run}_owncfg.log"))

    jobs = []
    for tag, drv, logpath in passes:
        out_rel = f"logs/ckpt_eval/{run_us}_{tag}{suffix}"
        local_out = PROTO / out_rel
        if core_pass_synced(local_out):
            print(f"{tag}: {out_rel} already on controller — skipping")
            continue
        if remote_eval_running(pod, out_rel):
            print(f"{tag}: eval_checkpoint already RUNNING on {pod} for "
                  f"{out_rel} — NOT launching a duplicate; poll "
                  f"{logpath} / kubectl exec {pod} -- ps aux for it "
                  f"instead of re-invoking podeval")
            continue
        # Orphaned-result check (bug found 08-28, unified1-mix triage):
        # a pass can finish REMOTELY (report.json written, process
        # exited) with nobody watching to copy it back — the original
        # supervisor's own wrapper timeout gave up while the eval was
        # still genuinely running (long video-every=1 panels can take
        # 1.5-2h+), and every later invocation saw `remote_eval_running`
        # -> False + no local copy -> would otherwise fall through to
        # LAUNCHING A DUPLICATE, silently discarding the finished
        # remote result and burning another 1.5-2h of pod compute for
        # nothing. Reap it directly instead: if the pod's own
        # report.json already exists, there is nothing to wait on, only
        # a copy-back to do.
        if remote_report_exists(pod, out_rel):
            print(f"{tag}: {out_rel} finished on {pod} with nobody "
                  f"watching — reaping (copy-back only, no relaunch)")
            jobs.append((tag, out_rel, logpath, None, None))
            continue
        cmd = (f"cd {POD_PROTO} && set -a && "
               f". rl_move/sim/wandb.env 2>/dev/null; set +a; "
               f"uv run python -m rl_move.sim.eval_checkpoint {shlex.quote(ckpt)}"
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
        elif remote_eval_running(pod, s_out_rel, "rl_move.sim.eval_session"):
            print(f"session: eval already RUNNING on {pod} for {s_out_rel}"
                  " — NOT launching a duplicate")
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
                         f"uv run python -m rl_move.sim.eval_session"
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

    # MIXED-SESSION gate (see MIXEDSESSION_TIMEOUT_S comment block
    # above): the env-native mode_seq sequencing candidates' own gate.
    # Independent of `session`/`side` above — a joint-mode dual-core
    # policy is EXPECTED to fail eval_session's single-mode partner-
    # pairing obs contract (informational there); this is the
    # instrument its own pre-registered gate actually needs.
    mixedsession = None  # (out_rel, logpath, proc, fh)
    if mode_seq_frac(all_cfgs) > 0:
        ms_out_rel = f"logs/ckpt_eval/{run_us}_mixedsession{suffix}"
        ms_log = f"/tmp/mixedsession_{run}.log"
        if (PROTO / ms_out_rel / "session_verdict.json").is_file():
            print(f"mixedsession: {ms_out_rel} already on controller "
                  "— skipping")
        elif remote_eval_running(pod, ms_out_rel,
                                  "rl_move.sim.eval_mixed_session"):
            print(f"mixedsession: eval already RUNNING on {pod} for "
                  f"{ms_out_rel} — NOT launching a duplicate")
        else:
            ms_cfg = "".join(f" --extra-cfg-set {shlex.quote(c)}"
                              for c in all_cfgs)
            ms_cmd = (f"cd {POD_PROTO} && set -a && "
                      f". rl_move/sim/wandb.env 2>/dev/null; set +a; "
                      f"uv run python -m rl_move.sim.eval_mixed_session "
                      f"{shlex.quote(ckpt)} --task {task} "
                      f"--own-dr-scale {dr} --n 6 --episode-seconds 60 "
                      f"--long-seconds 180 --video{ms_cfg} "
                      f"--out-dir {ms_out_rel}")
            ms_fh = open(ms_log, "w")
            ms_p = subprocess.Popen(
                ["kubectl", "exec", pod, "--", "bash", "-c", ms_cmd],
                stdout=ms_fh, stderr=subprocess.STDOUT, text=True)
            print(f"mixedsession: started on {pod} (own-dr {dr}) -> "
                  f"{ms_log}")
            mixedsession = (ms_out_rel, ms_log, ms_p, ms_fh)

    # Joystick DONE-gate (see JOYGATE_TIMEOUT_S comment block).
    joygate = None  # (out_rel, logpath, proc, fh)
    if side == "walk" and (entry.get("track") or tracks.infer(run)) == "joystick":
        j_out_rel = f"logs/ckpt_eval/{run_us}_joygate{suffix}"
        # Key on gate_verdict.json (written only after all passes
        # aggregate), so a half-finished attempt stays retryable.
        if (PROTO / j_out_rel / "gate_verdict.json").is_file():
            print(f"joygate: {j_out_rel} already on controller — skipping")
        elif remote_eval_running(pod, j_out_rel, "rl_move.sim.eval_joystick_gate"):
            print(f"joygate: eval already RUNNING on {pod} for {j_out_rel}"
                  " — NOT launching a duplicate")
        else:
            j_log = f"/tmp/eval_{run}_joygate.log"
            j_cmd = (f"cd {POD_PROTO} && set -a && "
                     f". rl_move/sim/wandb.env 2>/dev/null; set +a; "
                     f"uv run python -m rl_move.sim.eval_joystick_gate "
                     f"{shlex.quote(ckpt)} --own-dr-scale {dr}"
                     + "".join(f" --extra-cfg-set {shlex.quote(c)}"
                               for c in cfgs)
                     + f" --out-dir {j_out_rel}")
            j_fh = open(j_log, "w")
            j_p = subprocess.Popen(
                ["kubectl", "exec", pod, "--", "bash", "-c", j_cmd],
                stdout=j_fh, stderr=subprocess.STDOUT, text=True)
            print(f"joygate: started on {pod} (randomized 60s session "
                  f"gate, own-dr {dr}) -> {j_log}")
            joygate = (j_out_rel, j_log, j_p, j_fh)

    worst = 0
    for tag, out_rel, logpath, p, fh in jobs:
        if p is None:
            rc = 0  # reaped pass (see the orphaned-result check above):
            # already finished remotely, nothing to wait on.
        else:
            try:
                rc = p.wait(timeout=PASS_TIMEOUT_S * timeout_scale)
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
        if fh is not None:
            fh.write(f"\nSYNCED rc={rc}{note}: {out_rel}\n")
            fh.close()
        print(f"{tag}: rc={rc}{note} artifacts -> {out_rel}")
        worst = max(worst, abs(rc))

    # Core passes settled (synced or skipped): the verdict cycle may
    # spawn now. Session + joygate below are informational riders.
    core_synced(run)

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

    if joygate:
        out_rel, logpath, p, fh = joygate
        try:
            rc = p.wait(timeout=JOYGATE_TIMEOUT_S * timeout_scale)
        except subprocess.TimeoutExpired:
            p.kill()
            rc = -1
        if rc in (0, 1):
            # eval_joystick_gate writes gate_verdict.json on both PASS
            # (0) and FAIL (1); anything else died before aggregating.
            (PROTO / out_rel).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["kubectl", "cp", f"{pod}:{POD_PROTO}/{out_rel}",
                 str(PROTO / out_rel)],
                capture_output=True, text=True, timeout=600)
        has_v = (PROTO / out_rel / "gate_verdict.json").is_file()
        if rc == 0 and has_v:
            status = "DONE-GATE PASS"
        elif rc == 1 and has_v:
            status = ("DONE-GATE FAIL (expected until fine-tuning "
                      "closes the randomized-session gap)")
        else:
            status = f"ERROR rc={rc}"
        line = (f"JOYGATE (randomized 60s command script): {status} "
                f"artifacts -> {out_rel}")
        fh.write(f"\nSYNCED {line}\n")
        fh.close()
        print(line)
        # Informational only: never folds into pod_eval's exit code.

    if mixedsession:
        out_rel, logpath, p, fh = mixedsession
        try:
            rc = p.wait(timeout=MIXEDSESSION_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p.kill()
            rc = -1
        if rc in (0, 1):
            # eval_mixed_session writes session_verdict.json on both
            # PASS (0) and FAIL (1); anything else died before
            # aggregating.
            (PROTO / out_rel).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["kubectl", "cp", f"{pod}:{POD_PROTO}/{out_rel}",
                 str(PROTO / out_rel)],
                capture_output=True, text=True, timeout=600)
        has_v = (PROTO / out_rel / "session_verdict.json").is_file()
        if rc == 0 and has_v:
            status = "MIXED-SESSION PASS"
        elif rc == 1 and has_v:
            status = "MIXED-SESSION FAIL"
        else:
            status = f"ERROR rc={rc}"
        line = f"MIXEDSESSION: {status} artifacts -> {out_rel}"
        fh.write(f"\nSYNCED {line}\n")
        fh.close()
        print(line)
        # Informational only: never folds into pod_eval's exit code
        # (this run's own PASS/FAIL is a ledger-gate judgment call for
        # the triage cycle, same treatment as session/joygate above).
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
