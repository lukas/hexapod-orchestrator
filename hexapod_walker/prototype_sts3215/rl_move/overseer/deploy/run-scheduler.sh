#!/bin/sh
# One free gate; any eligible paid call uses the existing Metaagent ledger.
set -eu
umask 077
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"
METAAGENT_HOME="${METAAGENT_HOME:-$HOME/Library/Application Support/Hexapod Metaagent}"
export HEXAPOD_METAAGENT_DIR="${HEXAPOD_METAAGENT_DIR:-$HOME/Library/Application Support/Hexapod Lab/overseer}"
# Private JSON credentials are read inside Python, never placed in arguments,
# shell traces, logs or launchd plists. Missing keys produce a visible free hold.
export METAAGENT_CREDENTIAL_FILE="$METAAGENT_HOME/reviewer-credentials.json"
cd "$METAAGENT_HOME/runtime"
exec uv run --frozen python -m rl_move.overseer.scheduled_entry
