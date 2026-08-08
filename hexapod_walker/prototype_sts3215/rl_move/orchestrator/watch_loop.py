#!/usr/bin/env python3
"""Watcher for the autonomous experiment loop.

Polls W&B; whenever one or more training runs FINISH, spawns a headless
agent decision cycle (Claude Code / Fable 5) with the standing orchestrator
prompt plus the names of the newly finished runs. Cycles are event-driven
and CONCURRENT (cap MAX_CONCURRENT_CYCLES): a finish never queues behind a
cycle already in flight. The agent evals the checkpoints (including
watching motion videos), summarizes into RL_LOG.md, reviews RL_PLAN.md,
snapshots the code, and launches replacement experiments on the freed
pods. State that matters (results, decisions, lineage) lives in the repo;
this file only remembers which finished runs were already handled.

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
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], cwd=HERE, text=True
).strip()
PROMPT = (HERE / "ORCHESTRATOR_PROMPT.md").read_text()
PAUSE = HERE / "PAUSE"
LEDGER = HERE / "experiments.json"
LOG = pathlib.Path("/workspace/orchestrator.log")
STATE = pathlib.Path("/workspace/orchestrator_state.json")
# Watcher-owned post-launch checkups (moved out of the agent cycle
# 08-08 evening: sleeping out checkup_after_s inside the cycle serialized
# every launch into +5 min of wall clock while pods sat idle).
CHECKUP_AFTER_S = 300      # keep in sync with guardrails checkup_after_s
CHECKUP_WINDOW_S = 3600    # entries older than this are never checked (stale)
CHECKUP_STATE = pathlib.Path("/workspace/checkup_state.json")
FINDINGS = pathlib.Path("/workspace/checkup_findings.md")

POLL_S = 300
MAX_CYCLES_PER_DAY = 12         # keep in sync with guardrails.yaml
BACKOFF_AFTER_FAILED_CYCLES = 2  # consecutive agent failures -> long sleep
# Cycles are event-driven and CONCURRENT (08-08 evening): when a run
# finishes while another cycle is still working, its verdict/relaunch no
# longer queues behind that cycle. Serialization points that remain:
# snapshot.sh takes a git lock, launch_run.py takes launch+ledger locks.
MAX_CONCURRENT_CYCLES = 2
CYCLE_TIMEOUT_S = 3 * 3600
CYCLE_OUT_DIR = pathlib.Path("/workspace/cycle_logs")
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
# Experiment naming convention. Runs without this prefix (e.g. auto-named
# smoke/verification trainings) never trigger or block cycles — round 6.5
# was a spurious cycle caused by the agent's own seed-fix smoke runs.
RUN_PREFIX = "cw-"
# If nothing is training and nothing new finished for this many consecutive
# polls, kick a cycle anyway so the campaign can't deadlock (e.g. after a
# blocked launch or a watcher restart with idle pods).
IDLE_KICK_POLLS = 3


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
        r.name
        for r in api.runs(WANDB_PROJECT, filters={"state": "running"})
        if r.name.startswith(RUN_PREFIX)
    }
    finished = {
        r.name
        for r in api.runs(
            WANDB_PROJECT, filters={"state": {"$in": ["finished", "crashed", "failed"]}}
        )
        if r.name.startswith(RUN_PREFIX)
    }
    return running, finished


def load_processed() -> set[str] | None:
    if not STATE.exists():
        return None
    return set(json.loads(STATE.read_text())["processed"])


def ledger_verdicted() -> set[str]:
    """Runs whose experiments.json entry already carries a final status.

    Dedupe keys on the structured ledger, not on the watcher's own state
    file alone (external review 8b): the state file misses runs when a
    cycle is interrupted or the watcher restarts mid-cycle — that re-fired
    cw-walk-flag-s1/cw-walk-nv three times (rounds 8.5, 9). Exception-safe:
    a missing/corrupt ledger never blocks the loop.
    """
    try:
        entries = json.loads((HERE / "experiments.json").read_text())
        return {e["run"] for e in entries
                if e.get("status") in ("FINISHED", "FAILED")}
    except Exception:
        return set()


def save_processed(processed: set[str]) -> None:
    STATE.write_text(json.dumps({"processed": sorted(processed)}))


def _entry_key(e: dict) -> str:
    return f"{e.get('run')}|{e.get('created')}"


def _launch_ts(e: dict) -> float | None:
    for k in ("verified", "created"):
        v = e.get(k)
        if v:
            try:
                return datetime.datetime.fromisoformat(v).timestamp()
            except ValueError:
                pass
    return None


def checkup_worker() -> None:
    """Async post-launch checkups, owned by the watcher (not the agent).

    Every RUNNING ledger entry gets `launch_run.py checkup` once,
    ~CHECKUP_AFTER_S after its launch verification. HEALTHY results are
    just logged; DEAD/SUSPECT results are appended to FINDINGS, which both
    triggers the next agent cycle and is injected into its prompt so the
    agent can retry/kill/rebalance. Entries older than CHECKUP_WINDOW_S
    (stale statuses, backfills, watcher downtime) are skipped silently —
    a checkup of a long-finished run would false-alarm as DEAD.
    """
    try:
        done = set(json.loads(CHECKUP_STATE.read_text())["done"])
    except Exception:
        done = set()
    while True:
        try:
            entries = json.loads(LEDGER.read_text())
        except Exception:
            entries = []
        now = time.time()
        for e in entries:
            key = _entry_key(e)
            if key in done or e.get("status") != "RUNNING":
                continue
            if e.get("checkups"):  # already checked (e.g. agent did it)
                done.add(key)
                continue
            ts = _launch_ts(e)
            if ts is None or now - ts > CHECKUP_WINDOW_S:
                done.add(key)
                continue
            if now - ts < CHECKUP_AFTER_S:
                continue
            run = e["run"]
            try:
                proc = subprocess.run(
                    [sys.executable, str(HERE / "launch_run.py"),
                     "checkup", "--run", run],
                    capture_output=True, text=True, timeout=600, cwd=REPO)
                out = ((proc.stdout or "") + (proc.stderr or "")).strip()
                log(f"checkup {run}: rc={proc.returncode}\n{out[-800:]}")
                if proc.returncode != 0:
                    stamp = datetime.datetime.now().isoformat(timespec="seconds")
                    with FINDINGS.open("a") as f:
                        f.write(f"### {run} (checkup rc={proc.returncode}, "
                                f"{stamp})\n{out[-1500:]}\n\n")
            except Exception as exc:
                log(f"checkup {run} failed to execute: {exc!r}")
            done.add(key)
            try:
                CHECKUP_STATE.write_text(json.dumps({"done": sorted(done)}))
            except Exception:
                pass
        time.sleep(60)


def spawn_cycle(newly_finished: set[str], still_running: set[str],
                findings: str, in_flight: set[str]) -> dict:
    """Start one decision cycle as a CONCURRENT subprocess.

    Returns a handle {proc, runs, out, t0}; reap_cycles() collects it.
    Event-driven: each batch of newly finished runs gets its own cycle
    immediately instead of queuing behind whichever cycle is running.
    """
    if newly_finished:
        trigger = f"Runs that just finished: {', '.join(sorted(newly_finished))}\n"
    elif findings:
        trigger = (
            "No run just finished — this cycle was triggered by watcher "
            "post-launch checkup findings (section below). Act on them per "
            "the prompt's checkup rules (DEAD -> clean up + retry once, "
            "then NEEDS OPERATOR; SUSPECT -> read the log, kill/rebalance/"
            "fix), record the action, and exit; skip eval steps for runs "
            "already logged.\n"
        )
    else:
        trigger = (
            "No run just finished — this is an idle kick: pods are sitting "
            "idle with no experiments training. Resume the campaign from "
            "RL_LOG.md (a NEEDS OPERATOR section or planned-but-unlaunched "
            "experiments); skip eval steps for runs already logged.\n"
        )
    cycle_prompt = (
        PROMPT
        + "\n\n## This cycle\n"
        + trigger
        + (
            f"Runs still training (leave their pods alone): "
            f"{', '.join(sorted(still_running))}\n"
            if still_running
            else "No other runs are training; all pods are available.\n"
        )
    )
    if in_flight:
        cycle_prompt += (
            "Another decision cycle is running CONCURRENTLY and already "
            f"handles: {', '.join(sorted(in_flight))}. Do NOT evaluate, "
            "verdict, or launch on behalf of those runs. Concurrency is "
            "coordinated mechanically — the launcher enforces capacity/"
            "duplicates and snapshot.sh serializes git pushes (a brief "
            "wait on its lock is normal). Re-run `launch_run.py status` "
            "immediately before placing runs; free slots may have been "
            "taken since this prompt was written.\n"
        )
    if findings:
        cycle_prompt += (
            "\n## Watcher checkup findings (act on these first)\n"
            + findings + "\n"
        )
    # Sync with main first so the agent sees the operator's latest plan/log
    # edits and its later push can't be rejected as non-fast-forward.
    pull = subprocess.run(
        ["git", "pull", "--rebase", "--autostash", "origin", "main"],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )
    if pull.returncode != 0:
        log(f"git pull failed before cycle: {(pull.stderr or '')[-500:]}")
    CYCLE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    label = "-".join(sorted(newly_finished)) or ("findings" if findings else "kick")
    out = CYCLE_OUT_DIR / f"cycle_{stamp}_{label[:120]}.log"
    with out.open("w") as fh:
        proc = subprocess.Popen(
            AGENT_CMD + [cycle_prompt],
            cwd=REPO, stdout=fh, stderr=subprocess.STDOUT, text=True,
        )
    log(f"cycle spawned pid={proc.pid} for: {label} (log: {out})")
    return {"proc": proc, "runs": set(newly_finished), "out": out,
            "t0": time.time(), "label": label}


def reap_cycles(active: list[dict], processed: set[str]) -> tuple[list[dict], int, int]:
    """Collect finished cycles. Returns (still_active, n_ok, n_failed).

    Successful cycles mark their runs processed; failed cycles leave them
    unmarked so a later cycle can retry (ledger dedupe prevents double
    verdicts for anything the failed cycle did complete)."""
    still, n_ok, n_failed = [], 0, 0
    for c in active:
        rc = c["proc"].poll()
        if rc is None:
            if time.time() - c["t0"] > CYCLE_TIMEOUT_S:
                c["proc"].kill()
                log(f"cycle {c['label']} exceeded {CYCLE_TIMEOUT_S}s; killed")
                n_failed += 1
            else:
                still.append(c)
            continue
        try:
            tail = c["out"].read_text()[-2000:]
        except OSError:
            tail = "(cycle log unreadable)"
        log(f"cycle {c['label']} done rc={rc}; tail:\n{tail}")
        if rc == 0:
            processed |= c["runs"]
            n_ok += 1
        else:
            n_failed += 1
    return still, n_ok, n_failed


def main() -> None:
    cycle_times: list[float] = []
    failed_cycles = 0
    idle_polls = 0
    active: list[dict] = []
    log("watcher started")
    threading.Thread(target=checkup_worker, daemon=True).start()
    while True:
        try:
            processed = load_processed()
            if processed is not None:
                active, n_ok, n_failed = reap_cycles(active, processed)
                if n_ok:
                    save_processed(processed)
                    failed_cycles = 0
                    idle_polls = 0
                elif n_failed:
                    failed_cycles += n_failed

            if PAUSE.exists():
                log("PAUSE present; idling")
                time.sleep(POLL_S)
                continue
            if not os.environ.get("ANTHROPIC_API_KEY"):
                log("ANTHROPIC_API_KEY not set; cannot run agent cycles. idling")
                time.sleep(POLL_S)
                continue

            running, finished = runs_by_state()
            if processed is None:
                # First start: don't reprocess pre-existing history.
                save_processed(finished)
                log(f"state initialized; {len(finished)} historical runs marked handled")
                time.sleep(POLL_S)
                continue

            # Runs a live cycle is already handling must not fire a second one.
            in_flight: set[str] = set()
            for c in active:
                in_flight |= c["runs"]
            newly = finished - processed - ledger_verdicted() - in_flight
            try:
                findings = FINDINGS.read_text().strip() if FINDINGS.exists() else ""
            except OSError:
                findings = ""

            if not newly and not findings:
                if running or active:
                    idle_polls = 0
                    log(
                        f"{len(running)} training, {len(active)} cycle(s) "
                        f"active; nothing new finished"
                    )
                    time.sleep(POLL_S)
                    continue
                idle_polls += 1
                if idle_polls < IDLE_KICK_POLLS:
                    log(
                        f"nothing running, nothing new finished "
                        f"(idle poll {idle_polls}/{IDLE_KICK_POLLS})"
                    )
                    time.sleep(POLL_S)
                    continue
                log("pods idle too long — kicking a cycle to resume the campaign")
            else:
                idle_polls = 0
                if findings:
                    log("checkup findings pending — injecting into next cycle")

            if len(active) >= MAX_CONCURRENT_CYCLES:
                log(
                    f"{len(active)} cycles already active (cap "
                    f"{MAX_CONCURRENT_CYCLES}); waiting to handle: "
                    f"{', '.join(sorted(newly)) or 'findings/kick'}"
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
            if findings:
                # Delivered once; the full text also lives in orchestrator.log.
                FINDINGS.write_text("")
            active.append(spawn_cycle(newly, running, findings, in_flight))
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # survive transient W&B/network errors
            log(f"watcher error: {e!r}; retrying in {POLL_S}s")
            time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
