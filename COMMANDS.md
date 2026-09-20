# COMMANDS — how to run everything (60 seconds, saves 20 minutes)

Distilled from mining every prior cycle transcript (2026-08-09): the
same commands were re-derived, and the same mistakes re-made, dozens
of times. `ops.sh` implements the common operations — use it. The
orchestrator (`ops.sh`, `launch_run.py`, `status_server.py`,
`mcp_server.py`, `guardrails.yaml`, ...) and the research docs
(`RL_GOALS.md`, `RL_PLAN.md`, `RESEARCH_RULES.md`, `ORCHESTRATOR_PROMPT.md`)
are the separate repo https://github.com/lukas/hexapod-orchestrator; below,
`~/hexapod-orchestrator/orchestrator/...` is its checkout (Mac:
`~/hexapod-orchestrator`, controller pod: `/workspace/hexapod-orchestrator`).
Sibling docs here: `rl_docs/README.md` (index), `rl_docs/EXPERIMENT_LOGS.md`
(per-run summary.md convention).

**PYTHON RULE:** local/project Python commands go through `uv`. Use
`uv run python ...`, `uv run python -m ...`, or `uv run pytest ...`;
do not run bare `python3`, bare `python`, or direct `.venv/bin/python`
paths unless the command is an explicit exception. Native MuJoCo
GUI/viewer launches on macOS use `uv run mjpython ...` or the Makefile
viewer wrapper; board-side systemd and historical/generated logs are
also explicit exceptions.

**STANDING RULE — promote what you figure out:** if a command failed,
was slow, or took several tries before you got it right, add it as an
`ops.sh` subcommand (or a snippet below) IN THE SAME CYCLE, and note
it in `rl_docs/README.md` if it changes what a file covers. Never
leave the next agent to rediscover it.

## Which question → which command (don't mix these up)

| Question | The ONE command |
|---|---|
| **Triage a finished run (START HERE)** | `ops.sh review <run>` — ledger+gate, W&B trend, eval table, video paths in one shot |
| Eval numbers table from a report.json | `ops.sh report <run\|path>` (per-episode + medians + term counts) |
| What is actually training right now? | `ops.sh census` (/proc truth; W&B lags launches ~8 min) |
| How many slots are free / where? | `uv run python ~/hexapod-orchestrator/orchestrator/capacity.py` |
| Ledger + procs + watcher, one screen | `ops.sh status` |
| One run's metrics/state | `ops.sh wandb <run>` (ledger: `ops.sh entry <run>`) |
| What's queued to launch? | `launch_run.py backlog list` |
| Queue a seed/rung/variant of an existing run | `launch_run.py respec --from <run> --run <new> [--seed N] [--arg='--flag=v'] [--cfg k=v] --hypothesis … --gate …` — clones the ledger args; never re-type them. Add `--init-from-source` to warm-start from the source's checkpoint; add `--now [--pod P]` to skip the backlog and launch directly (snapshot → sync → self-repair → verify, one command). Phase/evidence inherit from the source; override with `--phase`/`--evidence` |
| Run the tests | `uv run pytest -m "not slow"` from `prototype_sts3215/` (default loop, minutes); `uv run pytest` for everything; laptops add `-n auto`. The MDP_PREFLIGHT rollout bank is RETIRED (09-08) — see RESEARCH_RULES "Tests" before adding any test |
| Eval a DR/noise/latency child against its parent honestly | `uv run python -m rl_move.sim.eval_checkpoint <child.zip> --baseline <parent.zip> --cfg-set <same injection> …` — matched-parent control; child-vs-clean-parent verdicts are invalid |
| OPERATOR: fire one launch during a LAUNCH_HOLD | `ops.sh oplaunch respec --from <run> --run <new> --init-from-source --now --operator-override 'why' --hypothesis '<plain English — this LEADS the W&B notes>' --gate '…'` — runs on the controller from anywhere (incl. the operator Mac); the override is audited in the ledger and operator-only |
| **How was a policy trained? (lineage, cfg diff vs parent, verdict, exports, real walks)** | `ops.sh index story <run>` — one shot, joined; `ops.sh index lineage <run>` for the family tree. Filter on the canonical `outcome`, not the raw `status` spelling |
| **What are the most promising experiments?** | `ops.sh index promising [--track t]` — three evidence tiers: walked on the real robot (ranked by achieved/commanded speed + IMU roll) > exported for the robot, not yet walked > sim PASS/PARTIAL never exported. Same as `/llm/index.md` and MCP `promising_runs` |
| **Did it walk on the real robot, how well?** | `ops.sh index real [<policy.json>\|<run>]` — every Robot Lab drive leg (speed_ratio, straight speed, tilt, stop reason) and older sweep exposure (roll/pitch RMS, harness verdict) per policy file, joined to its training run |
| Rebuild the joined index files (INDEX.md, runs.jsonl, lineage.json, policies.json, real_walks.jsonl, promising.json, status_map.json, open_questions.md) | `ops.sh index build` — Mac: writes `~/.hexapod/rl_index/` and joins the Robot Lab folders + the robots' own `/api/rl/policies`; controller: `snapshot.sh` does it after every run (ledger-only) into `<state>/index/` |
| A past run's story (generated prose) | `rl_docs/runs/<run>.md` — `ops.sh index story <run>` is the joined version |
| Journals too big to read (CURRENT_TRUTHS / OPERATOR_QUESTIONS / RL_LOG / track STATUS) | `ops.sh compact --dry-run` then `ops.sh compact` — keeps the last 7 days of findings, every OPEN question, all operator rulings and the durable sections; everything else moves to `<state>/archive/doc_compaction_<date>/` (pre-edit copies included, nothing deleted). Pauses cycle spawns and waits for in-flight cycles first |
| Yaw-command tracking (yawcmd lineage gate) | `uv run python -m rl_move.sim.eval_yaw <ckpt> --cfg-set … [--out j.json]` — scripted turn panel; reports turn-segment \|wz_err\| med, hold \|wz\| med, falls |
| AMP M5 cross-engine suite (track DONE gate) | `uv run python -m rl_move.sim.eval_amp_m5 <ckpt> --out-dir logs/ckpt_eval/<name>_m5 --cfg-set <own cfg…>` — ONE invocation composing walk/yaw/push/fault sections in plain MuJoCo with pre-registered bars (amp-m5-v1, q_20260823T0130Z); run on a pod, read `m5_verdict.json`, watch the section strips before claiming. `ops.sh m5eval <run> [pod]` (08-23) does this end-to-end: derives the run's own cfg-set from the ledger (same logic as `evalcmd`), syncs code to the target pod, runs it, copies `logs/ckpt_eval/<run>_m5/` back — never hand-roll the kubectl plumbing |
| Are results being lost/ignored? | `ops.sh triage [hours]` |
| Finished but not yet analyzed? | ledger `triage` field (watcher-stamped: `awaiting…` → `in-cycle…` → `done` on verdict); shown on the status page "Analysis pipeline" |
| Write the cycle's RL_LOG line | `ops.sh logline "c<N>: …"` — the ONLY way; never `cat >>` RL_LOG |
| Frames from a video | harness already wrote `*.png` sheets; else `ops.sh frames <mp4> [n]` |
| Full regression suite | `ops.sh testfull` (xdist parallel, ~5 min; serial is >60 min — never run the full suite bare) |
| Operator asks for a MuJoCo drive-around video | `ops.sh drivevideo <run> [out-dir] [--script square\|human\|sweep\|human_turn\|turn] [--wz-max 0.3] [--policy-mode stochastic\|deterministic]` — walk-only joystick video, full mesh required by default, run cfg stack carried from the ledger; `human_turn`/`turn` also record commanded/actual `wz` |
| Operator asks how a promising policy "feels" | `ops.sh feeltest <run> [out-root] [--unified]` — one-command transition plus yaw-heavy drive suite. Default composes scripted tuck rise/lower around any walk policy; `--unified` makes the checkpoint itself perform rise/walk/lower. Writes separate `transitions/` and `yaw/` artifacts. |
| Operator asks for a transfer-shaped MuJoCo demo | `ops.sh hybriddemo <run> [out-dir] [--script square\|human\|sweep\|human_turn\|turn] [--wz-max 0.3] [--policy-mode deterministic\|stochastic] [--stand-controller learned] [--stand-release stable\|profile]` — composable full-mesh stand->RL-walk->lower demo; learned stand defaults to stable handoff; writes `composition.json`, `transfer_manifest.json`, and `wz` metrics for turn-capable scripts |
| **What is the orchestrator doing RIGHT NOW?** | `ops.sh activity` — watcher heartbeat, pending kicks, every running cycle with the tail of its LIVE narration, recent finishes, newest ledger rows (works from the Mac) |
| Watch one cycle work (thoughts + commands, live) | `ops.sh cyclelog [pattern] [n]` (one-shot tail) or `ops.sh waitcycle [pattern]` (follow until `=== CYCLE END`) — cycles stream since 08-21; never blind-poll a kick again |
| What exactly was a cycle told? | its `.prompt.md` next to the cycle log (`/workspace/cycle_logs/`), or MCP `cycle_log(cycle, part='prompt')` |
| Operator wants an overview in a browser | status page at http://127.0.0.1:8090/now — latest research brief first; full setup/restart runbook in "Operator status page" section below |
| An external LLM (GPT/Claude) wants to read status | `https://hexapod.cwd1f0-new-cluster.coreweave.app/llms.txt` (no key) — see "LLM-readable mirror" in the status-page runbook |

