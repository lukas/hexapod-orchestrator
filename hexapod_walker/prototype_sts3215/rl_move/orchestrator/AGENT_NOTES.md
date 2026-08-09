# Agent notes — read this FIRST every cycle (60 seconds, saves 20 minutes)

Distilled from mining every prior cycle transcript (2026-08-09): the
same commands were re-derived, and the same mistakes re-made, dozens
of times. `ops.sh` implements the common operations — use it.

## Where things are (the #1 recurring failure: wrong paths)

- Controller repo root: `/workspace/weird_objects`. Cycles start HERE.
- PROTO dir: `/workspace/weird_objects/hexapod_walker/prototype_sts3215`
  — `cd` here first; every doc/tool path below is relative to it.
  (9/9 failures of `cat rl_move/orchestrator/guardrails.yaml` were
  agents trying orchestrator paths from the repo root.)
- `/workspace/prototype_sts3215` on the CONTROLLER is a STALE copy
  (its ledger is a symlink to the real one). Never work there.
- On TRAINING PODS the code IS at `/workspace/prototype_sts3215`
  (no git there; the `.code_sha` marker is the only version record).
- Docs: `RL_PLAN.md` + `RL_LOG.md` are CONDENSED (~120 lines each,
  read them whole — no more sed windows). Full history:
  `archive/RL_LOG_FULL_2026-08-09.md`, `archive/RL_PLAN_FULL_*.md`.
  Log append rule: 1–3 lines per entry; evidence goes to W&B/ledger.

## ops.sh (rl_move/orchestrator/ops.sh) — use instead of hand-rolling

- `ops.sh status` — active runs + live procs per pod + watcher tail.
- `ops.sh procs <pod>` — training/eval processes. **Pods have NO
  `ps`** — this scans /proc; agents rediscovered that trick 10+ times.
- `ops.sh trainlog <run> [n]` — tail the run's train log on its pod
  (pod + log path come from the ledger; don't guess).
- `ops.sh entry <run>` — the run's ledger entries.
- `ops.sh wandb <run>` — state, steps, reward-quarters trend, std, URL.
- `ops.sh pullckpt <run>` — fetch checkpoint from its pod + md5.
- `ops.sh evalcmd <run>` — prints the exact-path harness eval command
  with the run's own `--cfg-set`s pulled from the ledger.
- `ops.sh waitlog <file> <regex> [timeout]` — poll for completion.
  **`sleep 60; tail …` is BLOCKED by the harness** — use this.

## Hard-won gotchas (each cost a cycle at least once)

1. **`eval_checkpoint` runs ONLY as a module** from the PROTO dir:
   `python3 -m rl_move.sim.eval_checkpoint …`. Running the .py path
   dies on relative imports. Flags (stop re-running --help):
   `checkpoint --task {goal,joint_goal,joint_walk} --modes … --per-mode N
   --dr-scale F --seed N --episode-seconds S --stochastic
   [--end-posture-gate] [--no-video|--video-every N] --out DIR
   --cfg-set k=v (repeatable)`.
2. **Launch ONLY via `launch_run.py launch`.** Raw `kubectl exec …
   nohup train_ppo…` hits the 2-minute exec timeout (looks dead,
   actually launched → ledger drift; this caused a real incident).
   Ledger edits ONLY via `launch_run.py update`.
3. **Eval with the run's OWN cfg** (`ops.sh evalcmd`): evaluating with
   default cfg silently drops the run's reward package and voids the
   verdict (`lowent-dr03` burned 4M steps on this class of mistake).
4. **kubectl needs `KUBECONFIG=~/.kube/coreweave.yaml`** (ops.sh sets
   it). `kubectl exec` dying mid-command does NOT mean the remote
   command died — check before re-running anything with side effects.
5. **snapshot → sync → launch, in that order, same cycle.** The
   launcher refuses a pod whose `.code_sha` ≠ local HEAD (also
   `-dirty`). Snapshotting AFTER launching leaves the pod a commit
   behind and blocks the watcher's auto-continue (cycle 33 incident).
   After `snapshot.sh <run>`, run `snapshot.sh --sync <pod>` for the
   pod you're about to launch on.
6. **Checkpoint naming:** run `cw-walk-foo-c1` ⇒
   `rl_move/sim/policies/ppo_goal_cw_walk_foo_c1.zip` (dashes→
   underscores). Always record + compare md5 when pulling.
7. **W&B:** project `l2k2/hexapod-balance`; creds already in the
   cycle env. Prefer `ops.sh wandb <run>`; for ad-hoc queries use
   `wandb.Api()` filtered by `display_name`, newest match.
8. **git:** `snapshot.sh` serializes commit/tag/push under a lock —
   never raw `git push` for cycle edits; a brief wait on its lock is
   normal. Re-read RL_LOG/RL_PLAN right before editing (concurrent
   cycles append too).
9. Guardrails: `rl_move/orchestrator/guardrails.yaml` (from PROTO).
   Watcher log: `/workspace/orchestrator.log`. Cycle logs:
   `/workspace/cycle_logs/`. Per-run train logs live ON THE POD at
   `/tmp/train_<run>.log`.

## Time budget guidance

The operator's standing complaint is cycle latency. Read the two
condensed docs + guardrails (fast), use `ops.sh`, launch evals in
PARALLEL (`nohup … &` all of them, then `waitlog` each), and don't
reproduce evidence into RL_LOG — link it. If a run is clearly
improving and flagged auto-continue, the watcher already relaunched
it; your job is the verdict, not the relaunch.
