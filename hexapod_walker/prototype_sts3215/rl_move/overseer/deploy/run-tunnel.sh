#!/bin/sh
# Only the dedicated metaagent tunnel. Never manages the camera/Lab tunnel.
set -eu
umask 077
METAAGENT_KEYS="${METAAGENT_KEYS:-$HOME/.hexapod/metaagent-tunnel}"
METAAGENT_SSH_HOST="${METAAGENT_SSH_HOST:-metaagent.cwd1f0-new-cluster.coreweave.app}"
test -s "$METAAGENT_KEYS/id_ed25519"
test -s "$METAAGENT_KEYS/known_hosts"
exec /usr/bin/ssh -F /dev/null -nNT \
    -i "$METAAGENT_KEYS/id_ed25519" -p 2222 \
    -o BatchMode=yes -o IdentitiesOnly=yes -o ControlMaster=no \
    -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$METAAGENT_KEYS/known_hosts" \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -R 127.0.0.1:8768:127.0.0.1:8768 "tunnel@$METAAGENT_SSH_HOST"
