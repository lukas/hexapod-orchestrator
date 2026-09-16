#!/usr/bin/env bash
# One-time setup of the orchestrator on the controller pod.
# Run FROM THE LAPTOP. Prompts for the two secrets; nothing is stored here.
set -euo pipefail

POD="${POD:-hexapod-sweep-friction}"
KC="${KUBECONFIG:-$HOME/.kube/coreweave.yaml}"
REPO_URL_BASE="github.com/lukas/hexapod.git"                    # subject repo
ORCH_URL_BASE="github.com/lukas/hexapod-orchestrator.git"       # this repo

read -r -s -p "GitHub fine-grained token (repo contents read/write): " GH_TOKEN; echo
read -r -s -p "Cursor API key: " CURSOR_KEY; echo
read -r -s -p "W&B API key (blank = reuse pod's existing): " WANDB_KEY; echo

echo "== copying kubeconfig to $POD"
kubectl --kubeconfig="$KC" cp "$KC" "$POD":/root/.kube/coreweave.yaml 2>/dev/null || {
  kubectl --kubeconfig="$KC" exec "$POD" -- mkdir -p /root/.kube
  kubectl --kubeconfig="$KC" cp "$KC" "$POD":/root/.kube/coreweave.yaml
}

echo "== installing cursor-agent, kubectl, cloning both repos, starting loop"
kubectl --kubeconfig="$KC" exec -i "$POD" -- bash -s -- <<EOF
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
command -v tmux >/dev/null || (apt-get update -qq && apt-get install -y -qq tmux git curl)
command -v kubectl >/dev/null || {
  curl -sLo /usr/local/bin/kubectl "https://dl.k8s.io/release/\$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
  chmod +x /usr/local/bin/kubectl
}
command -v cursor-agent >/dev/null || curl -fsSL https://cursor.com/install | bash
export PATH="\$HOME/.local/bin:\$PATH"

# secrets -> root-only env file sourced by the loop
umask 077
cat > /root/orchestrator.env <<ENV
export CURSOR_API_KEY='$CURSOR_KEY'
export KUBECONFIG=/root/.kube/coreweave.yaml
# Both repo-root pyproject.toml/uv.lock files are for laptop development only.
# The controller runs its system Python + \`uv pip install --system\` packages;
# this keeps every \`uv run\` in the clones (watcher, cycles, evals) from
# discovering a project and building a full sim venv here.
export UV_NO_PROJECT=1
# The two roots (orchestrator/roots.py): this pod runs the orchestrator from
# /workspace/hexapod-orchestrator and operates on the hexapod checkout below.
export HEXAPOD_REPO=/workspace/hexapod
# Runtime state (ledger directory, queue, run stories, RL_LOG.md) -- a plain
# directory THIS pod writes and mirrors to the hexapod-state PVC after every
# run (state_dir.py, state_sync.sh push). Not a git repo.
export HEXAPOD_STATE_DIR=/workspace/hexapod/.state
$( [ -n "$WANDB_KEY" ] && echo "export WANDB_API_KEY='$WANDB_KEY'" )
ENV

# git clone with the token kept out of the remote URL / argv
git config --global credential.helper store
printf 'https://x-access-token:%s@github.com\n' '$GH_TOKEN' > /root/.git-credentials
chmod 600 /root/.git-credentials
git config --global user.name "hexapod-orchestrator"
git config --global user.email "orchestrator@users.noreply.github.com"
[ -d /workspace/hexapod-orchestrator ] || git clone \
    "https://$ORCH_URL_BASE" /workspace/hexapod-orchestrator
[ -d /workspace/hexapod ] || git clone --filter=blob:none \
    "https://$REPO_URL_BASE" /workspace/hexapod
# Runtime state: populate the plain state directory from the PVC mirror
# (state_sync.sh restore refuses an empty mirror and a non-empty target).
[ -d /workspace/hexapod/.state/ledger ] || \
    KUBECONFIG=/root/.kube/coreweave.yaml HEXAPOD_STATE_DIR=/workspace/hexapod/.state \
    HEXAPOD_REPO=/workspace/hexapod \
    bash /workspace/hexapod-orchestrator/orchestrator/state_sync.sh restore

pip install -q --no-cache-dir uv
uv pip install -q --system wandb pyyaml

tmux kill-session -t orchestrator 2>/dev/null || true
tmux new-session -d -s orchestrator \
  "source /root/orchestrator.env && cd /workspace/hexapod-orchestrator && \
   uv run --no-project python orchestrator/watch_loop.py"
echo OK
EOF

echo "== done. tail the log with:"
echo "kubectl --kubeconfig=$KC exec $POD -- tail -f /workspace/orchestrator.log"
