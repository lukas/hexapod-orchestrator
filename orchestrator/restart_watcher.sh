#!/bin/bash
# THE ONLY sanctioned way to restart the watcher. Waits out in-flight
# decision cycles, then restarts the watcher tmux session on fresh code.
# Runs nohup'd on the controller pod; log: /workspace/restart_watcher.log
#
#   nohup bash /workspace/restart_watcher.sh > /workspace/restart_watcher.log 2>&1 &
#
# NEVER `tmux kill-session` / kill the watcher directly: cycles are claude
# subprocesses mid-analysis — a hard kill throws away their un-saved work
# (verdicts not yet written, launches half-placed) and the replacement
# cycle re-triages the same runs. Three cycles died exactly this way on
# 2026-08-09 (10:46/11:38/11:56 restarts). Since 08-21 cycles STREAM
# their narration into /workspace/cycle_logs/*.log as they work, so the
# transcript survives a kill — but the wasted tokens and re-triage do
# not, hence the wrap-up protocol below stands. Copy lives in the repo;
# the deployed copy is /workspace/restart_watcher.sh on the controller.
#
# Two checkouts on the controller (2026-09-16 split): this repo at
# /workspace/hexapod-orchestrator (watcher, prompts, flags) and the subject
# repo lukas/hexapod at /workspace/hexapod (sim code, on the `orchestrator`
# branch). Both are brought up to date before the restart.
set -u
# Detached watchers must not reuse a dead parent W&B service socket.
unset WANDB_SERVICE
export UV_PYTHON=/usr/local/bin/python
ORCH_REPO=/workspace/hexapod-orchestrator
ORCH=$ORCH_REPO/orchestrator
HEXAPOD=/workspace/hexapod
# Both repo roots carry a pyproject.toml/uv.lock for LAPTOP development.
# The controller runs on its system Python with `uv pip install --system`
# packages; never let `uv run` discover a project here (it would build a
# full venv on the controller). /root/orchestrator.env also exports this.
export UV_NO_PROJECT=1

log() { echo "[$(date -u +%FT%TZ)] $*"; }

# One lifetime owner across both automatic and manual restart entry points.
# Duplicates must exit before touching another owner's pause/wrapup flags.
exec 8>/workspace/restart_watcher.lock || exit 1
flock -n -E 75 8
case $? in
  0) ;;
  75) log "restart already owned; leaving existing restart untouched"; exit 0 ;;
  *) log "cannot acquire restart ownership lock"; exit 1 ;;
esac

# Pause the old watcher so it can't spawn a fresh cycle in the gap
# between the current cycle ending and the tmux kill. WRAPUP tells
# in-flight cycles to save their work and exit at the next run
# boundary (shutdown protocol in ORCHESTRATOR_PROMPT.md) — operator
# order 08-09 evening, after a restart sat 2h behind slow cycles and
# ended in a manual kill anyway.
touch "$ORCH/PAUSE" "$ORCH/WRAPUP"
log "PAUSE+WRAPUP set; waiting for in-flight cycles to save and exit"

# PAUSE stops cycle SPAWNS only — mechanical throughput must continue.
# The 19:00 incident (08-09): this wait ran 25+ min behind 4 long
# cycles while finished runs freed 5 slots and a queued spec sat in
# the backlog; the operator found a third of the fleet idle. Drain
# every loop iteration (cheap no-op when backlog is empty).
#
# Hard deadline: cycles are told to wrap up, so anything still alive
# after WRAPUP_DEADLINE_MIN is stuck or ignoring the flag — kill it.
# Verdicts/evals already on disk survive; unverdicted runs get
# re-fanned-out by the new watcher (ledger dedupe = no double work).
WRAPUP_DEADLINE_MIN=30
i=0
# Live-cycle check. The claude binary rewrites its argv once running (ps shows
# a bare title), so `ps aux | grep "claude -p --bare"` misses live cycles: on
# 2026-09-17 00:04 this loop declared "cycles ended" 1 s after a cycle's last
# tool call and the tmux kill took it down mid-wrap-up (no CYCLE END in its
# log). cycle_render.py is a plain python process spawned next to every cycle
# and exits when claude's pipe closes, so it is the reliable witness; the old
# pattern stays as a second net (one pgrep call per poll: the test double counts).
cycles_alive() {
  pgrep -f "cycle_render.py|claude -p --bare" >/dev/null 2>&1
}
while cycles_alive; do
  sleep 60
  i=$((i + 1))
  if [ "$i" -ge "$WRAPUP_DEADLINE_MIN" ]; then
    log "wrap-up deadline (${WRAPUP_DEADLINE_MIN}m) exceeded; killing stragglers"
    pkill -TERM -f "claude -p --bare" 2>/dev/null
    pkill -TERM -x claude 2>/dev/null   # argv is rewritten; match the process name
    sleep 10
    break
  fi
  if [ $((i % 2)) -eq 0 ]; then
    (set -a; source "$HEXAPOD/hexapod_walker/prototype_sts3215/rl_move/sim/wandb.env" 2>/dev/null;
     source /root/orchestrator.env 2>/dev/null; set +a
     cd "$ORCH_REPO" && uv run --no-project python orchestrator/launch_run.py drain \
       >> /tmp/pause_drain.log 2>&1) || true
  fi
done
log "cycles ended"

# Bring BOTH checkouts up to date under the snapshot lock: this repo with a
# plain merge-pull of its tracking branch (no auto-deploy from main here, so
# snapshot.sh commits straight to it), the hexapod checkout by merging
# origin/main into its orchestrator branch. Never autostash: a
# conflicting/dirty checkout must leave the old watcher running, with its
# pause flags cleared. The subshell releases the lock before the tmux
# restart so the new watcher cannot inherit it.
if ! (
  flock -w 120 9 &&
    cd "$ORCH_REPO" &&
    git pull -q --ff-only &&
    cd "$HEXAPOD" &&
    git fetch -q origin main &&
    ( git -c merge.autoStash=false merge --no-edit origin/main || { git merge --abort; false; } )
) 9>/workspace/git_snapshot.lock; then
  log "repository sync failed; leaving old watcher running"
  rm -f "$ORCH/PAUSE" "$ORCH/WRAPUP"
  exit 1
fi
uv run --no-project python -c "import ast; ast.parse(open('$ORCH/watch_loop.py').read())" || {
  log "watch_loop.py failed to parse; leaving old watcher running"
  rm -f "$ORCH/PAUSE" "$ORCH/WRAPUP"
  exit 1
}

tmux kill-session -t orchestrator 8>&- 2>/dev/null
sleep 2
rm -f "$ORCH/PAUSE" "$ORCH/WRAPUP"
# Keep the lifetime lock in this supervisor, never in the tmux server/watcher.
tmux new-session -d -s orchestrator \
  "source /root/orchestrator.env && cd $ORCH_REPO && \
   env -u WANDB_SERVICE UV_PYTHON=/usr/local/bin/python uv run --no-project python orchestrator/watch_loop.py" 8>&-
sleep 5
if tmux has-session -t orchestrator 8>&- 2>/dev/null; then
  log "RESTARTED ok (tmux session up)"
else
  log "RESTART FAILED: tmux session not present"
  exit 1
fi
