# hexapod-orchestrator

The autonomous RL research loop for [lukas/hexapod](https://github.com/lukas/hexapod):
a watcher that launches trainings on CoreWeave GPU pods, pre-stages evals,
spawns LLM decision cycles (`claude -p --bare`) to triage finished runs and
refill the queue, plus the status board, the MCP server and the metaagent
reviewer. It was split out of the hexapod monorepo on 2026-09-16
(formerly `hexapod_walker/prototype_sts3215/rl_move/orchestrator/`). If this
file and the code disagree, the code is right; fix this file.

## Layout

    orchestrator/      the loop: watch_loop.py, launch_run.py, ops.sh, snapshot.sh,
                       status_server.py, mcp_server.py, pod_eval.py, seed_pruner.py,
                       capacity.py, roots.py (path roots), state_dir.py (state + ledger),
                       ORCHESTRATOR_PROMPT.md / META_PROMPT.md (cycle prompts),
                       guardrails.yaml, tracks.json, pod_torch_capability.json,
                       PAUSE / WRAPUP / KICK flag files (runtime, untracked)
    metaagent/         the reviewer service (see below)
    tests/             pytest suite for both
    RL_GOALS.md RL_PLAN.md STATUS.md RESEARCH_RULES.md RUN_INTERPRETATION_RULES.md
    RECOVERY_LESSONS.md EMERGENCY_HANDLING.md
                       the research-process docs the cycles read and edit
                       (served by the status server under their old names)

Architecture and operating notes: `orchestrator/README.md`. What a cycle
does: `orchestrator/ORCHESTRATOR_PROMPT.md`.

## The two roots

Everything that touches a path resolves it through `orchestrator/roots.py`
(shell twin: `orchestrator/roots.sh`):

| root | what | resolution |
| --- | --- | --- |
| `ORCH_ROOT` | this checkout: code, prompts, flags, the research docs | from `__file__` |
| `HEXAPOD_REPO` | the hexapod checkout the loop edits, launches and snapshots | `$HEXAPOD_REPO`, else sibling `../hexapod`, else `/workspace/hexapod` |
| `PROTO` | `HEXAPOD_REPO/hexapod_walker/prototype_sts3215`, the importable sim tree | derived |
| `STATE_DIR` | runtime state: `ledger/`, `backlog.json`, `RL_LOG.md`, `CURRENT_TRUTHS.md`, `OPERATOR_QUESTIONS.md`, `rl_docs/meta|tracks` (`rl_docs/runs` retired 09-25: `ops.sh index story` renders runs) | `$HEXAPOD_STATE_DIR`, else `ORCH_ROOT/.state` (never a git repo; mirrored to the `hexapod-state` PVC by `state_sync.sh`) |

Env vars: `HEXAPOD_REPO`, `HEXAPOD_STATE_DIR` (above), `HEXAPOD_ORCH_BRANCH`
(branch of the hexapod checkout that `snapshot.sh` commits to; default
`orchestrator`). On a laptop with `~/hexapod` and this repo elsewhere:
`export HEXAPOD_REPO=$HOME/hexapod`.

The decision cycle runs with `cwd=HEXAPOD_REPO` and `--add-dir ORCH_ROOT`.
The prompt markdown uses the placeholders `{ORCH_ROOT}`, `{HEXAPOD_REPO}`,
`{PROTO}` wherever a path is meant; `watch_loop.fill_roots` substitutes them
(plain `str.replace`) at spawn time.

## Protocol with hexapod

- Trainer entrypoints, run as modules from `PROTO` (on pods:
  `/workspace/prototype_sts3215`): `python -m rl_move.sim.train_ppo_mjx`
  (GPU, default), `python -m rl_move.sim.train_ppo_sim` (CPU, legacy),
  `python -m rl_move.dynamics.train`. Flags the launcher relies on:
  `--run-name <run>`, `--cfg-set k=v` (config.yaml overrides), plus the
  pass-through `extra_args` the ledger entry records.
- Ledger: `STATE_DIR/ledger/<seq>-<run>.json`, one JSON object per entry
  (status, hypothesis, gate, verdict, `extra_args`, pod, W&B id, code SHAs).
  The raw `status` has ~200 spellings; `orchestrator/rl_index.py` collapses
  them to one `outcome` vocabulary and joins runs to lineage, exported robot
  policy files and the Robot Lab's real-world drive results
  (`ops.sh index story|lineage|promising|real|build`, MCP `run_story` /
  `promising_runs` / `real_walks`, web `/llm/index.md`). `launch_run.py
  update` stamps `outcome` and a bool `hardware_ready` on every verdict.
  Read/write only through `state_dir.load_ledger/save_ledger`
  (`launch_run.py update` for edits).
- Checkpoints: `PROTO/rl_move/sim/policies/ppo_goal_<run_with_underscores>.zip`;
  W&B artifact names are bounded by `orchestrator/artifact_names.py`. hexapod
  keeps its own copy at `rl_move/sim/artifact_names.py`; keep them identical.
- Code provenance: `snapshot.sh <run>` commits the hexapod checkout's code
  on `$HEXAPOD_ORCH_BRANCH` (merging `origin/main` into it, never rebasing),
  tags `exp/<run>`, pushes, then commits and pushes this repo on its current
  branch. `snapshot.sh --sync <pod>` tars `hexapod_walker/prototype_sts3215`
  into the pod's `/workspace` and stamps `/workspace/prototype_sts3215/.code_sha`;
  `launch_run.py` refuses a pod whose stamp is not the local hexapod HEAD.
- W&B project `l2k2/hexapod-balance`; the secret `rl_move/sim/wandb.env` is
  gitignored in hexapod and copied to pods by the launcher.

## Requirements

Python >= 3.12, `uv`. System tools: `kubectl` with `~/.kube/coreweave.yaml`
(pods are reached by `kubectl exec`), `tmux`, `flock`, the `claude` CLI
(decision cycles), `git`, `wandb` credentials in the env.

    uv sync --group dev
    HEXAPOD_REPO=$HOME/hexapod uv run pytest -q -n 4 tests

## Running it

    # watcher (the loop) -- normally only on the controller, in tmux
    uv run python orchestrator/watch_loop.py
    # status board (:8090, /now, /llms.txt, /mcp) and the standalone MCP server (:8091)
    uv run python orchestrator/status_server.py
    uv run python orchestrator/mcp_server.py
    # one-stop helpers for humans and cycles (board, review <run>, verdict, pullckpt, ...)
    bash orchestrator/ops.sh board
    # capacity truth, launches, queue
    uv run python orchestrator/capacity.py
    uv run python orchestrator/launch_run.py --help

### Controller layout

    /workspace/hexapod-orchestrator   this repo (watcher, prompts, flags)
    /workspace/hexapod                hexapod, blob:none partial clone, branch `orchestrator`
    /workspace/hexapod/.state         STATE_DIR
    /root/orchestrator.env            HEXAPOD_REPO, HEXAPOD_STATE_DIR, UV_NO_PROJECT=1, KUBECONFIG, keys

System Python `/usr/local/bin/python` with `uv pip install --system`
packages; every `uv run` there is `uv run --no-project` (`UV_NO_PROJECT=1`).
The watcher runs in tmux session `orchestrator`:

    cd /workspace/hexapod-orchestrator && env -u WANDB_SERVICE UV_PYTHON=/usr/local/bin/python \
      uv run --no-project python orchestrator/watch_loop.py

`orchestrator/setup_controller.sh` provisions a fresh controller (clones
both repos, writes `/root/orchestrator.env`, restores state from the PVC).
Logs: `/workspace/orchestrator.log`, `/workspace/cycle_logs/`.

### PAUSE, WRAPUP, restart

- `touch orchestrator/PAUSE` stops cycle spawns (training and the backlog
  drain keep going); remove it to resume.
- `orchestrator/WRAPUP` tells in-flight cycles to save and exit at the next
  run boundary.
- Restart the watcher ONLY with `orchestrator/restart_watcher.sh` (nohup'd
  on the controller; deployed copy `/workspace/restart_watcher.sh`). It sets
  both flags, waits for `claude -p --bare` processes to finish, pulls both
  checkouts under `/workspace/git_snapshot.lock`, parses `watch_loop.py`,
  and relaunches the tmux session. Never `tmux kill-session` by hand.

## Metaagent

see metaagent/README.md
