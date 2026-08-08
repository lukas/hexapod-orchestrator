# Autonomous experiment orchestrator

A self-driving loop that keeps the CoreWeave RL campaign running while the
operator is away: when training runs finish, a headless Cursor agent
evaluates the checkpoints, appends results to the experiment log, decides
the next experiments within guardrails, snapshots the code, and launches.

## Architecture

```
controller pod (hexapod-sweep-friction, tmux session "orchestrator")
  watch_loop.py                       # polls W&B every 5 min
    └─ whenever a run FINISHES (others may still be training):
         claude -p --bare --model claude-fable-5 <ORCHESTRATOR_PROMPT.md>
         # one decision cycle (Claude Code headless, operator's Anthropic key)
         # cycles are spawned CONCURRENTLY (cap 2): a finish never queues
         # behind a cycle already in flight; git/launch/ledger locks keep
         # them from stepping on each other; per-cycle logs in
         # /workspace/cycle_logs/
            1. pull checkpoint, run gate evals WITH VIDEO, look at the
               frame strips (motion quality, not just scalars)
            2. append a short summary (incl. what videos showed) to RL_LOG.md
            3. review RL_PLAN.md vs the big goal; revise without growing it
            4. decide next experiment(s) for the freed pod(s)
            5. snapshot.sh <name>  →  git commit + tag exp/<name> + push
            6. sync code to pods, launch runs, record W&B notes + commit hash
```

State lives in the repo (RL_LOG.md at the prototype root, lineage.json,
tags), so every cycle is auditable and every run is pinned to an exact
commit. The watcher keeps a local set of already-handled finished runs in
/workspace/orchestrator_state.json.

The watcher also owns post-launch checkups: ~5 min after every verified
launch it runs `launch_run.py checkup` in a background thread
(/workspace/checkup_state.json tracks which launches were checked).
DEAD/SUSPECT verdicts are appended to /workspace/checkup_findings.md,
which triggers the next agent cycle and is injected into its prompt.
Agent cycles therefore exit right after launch verification instead of
sleeping 5 minutes per launch; the standing prompt likewise requires all
harness evals to run in parallel at cycle start.

## One-time setup

1. Create a fine-grained GitHub token with contents:read/write on
   `lukas/weird_objects`, and have a Cursor API key ready.
2. Run `setup_controller.sh` from the laptop (it prompts for both secrets,
   installs cursor-agent + a git clone on the controller pod, and starts the
   tmux loop).

## Operating it

- **Pause:** `touch PAUSE` in this directory on the controller pod
  (the loop idles until the file is removed). Training keeps going.
- **Stop:** kill the tmux session `orchestrator` on the controller pod.
- **Audit:** read EXPERIMENT_LOG.md (committed every cycle), the
  `exp/<run-name>` git tags, and W&B run notes — each records hypothesis,
  gate, parent checkpoint, and code commit.
- **Logs:** `/workspace/orchestrator.log` on the controller pod.

## Safety

The agent operates under `guardrails.yaml` and the standing prompt:
sim/pods only, never the physical robot, hard caps on concurrent runs,
steps per run, and decision cycles per day. The workspace hardware-safety
rules also travel with the repo (AGENTS.md, .cursor/rules/).
