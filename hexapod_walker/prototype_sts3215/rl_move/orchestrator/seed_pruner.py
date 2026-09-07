#!/usr/bin/env python3
"""Mechanical seed pruning for RUNNING training seeds (operator order,
2026-09-07 focus note).

Plain English: while several seeds of the same recipe train in parallel,
a seed that has stopped learning (flat reward AND flat/regressing
behavior) or has obviously collapsed (rising terminations, persistently
wrong-direction velocity) should be killed mechanically so the GPU goes
back to the queue -- WITHOUT killing seeds that are merely in a learning
valley, and WITHOUT touching anything before it has had a fair burn-in.

Decision rule (operator-specified, binding):
  * Burn-in protection: the slope-based prune may only fire after the
    run has consumed >= 25% of its planned budget, and only with >= 3
    consecutive controller-visible report windows entirely past that
    burn-in point.
  * Slope prune: reward EMA slope non-positive/negligible AND behavioral
    progress non-improving (velocity along command, gait/eval validity,
    episode length, falls/terminations -- none improving, at least one
    flat or regressing).
  * Immediate collapse kill (needs 3 consecutive windows of evidence but
    no burn-in protection): rising terminations, or persistently
    wrong-direction velocity.
  * Learning-valley veto: if EITHER reward or ANY behavioral series is
    improving beyond its noise epsilon, never kill.
  * On kill: stop ONLY that run's training procs (ops.sh killrun),
    retain checkpoint/logs, record KILLED + exact metric evidence in the
    ledger (launch_run.py update).

Controller-visible windows: live W&B history for the run (rollout
reward / episode length, terminations/* per-window counts,
env/v_along_cmd_m_s, sparse eval/walk/* panels), bucketed into
report windows of max(1M steps, budget/16).

Safeguards:
  * rl_move/orchestrator/PRUNE_OFF disables all killing (audit still runs).
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

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent          # prototype_sts3215/
LEDGER = HERE / "experiments.json"
PRUNE_OFF = HERE / "PRUNE_OFF"
WANDB_PROJECT = "l2k2/hexapod-balance"

MIN_WINDOW_STEPS = 1_000_000       # never judge on windows finer than this
WINDOWS_PER_BUDGET = 16            # window = max(MIN_WINDOW_STEPS, budget/16)
BURN_IN_FRAC = 0.25                # operator: protect >= 25% of budget
MIN_WINDOWS = 3                    # operator: 3 consecutive report windows


@dataclasses.dataclass
class Window:
    """One controller-visible report window (aggregated W&B rows)."""
    step: int                      # env-step at window end
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


def decide(windows: list[Window], budget_steps: int,
           thr: Thresholds | None = None) -> Decision:
    """Pure decision function -- unit-tested, no I/O.

    `windows` must be consecutive report windows in step order.
    """
    thr = thr or Thresholds()
    if len(windows) < MIN_WINDOWS:
        return Decision("KEEP", f"insufficient windows "
                        f"({len(windows)} < {MIN_WINDOWS})", {})

    ev: dict = {"budget_steps": budget_steps,
                "last_step": windows[-1].step,
                "windows_used": [w.step for w in windows[-MIN_WINDOWS:]]}

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
            f"{MIN_WINDOWS} consecutive windows ({[round(v,4) for v in v3]})"
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
    post = [w for w in windows if w.step > burn_in]
    if windows[-1].step < burn_in or len(post) < MIN_WINDOWS:
        return Decision("KEEP", "burn-in protection: "
                        f"{len(post)} post-burn-in windows < {MIN_WINDOWS} "
                        f"(burn-in {burn_in} of {budget_steps})", ev)
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
# W&B window assembly (I/O; not unit-tested)
# ---------------------------------------------------------------------------

def _series(run, keys: list[str]) -> list[dict]:
    try:
        return [h for h in run.history(keys=keys + ["global_step"],
                                       samples=1000, pandas=False)
                if h.get("global_step") is not None]
    except Exception:
        return []


def fetch_windows(run_name: str, budget_steps: int) -> tuple[list[Window], str]:
    """Build report windows from live W&B history. Returns (windows, state)."""
    import wandb
    api = wandb.Api()
    runs = list(api.runs(WANDB_PROJECT, filters={"display_name": run_name}))
    if not runs:
        return [], "absent"
    run = runs[-1] if len(runs) > 1 else runs[0]
    state = run.state

    rew = _series(run, ["rollout/ep_rew_mean"])
    eplen = _series(run, ["rollout/ep_len_mean"])
    vals = _series(run, ["env/v_along_cmd_m_s"])
    term = _series(run, ["terminations/tilt_roll", "terminations/tilt_pitch",
                         "terminations/truncated"])
    evalw = _series(run, ["eval/walk/speed_m_s", "eval/walk/survived_frac"])

    if not rew:
        return [], state

    # EMA over the raw reward series (halflife ~ one window)
    win = max(MIN_WINDOW_STEPS, budget_steps // WINDOWS_PER_BUDGET)
    ema, alpha = None, 0.3
    rew_ema = []
    for h in rew:
        v = h["rollout/ep_rew_mean"]
        ema = v if ema is None else alpha * v + (1 - alpha) * ema
        rew_ema.append((h["global_step"], ema))

    last_step = max(s for s, _ in rew_ema)
    n_win = max(1, (last_step + win - 1) // win)

    def bucket(pairs: list[tuple[int, float]]) -> dict[int, float]:
        acc: dict[int, list[float]] = {}
        for s, v in pairs:
            if v is None:
                continue
            acc.setdefault(min(int(s // win), n_win - 1), []).append(v)
        return {k: sum(v) / len(v) for k, v in acc.items()}

    b_rew = bucket(rew_ema)
    b_len = bucket([(h["global_step"], h.get("rollout/ep_len_mean"))
                    for h in eplen])
    b_val = bucket([(h["global_step"], h.get("env/v_along_cmd_m_s"))
                    for h in vals])
    fr = []
    for h in term:
        falls = (h.get("terminations/tilt_roll") or 0) + \
                (h.get("terminations/tilt_pitch") or 0)
        total = falls + (h.get("terminations/truncated") or 0)
        if total > 0:
            fr.append((h["global_step"], falls / total))
    b_fall = bucket(fr)
    b_espd = bucket([(h["global_step"], h.get("eval/walk/speed_m_s"))
                     for h in evalw])
    b_esrv = bucket([(h["global_step"], h.get("eval/walk/survived_frac"))
                     for h in evalw])

    windows = []
    for i in sorted(b_rew):
        windows.append(Window(
            step=(i + 1) * win, reward_ema=b_rew.get(i),
            v_along=b_val.get(i), ep_len=b_len.get(i),
            fall_rate=b_fall.get(i), eval_speed=b_espd.get(i),
            eval_survived=b_esrv.get(i)))
    return windows, state


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


def _kill(entry: dict, dec: Decision) -> None:
    run = entry["run"]
    subprocess.run(["bash", str(HERE / "ops.sh"), "killrun", run],
                   cwd=REPO, timeout=120)
    verdict = ("SEED-PRUNED (mechanical, operator rule 2026-09-07): "
               f"{dec.reason}. Evidence: {json.dumps(dec.evidence)}. "
               "Checkpoint and logs retained; only the training job was "
               "stopped.")
    subprocess.run([sys.executable, str(HERE / "launch_run.py"), "update",
                    "--run", run, "--set", "status=KILLED",
                    "--set", f"verdict={verdict}"],
                   cwd=REPO, timeout=120)
    print(f"KILLED {run}: {dec.reason}")


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
    results = []
    for e in entries:
        run = e["run"]
        budget = _budget(e)
        if budget <= 0:
            print(f"{run}: SKIP (no planned budget in ledger)")
            continue
        try:
            windows, state = fetch_windows(run, budget)
        except Exception as exc:
            print(f"{run}: SKIP (wandb fetch failed: {exc!r})")
            continue
        if state != "running":
            print(f"{run}: SKIP (wandb state={state}; not a live "
                  "training job)")
            continue
        dec = decide(windows, budget)
        results.append((run, dec))
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
                _kill(e, dec)
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
