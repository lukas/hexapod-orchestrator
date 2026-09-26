#!/usr/bin/env python3
"""Parallel fresh-draw rate eval of a checkpoint vs its parent, ON A TRAINING POD.

    uv run python orchestrator/pod_rate_eval.py <run> [--parent auto|<run>|none]
        [--n 96] [--workers 16] [--pod POD] [--scripted] [--dry-run]
    ops.sh rateeval <run> [...]           # same thing from the operator Mac

WHY (Lukas, 2026-09-26): the standard post-training panel scores gait_valid
as a bare 6-episode count over ONE fixed eval seed. At the per-leg
asymmetry ceilings about half of all draws lose a foot for ANY controller,
so a 6-count has a ~20 pp standard error -- "3/6" was read as a wall for a
day, and it took n=100..150 probes to show that trained and untrained
checkpoints are indistinguishable there. Those probes were single-process
(~2.3x real time, 15-25 min). A training pod has 26-28 cores and its
trainer lives on the GPU, so W niced single-process evals with W DIFFERENT
seeds give W*per_mode fresh draws in about the time of one 6-episode panel.

WHAT IT DOES (mirrors pod_eval.py's contract):
  1. Reads the child run's ledger entry: pod, task, cfg-sets, episode
     seconds, checkpoint (launch_run --out-name convention).
  2. Resolves the parent = the child's own --init-from checkpoint (resident
     on the pod because the child warm-started from it); refuses the parent
     leg when the child changed the observation layout (--obs-pad-transplant,
     new obs.* cfg keys) so a width error cannot masquerade as a result.
  3. Picks a pod: the child's pod if no trainer is live there, else the
     first idle GPU pod; caps workers at 6 next to a live trainer (the
     SUSPECT-fps incidents of 08-31..09-01 were eval contention), 16 idle.
  4. Writes ONE bash script per pod (every worker `nice -n 19 ... &`, then
     `wait`), copies it over, runs it detached, polls for report.json.
     Seeds 1..W (seed 0 is the fixed reference panel every ledger verdict
     already cites; --include-seed0 adds it deliberately). The parent runs
     the IDENTICAL seeds and cfg, so per-episode identity is reported too.
  5. Copies the reports back to <PROTO>/logs/ckpt_eval/rate_<run>_n<N>/ and
     merges them with rl_move.sim.gait_valid_rate (Wilson CI, pooled
     two-proportion z) into summary.json + one summary line.

It REPORTS; cycles decide. Nothing here is a gate.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import shlex
import statistics
import subprocess
import sys
import time

os.environ.setdefault(
    "KUBECONFIG", str(pathlib.Path.home() / ".kube" / "coreweave.yaml"))
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from roots import PROTO  # noqa: E402

POD_PROTO = "/workspace/prototype_sts3215"
MODE = "walk/det"
TEACHER_FLAGS = ("--compose-turn-blend-s 0.0 --stall-substitute-every-s 0.02 "
                 "--stall-substitute-dur-s 100")
EVAL_KEYS_DROP = ("goal.mode_seq", "goal.walk_residual", "env.dr_stage_ramp_steps")
SCHED_KEYS = {"sched.key", "sched.v0", "sched.v1", "sched.t0_steps",
              "sched.t1_steps", "sched.n_envs"}


# --------------------------------------------------------------------- stats
def _stats():
    """rl_move.sim.gait_valid_rate if the hexapod tree has it (so numbers
    match the controller's verdict text), else the same formulas inline."""
    try:
        sys.path.insert(0, str(PROTO))
        from rl_move.sim import gait_valid_rate as g  # type: ignore
        return g.wilson_interval, g.two_proportion_z_test
    except Exception:  # pragma: no cover - exercised only off-controller
        def wilson_interval(k, n, z=1.96):
            if n <= 0:
                return (float("nan"),) * 3
            p = k / n
            denom = 1.0 + z * z / n
            center = (p + z * z / (2 * n)) / denom
            half = (z * math.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n)))) / denom
            return (p, max(0.0, center - half), min(1.0, center + half))

        def two_proportion_z_test(k1, n1, k2, n2):
            if n1 <= 0 or n2 <= 0:
                return (float("nan"), float("nan"))
            p1, p2 = k1 / n1, k2 / n2
            pp = (k1 + k2) / (n1 + n2)
            var = pp * (1 - pp) * (1.0 / n1 + 1.0 / n2)
            if var <= 0:
                return (0.0, 1.0) if p1 == p2 else (float("inf"), 0.0)
            z = (p1 - p2) / math.sqrt(var)
            return (z, math.erfc(abs(z) / math.sqrt(2.0)))
        return wilson_interval, two_proportion_z_test


