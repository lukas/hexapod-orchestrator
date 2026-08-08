# Autonomous experiment orchestrator

A self-driving loop that keeps the CoreWeave RL campaign running while the
operator is away: when training runs finish, a headless Cursor agent
evaluates the checkpoints, appends results to the experiment log, decides
the next experiments within guardrails, snapshots the code, and launches.

## Architecture

```
controller pod (hexapod-sweep-friction, tmux session "orchestrator")
  watch_loop.py                       # polls W&B every 5 min
    └─ when no tracked runs are running:
         claude -p --bare --model claude-fable-5 <ORCHESTRATOR_PROMPT.md>
         # one decision cycle (Claude Code headless, operator's Anthropic key)
            1. pull checkpoints, run gate evals (eval_checkpoint.py)
            2. append results to EXPERIMENT_LOG.md
            3. decide next experiments (guardrails.yaml limits)
            4. snapshot.sh <name>  →  git commit + tag exp/<name> + push
            5. sync code to pods, launch runs, record W&B notes + commit hash
```

State lives in the repo (EXPERIMENT_LOG.md, lineage.json, tags), so every
cycle is auditable and every run is pinned to an exact commit.

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