**DO NOT hand-write python for any row above.** Transcript mining
(08-09) found >500 ad-hoc snippets re-parsing experiments.json,
report.json, and the W&B API for exactly these questions.

## Where things are (the #1 recurring failure: wrong paths)

- Controller repo root: `/workspace/hexapod`. Cycles start HERE.
- PROTO dir: `/workspace/hexapod/hexapod_walker/prototype_sts3215`
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
  Log append rule: ONE line per cycle via `ops.sh logline` — never
  `cat >>`; evidence goes to the ledger verdict + W&B, not the log.

## ops.sh (~/hexapod-orchestrator/orchestrator/ops.sh) — use instead of hand-rolling

- `ops.sh status` — active runs + live procs per pod + watcher tail.
- `ops.sh procs <pod>` — training/eval processes. **Pods have NO
  `ps`** — this scans /proc; agents rediscovered that trick 10+ times.
- `ops.sh census` — every train pod's live trainer from /proc. THE
  ground truth for "what is running": W&B lags fresh launches by up
  to ~8 min (JAX compile) and looks empty when things are fine.
- `ops.sh trainlog <run> [n]` — tail the run's train log on its pod
  (pod + log path come from the ledger; don't guess).
- `ops.sh entry <run>` — the run's ledger entries.
- `ops.sh argdiff <run> [runB]` — launch-arg diff vs parent (or runB).
- `ops.sh cfgset <run>` — the run's FULL training `--cfg-set` list,
  probe-ready; never hand-pick a cfg subset for a probe/eval.
- `ops.sh wandb <run>` — state, steps, reward-quarters trend, std, URL.
- `ops.sh review <run>` — the standard triage read in ONE command
  (ledger, W&B, eval table, videos). If its output + one video answer
  pass/fail, record the verdict and stop.
- `ops.sh report <run|report.json>` — per-episode table + medians +
  gait_valid/termination counts from a harness report.
- `ops.sh logline "text"` — the only sanctioned RL_LOG write (one
  timestamped line under the git lock).
- `ops.sh frames <mp4> [n]` — contact sheet from any video (but the
  harness already writes `walk_*.png` sheets next to eval videos —
  check those first).
- `ops.sh drivevideo <run> [out-dir] [args...]` — clean walk-only
  joystick drive video for "show me driving <run> around": uses the
  run's own cfg stack, pulls the checkpoint if needed, builds/requires
  local full-mesh assets, starts from a settled plant walk episode, and
  writes `drive.mp4`, `contact_sheet.png`, `summary.json`, and
  `ticks.json`. Extra args pass through to `rl_move.sim.drive_video`
  (`--script human|square|sweep`, `--policy-mode stochastic|deterministic`,
  `--seconds N`, `--speed M`, ...).
- `ops.sh hybriddemo <run> [out-dir] [args...]` — transfer-shaped
  MuJoCo demo for comparing controller compositions: baked STEP or
  learned stance stand,
  explicit sim-walk-ready align, bookkeeping re-anchor into the walk
  policy's plant frame, RL joystick walk, align-back, STEP or learned
  lower, limp settle. Full mesh is required by default. It writes
  `drive.mp4`, `contact_sheet.png`, `composition.json`, `summary.json`,
  `ticks.json`, and `transfer_manifest.json`. Use
  `--stand-controller learned` for the promoted mesh stance policy
  (`stand_stancemix_tuckclock_scratch8m`) and
  `--lower-controller learned` when specifically comparing learned sit.
  Use `--stand-mode tuck --lower-mode tuck` for the lower-current
  scripted tuck stand/lower baseline; this is the preferred non-RL
  comparison when foot sliding is the concern.
  Learned stand defaults to `--stand-release stable`, so transfer demos
  hand off after the trained rise ramp is upright and calm instead of
  waiting out the full validation profile; use `--stand-release profile`
  for stance soak/evaluation.
  Use this when comparing "policy + state" bundles rather than judging a
  walk-only policy in isolation.
- `ops.sh feeltest <run> [out-root] [--unified]` — the standard
  subjective-control suite. It runs a forward/reverse transition demo and a
  separate `human_turn` drive (arcs plus pure left/right yaw). Default uses
  scripted tuck rise/lower so any walk checkpoint can be compared;
  `--unified` evaluates a unified checkpoint's learned rise/lower directly.
  Inspect both `summary.json` files and both videos/contact sheets. The helper
  also regenerates the gitignored electronics-stack STLs and full MuJoCo mesh
  when absent, so a clean checkout does not require manual CAD preparation.
- `ops.sh pullckpt <run>` — fetch checkpoint + md5. It prefers the controller's
  durable canonical repo copy (`/workspace/hexapod/.../rl_move/sim/policies/`),
  then falls back to the original training pod for a fresh unsynced run. This
  order is deliberate: training pods are reused and may contain different
  weights under a historical filename.
- `ops.sh pushckpt <pod> <ckpt>` — copy a checkpoint TO a pod + md5
  both sides. **`snapshot.sh --sync` EXCLUDES policies/** — a
  warm-start parent must be pushed explicitly or the run dies at
  init with FileNotFoundError (killed cw-walk-longdist, 08-09).
  If `kubectl cp`/exec-stdin streams keep dropping (websocket
  close/broken pipe — hit train-2/3, 08-09 c35): HTTP-serve from
  the controller (`uv run python -m http.server 8765` in policies/) and
  on the pod `uv run python -c "import urllib.request; urllib.request.
  urlretrieve('http://10.0.0.46:8765/<zip>', '<dest>')"` — pods
  have no curl/wget. Always md5 after.
- `ops.sh evalcmd <run>` — prints the exact-path harness eval command
  with the run's own `--cfg-set`s pulled from the ledger.
- `ops.sh waitlog <file> <regex> [timeout]` — poll for completion.
  **`sleep 60; tail …` is BLOCKED by the harness** — use this.
- `ops.sh oplaunch <launch_run.py args…>` — run a launcher command ON
  THE CONTROLLER (detached, creds sourced, result polled), from the
  operator Mac or the controller itself. Exists because launches must
  run where git is the code-sha truth: a laptop clone is stale/dirty
  and gets refused (08-10: the operator's assistant hand-rolled
  kubectl-cp + tmux + hold-file juggling for one continuation launch).
  Pairs with `respec --now` and, for operators only,
  `--operator-override` (audited LAUNCH_HOLD bypass for a single
  launch — agents must never pass it). Put the plain-English paragraph
  in `--hypothesis` (it leads the W&B notes) or override wholesale
  with `--arg='--notes=…'`. Record the launch with `ops.sh logline`.
- `ops.sh expdir <run>` — create `logs/experiments/<run>/` with the
  summary.md template. Only for DIG-IN runs (08-09 lightweight
  process): clear pass/fail needs just the ledger verdict (which
  auto-renders `rl_docs/runs/<run>.md`) + `wandbnote`.
- `ops.sh wandbdump <run>` — cache the run's W&B summary/config/
  history into its experiment dir (query the cache, not the API).
- `ops.sh triage [hours]` — "is anything lost/ignored?" table: every
  recent W&B run × ledger verdict × OUTCOME note × watcher processed
  flag. Run it whenever the operator asks if results are being
  dropped (they asked twice on 08-09; this answers in 5 s).
- `ops.sh drain` — place backlog onto free pods, detached + creds
  sourced. Raw `launch_run.py drain` needs W&B creds (dedupe check)
  and takes minutes PER LAUNCH by design (two-phase verify waits out
  the pod's JAX/Warp compile) — never run it attached to a terminal
  you might close. The watcher auto-drains too, but NOT while PAUSEd
  (e.g. during restart_watcher.sh).
- `ops.sh killrun <run>` — kill a run's procs on its pod. Pods have
  no pkill, and a naive /proc scan KILLS ITSELF (your scan's cmdline
  contains the run name — a kill command suicided this way 08-09).
  Then record it: `launch_run.py update … status=KILLED verdict=…`.
- `ops.sh activity` — the orchestrator in one shot: watcher heartbeat,
  pending kicks, every RUNNING cycle with its live narration tail,
  recent finishes, newest ledger rows, watcher log tail. Same view as
  the MCP `orchestrator_activity` tool. Works from the operator Mac
  (re-execs itself on the controller).
- `ops.sh cyclelog [pattern] [lines]` — tail one cycle's narration log
  (default newest). Cycles STREAM since 08-21: assistant thoughts,
  every tool command, result previews, final verdict + cost, ending
  `=== CYCLE END: <how> ===`. Siblings: `.prompt.md` (exact prompt),
  `.jsonl` (raw events), `cycles.json` (registry).
- `ops.sh waitcycle [pattern] [timeout]` — FOLLOW a cycle live until
  it ends. The kick workflow is now `ops.sh cycle "focus"` then
  `ops.sh waitcycle operator-kick` — no more sleep/poll loops guessing
  whether a silent session is alive.

## Hard-won gotchas (each cost a cycle at least once)

0. **Any untracked NON-doc file under the prototype tree (e.g. a fresh
   `rl_move/sim/park_banks/*.npz` from `harvest_park_states`) marks
   every `snapshot.sh --sync` `-dirty` and the launcher then REFUSES
   ALL drain launches** — 4 GPUs idled behind one uncommitted 26KB
   npz while its specs burned 3 attempts each into `backlog_failed.json`
   (08-09 c51). Commit (`snapshot.sh <name>`) right after generating
   any training-input artifact, BEFORE queueing specs that need it.
   Requeue after fixing: move items backlog_failed→backlog under
   `backlog.json.lock` with attempts reset, then `ops.sh drain`.

0b. **A controller eval can DEADLOCK on a corrupt ffmpeg pipe**
   (log shows `corrupt input packet` / `Invalid buffer size`, then
   the python's utime freezes with no children — hit the groundtilt5
   dr0ret pass, 08-09 c60, under heavy concurrent-eval load). Detect:
   output dir stops growing AND `cat /proc/<pid>/stat` utime is
   static across 5 s. Fix: kill the pid and rerun the pass with
   `--no-video` (metrics JSON is what gates need; frame strips from
   the hung run remain usable).

1. **`eval_checkpoint` runs ONLY as a module** from the PROTO dir:
   `uv run python -m rl_move.sim.eval_checkpoint …`. Running the .py path
   dies on relative imports. Flags (stop re-running --help):
   `checkpoint --task {goal,joint_goal,joint_walk} --modes … --per-mode N
   --dr-scale F --seed N --episode-seconds S --stochastic
   [--end-posture-gate] [--no-video|--video-every N] --out DIR
   --cfg-set k=v (repeatable)`.
   **Driving candidates additionally need the JOYSTICK GATE**
   (`uv run python -m rl_move.sim.eval_drive <ckpt> --dr-scale 0.2 --out
   FILE.json [--cfg-set …]`): scripted direction panel + randomized
   instant-flip stress; zero in-envelope falls = exit 0. The generic
   harness only samples the training distribution — it can't prove
   direction coverage or flip robustness (backforth lesson, 08-09).
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
   `-dirty`). **Never `--sync` with a dirty tree**: it stamps the
   pod marker `<sha>-dirty`, which can NEVER equal HEAD, so every
   later launch on that pod is refused until you commit
   (`snapshot.sh <name>`) and re-sync (cost cycle 51 four refused
   drain launches, 08-09). Snapshotting AFTER launching leaves the pod a commit
   behind and blocks the watcher's auto-continue (cycle 33 incident).
   After `snapshot.sh <run>`, run `snapshot.sh --sync <pod>` for the
   pod you're about to launch on.
6. **Checkpoint naming:** run `cw-walk-foo-c1` ⇒
   `rl_move/sim/policies/ppo_goal_cw_walk_foo_c1.zip` (dashes→
   underscores). Always record + compare md5 when pulling. That
   name is only guaranteed because the launch command carries
   `--out-name`; `launch_run.py launch`/`respec` now always inject
   it if missing (08-10 fix). A run launched BEFORE that fix (or by
   hand, without going through the launcher) with no `--out-name`
   saved under `train_ppo_mjx`'s own default instead:
   `ppo_mjx_<task>_<run>.zip` (e.g. `--task joint_goal` ⇒
   `ppo_mjx_joint_goal_cw-stance-riseproof1.zip`) — `ops.sh
   pullckpt`'s `ppo_goal_...` guess 404s (`cw-stance-riseproof1`,
   08-10: watcher's pre-stage `pullckpt rc=1`, pulled manually once
   diagnosed). `ops.sh pullckpt` now falls back to the
   `ppo_mjx_{joint_goal,joint_walk,goal}_<run>.zip` variants
   automatically before giving up.
7. **W&B:** project `l2k2/hexapod-balance`; creds already in the
   cycle env (elsewhere: source `rl_move/sim/wandb.env`). Prefer
   `ops.sh wandb <run>`; for ad-hoc queries use `wandb.Api()`
   filtered by `display_name`, newest match. Full picture (run-page
   anatomy, OUTCOME notes, artifact lineage): `rl_docs/WANDB.md`.
8. **git:** `snapshot.sh` serializes commit/tag/push under a lock —
   never raw `git push` for cycle edits; a brief wait on its lock is
   normal. Re-read RL_LOG/RL_PLAN right before editing (concurrent
   cycles append too).
9. Guardrails: `/workspace/hexapod-orchestrator/orchestrator/guardrails.yaml` (controller).
   Watcher log: `/workspace/orchestrator.log`. Cycle logs:
   `/workspace/cycle_logs/` — live-streaming narration since 08-21
   (`ops.sh activity` / `cyclelog` / `waitcycle`; prompt in
   `.prompt.md`, raw events in `.jsonl`, registry in `cycles.json`).
   Per-run train logs live ON THE POD at `/tmp/train_<run>.log`.
10. **Restart the watcher ONLY via `restart_watcher.sh`** (in the
    orchestrator dir; deployed at `/workspace/restart_watcher.sh`).
    It sets PAUSE + WRAPUP, waits for in-flight cycles, sanity-parses
    the new code, then swaps the tmux session. WRAPUP (08-09 evening)
    tells cycles to save work and exit at the next run boundary
    (shutdown protocol in ORCHESTRATOR_PROMPT.md); stragglers are
    killed at a 30-min deadline — verdicts already recorded survive,
    unverdicted runs are re-assigned after the swap. The wait loop
    also keeps draining the backlog so already-queued (blocker-vetted)
    specs still place during an update. Killing the watcher/tmux directly still murders
    in-flight cycles mid-thought — 3 cycles' tokens were torched
    this way on 08-09 (and the operator's assistant repeated the
    exact mistake later the same day — READ THIS LIST before
    touching infrastructure).
11. **Verdicts auto-mirror to W&B notes AND package the analysis
    artifact.** `launch_run.py update --set verdict=…` pushes the
    verdict under the `--- OUTCOME ---` marker on the run's W&B page
    and attaches `analysis-<run>` (type run-analysis) to the run:
    ledger entry, `rl_docs/runs/<run>.md`, and every
    `logs/ckpt_eval/<run>_*` + `logs/experiments/<run>/` file
    (report.json, contact sheets, videos). So run your harness evals
    BEFORE setting the verdict — files that exist at verdict time are
    what gets archived. `ops.sh wandbnote` can still replace the note
    with a richer paragraph. History: all 87 pre-existing verdicted
    runs were backfilled 08-09 ~15:20Z — DON'T re-backfill. Early-
    campaign artifacts legitimately hold 0 eval files (outputs were
    already deleted); probe-*/smoke-* runs have no artifact at all
    (no W&B run to attach to). Mechanism note: the public API can't
    create artifacts on a finished run, so the code briefly
    `wandb.init(id=…, resume="allow")`s it — the extra short resume
    blip on a run's timeline is this, not a training restart.
12. **Checkpoint lineage lives in W&B artifacts** (08-09): every
    training run publishes `ckpt-<out-name>` (type
    policy-checkpoint, md5 + parent in metadata) and declares its
    `--init-from` parent via `use_artifact`. The W&B artifact DAG is
    now the run/checkpoint family tree — pre-08-09 parents predate
    this and appear rootless.
13. **`killrun` leaks /dev/shm segments; the NEXT launch on that pod
    dies at first env reset with worker `EOFError`** (c54: two 0-step
    corpses on train-4 after c53's stopgo35 kill — /dev/shm 64M was
    98% full of `hexmjx-*` segments). Diagnose: `kubectl exec <pod>
    -- df -h /dev/shm`. Fix: confirm no live trainer (mind the
    self-match gotcha), then `rm -f /dev/shm/hexmjx-*` and relaunch
    under a NEW name (`-r1`): W&B names are append-only, the launcher
    refuses reuse. Eval completion marker is `artifacts` (the harness
    never prints WROTE) — `waitlog ... 'artifacts|Traceback'`.

13b. **Launch-collision `EOFError` even with a CLEAN /dev/shm** (this
    cycle, 22:1x-22:3x): under concurrent-cycle drain storms (2+
    cycles draining into the same free-pod set within seconds of each
    other), a worker can die with the SAME `EOFError` at first env
    reset as gotcha 13 even when `df -h /dev/shm` shows single-digit
    % used — this is a race between simultaneous launches on
    neighboring GPU pods on the same node, not a shm leak. 3-for-3
    crashed this way in one cycle (imupos15, gyrobias3, tiltnoise; a
    concurrent cycle independently hit the same pattern on
    joyhead90-lat25-s1 and placementnoise6). No science result (0
    steps) — just relaunch under a `-r1` name once (W&B run names are
    append-only) and move on; don't diagnose further unless it
    recurs on a retry with no other drain active.

13c. **RESOLVED (08-10 deep dig-in): the 13/13b `EOFError` class was
    /dev/shm SIGBUS, and it is now self-healing + diagnosable.** Train
    pods have the 64M k8s-default /dev/shm; a normal 4096-env sharded
    layout maps ~58M (measured live), so ANY leaked segments poison
    every later launch on the pod: workers SIGBUS on first page touch
    (POSIX shm is sparse) and the parent saw only a bare `EOFError`.
    Since snapshot `bcf46be`: (a) workers run `faulthandler` and the
    parent prints per-worker exit codes (`-7` = SIGBUS) instead of the
    bare EOFError — read the train log tail, it now names the killer;
    (b) each trainer start GCs orphaned `hexmjx-*` segments (keeps
    live-mapped ones), so poisoned pods self-heal on next launch — no
    more manual `rm`. LIMIT: `obs.history_frames=16` at 4096 envs maps
    >64M and can NEVER boot on a default pod (the 8x arch-hist16 death
    chain) — either run it at `--n-envs 3072` (~50M) or recreate the
    pod (WHILE IDLE) with the dshm-4Gi manifests
    (`coreweave_pod*_mjx_*.yaml`, patched 08-10):
    `kubectl delete pod <pod>` → `kubectl apply -f
    rl_move/sim/coreweave_pods_mjx_scaleout.yaml` →
    `orchestrator/bootstrap_train_pod.sh <pod>` → `snapshot.sh --sync
    <pod>`. Verify with `df -h /dev/shm` (should say 4.0G).

    **08-24 UPDATE: the fix was only ever HALF-APPLIED fleet-wide —
    audit before trusting any pod.** `df -h /dev/shm` on all 12 pods
    (08-24 ~18:4x) found train-1/5/7/9/10/11 on the fixed 4.0G tmpfs
    but train-0/2/3/4/6/8 STILL on the legacy 64M `shm` mount, years
    after the "fixed" snapshot — nobody had ever gone back and
    recreated the stragglers once they went idle. This bit
    `obs.history_frames=64` (a full transformer/hist64 100 Hz arm,
    n_envs=3072): the "obs" shm array alone is ~3072*4608*4 =
    56.6MB, and on a legacy 64M pod that alone is enough — ALL 24
    workers SIGBUS in `env.reset()` before a single PPO step (0
    training, not a science result). Recreated train-6/train-8 this
    cycle (both were idle); a retry of the exact same config on the
    now-4.0G pod trained cleanly past reset. **train-0/2/3/4 remain
    legacy 64M** (0/4 idle at audit time) — recreate opportunistically
    the next time one goes idle, and re-run this same `df -h`
    12-pod sweep periodically since apply-time "fixed" is not
    permanent (a pod recreated for an unrelated reason reverts to the
    k8s default unless it's re-applied from the dshm-4Gi manifest).
    CAUTION: `kubectl apply -f coreweave_pods_mjx_scaleout.yaml`
    applies EVERY pod block in that file, including
    train-12..15 blocks that guardrails.yaml's `gpu_pods` list does
    NOT include (no 4th node exists to schedule them) — it will
    silently CREATE 4 unauthorized Pending pods if you don't delete
    them right back; only ever delete the ONE pod you mean to fix
    before applying, then double-check `kubectl get pod` for
    surprises.

14. **Batch-eval shell footgun (c60):** `CFG="..." && nohup A $CFG & nohup B $CFG &`
    puts the assignment INSIDE the first background job's subshell — B
    (and later jobs) run with an EMPTY $CFG, i.e. default cfg = silently
    voided verdicts (gotcha 3), detectable as cmd_dist/30s outside the
    walk band in report.json. Assign the variable on its OWN line (or
    `export` it), THEN background the evals; always spot-check one
    `/proc/<pid>/cmdline` for the cfg-sets after launching a batch.
    Related (c60/c61): controller evals get load/OOM-killed SILENTLY
    under heavy contention (empty log, no Traceback, no report.json,
    partial video files) — verify the pid in /proc before trusting
    `waitlog`, and relaunch (setsid helps).

14b. **A backlog item silently VANISHES (no backlog_failed entry, no
    error) if a W&B run with the same name already exists** — the
    drain's dedupe check (`drain: <run> already exists in W&B —
    dropping backlog item`) fires even when that prior run FAILED in
    seconds (e.g. a bad `--cfg-set` crash) and never trained anything;
    it only checks the NAME, not whether the prior attempt produced
    real data. If a `--now` launch dies instantly, don't re-`respec`
    onto the SAME run name — use a fresh one (`-r1` suffix) or the
    backlog re-queue will queue-then-disappear with zero trace (cost
    a queue-recheck cycle building `cw-dep-vref1-r1-megastack1`, 08-10).

15. **`--cfg-set dr.<field>=X` needs `lo,hi` (comma, no brackets) for
    every RandRanges field that's typed as a `tuple[float,float]` —
    a bare scalar crashes the worker at reset with `TypeError:
    Generator.uniform() argument after * must be an iterable, not
    float` (cost a launch attempt building `cw-dep-vref1-r1-megastack1`,
    08-10). Scalar (single-float) fields take a bare number; tuple
    fields need both ends. Check `class RandRanges` in
    `rl_move/sim/domain_rand.py` before guessing, or grep an existing
    sibling run's FULL `command` string (not just a `[0-9.]*` regex —
    that silently eats the `,hi` half and looks like a scalar).
    Tuple fields (need `lo,hi`): `mass_scale`, `friction_scale`,
    `contact_stiff_scale`, `torque_scale`, `latency_scale`,
    `deadband_scale`, `vel_scale`, `bad_start_deg`, `imu_pos_z_m`.
    Scalar fields (bare number): `leg_mass_jitter_pct`,
    `link_len_scale_pct`, `link_len_leg_pct`, `ground_tilt_deg`,
    `kp_scale_pct`, `kv_scale_pct`, `placement_noise_deg`,
    `joint_zero_bias_deg`, `encoder_noise_deg`, `imu_mount_deg`,
    `imu_bias_deg`, `tilt_noise_deg`, `gyro_bias_deg_s`,
    `gyro_noise_deg_s`, `com_offset_m`, `imu_pos_xy_m`,
    `cmd_drop_prob_max`.
16. **A manual `kubectl exec` probe on an arbitrary FREE pod can
    silently run STALE code** (08-11, gait-cleanup terrain probe):
    `launch_run.py launch` refuses a `.code_sha` mismatch, but a
    hand-run eval/probe via `kubectl exec` has no such gate — an idle
    pod keeps whatever code was live at its last launch, sometimes
    commits behind. This exactly reproduced an already-fixed bug
    (the `env.terrain_amp>1` clamp, 434a6e0): probing the champion at
    amp 1/2/3 on a stale pod returned bit-identical reports (the OLD
    clamped code), which would have wrongly re-confirmed the closed
    bug. Check `kubectl exec <pod> -- cat
    /workspace/prototype_sts3215/.code_sha` vs local HEAD before
    trusting ANY ad-hoc pod probe that depends on recent code; `bash
    snapshot.sh --sync <pod>` first if it's behind (safe on an idle
    pod, never on one with a live trainer).
17. **FIXED 2026-09-11 (was: real, open mass-audit bug 09-11 06:5x..12:1x).**
    A `mesh`-source eval run LOCALLY on the controller used to silently
    pick up a DIFFERENT, LIGHTER model than every GPU-pod eval/training
    run: the controller has the gitignored full-STL mesh assets checked
    out, so `resolve_model_source`'s default (`mesh`) loaded
    `variant=full_mesh` (3.494 kg) there — but every GPU pod (no STL
    assets, where ALL training runs) transparently fell back to
    `variant=mesh_mjx_twin`, which had drifted to **4.806 kg (+37.5%)**
    since a stale regeneration committed 2026-09-03 (`a55173ab`, no
    matching `build_mesh_model.py` change). ROOT-CAUSED + FIXED this
    cycle: regenerated the checked-in twin via the (unmodified) checked-in
    `mesh_mujoco/build_mesh_model.py` — both variants now compile to the
    identical **3.490 kg**, matching the documented "same kinematics/
    masses/inertia" contract again. `--cfg-set env.model_source=mesh_mjx`
    is no longer required for MASS parity on a controller eval (contact
    geometry — convex-hull vs fitted-primitive — still legitimately
    differs by design, per the docstring, so still prefer `ops.sh podeval`/
    `kubectl exec` for anything contact-sensitive). Full derivation, the
    zero-training re-verification (the standwalk over_current saga very
    likely was fighting this bug, not a real ceiling), and the regression
    test hardened to catch any future re-drift
    (`test_mesh_mjx_twin_builds_and_plants`, was `3.0<m<6.0`, now
    `3.3<m<3.7`): `CURRENT_TRUTHS.md` 2026-09-11 ~12:1x (top entry).
    Evidence: `ops.sh entry cw-stand50hz-stance-tuckclock-scratch6m-dqfix-
    retention-s1-fprent-k0ctl-gentlestd` (verdict, original discovery);
    `logs/ckpt_eval/massfix_verify/` (fix verification).

18. **Pre-registered non-default probes: set `probe_args`, stop
    hand-running them.** If a run's registered gate is NOT the standard
    mixed-start panel (e.g. the stand50hz flat-pinned probe), set
    `launch_run.py update --run <run> --set probe_args='--cfg-set
    goal.rise_flat_frac=1.0 ...'` (raw `eval_checkpoint` args, appended
    last, override the defaults) right after launch — the watcher's
    prestage then runs it on-pod as a third DR-0 pass and triage finds
    it at `logs/ckpt_eval/<run>_probe/report.json` alongside `_gate`/
    `_owncfg`. Never verdict a flat-probe gate off the mixed-start
    `_gate` report (2 wrong verdicts + 1 mispremised launch on 09-11).

19. **`eval_checkpoint --task joint_walk` with no `--modes` does NOT
    default to just "walk"** — `SimHexapodJointWalkEnv.EVAL_MODES`
    (`walk_task.py`) is `("hold", "track", "unload", "raise", "rise",
    "walk")`, six modes, because that class inherits the joint-goal
    env's full skill panel. A hand-rolled speed/behavior panel that
    forgets `--modes walk` silently runs ~5x too many episodes (hold/
    track/unload/raise/rise, all irrelevant to a walk-only question)
    and takes correspondingly longer — cost ~20 min before the mode
    list on disk gave it away, 09-11. `evalcmd`'s own modes-derivation
    (from the run's `--goal-mix` train arg) already gets this right;
    any NEW hand-rolled or ops.sh-built eval invocation for a
    walk-only checkpoint must do the same (see `ops.sh speedpanel`/
    `speedretention`, which now derive `--modes` from the ledger's
    `--goal-mix` the same way).

20. **`respec --init-from-source` used to inherit `--obs-pad-transplant`/
    `--hist-stride-transplant` verbatim from the source run's own extra_args**
    — those flags record the ONE-SHOT widening the source used to warm-start
    from ITS OWN parent, not a property of the source's checkpoint itself.
    Respeccing again onto that already-widened checkpoint (same obs width in,
    same obs width out) re-ran the identical transplant against a same-shaped
    pair and hit `pad_obs_transplant`'s own width-mismatch guard: `SystemExit`,
    zero training steps, no traceback (just the guard's plain message on
    stderr) — cost a dead pod + a 240s launcher timeout on
    `cw-walk50hz-amp-mesh-m2plain-styleoff-pushfaultcurr-rampacq15m` (09-11),
    the third instance of this exact respec-inheritance footgun class after
    `--activation-fn` (08-1x) and `--use-sde` (09-10, `decleg-sde-s0-acq1`).
    **FIXED** same day: `launch_run.py`'s `_respec_plain_warm_obs_pad_transplant`
    now drops an inherited transplant flag on a plain `--init-from-source`
    warm start; pass `--arg='--obs-pad-transplant=N'` explicitly if a NEW
    widening is actually wanted in that respec.

## Operator status page (web) — setup & restart runbook

One auto-refreshing HTML page for the human operator: a first-screen
research brief answering "what is the latest on each topic and where
are we?", watcher ON/PAUSED/OFF, in-flight cycles + what they're
triaging, analysis pipeline (ledger `triage` field), per-pod fleet
census, backlog, ledger runs, Claude token usage + est. spend, log
tails. Code:
`~/hexapod-orchestrator/orchestrator/status_server.py` (stdlib only, port 8090 —
5183/5173 are BuildViz, 8080 is the robot).

Two pieces, both must be up:

1. **Server, on the controller pod** (`hexapod-sweep-friction`), in
   tmux session `statusweb`:

   ```sh
   kubectl --kubeconfig=$HOME/.kube/coreweave.yaml exec hexapod-sweep-friction -- \
     bash -c "tmux kill-session -t statusweb 2>/dev/null; \
       tmux new-session -d -s statusweb 'source /root/orchestrator.env; \
       cd /workspace/hexapod/hexapod_walker/prototype_sts3215 && \
       uv run python /workspace/hexapod-orchestrator/orchestrator/status_server.py 2>&1 | tee /tmp/status_server.log'"
   ```

2. **Port-forward, on the operator's laptop** (dies on sleep/network
   blips — restart it freely, it's stateless):

   ```sh
   kubectl --kubeconfig=$HOME/.kube/coreweave.yaml \
     port-forward hexapod-sweep-friction 8090:8090
   ```

Then open **http://127.0.0.1:8090/now** (raw data at `/json`; `/`,
`/research`, `/dashboard`, and `/status` are aliases).

Health checks: `curl -s http://127.0.0.1:8090/now | head -c 100` on the
laptop; on the pod, `tmux has-session -t statusweb` and
`/tmp/status_server.log`. If the page loads but fleet/token sections
are empty, the slow collector hasn't finished its first pass — wait
~2 min. After editing `status_server.py`: commit + push, wait ~1 min
for the auto-sync to pull it (or `git pull` on the controller), then
re-run step 1 (kill+new tmux session). The
server is read-only and safe to restart at any time — it never
touches training, the watcher, or the ledger.

### Public URL + LLM-readable mirror (GPT/Claude reading status)

The page is public at **https://hexapod.cwd1f0-new-cluster.coreweave.app/now**
(operator 08-10 setup): the `hexapod-status` LoadBalancer service
routes 80/443 to the controller pod, where **Caddy** (tmux session
`caddyweb`, `/workspace/caddy run --config /workspace/Caddyfile`,
auto-TLS with certs cached in `/workspace/.caddy`) reverse-proxies to
the status server on 127.0.0.1:8090. Access requires the token in
`/workspace/.status_token` on the controller (the server reads it once
at startup — restart `statusweb` after changing it): first browser
visit uses `?key=<token>`, which sets a cookie and redirects clean.

**MCP server (LLMs investigating results as tools):** the status
server also mounts an MCP endpoint at **POST /mcp**
(`~/hexapod-orchestrator/orchestrator/mcp_server.py`, streamable-HTTP transport,
stdlib only). Add `https://hexapod.cwd1f0-new-cluster.coreweave.app/mcp`
as a remote MCP server in Claude/Cursor/ChatGPT — **requires the
operator's MCP key** (operator 08-15; the old keyless mode made
client-side safety layers classify the endpoint as public and block
feedback): send `Authorization: Bearer <key>`, `X-Api-Key: <key>`,
or `?key=<key>` on the URL (ChatGPT connectors can't set headers —
use the `?key=` form). Key lives in `/workspace/.mcp_key` on the
controller (`MCP_AUTH_KEY` env overrides; `logs/.mcp_key` for laptop
dev; server reads it once at startup — restart `statusweb` after
changing it; no key on disk = endpoint disabled). Content policy
unchanged: public-repo data only, no spend, no pod names. Tools:
`campaign_status`, `get_plan`, `log_tail`,
`list_runs` (ledger with status/track/substring filters), `get_run`
(entry + story), `run_metrics` (cached W&B summary/history),
`eval_report` (gate report.json), `get_run_videos` (existing eval
recordings as MCP resource links), `list_docs` / `read_doc`,
`search_docs`, plus a write path: `submit_feedback` /
`list_feedback` — keyed clients file notes into
`/workspace/llm_feedback/` on the controller (size-capped, per-IP
rate-limited), shown in the dashboard's "LLM feedback inbox" section.
The watcher injects unseen entries into the next decision cycle's
prompt as operator-sanctioned advisory notes (operator 08-14, keyed
08-15; stamped `injected_utc`, ≤8 entries / 12 kB per cycle, never
spawns a cycle by itself; guardrails/rulings still win on conflict —
ORCHESTRATOR_PROMPT.md § "MCP feedback"). `kick_orchestrator` files
an operator-tier kick (deep model, trusted focus note). It runs
inside `statusweb`, so deploy = the same kill+restart runbook above.
Dev standalone: `uv run python ~/hexapod-orchestrator/orchestrator/mcp_server.py` (port
8091).