# ------------------------------------------------------------- pure helpers
def split_episodes(n: int, workers: int) -> list[int]:
    """Episodes per worker: as even as possible, no empty worker, sum == n."""
    workers = max(1, min(int(workers), int(n)))
    base, rem = divmod(int(n), workers)
    return [base + (1 if i < rem else 0) for i in range(workers)]


def worker_seeds(workers: int, include_seed0: bool = False) -> list[int]:
    start = 0 if include_seed0 else 1
    return list(range(start, start + workers))


def eval_cfgs(extra_args: list[str], drv: float) -> list[str]:
    """The child's --cfg-set pairs as the eval should see them: drop the
    trainer-only keys pod_eval also drops, then the DR-stage ramp (an eval
    judges the FULL ranges; pod_eval's strip helper does the same)."""
    cfgs = [extra_args[i + 1] for i, a in enumerate(extra_args)
            if a == "--cfg-set" and i + 1 < len(extra_args)]
    out = []
    for c in cfgs:
        key = c.split("=", 1)[0].strip()
        if key.startswith(EVAL_KEYS_DROP) or key in SCHED_KEYS:
            continue
        out.append(c)
    return out


def arg_val(extra_args: list[str], flag: str, default=None):
    if flag in extra_args:
        i = extra_args.index(flag)
        if i + 1 < len(extra_args):
            return extra_args[i + 1]
    for a in extra_args:
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return default


def obs_layout_keys(cfgs: list[str]) -> dict[str, str]:
    """cfg-set keys that change the observation width/layout."""
    out = {}
    for c in cfgs:
        k, _, v = c.partition("=")
        k = k.strip()
        if k.startswith("obs.") or k in ("goal.walk_yaw_cmd", "goal.walk_phase_obs"):
            out[k] = v.strip()
    return out


def parent_compatible(child_args: list[str], parent_args: list[str] | None) -> tuple[bool, str]:
    """Can the child's --init-from checkpoint be evaluated under the child's
    cfg? Not when the child widened/reordered the observation."""
    if any(a.startswith("--obs-pad-transplant") or a.startswith("--hist-stride-transplant")
           for a in child_args):
        return False, "child used an obs transplant (--obs-pad-transplant); parent width differs"
    if parent_args is None:
        return True, "parent ledger entry not found; obs keys unchecked"
    c = obs_layout_keys(eval_cfgs(child_args, 1.0))
    p = obs_layout_keys(eval_cfgs(parent_args, 1.0))
    diff = {k: (p.get(k), v) for k, v in c.items() if p.get(k) != v}
    diff.update({k: (v, c.get(k)) for k, v in p.items() if k not in c})
    if diff:
        return False, f"child changes obs layout vs parent: {diff}"
    return True, "obs layout unchanged"


def build_worker_cmd(ckpt: str, cfgs: list[str], *, per_mode: int, seed: int,
                     episode_s: str | None, out_rel: str, dr_scale: float,
                     scripted: bool = False) -> str:
    cmd = (f"nice -n 19 uv run python -m rl_move.sim.eval_checkpoint {shlex.quote(ckpt)}"
           f" --task joint_walk --modes walk --per-mode {int(per_mode)}"
           f" --dr-scale {dr_scale:g} --seed {int(seed)}")
    if episode_s:
        cmd += f" --episode-seconds {episode_s}"
    cmd += "".join(" --cfg-set " + shlex.quote(c) for c in cfgs)
    if scripted:
        cmd += " " + TEACHER_FLAGS
    cmd += f" --no-video --no-wandb --out {shlex.quote(out_rel)}"
    return cmd


