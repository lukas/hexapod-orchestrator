#!/bin/sh
# Serve saved Metaagent reviews; never launch the reviewer or touch Robot Lab.
set -eu
umask 077
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"
METAAGENT_HOME="${METAAGENT_HOME:-$HOME/Library/Application Support/Hexapod Metaagent}"
export METAAGENT_API_TOKEN="$(cat "$METAAGENT_HOME/api-token")"
export HEXAPOD_METAAGENT_DIR="${HEXAPOD_METAAGENT_DIR:-$HOME/Library/Application Support/Hexapod Lab/overseer}"
export METAAGENT_SSO_SECRET_FILE="${METAAGENT_SSO_SECRET_FILE:-$HOME/.hexapod/sso_secret}"
export METAAGENT_SSO_USERS="${METAAGENT_SSO_USERS:-operator:lukas}"
export METAAGENT_PUBLIC_ORIGIN="https://metaagent.cwd1f0-new-cluster.coreweave.app"
cd "$METAAGENT_HOME/runtime"
exec uv run --frozen python -m rl_move.metaagent serve --host 127.0.0.1 --port 8768
