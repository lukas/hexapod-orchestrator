#!/usr/bin/env python3
"""Mechanical seed pruning for RUNNING training seeds (operator order,
2026-09-07 focus note; safety repair 2026-09-07 PM focus note).

Plain English: while several seeds of the same recipe train in parallel,
a seed that has stopped learning (flat reward AND flat/regressing
behavior) or has obviously collapsed (rising terminations, persistently
wrong-direction velocity) should be killed mechanically so the GPU goes
back to the queue -- WITHOUT killing seeds that are merely in a learning
valley, WITHOUT touching anything before it has had a fair burn-in, and
NEVER on missing, partial, or uncertain evidence.

Decision rule (operator-specified, binding):
  * Burn-in protection: the slope-based prune may only fire on >= 3
    ADJACENT complete report windows, each lying ENTIRELY beyond the
    25%-of-budget burn-in point (window start >= burn-in).
  * Slope prune: reward EMA slope non-positive/negligible AND behavioral
    progress non-improving (velocity along command, gait/eval validity,
    episode length, falls/terminations -- none improving, at least one
    behavioral axis actually observed).
  * Immediate collapse kill (3 adjacent windows of evidence, but no
    burn-in protection): rising terminations, or persistently
    wrong-direction velocity.
  * Learning-valley veto: if EITHER reward or ANY behavioral series is
    improving beyond its noise epsilon, never kill.
  * On kill: stop ONLY that run's pinned trainer processes, confirm the
    stop, retain checkpoint/logs, and update ONLY the exact pinned
    ledger attempt (run + created) via launch_run.py update.

Evidence integrity (2026-09-07 PM repair -- each was a verified live bug):
  * Windows keep their ACTUAL observed step bounds (obs_lo/obs_hi);
    partial/future windows (window end beyond the last observed step)
    are EXCLUDED. Previously a 2,097,152-step 2M canary invented a 3M
    window and a 40M run at 15.1M invented 17.5M "last-window" evidence.
  * The three deciding windows must be ADJACENT (consecutive bucket
    indices). Previously sparse buckets (12.5M / 20M / 32.5M) were
    accepted as "3 consecutive windows".
  * W&B lookup is by the ledger attempt's wandb_id (display-name match
    was ambiguous across retries); the fetched run's name must equal
    the ledger run name.
  * A budget-complete attempt (observed steps >= planned budget), a
    deferred-artifacts attempt past phase=training (CPU finalizer
    only), or an attempt with no live pinned trainer is NEVER killed,
    regardless of stale W&B/ledger RUNNING state.
  * The kill path revalidates (ledger attempt, W&B state+steps, handoff
    phase, trainer PID + /proc start-time identity) immediately before
    targeted termination, treats kill-command failure as failure,
    confirms the processes actually stopped, and only then writes
    KILLED -- pinned with --created to the exact attempt.

Controller-visible windows: live W&B history for the run (rollout
reward / episode length, terminations/* per-window counts,
env/v_along_cmd_m_s, sparse eval/walk/* panels), bucketed into
report windows of max(1M steps, budget/16).

Safeguards:
  * rl_move/orchestrator/PRUNE_OFF disables all killing (audit still
    runs when invoked by hand; the watcher skips the pass entirely).
  * Only runs in --track (default: walkcurr) are ever considered.
  * A run whose W&B state is not 'running' is never touched.
  * --execute is required to kill; the default is a dry-run audit.

Usage:
  uv run python rl_move/orchestrator/seed_pruner.py --all [--execute]
  uv run python rl_move/orchestrator/seed_pruner.py --run <name> [--execute]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent          # prototype_sts3215/
LEDGER = HERE / "experiments.json"
PRUNE_OFF = HERE / "PRUNE_OFF"
WANDB_PROJECT = "l2k2/hexapod-balance"
POD_PROTO = "/workspace/prototype_sts3215"  # pods' tree (NOT the controller's)

MIN_WINDOW_STEPS = 1_000_000       # never judge on windows finer than this
WINDOWS_PER_BUDGET = 16            # window = max(MIN_WINDOW_STEPS, budget/16)
BURN_IN_FRAC = 0.25                # operator: protect >= 25% of budget
MIN_WINDOWS = 3                    # operator: 3 adjacent report windows
STOP_CONFIRM_TRIES = 5             # confirm-stop polls after kill
STOP_CONFIRM_SLEEP_S = 6.0


@dataclasses.dataclass
class Window:
    """One controller-visible report window (aggregated W&B rows).

    index/start/step are the bucket grid (index = global_step // win);
    obs_lo/obs_hi are the ACTUAL observed step bounds of the data rows
    inside the window -- evidence must never claim steps that were not
    observed.
    """
    index: int                     # bucket index on the window grid
    start: int                     # window start boundary (index * win)
    step: int                      # window end boundary ((index+1) * win)
    obs_lo: int = -1               # first observed global_step in window
    obs_hi: int = -1               # last observed global_step in window
    reward_ema: float | None = None
    v_along: float | None = None   # m/s along the commanded direction
    ep_len: float | None = None    # mean episode length (ticks)
    fall_rate: float | None = None  # tilt terminations / all episode ends
    eval_speed: float | None = None       # sparse eval/walk/speed_m_s
    eval_survived: float | None = None    # sparse eval/walk/survived_frac
    wrong_dir_frac: float | None = None   # sparse eval/walk/wrong_dir_frac


@dataclasses.dataclass
class Thresholds:
    # reward slope <= rel_eps * |ema| per window counts as negligible
    reward_slope_rel_eps: float = 0.002
    reward_slope_abs_eps: float = 1e-6
    v_along_eps: float = 0.002     # m/s
    ep_len_rel_eps: float = 0.02
    fall_rate_eps: float = 0.005
    frac_eps: float = 0.01         # survived/wrong-dir fracs
    collapse_min_fall_rate: float = 0.08
    collapse_fall_ratio: float = 2.0


@dataclasses.dataclass
class Decision:
    action: str                    # KEEP | KILL | KILL_COLLAPSE
    reason: str
    evidence: dict


def _slope_per_window(vals: list[float]) -> float:
    """Least-squares slope over the given window values (per window)."""
    n = len(vals)
    if n < 2:
        return 0.0
    xm = (n - 1) / 2.0
    ym = sum(vals) / n
    num = sum((i - xm) * (v - ym) for i, v in enumerate(vals))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0.0


def _last3(windows: list[Window], attr: str) -> list[float] | None:
    """The attr over the last 3 windows, or None if any is missing."""
    vals = [getattr(w, attr) for w in windows[-MIN_WINDOWS:]]
    if len(vals) < MIN_WINDOWS or any(v is None for v in vals):
        return None
    return vals


def _adjacent(windows: list[Window]) -> bool:
    """True iff the last MIN_WINDOWS windows have consecutive indices."""
    tail = windows[-MIN_WINDOWS:]
    if len(tail) < MIN_WINDOWS:
        return False
    idx = [w.index for w in tail]
    if any(i < 0 for i in idx):
        return False               # unknown grid position = uncertain
    return all(b == a + 1 for a, b in zip(idx, idx[1:]))


def decide(windows: list[Window], budget_steps: int,
           thr: Thresholds | None = None) -> Decision:
    """Pure decision function -- unit-tested, no I/O.

    `windows` must be COMPLETE report windows (partial/future windows
    already excluded by assemble_windows) in step order.
    """
    thr = thr or Thresholds()
    windows = sorted(windows, key=lambda w: w.index)
    if len(windows) < MIN_WINDOWS:
        return Decision("KEEP", f"insufficient windows "
                        f"({len(windows)} < {MIN_WINDOWS})", {})

    ev: dict = {"budget_steps": budget_steps,
                "last_step": windows[-1].step,
                "windows_used": [
                    {"index": w.index, "start": w.start, "end": w.step,
                     "obs_lo": w.obs_lo, "obs_hi": w.obs_hi}
                    for w in windows[-MIN_WINDOWS:]]}

    # ---- budget-complete guard: completion is never stagnation --------
    # Either observed steps reach the budget, or the complete windows
    # tile the whole budget (a complete final window requires data
    # observed through its end boundary): the flat tail of a FINISHED
    # optimization must never read as stagnation.
    obs_hi_all = max((w.obs_hi for w in windows), default=-1)
    if budget_steps > 0 and (obs_hi_all >= budget_steps
                             or windows[-1].step >= budget_steps):
        return Decision("KEEP", "budget complete: observed step "
                        f"{obs_hi_all} / complete windows through "
                        f"{windows[-1].step} vs planned budget "
                        f"{budget_steps}; a finished optimization is "
                        "never prunable", ev)

    # ---- adjacency: sparse telemetry is not evidence -------------------
    if not _adjacent(windows):
        idx = [w.index for w in windows[-MIN_WINDOWS:]]
        return Decision("KEEP", "last 3 report windows are not adjacent "
                        f"(bucket indices {idx}); sparse telemetry is "
                        "not stagnation evidence -- refusing to judge", ev)

    # ---- reward trend over the last 3 windows -------------------------
    rew = _last3(windows, "reward_ema")
    reward_improving = False
    reward_slope = None
    if rew is not None:
        reward_slope = _slope_per_window(rew)
        scale = abs(sum(rew) / len(rew))
        neg = max(thr.reward_slope_abs_eps, thr.reward_slope_rel_eps * scale)
        reward_improving = reward_slope > neg
        ev["reward_ema_last3"] = [round(v, 4) for v in rew]
        ev["reward_slope_per_window"] = round(reward_slope, 6)
        ev["reward_negligible_below"] = round(neg, 6)

    # ---- behavioral series: improving / regressing per axis -----------
    improving: list[str] = []
    regressing: list[str] = []

    def trend(attr: str, eps: float, up_is_good: bool,
              rel: bool = False) -> None:
        vals = _last3(windows, attr)
        if vals is None:
            return
        e = eps * abs(vals[0]) if rel else eps
        e = max(e, 1e-9)
        delta = vals[-1] - vals[0]
        good = delta > e if up_is_good else delta < -e
        bad = delta < -e if up_is_good else delta > e
        ev[f"{attr}_last3"] = [round(v, 4) for v in vals]
        if good:
            improving.append(attr)
        elif bad:
            regressing.append(attr)

    trend("v_along", thr.v_along_eps, up_is_good=True)
    trend("ep_len", thr.ep_len_rel_eps, up_is_good=True, rel=True)
    trend("fall_rate", thr.fall_rate_eps, up_is_good=False)
    trend("eval_speed", thr.v_along_eps, up_is_good=True)
    trend("eval_survived", thr.frac_eps, up_is_good=True)
    trend("wrong_dir_frac", thr.frac_eps, up_is_good=False)
    ev["behavior_improving"] = improving
    ev["behavior_regressing"] = regressing

    # ---- learning-valley veto: ANY improvement -> keep -----------------
    if reward_improving or improving:
        return Decision("KEEP", "improving (learning-valley veto): "
                        f"reward_improving={reward_improving}, "
                        f"behavior={improving}", ev)

    # ---- immediate collapse kills (no burn-in protection) --------------
    v3 = _last3(windows, "v_along")
    if v3 is not None and all(v < 0 for v in v3):
        return Decision(
            "KILL_COLLAPSE",
            "persistently wrong-direction velocity: v_along < 0 in "
            f"{MIN_WINDOWS} adjacent windows ({[round(v,4) for v in v3]})"
            " with no improvement", ev)
    f3 = _last3(windows, "fall_rate")
    if (f3 is not None and f3[0] < f3[1] < f3[2]
            and f3[-1] >= thr.collapse_min_fall_rate
            and f3[-1] >= thr.collapse_fall_ratio * max(f3[0], 1e-9)
            and rew is not None and reward_slope is not None
            and reward_slope <= 0):
        return Decision(
            "KILL_COLLAPSE",
            "rising terminations: fall_rate strictly rising "
            f"({[round(v,4) for v in f3]}) with non-positive reward slope "
            f"({reward_slope:.6f}/window)", ev)

    # ---- burn-in-protected slope prune ---------------------------------
    burn_in = int(BURN_IN_FRAC * budget_steps)
    ev["burn_in_steps"] = burn_in
    tail = windows[-MIN_WINDOWS:]
    if not all(w.start >= burn_in for w in tail):
        starts = [w.start for w in tail]
        return Decision("KEEP", "burn-in protection: the 3 deciding "
                        f"windows must lie ENTIRELY past burn-in "
                        f"{burn_in} of {budget_steps} (window starts "
                        f"{starts})", ev)
    if rew is None:
        return Decision("KEEP", "no reward series in last 3 windows", ev)
    if reward_slope is not None and not reward_improving:
        # reward flat/negative AND no behavioral axis improving; require
        # at least one behavioral axis actually observed so we never
        # prune on reward alone.
        observed = [k for k in ("v_along", "ep_len", "fall_rate",
                                "eval_speed", "eval_survived",
                                "wrong_dir_frac")
                    if _last3(windows, k) is not None]
        if not observed:
            return Decision("KEEP", "no behavioral series visible; "
                            "refusing to prune on reward alone", ev)
        return Decision(
            "KILL",
            "post-burn-in stagnation: reward EMA slope "
            f"{reward_slope:.6f}/window (negligible) and no behavioral "
            f"improvement across {observed} "
            f"(regressing: {regressing or 'none'})", ev)
    return Decision("KEEP", "no rule fired", ev)


# ---------------------------------------------------------------------------
# Window assembly (pure part unit-tested; W&B fetch is thin I/O)
# ---------------------------------------------------------------------------

def assemble_windows(budget_steps: int,
                     rew: list[dict],
                     eplen: list[dict] = (),
                     vals: list[dict] = (),
                     term: list[dict] = (),
                     evalw: list[dict] = ()) -> list[Window]:
    """Bucket raw W&B history rows into COMPLETE report windows.

    Pure and unit-tested. Rules (operator repair 2026-09-07 PM):
      * window width = max(MIN_WINDOW_STEPS, budget/16);
      * bucket index = global_step // win, NO clamping into a last
        bucket (the old clamp let overflow rows invent future windows);
      * a window is included only if it is COMPLETE: its end boundary
        (index+1)*win <= the last observed step across ALL series --
        partial/future windows are excluded;
      * each window records its actual observed step bounds
        (obs_lo/obs_hi).
    """
    rew = [h for h in rew if h.get("global_step") is not None
           and h.get("rollout/ep_rew_mean") is not None]
    if not rew:
        return []
    win = max(MIN_WINDOW_STEPS,
              (budget_steps // WINDOWS_PER_BUDGET) if budget_steps > 0
              else 0)

    all_steps = [h["global_step"] for series in (rew, eplen, vals, term,
                                                 evalw)
                 for h in series if h.get("global_step") is not None]
    last_obs = max(all_steps)

    # EMA over the raw reward series (halflife ~ one window)
    ema, alpha = None, 0.3
    rew_ema: list[tuple[int, float]] = []
    for h in rew:
        v = h["rollout/ep_rew_mean"]
        ema = v if ema is None else alpha * v + (1 - alpha) * ema
        rew_ema.append((h["global_step"], ema))

    obs_lo: dict[int, int] = {}
    obs_hi: dict[int, int] = {}
    for s in all_steps:
        i = int(s // win)
        obs_lo[i] = min(obs_lo.get(i, s), s)
        obs_hi[i] = max(obs_hi.get(i, s), s)

    def bucket(pairs) -> dict[int, float]:
        acc: dict[int, list[float]] = {}
        for s, v in pairs:
            if v is None or s is None:
                continue
            acc.setdefault(int(s // win), []).append(v)
        return {k: sum(v) / len(v) for k, v in acc.items()}

    b_rew = bucket(rew_ema)
    b_len = bucket([(h.get("global_step"), h.get("rollout/ep_len_mean"))
                    for h in eplen])
    b_val = bucket([(h.get("global_step"), h.get("env/v_along_cmd_m_s"))
                    for h in vals])
    fr = []
    for h in term:
        falls = (h.get("terminations/tilt_roll") or 0) + \
                (h.get("terminations/tilt_pitch") or 0)
        total = falls + (h.get("terminations/truncated") or 0)
        if total > 0:
            fr.append((h.get("global_step"), falls / total))
    b_fall = bucket(fr)
    b_espd = bucket([(h.get("global_step"), h.get("eval/walk/speed_m_s"))
                     for h in evalw])
    b_esrv = bucket([(h.get("global_step"), h.get("eval/walk/survived_frac"))
                     for h in evalw])
    b_ewrd = bucket([(h.get("global_step"), h.get("eval/walk/wrong_dir_frac"))
                     for h in evalw])

    windows = []
    for i in sorted(b_rew):
        if (i + 1) * win > last_obs:
            continue               # partial/future window: never evidence
        windows.append(Window(
            index=i, start=i * win, step=(i + 1) * win,
            obs_lo=obs_lo.get(i, -1), obs_hi=obs_hi.get(i, -1),
            reward_ema=b_rew.get(i),
            v_along=b_val.get(i), ep_len=b_len.get(i),
            fall_rate=b_fall.get(i), eval_speed=b_espd.get(i),
            eval_survived=b_esrv.get(i), wrong_dir_frac=b_ewrd.get(i)))
    return windows


def _series(run, keys: list[str]) -> list[dict]:
    try:
        return [h for h in run.history(keys=keys + ["global_step"],
                                       samples=1000, pandas=False)
                if h.get("global_step") is not None]
    except Exception:
        return []


def _summary_steps(summary) -> int:
    """Best available 'how many env steps has this run consumed'."""
    out = 0
    for k in ("time/total_env_steps", "global_step"):
        try:
            v = summary.get(k)
        except Exception:
            v = None
        if isinstance(v, (int, float)):
            out = max(out, int(v))
    return out


class AttemptIdentityError(RuntimeError):
    """The W&B run behind wandb_id does not match the ledger attempt."""


def _wandb_run_by_id(entry: dict):
    """Fetch the exact W&B run for this ledger attempt by wandb_id.

    Display-name matching was a verified bug (retries/duplicates share a
    name); the ledger wandb_id pins the attempt. The fetched run's name
    must still equal the ledger run name or we refuse to judge.
    """
    import wandb
    api = wandb.Api()
    run = api.run(f"{WANDB_PROJECT}/{entry['wandb_id']}")
    if run.name != entry["run"]:
        raise AttemptIdentityError(
            f"wandb_id {entry['wandb_id']} has display name {run.name!r}, "
            f"ledger says {entry['run']!r}")
    return run


def fetch_windows(entry: dict, budget_steps: int
                  ) -> tuple[list[Window], str, int]:
    """Build report windows from live W&B history for the PINNED attempt.

    Returns (windows, state, summary_steps). Raises on fetch/identity
    problems -- the caller treats any exception as SKIP (never kill on
    missing/uncertain evidence).
    """
    run = _wandb_run_by_id(entry)
    state = run.state
    steps = _summary_steps(run.summary)

    rew = _series(run, ["rollout/ep_rew_mean"])
    eplen = _series(run, ["rollout/ep_len_mean"])
    vals = _series(run, ["env/v_along_cmd_m_s"])
    term = _series(run, ["terminations/tilt_roll", "terminations/tilt_pitch",
                         "terminations/truncated"])
    evalw = _series(run, ["eval/walk/speed_m_s", "eval/walk/survived_frac"])

    windows = assemble_windows(budget_steps, rew, eplen, vals, term, evalw)
    return windows, state, steps


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def _running_entries(track: str) -> list[dict]:
    led = json.loads(LEDGER.read_text())
    by_run: dict[str, dict] = {}
    for e in led:
        if e.get("run"):
            by_run[e["run"]] = e  # newest entry wins
    out = []
    for e in by_run.values():
        if e.get("status") != "RUNNING":
            continue
        if track and e.get("track") != track:
            continue
        if e.get("smoke"):
            continue
        out.append(e)
    return out


def _budget(entry: dict) -> int:
    try:
        if entry.get("steps"):
            return int(entry["steps"])
    except (TypeError, ValueError):
        pass
    cmd = entry.get("command") or ""
    for tok in ("--steps ", "--steps="):
        if tok in cmd:
            try:
                return int(cmd.split(tok, 1)[1].split()[0])
            except (ValueError, IndexError):
                pass
    return 0


# --- kill-path seams (each monkeypatchable in tests) -----------------------

# Exact-token trainer match (same rule as ops.sh killrun: only
# "--run-name <run>", never a bare substring; skip the scanner itself).
_MATCH_CASE = ('*"--run-name $1 "*|*"--run-name=$1 "*'
               '|*"--run-name $1"|*"--run-name=$1"')

_SCAN_SH = r'''
for d in /proc/[0-9]*; do
  p=${d#/proc/}; [ "$p" = "$$" ] && continue
  c=$(tr "\0" " " < "$d/cmdline" 2>/dev/null)
  case "$c" in
    *"--run-name $1 "*|*"--run-name=$1 "*|*"--run-name $1"|*"--run-name=$1")
      st=$(sed 's/^.*) //' "$d/stat" 2>/dev/null | cut -d' ' -f20)
      [ -n "$st" ] && echo "PIN $p $st";;
  esac
done
exit 0
'''

_KILL_SH = r'''
run="$1"; shift
rc=0
for pair in "$@"; do
  pid=${pair%%:*}; st=${pair##*:}
  cur=$(sed 's/^.*) //' "/proc/$pid/stat" 2>/dev/null | cut -d' ' -f20)
  if [ -z "$cur" ]; then echo "GONE $pid"; continue; fi
  if [ "$cur" != "$st" ]; then echo "IDENTITY_CHANGED $pid"; rc=1; continue; fi
  c=$(tr "\0" " " < "/proc/$pid/cmdline" 2>/dev/null)
  case "$c" in
    *"--run-name $run "*|*"--run-name=$run "*|*"--run-name $run"|*"--run-name=$run") ;;
    *) echo "CMD_MISMATCH $pid"; rc=1; continue;;
  esac
  if kill "$pid" 2>/dev/null; then echo "KILLED $pid"; else echo "KILLFAIL $pid"; rc=1; fi
done
exit $rc
'''

_HANDOFF_SH = r'''
f="%s/rl_move/sim/policies/artifact_handoff/$1/state.json"
if [ -f "$f" ]; then cat "$f"; else echo "__NO_HANDOFF__"; fi
''' % POD_PROTO


def _kubectl_exec(pod: str, script: str, args: list[str],
                  timeout: float = 90.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl", "exec", pod, "--", "bash", "-c", script, "_"] + args,
        capture_output=True, text=True, timeout=timeout)


def _pin_procs(pod: str, run: str) -> list[tuple[int, int]] | None:
    """Live trainer PIDs + /proc start-time identity, or None on failure."""
    try:
        r = _kubectl_exec(pod, _SCAN_SH, [run])
    except Exception:
        return None
    if r.returncode != 0:
        return None
    out = []
    for ln in (r.stdout or "").splitlines():
        parts = ln.split()
        if len(parts) == 3 and parts[0] == "PIN":
            try:
                out.append((int(parts[1]), int(parts[2])))
            except ValueError:
                return None        # unparseable identity = uncertain
    return out


def _kill_procs(pod: str, run: str, pairs: list[tuple[int, int]]
                ) -> tuple[bool, list[int], list[int]]:
    """SIGTERM exactly the pinned (pid, starttime) trainer processes.

    Returns (ok, killed_pids, failed_pids). ok is False on ANY
    kill/kubectl failure or identity mismatch -- a failed kill command
    must never be ignored.
    """
    args = [run] + [f"{p}:{s}" for p, s in pairs]
    try:
        r = _kubectl_exec(pod, _KILL_SH, args)
    except Exception:
        return False, [], [p for p, _ in pairs]
    killed, failed = [], []
    for ln in (r.stdout or "").splitlines():
        parts = ln.split()
        if len(parts) != 2:
            continue
        tag, pid = parts[0], parts[1]
        if tag in ("KILLED", "GONE"):
            killed.append(int(pid))
        elif tag in ("KILLFAIL", "IDENTITY_CHANGED", "CMD_MISMATCH"):
            failed.append(int(pid))
    ok = (r.returncode == 0) and not failed and len(killed) == len(pairs)
    return ok, killed, failed


def _procs_alive(pod: str, run: str) -> bool | None:
    """Any live --run-name match left? None = could not determine."""
    pins = _pin_procs(pod, run)
    if pins is None:
        return None
    return bool(pins)


def _handoff_phase(pod: str, run: str) -> str | None:
    """Deferred-artifacts registry phase on the run's pod.

    None = no handoff dir (run not deferred). 'ERROR' = could not read
    (uncertain -> caller must refuse to kill).
    """
    try:
        r = _kubectl_exec(pod, _HANDOFF_SH, [run])
    except Exception:
        return "ERROR"
    if r.returncode != 0:
        return "ERROR"
    out = (r.stdout or "").strip()
    if out == "__NO_HANDOFF__":
        return None
    try:
        return json.loads(out).get("phase") or "ERROR"
    except Exception:
        return "ERROR"


def _reload_entry(run: str, created: str) -> dict | None:
    """Fresh ledger read of the EXACT attempt (run + created)."""
    try:
        led = json.loads(LEDGER.read_text())
    except Exception:
        return None
    ms = [e for e in led if e.get("run") == run
          and e.get("created") == created]
    return ms[-1] if ms else None


def _wandb_state_steps(entry: dict) -> tuple[str, int]:
    run = _wandb_run_by_id(entry)
    return run.state, _summary_steps(run.summary)


def _mark_killed(run: str, created: str, verdict: str) -> bool:
    r = subprocess.run(
        [sys.executable, str(HERE / "launch_run.py"), "update",
         "--run", run, "--created", created,
         "--set", "status=KILLED", "--set", f"verdict={verdict}"],
        cwd=REPO, timeout=180)
    return r.returncode == 0


def _kill(entry: dict, dec: Decision, budget: int) -> bool:
    """Targeted, revalidated kill of ONE pinned attempt.

    Never writes KILLED unless the stop is confirmed; any uncertainty
    aborts with no ledger write (operator repair 2026-09-07 PM).
    """
    run = entry.get("run")
    created = entry.get("created")
    wandb_id = entry.get("wandb_id")
    pod = entry.get("pod")

    def abort(msg: str) -> bool:
        print(f"{run}: KILL ABORTED -- {msg}; no ledger write "
              "(never kill on missing/uncertain evidence)")
        return False

    if not (run and created and wandb_id and pod):
        return abort("attempt not pinnable (missing "
                     "run/created/wandb_id/pod)")

    # 1. ledger revalidation: the EXACT attempt must still match
    fresh = _reload_entry(run, created)
    if fresh is None:
        return abort(f"no ledger attempt with created={created}")
    if fresh.get("status") != "RUNNING":
        return abort(f"attempt status is now {fresh.get('status')!r}")
    if fresh.get("wandb_id") != wandb_id or fresh.get("pod") != pod:
        return abort("attempt identity changed (wandb_id/pod) -- "
                     "concurrent relaunch?")

    # 2. W&B revalidation just before termination
    try:
        state, steps = _wandb_state_steps(entry)
    except Exception as exc:
        return abort(f"wandb revalidation failed: {exc!r}")
    if state != "running":
        return abort(f"wandb state is now {state!r}")
    if budget > 0 and steps >= budget:
        return abort(f"budget complete ({steps} >= {budget} observed "
                     "steps); finished optimization is never prunable")

    # 3. deferred-artifacts registry: past training = CPU finalizer only
    phase = _handoff_phase(pod, run)
    if phase == "ERROR":
        return abort("could not read deferred-artifacts registry")
    if phase is not None and phase != "training":
        return abort(f"deferred-artifacts phase={phase!r}: GPU training "
                     "is over; only the CPU finalizer remains")

    # 4. pin the live trainer processes (pid + start-time identity)
    pairs = _pin_procs(pod, run)
    if pairs is None:
        return abort("trainer process scan failed")
    if not pairs:
        return abort("no live trainer process matches --run-name "
                     f"{run} on {pod}")

    # 5. targeted kill; command failure is failure
    ok, killed, failed = _kill_procs(pod, run, pairs)
    if not ok:
        return abort(f"kill command failed (killed={killed}, "
                     f"failed={failed})")

    # 6. confirm the stop before any ledger write
    stopped = False
    for _ in range(STOP_CONFIRM_TRIES):
        time.sleep(STOP_CONFIRM_SLEEP_S)
        alive = _procs_alive(pod, run)
        if alive is False:
            stopped = True
            break
    if not stopped:
        return abort("trainer still alive (or unverifiable) after kill")

    # 7. update ONLY the exact pinned attempt
    verdict = ("SEED-PRUNED (mechanical, operator rule 2026-09-07): "
               f"{dec.reason}. Evidence: {json.dumps(dec.evidence)}. "
               f"Pinned attempt: wandb_id={wandb_id}, created={created}, "
               f"pod={pod}, trainer pids/starttimes="
               f"{[f'{p}:{s}' for p, s in pairs]}; stop confirmed. "
               "Checkpoint and logs retained; only the training job was "
               "stopped.")
    if not _mark_killed(run, created, verdict):
        # one retry -- trainer is already dead; a stale RUNNING row would
        # otherwise linger for the watcher checkup to find.
        if not _mark_killed(run, created, verdict):
            print(f"{run}: ERROR -- trainer stopped but ledger update "
                  "FAILED twice; row left for watcher checkup")
            return False
    print(f"KILLED {run} (attempt created={created}): {dec.reason}")
    return True


def audit(run_names: list[str] | None, track: str, execute: bool,
          as_json: bool = False) -> int:
    if run_names:
        led = json.loads(LEDGER.read_text())
        entries = [e for e in led if e.get("run") in run_names
                   and e.get("status") == "RUNNING"]
        # newest entry per run
        entries = list({e["run"]: e for e in entries}.values())
    else:
        entries = _running_entries(track)
    if not entries:
        print("seed_pruner: no RUNNING entries in scope")
        return 0
    for e in entries:
        run = e["run"]
        budget = _budget(e)
        if budget <= 0:
            print(f"{run}: SKIP (no planned budget in ledger)")
            continue
        if not (e.get("wandb_id") and e.get("created") and e.get("pod")):
            print(f"{run}: SKIP (attempt not pinnable: missing "
                  "wandb_id/created/pod in ledger)")
            continue
        try:
            windows, state, steps = fetch_windows(e, budget)
        except Exception as exc:
            print(f"{run}: SKIP (wandb fetch failed: {exc!r})")
            continue
        if state != "running":
            print(f"{run}: SKIP (wandb state={state}; not a live "
                  "training job)")
            continue
        if steps >= budget:
            print(f"{run}: SKIP (budget complete: {steps} >= {budget} "
                  "steps observed; stale RUNNING row is the watcher's "
                  "to reconcile, never the pruner's to kill)")
            continue
        if not windows:
            print(f"{run}: SKIP (no complete report windows yet)")
            continue
        dec = decide(windows, budget)
        line = f"{run}: {dec.action} -- {dec.reason}"
        print(line if not as_json else json.dumps(
            {"run": run, "action": dec.action, "reason": dec.reason,
             "evidence": dec.evidence}))
        if dec.action.startswith("KILL"):
            if PRUNE_OFF.exists():
                print(f"{run}: kill suppressed (PRUNE_OFF exists)")
            elif not execute:
                print(f"{run}: dry-run (pass --execute to kill)")
            else:
                _kill(e, dec, budget)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", action="append",
                    help="audit specific run(s) (repeatable)")
    ap.add_argument("--all", action="store_true",
                    help="audit every RUNNING run in --track")
    ap.add_argument("--track", default="walkcurr",
                    help="ledger track scope for --all (default walkcurr)")
    ap.add_argument("--execute", action="store_true",
                    help="actually kill qualifying runs (default: dry-run)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()
    if not a.run and not a.all:
        ap.error("need --run or --all")
    return audit(a.run, a.track, a.execute, a.as_json)


if __name__ == "__main__":
    sys.exit(main())
