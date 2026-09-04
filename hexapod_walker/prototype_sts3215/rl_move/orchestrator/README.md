# Autonomous experiment orchestrator

A self-driving loop that keeps the CoreWeave RL campaign running while
the operator is away. Mechanical software owns state and throughput;
an LLM cycle owns judgment (verdicts + what to try next). If this file
and the code disagree, the code is right — fix this file.

**Taking over this project (human or LLM)? Start with `RL_GOALS.md`
and `RL_PLAN.md`** (prototype root) — the two goals and the operating
plan — then `ORCHESTRATOR_PROMPT.md` for how a cycle behaves. This
file covers mechanics only.

## Architecture (2026-08-09)

```
controller pod (hexapod-sweep-friction, tmux session "orchestrator")
  watch_loop.py — polls W&B every 5 min, plus three background workers:
    • backlog worker: every 2 min, `launch_run.py drain` pushes queued
      specs from backlog.json onto free GPU pods (self-repairing:
      syncs code, pushes checkpoints + W&B secret, retries 3x, then
      parks in backlog_failed.json)
    • checkup worker: ~5 min after each launch, `launch_run.py
      checkup`; DEAD/SUSPECT findings are injected into the next cycle
    • pre-stager: for each newly finished run, pulls the checkpoint,
      starts the DR-0 gate eval, caches W&B data
  when runs FINISH → spawns a decision cycle (cap 2, concurrent):
    claude -p --bare --model claude-fable-5 <ORCHESTRATOR_PROMPT.md>
    the cycle TRIAGES each finished run (~10 min: video, curves,
    gate scalars), records verdicts via `launch_run.py update`
    (auto-renders rl_docs/runs/<run>.md) + `ops.sh wandbnote`,
    digs in only on a real trigger, and refills the pipeline by
    queueing specs into the backlog. Logs: /workspace/cycle_logs/
```

Training pods: `hexapod-mjx-train-0..15` (1 H200 + 24 cores each; see
`CAPACITY.md`, live truth via `capacity.py`). New pods are initialized
by `bootstrap_train_pod.sh`, which writes the `.bootstrapped` marker
the drain requires before treating a pod as a slot.

## State — machines own facts, the LLM owns interpretation

- `experiments.json` — the ledger, single source of truth per run
  (status, hypothesis, gate, verdict, W&B id). Edit ONLY via
  `launch_run.py update`. Every update regenerates the browsable
  per-run summary in `rl_docs/runs/`.
- `backlog.json` — mechanical launch queue, fed by cycles/operator
  (`launch_run.py backlog add`), drained automatically.
- `RL_LOG.md` — 1 line per cycle; `RL_PLAN.md` — the plan (~120
  lines). Everything else: `rl_docs/` (start at its README).
- Code provenance: `snapshot.sh` commits/tags/pushes, `--sync` stamps
  pods with `.code_sha`; the launcher refuses mismatched pods.

## Operating it

- **Everything routine**: see `rl_docs/COMMANDS.md` (ops.sh helpers,
  gotchas, which command answers which question).
- **Pause cycles:** `touch PAUSE` in this directory on the controller
  (training keeps going). Unpause: remove the file.
- **Kick a session now:** `ops.sh cycle ["focus text"]` (works from the
  operator Mac) writes `KICK` here; the watcher wakes within seconds
  (sleep_poll) and spawns one deep-model session, allowed past the
  triage concurrency cap into the kick overflow pool (up to
  KICK_OVERFLOW_SLOTS extra sessions, operator 08-15), counted in the
  daily budget.
- **Kick via MCP:** `/mcp` requires the operator's MCP key since
  08-15 (`MCP_AUTH_KEY` env or `/workspace/.mcp_key`; sent as
  `Authorization: Bearer`, `X-Api-Key`, or `?key=` — the old keyless
  mode made client-side safety layers block feedback), so
  `kick_orchestrator` files the TRUSTED operator `KICK` (deep-model
  session that does what the focus note asks, same as `ops.sh
  cycle`). The `/workspace/llm_kicks/` advisory queue remains only to
  drain pre-gate entries: one triage-model session per request in the
  kick overflow pool, each counted in the daily budget.
- **Save feedback on a run via MCP:** call
  `submit_run_feedback(run, feedback, topic?, author?)`. The run name is
  validated against `experiments.json`, then the JSON note is stored
  atomically in `/workspace/llm_feedback/` (outside the git checkout), shown
  on `/run/<run>` and the dashboard, returned by `get_run` and
  `list_run_feedback`, counted in `list_runs`, and injected into the next
  watcher cycle with the run association intact. Use plain `submit_feedback`
  only for campaign-wide notes. Feedback survives service and git-sync
  restarts; it does not launch a cycle by itself.
- **Watch a cycle live (08-21 observability pass):** cycles run with
  `--output-format stream-json` piped through `cycle_render.py`, so
  each `/workspace/cycle_logs/cycle_<stamp>_<label>.log` fills with a
  readable narration AS THE CYCLE WORKS — every assistant thought,
  tool command, result preview, then the final verdict + cost, ending
  with `=== CYCLE END: <how> ===`. Siblings: `.prompt.md` (the exact
  prompt the cycle received) and `.jsonl` (raw events).
  `cycle_logs/cycles.json` is the watcher-maintained registry (one
  row per cycle: label/model/pid/runs/paths, then rc/outcome).
  From the Mac or the controller:
  `ops.sh activity` (everything in one shot), `ops.sh cyclelog
  [pattern]` (one cycle's narration), `ops.sh waitcycle [pattern]`
  (follow live until it ends — the answer to kick-then-blind-poll).
  Same data via MCP: `orchestrator_activity`, `cycle_log`.
- **Restart the watcher:** ONLY via `restart_watcher.sh` (nohup'd on
  the controller). Hard-killing the tmux session murders in-flight
  cycles — their narration survives on disk, but un-saved verdicts
  and the spent tokens do not.
- **Operator-blocking alert:** `ops.sh blocker report <source> <summary>
  [details]` writes a concurrency-safe runtime record outside the git
  checkout. `ops.sh blocker list` and `resolve <id> [resolution]` inspect and
  close it. The private `GET /api/blockers` feed accepts the existing MCP
  operator key and is polled by the Mac blocker-alert relay. Use this only
  after retries and alternate useful work are exhausted; routine experiment
  failures and normal operator-owned hardware steps are not alert-worthy.
- **Logs:** `/workspace/orchestrator.log` (watcher),
  `/workspace/cycle_logs/` (cycles, live-streaming),
  `/tmp/train_<run>.log` (on pods).

## Safety

`guardrails.yaml` binds every cycle: sim/pods only, never the physical
robot, caps on concurrent runs / steps / cycles per day. The workspace
hardware-safety rules travel with the repo (AGENTS.md, .cursor/rules/).
