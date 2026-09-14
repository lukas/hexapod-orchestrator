#!/usr/bin/env bash
# state_sync.sh push | pull | restore [--force]
#
# The ONE transport for the orchestrator's runtime state (ledger directory,
# backlog, pending evals, run stories, RL_LOG.md). The state dir --
# <checkout>/.state or $HEXAPOD_STATE_DIR, see state_dir.py -- is a plain
# directory, NOT a git repo: the lukas/hexapod-state repo it replaced
# (2026-09-08..14) grew 2.5 GB of history in a week from committing a 34 MB
# ledger after every run. Git is not a log. Durability is a mirror on the
# `hexapod-state` PVC (RWX), mounted at /state by Deployment hexapod-state:
#
#   push     controller -> PVC.  snapshot.sh runs this after every run. Full
#            copy, streamed as one tar into a fresh sibling dir on the PVC and
#            swapped into /state/hexapod, so files deleted at the source are
#            gone from the mirror too. Once per UTC day it also writes
#            /state/backups/hexapod-state-YYYYMMDD.tgz and prunes to the
#            newest 30. Prints one line: bytes and seconds.
#   pull     controller (LIVE state) -> $STATE_DIR on a laptop or worktree;
#            when the controller is unreachable it pulls the PVC mirror instead
#            and says so.  `make -C hexapod_walker/prototype_sts3215 state`.
#   restore  PVC mirror -> an EMPTY $STATE_DIR on a fresh controller
#            (setup_controller.sh). Refuses a non-empty target without --force
#            and refuses a mirror that holds no ledger (nothing to restore).
#
# Every transfer lands in <target>.incoming.<pid> next to the target and is
# swapped into place only after it completed, so a failed transfer never
# leaves a half-written state dir. Loud and non-zero on any failure.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
STATE="${HEXAPOD_STATE_DIR:-$REPO/.state}"
KC="${KUBECONFIG:-$HOME/.kube/coreweave.yaml}"
CONTROLLER_POD="${HEXAPOD_CONTROLLER_POD:-hexapod-sweep-friction}"
CONTROLLER_STATE="${HEXAPOD_CONTROLLER_STATE_DIR:-/workspace/hexapod/.state}"
MIRROR_TARGET="${HEXAPOD_STATE_MIRROR:-deploy/hexapod-state}"   # kubectl exec target
MIRROR_DIR=/state/hexapod
BACKUP_DIR=/state/backups
KEEP_BACKUPS=30
# Never transported: a leftover .git from the retired state repo, writers'
# flock files, and atomic-write temp files that a live writer may be mid-way
# through (temp + os.replace means the .json next to them is always whole).
EXCLUDES=(--exclude=.git --exclude='*.lock' --exclude='*.tmp*')

die() { echo "state_sync.sh: ERROR: $*" >&2; exit 1; }
kc() { kubectl --kubeconfig="$KC" "$@"; }

# A symlinked state dir (worktrees sharing one copy) is resolved so the swap
# below replaces the real directory, not the link.
if [ -L "$STATE" ]; then
  STATE="$(cd "$STATE" 2>/dev/null && pwd -P)" || die "state dir link $STATE is dangling"
fi

# Stream a state dir out of the cluster. GNU tar exits 1 when a file changed
# while it was being read (the watcher writes between our listing and our
# read); that copy is still whole per file, so 1 is tolerated -- 2 is not.
remote_tar() {  # remote_tar <kubectl target> <dir>
  kc exec "$1" -- sh -c "tar -C '$2' -cf - --exclude=.git --exclude='*.lock' --exclude='*.tmp*' .; rc=\$?; if [ \$rc -eq 1 ]; then echo 'NOTE: files changed under tar (live writer); copied what it read' >&2; exit 0; fi; exit \$rc"
}

local_tar() {  # the same tolerance for the controller's own live state
  local rc=0
  tar -C "$STATE" -cf - "${EXCLUDES[@]}" . || rc=$?
  if [ "$rc" -eq 1 ]; then
    echo "NOTE: files changed under tar (live writer); pushed what it read" >&2
    return 0
  fi
  return "$rc"
}

swap_local() {  # swap_local <incoming> <target>: atomic-enough replace, one dir at a time
  local incoming="$1" target="$2"
  rm -rf "$target.prev"
  if [ -e "$target" ]; then
    if [ -d "$target/.git" ]; then
      echo "NOTE: $target was a git clone of the retired state repo; replacing it (the repo is history, not state)" >&2
    fi
    mv "$target" "$target.prev"
  fi
  mv "$incoming" "$target"
  rm -rf "$target.prev"
}

count_ledger() { ls -1 "$1/ledger" 2>/dev/null | grep -c '\.json$' || true; }

require_ledger() {  # require_ledger <dir> <what>: a state copy without a ledger is not state
  if [ ! -d "$1/ledger" ] && [ ! -f "$1/experiments.json" ]; then
    die "$2 holds no ledger (neither ledger/ nor a legacy experiments.json) -- refusing to install an empty state dir"
  fi
}

