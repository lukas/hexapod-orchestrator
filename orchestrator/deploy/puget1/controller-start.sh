#!/usr/bin/env bash
# Persistent workspace and credentials must be restored before first startup.
set -euo pipefail
umask 077
private=/workspace/controller-private
orch=/workspace/hexapod-orchestrator
subject=/workspace/hexapod
for file in "$private/orchestrator.env" "$private/.git-credentials" \
  /workspace/.sso_secret /workspace/.lab_login.json /workspace/.status_token \
  /workspace/.mcp_key /workspace/.kube/puget1.yaml \
  "$orch/uv.lock" "$subject/uv.lock" "$subject/.state/pod_torch_capability.json"; do
  test -s "$file" || { echo "Restore required controller file: $file" >&2; exit 1; }
done
install -m 0600 "$private/.git-credentials" /root/.git-credentials
git config --global credential.helper store
git config --global user.name hexapod-orchestrator
git config --global user.email orchestrator@users.noreply.github.com
# Reuse the existing API keys without retaining the old cluster/runtime settings.
set -a
source "$private/orchestrator.env"
set +a
unset UV_NO_PROJECT UV_PROJECT UV_PROJECT_ENVIRONMENT UV_NO_SYNC WANDB_SERVICE
export PATH="/workspace/.controller-tools/bin:/workspace/.controller-tools/claude/node_modules/.bin:/usr/local/bin:/usr/bin:/bin"
export KUBECONFIG=/workspace/.kube/puget1.yaml
export HEXAPOD_REPO="$subject"
export HEXAPOD_STATE_DIR="$subject/.state"
export SSO_COOKIE_DOMAIN=.l2k.dev
export SSO_LOGIN_HOST=rl.l2k.dev
export SSO_REDIRECT_DOMAINS=.l2k.dev,.cwd1f0-new-cluster.coreweave.app
export IS_SANDBOX=1
# All entry points, including the sanctioned watcher restart, source this file.
python - <<'PY'
import os, shlex
keys = ('PATH', 'KUBECONFIG', 'HEXAPOD_REPO', 'HEXAPOD_STATE_DIR',
        'SSO_COOKIE_DOMAIN', 'SSO_LOGIN_HOST', 'SSO_REDIRECT_DOMAINS', 'IS_SANDBOX')
with open('/root/orchestrator.env', 'w') as f:
    f.write('set -a\nsource /workspace/controller-private/orchestrator.env\nset +a\n')
    f.write('unset UV_NO_PROJECT UV_PROJECT UV_PROJECT_ENVIRONMENT UV_NO_SYNC WANDB_SERVICE\n')
    for key in keys:
        f.write(f'export {key}={shlex.quote(os.environ[key])}\n')
os.chmod('/root/orchestrator.env', 0o600)
PY
uv sync --frozen --project "$orch" --no-dev
uv sync --frozen --project "$subject" --no-dev
claude --version
kubectl get nodes
kubectl get pod hexapod-mjx-train-puget1
install -m 0755 "$orch/orchestrator/restart_watcher.sh" /workspace/restart_watcher.sh
cd "$orch"
tmux new-session -d -s orchestrator \
  "source /root/orchestrator.env && cd '$orch' && uv run --frozen python orchestrator/watch_loop.py"
# On first deployment the restored PAUSE/WRAPUP/LAUNCH_HOLD remain set.
# Cutover validation explicitly releases them; restarts preserve their state.
uv run --frozen python orchestrator/status_server.py &
status_pid=$!
stop() {
  trap - TERM INT EXIT
  bash /workspace/restart_watcher.sh --stop
  kill -TERM "$status_pid" 2>/dev/null || true
  wait "$status_pid" 2>/dev/null || true
}
trap stop TERM INT EXIT
while kill -0 "$status_pid" 2>/dev/null && tmux has-session -t orchestrator; do
  sleep 5
done
echo 'Controller status server or watcher exited; inspect their logs.' >&2
exit 1
