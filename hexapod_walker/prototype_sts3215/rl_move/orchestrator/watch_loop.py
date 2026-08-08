#!/usr/bin/env python3
"""Watcher for the autonomous experiment loop.

Polls W&B; whenever one or more training runs FINISH, invokes one headless
agent decision cycle (Claude Code / Fable 5) with the standing orchestrator
prompt plus the names of the newly finished runs. The agent evals the
checkpoints (including watching motion videos), summarizes into RL_LOG.md,
reviews RL_PLAN.md, snapshots the code, and launches replacement
experiments on the freed pods. State that matters (results, decisions,
lineage) lives in the repo; this file only remembers which finished runs
were already handled.

Run on the controller pod inside tmux:
    python3 rl_move/orchestrator/watch_loop.py
Kill switch: `touch rl_move/orchestrator/PAUSE` (loop idles until removed).
"""
import datetime
import json
import os
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
STATE = pathlib.Path("/workspace/orchestrator_state.json")

POLL_S = 300
MAX_CYCLES_PER_DAY = 12         # keep in sync with guardrails.yaml
BACKOFF_AFTER_FAILED_CYCLES = 2  # consecutive agent failures -> long sleep
# Decision cycles run on Claude Code (headless) with the operator's own
# Anthropic API key — Fable 5, billed directly to Anthropic. Cursor's CLI
# was dropped because editor BYOK keys don't apply to headless sessions,
# which left cycles stuck behind Cursor plan usage limits.
AGENT_MODEL = "claude-fable-5"
AGENT_CMD = [
    "claude", "-p", "--bare",
    "--model", AGENT_MODEL,
    "--dangerously-skip-permissions",
    "--output-format", "text",
]

WANDB_PROJECT = "l2k2/hexapod-balance"


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def runs_by_state() -> tuple[set[str], set[str]]:
    """Return (running, finished) run-name sets from W&B."""
    import wandb

    api = wandb.Api()
    running = {
        r.name for r in api.runs(WANDB_PROJECT, filters={"state": "running"})
    }
    finished = {
        r.name
        for r in api.runs(
            WANDB_PROJECT, filters={"state": {"$in": ["finished", "crashed", "failed"]}}
        )
    }
    return running, finished


def load_processed() -> set[str] | None:
    if not STATE.exists():
        return None
    return set(json.loads(STATE.read_text())["processed"])


def save_processed(processed: set[str]) -> None:
    STATE.write_text(json.dumps({"processed": sorted(processed)}))


def agent_cycle(newly_finished: set[str], still_running: set[str]) -> bool:
    """Run one decision cycle. Returns True on agent success (rc == 0)."""
    cycle_prompt = (
        PROMPT
        + "\n\n## This cycle\n"
        + f"Runs that just finished: {', '.join(sorted(newly_finished))}\n"
        + (
            f"Runs still training (leave their pods alone): "
            f"{', '.join(sorted(still_running))}\n"
            if still_running
            else "No other runs are training; all pods are available.\n"
        )
    )
    # Sync with main first so the agent sees the operator's latest plan/log
    # edits and its later push can't be rejected as non-fast-forward.
    pull = subprocess.run(
        ["git", "pull", "--rebase", "--autostash", "origin", "main"],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )
    if pull.returncode != 0:
        log(f"git pull failed before cycle: {(pull.stderr or '')[-500:]}")
    log(f"starting agent cycle for: {', '.join(sorted(newly_finished))}")
    proc = subprocess.run(
        AGENT_CMD + [cycle_prompt],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=3 * 3600,
    )
    tail = (proc.stdout or "")[-2000:]
    log(f"agent cycle done rc={proc.returncode}; tail:\n{tail}")
    if proc.returncode != 0:
        log(f"agent stderr tail:\n{(proc.stderr or '')[-1000:]}")
    return proc.returncode == 0


def main() -> None:
    cycle_times: list[float] = []
    failed_cycles = 0
    log("watcher started")
    while True:
        try:
            if PAUSE.exists():
                log("PAUSE present; idling")
                time.sleep(POLL_S)
                continue
            if not os.environ.get("ANTHROPIC_API_KEY"):
                log("ANTHROPIC_API_KEY not set; cannot run agent cycles. idling")
                time.sleep(POLL_S)
                continue

            running, finished = runs_by_state()
            processed = load_processed()
            if processed is None:
                # First start: don't reprocess pre-existing history.
                save_processed(finished)
                log(f"state initialized; {len(finished)} historical runs marked handled")
                time.sleep(POLL_S)
                continue

            newly = finished - processed
            if not newly:
                log(
                    f"{len(running)} running: {', '.join(sorted(running)) or 'none'}; "
                    "nothing new finished"
                )
                time.sleep(POLL_S)
                continue

            now = time.time()
            cycle_times = [t for t in cycle_times if now - t < 86400]
            if len(cycle_times) >= MAX_CYCLES_PER_DAY:
                log("daily cycle cap reached; idling 1h")
                time.sleep(3600)
                continue
            if failed_cycles >= BACKOFF_AFTER_FAILED_CYCLES:
                log("agent failed twice in a row; needs operator. idling 6h")
                time.sleep(6 * 3600)
                failed_cycles = 0
                continue

            cycle_times.append(now)
            if agent_cycle(newly, running):
                processed |= newly
                save_processed(processed)
                failed_cycles = 0
            else:
                failed_cycles += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:  # survive transient W&B/network errors
            log(f"watcher error: {e!r}; retrying in {POLL_S}s")
            time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