def build_pod_script(jobs: list[tuple[str, str]]) -> str:
    """jobs: (worker command, log path). One detached process per worker."""
    lines = ["#!/bin/bash", f"cd {POD_PROTO} || exit 1",
             "set -a; . rl_move/sim/wandb.env 2>/dev/null; set +a",
             "export WANDB_MODE=disabled"]
    for cmd, log in jobs:
        lines.append(f"( {cmd} ) > {shlex.quote(log)} 2>&1 &")
    lines += ["wait", "echo RATE-EVAL-DONE"]
    return "\n".join(lines) + "\n"


def merge_reports(reports: list[dict], mode: str = MODE) -> dict:
    """Pool walk/det episodes across seed reports (in report order)."""
    eps = []
    for r in reports:
        eps.extend(r.get("episodes", {}).get(mode, []) or [])
    gv = [bool(e.get("gait_valid")) for e in eps]
    valid_prog = [float(e["progress_ratio"]) for e in eps
                  if e.get("gait_valid") and e.get("progress_ratio") is not None]
    hard = [e for e in eps if not e.get("gait_valid")]
    parked = sum(1 for e in hard if e.get("duty_cycle")
                 and min(float(x) for x in e["duty_cycle"]) < 0.10)
    hist: dict[int, int] = {}
    for e in eps:
        for leg in e.get("sacrificed_legs") or []:
            hist[int(leg)] = hist.get(int(leg), 0) + 1
    terms = sum(1 for e in eps if e.get("terminated") or (e.get("reason") not in (None, "time", "timeout", "")))
    return {"n": len(eps), "k": sum(gv), "gait_valid": gv,
            "prog_valid_med": (statistics.median(valid_prog) if valid_prog else None),
            "hard_eps": len(hard), "hard_with_parked_leg": parked,
            "sacrifice_hist": {str(k): v for k, v in sorted(hist.items())},
            "terminations": terms}


def compare(child: dict, parent: dict | None) -> dict:
    wilson, ztest = _stats()
    p, lo, hi = wilson(child["k"], child["n"])
    out = {"child": {**{k: v for k, v in child.items() if k != "gait_valid"},
                     "rate": p, "ci95": [lo, hi]}}
    if parent and parent["n"]:
        pp, plo, phi = wilson(parent["k"], parent["n"])
        z, pv = ztest(child["k"], child["n"], parent["k"], parent["n"])
        m = min(len(child["gait_valid"]), len(parent["gait_valid"]))
        same = sum(1 for a, b in zip(child["gait_valid"][:m], parent["gait_valid"][:m]) if a == b)
        out["parent"] = {**{k: v for k, v in parent.items() if k != "gait_valid"},
                         "rate": pp, "ci95": [plo, phi]}
        out["delta_pp"] = 100.0 * (p - pp)
        out["z"] = z
        out["p_value"] = pv
        out["episode_identity"] = {"same": same, "of": m,
                                   "frac": (same / m if m else None)}
    return out


def summary_line(run: str, res: dict, tag: str = "") -> str:
    c = res["child"]
    s = (f"RATE {run}{tag}: child {c['k']}/{c['n']} = {c['rate']:.3f} "
         f"[{c['ci95'][0]:.3f},{c['ci95'][1]:.3f}] prog_valid_med "
         f"{c['prog_valid_med'] if c['prog_valid_med'] is None else round(c['prog_valid_med'], 3)}")
    if "parent" in res:
        p = res["parent"]
        s += (f" | parent zero-shot {p['k']}/{p['n']} = {p['rate']:.3f} "
              f"[{p['ci95'][0]:.3f},{p['ci95'][1]:.3f}] | delta {res['delta_pp']:+.1f} pp "
              f"z={res['z']:.2f} p={res['p_value']:.3f} | episode identity "
              f"{res['episode_identity']['same']}/{res['episode_identity']['of']}")
    if "scripted" in res:
        sc = res["scripted"]
        s += f" | scripted tripod (context) {sc['k']}/{sc['n']} = {sc['k'] / max(1, sc['n']):.3f}"
    return s


# --------------------------------------------------------------- pod plumbing
def kexec(pod: str, cmd: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "exec", "--request-timeout=%ds" % timeout, pod,
                           "--", "bash", "-c", cmd],
                          capture_output=True, text=True, timeout=timeout + 30)


def trainer_live(pod: str) -> bool:
    r = kexec(pod, "for p in /proc/[0-9]*/cmdline; do tr '\\0' ' ' < $p 2>/dev/null; echo; done "
                   "| grep -c 'rl_move.sim.train_ppo' || true")
    try:
        return int((r.stdout or "0").strip().splitlines()[-1]) > 0
    except (ValueError, IndexError):
        return False


