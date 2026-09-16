# Shell mirror of roots.py -- source it: `. "$(dirname "$0")/roots.sh"`.
# Sets ORCH_ROOT (this checkout), HEXAPOD_REPO (the hexapod checkout:
# $HEXAPOD_REPO, else the sibling ../hexapod, else /workspace/hexapod),
# PROTO (HEXAPOD_REPO/hexapod_walker/prototype_sts3215) and STATE_DIR
# ($HEXAPOD_STATE_DIR, else ORCH_ROOT/.state). Exports HEXAPOD_REPO so the
# Python it spawns resolves the same checkout.
_roots_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCH_ROOT="$(cd "$_roots_here/.." && pwd)"
if [ -z "${HEXAPOD_REPO:-}" ]; then
  if [ -d "$ORCH_ROOT/../hexapod/hexapod_walker/prototype_sts3215" ]; then
    HEXAPOD_REPO="$(cd "$ORCH_ROOT/../hexapod" && pwd)"
  else
    HEXAPOD_REPO=/workspace/hexapod
  fi
fi
export HEXAPOD_REPO
PROTO="$HEXAPOD_REPO/hexapod_walker/prototype_sts3215"
STATE_DIR="${HEXAPOD_STATE_DIR:-$ORCH_ROOT/.state}"
unset _roots_here
