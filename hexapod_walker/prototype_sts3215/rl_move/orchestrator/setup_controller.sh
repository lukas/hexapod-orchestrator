#!/usr/bin/env bash
# One-time setup of the orchestrator on the controller pod.
# Run FROM THE LAPTOP. Prompts for the two secrets; nothing is stored here.
set -euo pipefail

POD="${POD:-hexapod-sweep-friction}"
KC="${KUBECONFIG:-$HOME/.kube/coreweave.yaml}"
REPO_URL_BASE="github.com/lukas/hexapod.git"

read -r -s -p "GitHub fine-grained token (repo contents read/write): " GH_TOKEN; echo
read -r -s -p "Cursor API key: " CURSOR_KEY; echo
read -r -s -p "W&B API key (blank = reuse pod's existing): " WANDB_KEY; echo

echo "== copying kubeconfig to $POD"
kubectl --kubeconfig="$KC" cp "$KC" "$POD":/root/.kube/coreweave.yaml 2>/dev/null || {
  kubectl --kubeconfig="$KC" exec "$POD" -- mkdir -p /root/.kube
  kubectl --kubeconfig="$KC" cp "$KC" "$POD":/root/.kube/coreweave.yaml
}

echo "== installing cursor-agent, kubectl, cloning repo, starting loop"
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
$( [ -n "$WANDB_KEY" ] && echo "export WANDB_API_KEY='$WANDB_KEY'" )
ENV

# git clone with the token kept out of the remote URL / argv
git config --global credential.helper store
printf 'https://x-access-token:%s@github.com\n' '$GH_TOKEN' > /root/.git-credentials
chmod 600 /root/.git-credentials
git config --global user.name "hexapod-orchestrator"
git config --global user.email "orchestrator@users.noreply.github.com"
[ -d /workspace/hexapod ] || git clone --filter=blob:none \
    "https://$REPO_URL_BASE" /workspace/hexapod

pip install -q --no-cache-dir uv
uv pip install -q --system wandb pyyaml

tmux kill-session -t orchestrator 2>/dev/null || true
tmux new-session -d -s orchestrator \
  "source /root/orchestrator.env && cd /workspace/hexapod && \
   uv run python hexapod_walker/prototype_sts3215/rl_move/orchestrator/watch_loop.py"
echo OK
EOF

echo "== done. tail the log with:"
echo "kubectl --kubeconfig=$KC exec $POD -- tail -f /workspace/orchestrator.log"
