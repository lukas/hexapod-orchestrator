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
sb3-contrib==2.9.0 wandb==0.28.1 tensorboard imageio imageio-ffmpeg pyyaml"
# sb3-contrib: train_ppo_sim's background eval/video/canary child imports
# gru_policy -> sb3_contrib unconditionally; without it the child dies at
# first import and the trainer runs eval/video/canary-BLIND for its whole
# life (busy flag never clears — bit cw-recover-any2 on a freshly
# re-bootstrapped train-1, 2026-08-15).
# tensorboard: wandb.init() monkeypatches it and hard-fails if missing
# (killed the first credentialed launches on train-4..11, 2026-08-09).

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
    # uv is part of the pod contract: launch_run.py and ops.sh run trainers
    # and evals as `uv run python ...`, so a pod without uv is not launchable.
    pip install -q --no-cache-dir uv
    INST="uv pip install -q --system --no-cache"
    # torch must be a CUDA build: train_ppo_mjx --require-gpu-physics
    # (every real launch) hard-refuses when torch.cuda is unavailable.
    # The old torch==2.13.0+cpu pin silently bricked re-bootstrapped
    # pods (train-1, found 2026-09-05: "Torch not compiled with CUDA
    # enabled" -> cw-walkscratch-easy0905-sdehalfgrav-s1 FAILED
    # pre-boot). 2.11.0+cu128 mirrors the working fleet (train-2..11,
    # checked 2026-09-05).
    $INST torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
    $INST '"$PKGS"'
    mkdir -p /workspace/prototype_sts3215
    echo "packages OK"
  ' || { echo "$POD bootstrap FAILED"; continue; }
  # Code + champion checkpoint; both are idempotent.
  bash "$HERE/snapshot.sh" --sync "$POD"
  # Current walk champion (cycle 44 promotion). Update when the champion
  # shifts, or fresh pods can't warm-start the lineage.
  bash "$HERE/ops.sh" pushckpt "$POD" rl_move/sim/policies/ppo_goal_cw_walk_longdist_r2.zip || true
  # W&B credentials: rl_move/sim/wandb.env is a gitignored secret, so code
  # sync never carries it. Without it the trainer runs BLIND ("no API key —
  # logging skipped") and the run never appears in W&B (bit us 2026-08-09:
  # cw-chain-standwalksit trained 1.5M+ steps invisibly on train-6).
  kubectl --kubeconfig "$KC" cp \
    "$(dirname "$HERE")/sim/wandb.env" \
    "$POD:/workspace/prototype_sts3215/rl_move/sim/wandb.env" \
    || echo "$POD: wandb.env push FAILED — runs will not log to W&B"
  # Smoke: import chain + GPU visible.
  # The .bootstrapped marker gates the backlog drain: launch_run.py
  # treats an idle pod WITHOUT it as not-a-slot, so a freshly scheduled
  # pod can't receive launches while pip is still installing.
  kubectl --kubeconfig "$KC" exec "$POD" -- bash -c '
    cd /workspace/prototype_sts3215 && \
    uv run python -c "import mujoco, warp, jax, stable_baselines3, sb3_contrib, \
wandb; import mujoco.mjx; print(\"imports OK\", jax.devices())" && \
    touch /workspace/prototype_sts3215/.bootstrapped' \
    && echo "$POD READY" || echo "$POD smoke FAILED"
done
