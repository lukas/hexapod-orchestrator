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
set -u
ORCH=/workspace/hexapod/hexapod_walker/prototype_sts3215/rl_move/orchestrator
# The repo root carries a pyproject.toml/uv.lock for LAPTOP development.
# The controller runs on its system Python with `uv pip install --system`
# packages; never let `uv run` discover that project here (it would build a
# full sim venv on the controller). /root/orchestrator.env also exports this.
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
while ps aux | grep "claude -p --bare" | grep -v grep >/dev/null; do
  sleep 60
  i=$((i + 1))
  if [ "$i" -ge "$WRAPUP_DEADLINE_MIN" ]; then
    log "wrap-up deadline (${WRAPUP_DEADLINE_MIN}m) exceeded; killing stragglers"
    pkill -TERM -f "claude -p --bare" 2>/dev/null
    sleep 10
    break
  fi
  if [ $((i % 2)) -eq 0 ]; then
    (set -a; source "$ORCH/../sim/wandb.env" 2>/dev/null;
     source /root/orchestrator.env 2>/dev/null; set +a
     cd "$ORCH/../.." && uv run --no-project python rl_move/orchestrator/launch_run.py drain \
       >> /tmp/pause_drain.log 2>&1) || true
  fi
done
log "cycles ended"

# Share the snapshot lock with concurrent Git writers. Never autostash
# live runtime ledgers: a conflicting/dirty checkout must leave the old
# watcher running, with its pause flags cleared. The subshell releases
# the lock before tmux restart so the new watcher cannot inherit it.
if ! (
  flock -w 120 9 &&
    cd /workspace/hexapod &&
    git -c rebase.autoStash=false -c merge.autoStash=false \
      pull --no-rebase --ff-only origin main
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
  "source /root/orchestrator.env && cd /workspace/hexapod && \
   uv run --no-project python hexapod_walker/prototype_sts3215/rl_move/orchestrator/watch_loop.py" 8>&-
sleep 5
if tmux has-session -t orchestrator 8>&- 2>/dev/null; then
  log "RESTARTED ok (tmux session up)"
else
  log "RESTART FAILED: tmux session not present"
  exit 1
fi