push() {
  [ -d "$STATE" ] || die "state dir missing: $STATE"
  require_ledger "$STATE" "$STATE"
  local t0 bytes incoming="$MIRROR_DIR.incoming.$$"
  t0="$(date +%s)"
  bytes="$(local_tar | wc -c | tr -d ' ')"
  local_tar | kc exec -i "$MIRROR_TARGET" -- sh -ec "
    rm -rf '$incoming' && mkdir -p '$incoming' && tar -C '$incoming' -xf - &&
    rm -rf '$MIRROR_DIR.prev' &&
    { [ ! -e '$MIRROR_DIR' ] || mv '$MIRROR_DIR' '$MIRROR_DIR.prev'; } &&
    mv '$incoming' '$MIRROR_DIR' && rm -rf '$MIRROR_DIR.prev'" \
    || die "push to $MIRROR_TARGET:$MIRROR_DIR failed (state is only on this controller until the next push)"
  # One .tgz per UTC day, newest $KEEP_BACKUPS kept.
  kc exec "$MIRROR_TARGET" -- sh -ec "
    mkdir -p '$BACKUP_DIR'
    f='$BACKUP_DIR/hexapod-state-'\"\$(date -u +%Y%m%d)\"'.tgz'
    if [ ! -f \"\$f\" ]; then
      tar -C '$(dirname "$MIRROR_DIR")' -czf \"\$f.tmp\" '$(basename "$MIRROR_DIR")' && mv \"\$f.tmp\" \"\$f\"
      echo \"state backup: \$f\"
    fi
    for old in \$(ls -1 '$BACKUP_DIR'/hexapod-state-*.tgz 2>/dev/null | sort -r | tail -n +$((KEEP_BACKUPS + 1))); do
      rm -f \"\$old\"
    done" || die "daily backup on $MIRROR_TARGET failed (mirror itself was updated)"
  echo "state push: $bytes bytes -> $MIRROR_TARGET:$MIRROR_DIR in $(( $(date +%s) - t0 )) s"
}

fetch_into() {  # fetch_into <incoming> ; sets $SRC to a description of the source used
  local incoming="$1"
  if kc exec "$CONTROLLER_POD" -- test -d "$CONTROLLER_STATE" >/dev/null 2>&1; then
    SRC="controller $CONTROLLER_POD:$CONTROLLER_STATE (live)"
    remote_tar "$CONTROLLER_POD" "$CONTROLLER_STATE" | tar -C "$incoming" -xf - \
      || die "copy from $SRC failed"
  else
    echo "NOTE: controller $CONTROLLER_POD unreachable; pulling the PVC mirror instead (same bytes modulo minutes)" >&2
    SRC="PVC mirror $MIRROR_TARGET:$MIRROR_DIR"
    remote_tar "$MIRROR_TARGET" "$MIRROR_DIR" | tar -C "$incoming" -xf - \
      || die "copy from $SRC failed (controller unreachable too)"
  fi
}

pull() {
  local incoming="$STATE.incoming.$$"
  mkdir -p "$(dirname "$STATE")"
  rm -rf "$incoming" && mkdir -p "$incoming"
  trap 'rm -rf "$incoming"' EXIT
  fetch_into "$incoming"
  require_ledger "$incoming" "$SRC"
  swap_local "$incoming" "$STATE"
  trap - EXIT
  echo "state pull: $SRC -> $STATE ($(count_ledger "$STATE") ledger entries)"
}

restore() {
  local force="${1:-}" incoming="$STATE.incoming.$$"
  if [ -e "$STATE" ] && [ -n "$(ls -A "$STATE" 2>/dev/null)" ] && [ "$force" != "--force" ]; then
    die "restore: $STATE exists and is not empty -- restore is for a FRESH controller; use pull on a laptop, or --force to replace"
  fi
  mkdir -p "$(dirname "$STATE")"
  rm -rf "$incoming" && mkdir -p "$incoming"
  trap 'rm -rf "$incoming"' EXIT
  remote_tar "$MIRROR_TARGET" "$MIRROR_DIR" | tar -C "$incoming" -xf - \
    || die "copy from $MIRROR_TARGET:$MIRROR_DIR failed"
  require_ledger "$incoming" "PVC mirror $MIRROR_TARGET:$MIRROR_DIR"
  swap_local "$incoming" "$STATE"
  trap - EXIT
  echo "state restore: $MIRROR_TARGET:$MIRROR_DIR -> $STATE ($(count_ledger "$STATE") ledger entries)"
}

case "${1:-}" in
  push)    push ;;
  pull)    pull ;;
  restore) restore "${2:-}" ;;
  *) echo "usage: state_sync.sh push | pull | restore [--force]   (see header comment)" >&2; exit 2 ;;
esac
