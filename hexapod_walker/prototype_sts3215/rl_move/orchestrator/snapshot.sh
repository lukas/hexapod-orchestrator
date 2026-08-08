#!/usr/bin/env bash
# snapshot.sh <run-name>       commit everything, tag exp/<run-name>, push, print hash
# snapshot.sh --sync <pod>     sync the prototype tree to a pod's /workspace
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ "${1:-}" = "--sync" ]; then
  POD="$2"
  KC="${KUBECONFIG:-$HOME/.kube/coreweave.yaml}"
  tar -C hexapod_walker -czf /tmp/proto_sync.tgz \
      --exclude='prototype_sts3215/logs' \
      --exclude='prototype_sts3215/rl_move/sim/policies' \
      --exclude='*.stl' --exclude='*.mp4' \
      prototype_sts3215
  kubectl --kubeconfig="$KC" cp /tmp/proto_sync.tgz "$POD":/tmp/proto_sync.tgz
  kubectl --kubeconfig="$KC" exec "$POD" -- \
      tar -C /workspace -xzf /tmp/proto_sync.tgz
  echo "synced -> $POD"
  exit 0
fi

RUN_NAME="${1:?usage: snapshot.sh <run-name> | snapshot.sh --sync <pod>}"
TAG="exp/${RUN_NAME}"

git add -A hexapod_walker/prototype_sts3215
if ! git diff --cached --quiet; then
  git commit -m "orchestrator snapshot before ${RUN_NAME}"
fi
# Integrate anything the operator pushed from elsewhere before we push.
git pull --rebase --autostash origin main
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  echo "tag ${TAG} already exists" >&2; exit 1
fi
git tag "${TAG}"
git push origin HEAD --tags
git rev-parse HEAD
