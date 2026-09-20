#!/usr/bin/env bash
# compact_journals.sh [--dry-run] -- run doc_compact.py against the LIVE state
# dir on the controller without racing a decision cycle.
#
# Cycles read-modify-write CURRENT_TRUTHS.md / OPERATOR_QUESTIONS.md / the
# track STATUS.md files as whole files, so compacting while one is in flight
# could drop its entry. This does what restart_watcher.sh does around a
# restart: set PAUSE+WRAPUP (no new spawns, in-flight cycles told to finish),
# wait for the cycles to end (cycle_render.py is the reliable witness), run
# the compaction, clear the flags, push the state to the PVC mirror.
#
# Run ON the controller:   bash orchestrator/compact_journals.sh
# From the Mac:            ops.sh compact            (re-execs here via kubectl)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The controller keeps HEXAPOD_STATE_DIR (=/workspace/hexapod/.state) in
# /root/orchestrator.env, not in the shell kubectl exec gives us; without it
# roots.sh would resolve STATE_DIR to <checkout>/.state (empty) and doc_compact
# would refuse -- after having paused and waited. Same as restart_watcher.sh.
set -a; source /root/orchestrator.env 2>/dev/null || true; set +a
. "$HERE/roots.sh"                                   # ORCH_ROOT, STATE_DIR
DRY=""; [ "${1:-}" = "--dry-run" ] && DRY=1
log() { echo "[$(date -u +%FT%TZ)] compact_journals: $*"; }

if [ -n "$DRY" ]; then
  python3 "$HERE/doc_compact.py" --state "$STATE_DIR"
  exit 0
fi

already_paused=""
[ -e "$HERE/PAUSE" ] && already_paused=1
if [ -z "$already_paused" ]; then
  printf '%s\n' "PAUSED $(date -u +%FT%TZ) by compact_journals.sh for journal compaction; removed automatically when it finishes." > "$HERE/PAUSE"
fi
touch "$HERE/WRAPUP"
trap 'rm -f "$HERE/WRAPUP"; [ -z "$already_paused" ] && rm -f "$HERE/PAUSE"; log "flags cleared"' EXIT
log "PAUSE+WRAPUP set; waiting for in-flight cycles"

cycles_alive() { pgrep -f "cycle_render.py|claude -p --bare" >/dev/null 2>&1; }
i=0
while cycles_alive; do
  sleep 30; i=$((i + 1))
  if [ "$i" -ge 60 ]; then                            # 30 min, same deadline as restart_watcher.sh
    log "cycles still alive after 30 min; NOT compacting (rerun later or kill the stragglers first)"
    exit 1
  fi
done
log "no cycles in flight; compacting $STATE_DIR"
python3 "$HERE/doc_compact.py" --state "$STATE_DIR" --execute
bash "$HERE/state_sync.sh" push || log "WARNING: state push failed; the compaction is on this controller only until the next snapshot"
PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}" python3 "$HERE/rl_index.py" build --no-real >/dev/null 2>&1 || true
log "done"
