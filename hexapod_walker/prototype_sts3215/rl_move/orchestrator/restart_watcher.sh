#!/bin/bash
# THE ONLY sanctioned way to restart the watcher. Waits out in-flight
# decision cycles, then restarts the watcher tmux session on fresh code.
# Runs nohup'd on the controller pod; log: /workspace/restart_watcher.log
#
#   nohup bash /workspace/restart_watcher.sh > /workspace/restart_watcher.log 2>&1 &
#
# NEVER `tmux kill-session` / kill the watcher directly: cycles are claude
# subprocesses that only WRITE THEIR OUTPUT AT EXIT, so a hard restart
# throws away the whole cycle's tokens and analysis, and the replacement
# cycle re-triages the same runs. Three cycles died exactly this way on
# 2026-08-09 (10:46/11:38/11:56 restarts). Copy lives in the repo; the
# deployed copy is /workspace/restart_watcher.sh on the controller.
set -u
ORCH=/workspace/weird_objects/hexapod_walker/prototype_sts3215/rl_move/orchestrator

log() { echo "[$(date -u +%FT%TZ)] $*"; }

# Pause the old watcher so it can't spawn a fresh cycle in the gap
# between the current cycle ending and the tmux kill.
touch "$ORCH/PAUSE"
log "PAUSE set; waiting for in-flight cycle to end"

# PAUSE stops cycle SPAWNS only — mechanical throughput must continue.
# The 19:00 incident (08-09): this wait ran 25+ min behind 4 long
# cycles while finished runs freed 5 slots and a queued spec sat in
# the backlog; the operator found a third of the fleet idle. Drain
# every loop iteration (cheap no-op when backlog is empty).
i=0
while ps aux | grep "claude -p --bare" | grep -v grep >/dev/null; do
  sleep 60
  i=$((i + 1))
  if [ $((i % 2)) -eq 0 ]; then
    (set -a; source "$ORCH/../sim/wandb.env" 2>/dev/null;
     source /root/orchestrator.env 2>/dev/null; set +a
     cd "$ORCH/../.." && python3 rl_move/orchestrator/launch_run.py drain \
       >> /tmp/pause_drain.log 2>&1) || true
  fi
done
log "cycle ended"

cd /workspace/weird_objects
git pull --rebase --autostash origin main
python3 -c "import ast; ast.parse(open('$ORCH/watch_loop.py').read())" || {
  log "watch_loop.py failed to parse; leaving old watcher running"
  rm -f "$ORCH/PAUSE"
  exit 1
}

tmux kill-session -t orchestrator 2>/dev/null
sleep 2
rm -f "$ORCH/PAUSE"
tmux new-session -d -s orchestrator \
  "source /root/orchestrator.env && cd /workspace/weird_objects && \
   python3 hexapod_walker/prototype_sts3215/rl_move/orchestrator/watch_loop.py"
sleep 5
if tmux has-session -t orchestrator 2>/dev/null; then
  log "RESTARTED ok (tmux session up)"
else
  log "RESTART FAILED: tmux session not present"
  exit 1
fi
