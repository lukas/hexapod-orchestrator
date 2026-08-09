#!/usr/bin/env bash
# Bootstrap a fresh hexapod-mjx-train-* pod to training-ready.
# Usage: bash bootstrap_train_pod.sh <pod> [<pod> ...]
# Idempotent; safe to re-run. Run from the controller (needs kubectl +
# the repo checkout). Package pins mirror the working train-0..3 pods
# (checked 2026-08-09): mujoco/mjx/warp 3.11.0, warp-lang 1.16.0,
# jax[cuda12] 0.10.2, sb3 2.9.0, wandb 0.28.1, torch 2.13.0+cpu.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
KC="${KUBECONFIG:-$HOME/.kube/coreweave.yaml}"

PKGS="numpy==2.4.6 mujoco==3.11.0 mujoco-mjx==3.11.0 mujoco-warp==3.11.0 \
warp-lang==1.16.0 jax[cuda12]==0.10.2 stable-baselines3==2.9.0 \
wandb==0.28.1 imageio imageio-ffmpeg pyyaml"

for POD in "$@"; do
  echo "=== $POD"
  phase=$(kubectl --kubeconfig "$KC" get pod "$POD" -o jsonpath='{.status.phase}' 2>/dev/null)
  if [ "$phase" != "Running" ]; then
    echo "$POD not Running (phase=${phase:-absent}) — likely Pending on a "
    echo "health-check-held GPU. Re-run when it schedules."
    continue
  fi
  kubectl --kubeconfig "$KC" exec "$POD" -- bash -c '
    set -e
    apt-get update -qq && apt-get install -y -qq libosmesa6 libegl1 libgl1 ffmpeg rsync procps > /dev/null
    pip install -q --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
    pip install -q --no-cache-dir '"$PKGS"'
    mkdir -p /workspace/prototype_sts3215
    echo "packages OK"
  ' || { echo "$POD bootstrap FAILED"; continue; }
  # Code + champion checkpoint; both are idempotent.
  bash "$HERE/snapshot.sh" --sync "$POD"
  bash "$HERE/ops.sh" pushckpt "$POD" rl_move/sim/policies/ppo_goal_cw_walk_anchorgate.zip || true
  # Smoke: import chain + GPU visible.
  kubectl --kubeconfig "$KC" exec "$POD" -- bash -c '
    cd /workspace/prototype_sts3215 && \
    python -c "import mujoco, warp, jax, stable_baselines3, wandb; \
import mujoco.mjx; print(\"imports OK\", jax.devices())"' \
    && echo "$POD READY" || echo "$POD smoke FAILED"
done