def ledger_entries():
    import state_dir  # noqa: WPS433  (controller module)
    return [e for e in state_dir.load_ledger() if isinstance(e, dict)]


def run_entry(entries, run: str) -> dict | None:
    cands = [e for e in entries if e.get("run") == run and e.get("extra_args")
             and e.get("status") != "REFUSED"]
    return cands[-1] if cands else None


def entry_by_out_name(entries, stem: str) -> dict | None:
    for e in reversed(entries):
        a = e.get("extra_args") or []
        if e.get("status") == "REFUSED":
            continue
        if arg_val(a, "--out-name") == stem or "ppo_goal_" + str(e.get("run", "")).replace("-", "_") == stem:
            return e
    return None


def idle_pods(entries) -> list[str]:
    busy = {e.get("pod") for e in entries if e.get("status") in ("RUNNING", "INTENT")}
    return [f"hexapod-mjx-train-{i}" for i in range(16)
            if i != 6 and f"hexapod-mjx-train-{i}" not in busy]


def remote_exists(pod: str, path: str) -> bool:
    return kexec(pod, f"test -s {shlex.quote(path)}").returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run")
    ap.add_argument("--parent", default="auto",
                    help="'auto' = the child's --init-from checkpoint (default); "
                         "'none' = child only; or a run name whose checkpoint is on the pod")
    ap.add_argument("--n", type=int, default=96, help="fresh walk/det episodes per leg")
    ap.add_argument("--workers", type=int, default=0, help="0 = auto (16 idle pod, 6 next to a trainer)")
    ap.add_argument("--pod", default="", help="target pod (default: child's pod if idle, else first idle)")
    ap.add_argument("--dr-scale", type=float, default=1.0)
    ap.add_argument("--scripted", action="store_true",
                    help="also run the open-loop scripted tripod on the same seeds (context only)")
    ap.add_argument("--include-seed0", action="store_true")
    ap.add_argument("--force-parent", action="store_true",
                    help="run the parent leg even when the obs layout check fails")
    ap.add_argument("--timeout-s", type=int, default=2400)
    ap.add_argument("--dry-run", action="store_true", help="print the pod script, run nothing")
    a = ap.parse_args()

    entries = ledger_entries()
    child = run_entry(entries, a.run)
    if child is None:
        print(f"no ledger entry with extra_args for {a.run}")
        return 1
    args = list(child["extra_args"])
    task = arg_val(args, "--task", "joint_walk")
    if task != "joint_walk":
        print(f"{a.run} is a {task} run; this tool scores walk/det only")
        return 1
    episode_s = arg_val(args, "--episode-seconds", None)
    cfgs = eval_cfgs(args, a.dr_scale)
    stem = arg_val(args, "--out-name") or "ppo_goal_" + a.run.replace("-", "_")
    child_ckpt = f"rl_move/sim/policies/{stem}.zip"

    parent_ckpt = None
    parent_note = "parent leg skipped (--parent none)"
    if a.parent != "none":
        if a.parent == "auto":
            init = arg_val(args, "--init-from")
            if not init:
                parent_note = "child has no --init-from; no parent leg"
            else:
                parent_ckpt = init
                pstem = pathlib.Path(init).stem
                pentry = entry_by_out_name(entries, pstem)
                ok, why = parent_compatible(args, (pentry or {}).get("extra_args"))
                parent_note = f"parent {pstem}: {why}"
                if not ok and not a.force_parent:
                    parent_ckpt = None
                    parent_note += " -> parent leg REFUSED (use --force-parent to override)"
        else:
            pe = run_entry(entries, a.parent)
            if pe is None:
                print(f"no ledger entry for parent run {a.parent}")
                return 1
            pstem = arg_val(pe["extra_args"], "--out-name") or "ppo_goal_" + a.parent.replace("-", "_")
            parent_ckpt = f"rl_move/sim/policies/{pstem}.zip"
            ok, why = parent_compatible(args, pe["extra_args"])
            parent_note = f"parent {pstem}: {why}"
            if not ok and not a.force_parent:
                parent_ckpt = None
                parent_note += " -> parent leg REFUSED (use --force-parent to override)"

    # pod + worker count
    pod = a.pod or child.get("pod") or ""
    if not a.dry_run:
        if not pod or trainer_live(pod):
            for cand in ([pod] if pod else []) + idle_pods(entries):
                if cand and not trainer_live(cand):
                    pod = cand
                    break
        live = trainer_live(pod) if pod else False
    else:
        live = False
    workers = a.workers or (6 if live else 16)
    per = split_episodes(a.n, workers)
    seeds = worker_seeds(len(per), a.include_seed0)
    tag = f"rate_{a.run.replace('-', '_')}_n{a.n}"
    out_root = f"logs/ckpt_eval/{tag}"
    jobs: list[tuple[str, str]] = []
    legs: dict[str, str] = {"child": child_ckpt}
    if parent_ckpt:
        legs["parent"] = parent_ckpt
    if a.scripted:
        legs["scripted"] = child_ckpt
    for leg, ckpt in legs.items():
        for s, pm in zip(seeds, per):
            out_rel = f"{out_root}/{leg}/seed{s}"
            jobs.append((build_worker_cmd(ckpt, cfgs, per_mode=pm, seed=s, episode_s=episode_s,
                                          out_rel=out_rel, dr_scale=a.dr_scale,
                                          scripted=(leg == "scripted")),
                         f"/tmp/{tag}_{leg}_seed{s}.log"))
    script = build_pod_script(jobs)
    print(f"{a.run}: pod {pod or '?'} (trainer live: {live}), {len(per)} workers x {per[0]}..{per[-1]} eps, "
          f"seeds {seeds[0]}..{seeds[-1]}, legs {list(legs)}; {parent_note}")
    if a.dry_run:
        print(script)
        return 0
    if not pod:
        print("no idle GPU pod found")
        return 1
    for leg, ckpt in legs.items():
        if not remote_exists(pod, f"{POD_PROTO}/{ckpt}"):
            print(f"{leg} checkpoint missing on {pod}: {ckpt}")
            return 1
    local_script = pathlib.Path(f"/tmp/{tag}.sh")
    local_script.write_text(script)
    subprocess.run(["kubectl", "cp", str(local_script), f"{pod}:/tmp/{tag}.sh"], check=True)
    kexec(pod, f"nohup bash /tmp/{tag}.sh > /tmp/{tag}.out 2>&1 < /dev/null &")
    t0 = time.time()
    want = len(jobs)
    while time.time() - t0 < a.timeout_s:
        r = kexec(pod, f"ls {POD_PROTO}/{out_root}/*/seed*/report.json 2>/dev/null | wc -l")
        have = int((r.stdout or "0").strip().splitlines()[-1] or 0)
        if have >= want:
            break
        time.sleep(20)
    else:
        print(f"timeout: {have}/{want} reports after {a.timeout_s}s (pod {pod}, /tmp/{tag}.out)")
        return 2
    local_root = PROTO / out_root
    local_root.mkdir(parents=True, exist_ok=True)
    tar_in = subprocess.Popen(["kubectl", "exec", pod, "--", "tar", "-C", f"{POD_PROTO}/{out_root}",
                               "-czf", "-", "."], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-C", str(local_root), "-xzf", "-"], stdin=tar_in.stdout, check=True)
    tar_in.wait()
    merged = {}
    for leg in legs:
        reps = []
        for s in seeds:
            p = local_root / leg / f"seed{s}" / "report.json"
            if p.is_file():
                reps.append(json.loads(p.read_text()))
        merged[leg] = merge_reports(reps)
    res = compare(merged["child"], merged.get("parent"))
    if "scripted" in merged:
        res["scripted"] = {k: v for k, v in merged["scripted"].items() if k != "gait_valid"}
    res.update({"run": a.run, "pod": pod, "seeds": seeds, "episodes_per_seed": per,
                "cfg_set": cfgs, "dr_scale": a.dr_scale, "legs": legs, "parent_note": parent_note,
                "elapsed_s": round(time.time() - t0, 1), "mode": MODE})
    (local_root / "summary.json").write_text(json.dumps(res, indent=1))
    line = summary_line(a.run, res, f" (n={a.n}, {res['elapsed_s']:.0f}s on {pod})")
    print(line)
    print(f"summary: {local_root / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
