#!/usr/bin/env python3
"""Watcher for the autonomous experiment loop.

Polls W&B; when no tracked training run is active, invokes one headless
Cursor agent cycle with the standing orchestrator prompt. State that
matters (results, decisions, lineage) lives in the repo, not here.

Run on the controller pod inside tmux:
    python3 rl_move/orchestrator/watch_loop.py
Kill switch: `touch rl_move/orchestrator/PAUSE` (loop idles until removed).
"""
import datetime
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], cwd=HERE, text=True
).strip()
PROMPT = (HERE / "ORCHESTRATOR_PROMPT.md").read_text()
PAUSE = HERE / "PAUSE"
LOG = pathlib.Path("/workspace/orchestrator.log")

POLL_S = 300
MAX_CYCLES_PER_DAY = 8          # keep in sync with guardrails.yaml
BACKOFF_AFTER_IDLE_CYCLES = 2   # cycles that launched nothing -> long sleep

WANDB_PROJECT = "l2k2/hexapod-balance"


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def running_runs() -> list[str]:
    import wandb

    api = wandb.Api()
    return [
        r.name
        for r in api.runs(WANDB_PROJECT, filters={"state": "running"})
    ]


def agent_cycle() -> bool:
    """Run one decision cycle. Returns True if new runs got launched."""
    before = set(running_runs())
    log("starting agent cycle")
    proc = subprocess.run(
        ["cursor-agent", "-p", PROMPT, "--force", "--output-format", "text"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=3 * 3600,
    )
    tail = (proc.stdout or "")[-2000:]
    log(f"agent cycle done rc={proc.returncode}; tail:\n{tail}")
    if proc.returncode != 0:
        log(f"agent stderr tail:\n{(proc.stderr or '')[-1000:]}")
    after = set(running_runs())
    launched = sorted(after - before)
    log(f"launched: {launched or 'nothing'}")
    return bool(launched)


def main() -> None:
    cycle_times: list[float] = []
    idle_cycles = 0
    log("watcher started")
    while True:
        try:
            if PAUSE.exists():
                log("PAUSE present; idling")
                time.sleep(POLL_S)
                continue

            active = running_runs()
            if active:
                log(f"{len(active)} running: {', '.join(sorted(active))}")
                time.sleep(POLL_S)
                continue

            now = time.time()
            cycle_times = [t for t in cycle_times if now - t < 86400]
            if len(cycle_times) >= MAX_CYCLES_PER_DAY:
                log("daily cycle cap reached; idling 1h")
                time.sleep(3600)
                continue
            if idle_cycles >= BACKOFF_AFTER_IDLE_CYCLES:
                log("agent launched nothing twice; needs operator. idling 6h")
                time.sleep(6 * 3600)
                idle_cycles = 0
                continue

            cycle_times.append(now)
            idle_cycles = 0 if agent_cycle() else idle_cycles + 1
        except KeyboardInterrupt:
            raise
        except Exception as e:  # survive transient W&B/network errors
            log(f"watcher error: {e!r}; retrying in {POLL_S}s")
            time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