**Viewing/downloading evaluation video:** use `get_run_videos(run)` first.
It is a read-only MCP tool returning up to six clips (limit 1–24), each
with a direct `/media/` playback/download URL valid for one hour. These
links authorize only the named video; they do not expose the MCP key,
set a dashboard cookie, or unlock reports/control endpoints. HEAD and
Range requests support normal browser playback and seeking. Call the
tool again for fresh links after expiry. This avoids shell/kubectl
downloads and their separate sandbox approvals. Original recordings may
play slower than simulation time; read the telemetry clock before making
endurance claims. Clients must reconnect to discover a newly deployed
tool. The server advertises `get_run_videos` with `readOnlyHint=true`.

The server also serves a plain-markdown mirror so external LLMs
(ChatGPT, Claude web fetch) can assess the campaign: `/llms.txt` is
the index (llmstxt.org convention), `/llm/brief.md` is the short
latest-research-first answer, `/llm/status.md` lists per-track STATUS
docs first (authoritative for track state) and the campaign digest last,
`/llm/plan.md`, `/llm/log.md`, `/llm/runs.md`
(ledger with hypotheses/verdicts, each linking its per-run story),
`/llm/docs.md` (index of EVERY .md in the prototype tree), and
`/llm/doc/<path>` (any individual doc, e.g.
`/llm/doc/rl_docs/HARDWARE.md`). Spend/token numbers and pod names
are deliberately NOT on those paths. The /llm paths need **no token**
(operator 08-13): they mirror the PUBLIC GitHub repo so the gate
protected nothing, and GPT's URL-safety wrapper refuses keyed URLs
outright. The dashboard and /json (spend, infra) remain token-gated.

**Docs auto-update on git push:** the server runs a sync thread on the
controller that pulls origin/main every 60 s (skipping rounds where a
decision cycle holds the snapshot lock), so pushed doc edits go live
within ~1 min with no manual pull. Sync failures show as a red warning
card on the dashboard. This covers DOCS only — a `status_server.py`
code change still needs the tmux kill+restart in step 1 above (the
pull itself is now automatic).

Human bookmark:
`https://hexapod.cwd1f0-new-cluster.coreweave.app/now`

Hand an LLM:
`https://hexapod.cwd1f0-new-cluster.coreweave.app/llms.txt`
(no key). Recover the dashboard token with:

```sh
kubectl --kubeconfig=$HOME/.kube/coreweave.yaml exec hexapod-sweep-friction -- \
  cat /workspace/.status_token
```

## Time budget guidance

The operator's standing complaint is cycle latency. Read the two
condensed docs + guardrails (fast), use `ops.sh`, launch evals in
PARALLEL (`nohup … &` all of them, then `waitlog` each), and don't
reproduce evidence into RL_LOG — link it. If a run is clearly
improving and flagged auto-continue, the watcher already relaunched
it; your job is the verdict, not the relaunch.
