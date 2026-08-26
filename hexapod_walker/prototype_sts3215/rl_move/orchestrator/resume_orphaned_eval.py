#!/usr/bin/env python3
"""Finish an ORPHANED pod_eval.py run's copy-back, without relaunching.

    uv run python rl_move/orchestrator/resume_orphaned_eval.py <run> [suffix]
        [--timeout-s N] [--poll-s N]

Why this exists (2026-08-26, cw-standwalk-stance-mesh2-stage2-dualbc1-
anchor3/-s1): pod_eval.py's own controller-side process is itself
wrapped in a hard subprocess timeout by the watcher's prestage worker.
On a live watch_loop.py process running STALE in-memory code (the
watcher is a long-lived process; a `PASS_TIMEOUT_S`/wrapper-timeout
constant change on disk does not take effect until the watcher itself
restarts), that wrapper can fire and kill pod_eval.py's controller-side
script WHILE its remote `kubectl exec eval_checkpoint...` child
processes are still alive and healthy on the pod (kubectl exec streams
are independent of the parent CLI's local supervising script in this
setup — confirmed by `ps aux` on the pod showing the eval processes
still consuming CPU and producing new episode videos long after
pod_eval.py itself was reaped on the controller). The remote compute
is NOT wasted, but nothing will ever copy the results back or write
the `_prestage.synced` sentinel, so the run silently rots as
"processed but never verdicted" (the watcher's reap_cycles marks a
triage cycle's runs `processed` on any rc==0 exit, verdict or not).

This script does ONLY the back half of pod_eval.py's job for a run
that is already mid-eval on its pod: poll for each pass's
`report.json` to appear REMOTELY (bounded wait, no new compute
started), `kubectl cp` it back the moment it does, append the same
`SYNCED ...` line to the pass's `/tmp/eval_<run>*.log` that
`ops.sh waitlog` already knows how to watch for, and once every CORE
pass (gate + own-DR if the run trained at DR>0) is synced, write the
`_prestage.synced` sentinel exactly like pod_eval.py's own
`core_synced()` — so `ops.sh review`/the next cycle sees it as ready,
with zero duplicate CPU contention on the pod.

Idempotent + safe to run detached (`nohup ... &`): a pass whose local
report.json already exists is skipped; a pass whose remote report.json
never appears within --timeout-s just times out and is logged, exactly
like pod_eval.py's own behavior, and the sentinel is still written
(best-effort, mirrors core_synced's own "write it regardless" contract
so a genuinely-dead pass doesn't wedge triage forever).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

import pod_eval  # reuse LEDGER/PROTO/POD_PROTO/core_synced — no duplication

HERE = pathlib.Path(__file__).resolve().parent


def find_entry(run: str) -> dict | None:
    entry = None
    fallback = None
    for e in json.loads(pod_eval.LEDGER.read_text()):
        if isinstance(e, dict) and e.get("run") == run and e.get("extra_args"):
            fallback = e
            if e.get("wandb_id") or e.get("checks", {}).get("pid"):
                entry = e
    return entry or fallback


def wait_and_sync(pod: str, out_rel: str, tag: str, run: str,
                   timeout_s: float, poll_s: float) -> int:
    local = pod_eval.PROTO / out_rel
    logpath = pathlib.Path(f"/tmp/eval_{run}.log" if tag == "gate"
                            else f"/tmp/eval_{run}_{tag}.log")
    if (local / "report.json").is_file():
        print(f"{tag}: {out_rel} already synced locally — skipping")
        return 0
    t0 = time.time()
    while True:
        r = subprocess.run(
            ["kubectl", "exec", pod, "--", "test", "-f",
             f"{pod_eval.POD_PROTO}/{out_rel}/report.json"],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            break
        if time.time() - t0 > timeout_s:
            print(f"{tag}: TIMEOUT after {timeout_s:.0f}s waiting for "
                  f"remote {out_rel}/report.json")
            with open(logpath, "a") as fh:
                fh.write(f"\nSYNCED rc=-1 (resume-orphan timeout): {out_rel}\n")
            return 1
        time.sleep(poll_s)
    local.parent.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(
        ["kubectl", "cp", "--retries=5", f"{pod}:{pod_eval.POD_PROTO}/{out_rel}",
         str(local)], capture_output=True, text=True, timeout=600)
    ok = (local / "report.json").is_file()
    rc = 0 if ok else 1
    note = "" if ok else f" (copy-back missing report.json: {(cp.stderr or '')[-200:]})"
    with open(logpath, "a") as fh:
        fh.write(f"\nSYNCED rc={rc}{note}: {out_rel}\n")
    print(f"{tag}: rc={rc}{note} synced -> {out_rel} "
          f"(waited {time.time() - t0:.0f}s)")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("suffix", nargs="?", default="")
    ap.add_argument("--timeout-s", type=float, default=3600.0)
    ap.add_argument("--poll-s", type=float, default=20.0)
    args = ap.parse_args()

    entry = find_entry(args.run)
    if entry is None:
        print(f"no ledger entry with extra_args for {args.run}")
        return 1
    pod = entry["pod"]
    a = list(entry["extra_args"])
    dr = float(a[a.index("--dr-scale") + 1]) if "--dr-scale" in a else 0.0
    run_us = args.run.replace("-", "_")

    passes = [("gate", f"logs/ckpt_eval/{run_us}_gate{args.suffix}")]
    if dr > 0:
        passes.append(("owncfg", f"logs/ckpt_eval/{run_us}_owncfg{args.suffix}"))

    worst = 0
    for tag, out_rel in passes:
        rc = wait_and_sync(pod, out_rel, tag, args.run,
                            args.timeout_s, args.poll_s)
        worst = max(worst, rc)

    pod_eval.core_synced(args.run)
    print(f"core_synced written for {args.run}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
