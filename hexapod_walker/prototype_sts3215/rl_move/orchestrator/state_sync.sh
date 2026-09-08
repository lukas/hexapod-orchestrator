#!/usr/bin/env bash
# Clone or fast-forward the orchestrator's runtime state (lukas/hexapod-state)
# into <checkout>/.state (or $HEXAPOD_STATE_DIR). Read-only convenience for
# laptops and worktrees: the ONLY writer is the controller's snapshot.sh.
#   make -C hexapod_walker/prototype_sts3215 state      # same thing
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
STATE="${HEXAPOD_STATE_DIR:-$REPO/.state}"
URL="https://github.com/lukas/hexapod-state.git"
if [ -d "$STATE/.git" ]; then
  git -C "$STATE" pull -q --ff-only origin main
  echo "state: fast-forwarded $STATE -> $(git -C "$STATE" log -1 --format='%h %s')"
elif [ -L "$STATE" ] && [ -d "$STATE/.git" ]; then
  echo "state: $STATE is a link to a synced clone"
else
  git clone -q --depth 50 "$URL" "$STATE"
  echo "state: cloned into $STATE ($(git -C "$STATE" log -1 --format='%h %s'))"
fi
echo "ledger entries: $(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$STATE/experiments.json" 2>/dev/null || echo '? (no experiments.json yet)')"
