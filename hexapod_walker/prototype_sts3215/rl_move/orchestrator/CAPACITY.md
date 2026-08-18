# Cluster capacity — run the script, never guess

```sh
python3 rl_move/orchestrator/capacity.py          # live truth, human table
python3 rl_move/orchestrator/capacity.py --json   # machine-readable
```

That script is THE canonical answer to "what machines exist, what's
running, what's free". It queries the cluster live every time. Static
numbers in docs (including this one) go stale — **if any doc disagrees
with the script, the script is right; fix the doc.**

## Policy (operator rulings, 2026-08-09 — binding)

1. **One pool.** All nodes and all GPUs belong to this project. No
   partitioning into "our node" vs anything else.
2. **At least 4 train slots per machine, never in doubt.** One
   `hexapod-mjx-train-*` pod = one slot = one H200 + one training run.
3. **The drain is mechanical.** The watcher drains `backlog.json` into
   free slots (`launch_run.py drain`) with no agent deliberation — a
   queued spec that sits unplaced next to a free slot is a bug.
   **This is a placement rule, not a demand for a full backlog**
   (prime directive, 08-10): nothing enters the backlog unless it
   removes an unresolved blocker to the next hardware test. Idle
   slots with an empty backlog are a normal, healthy state.
4. Slot list lives in `guardrails.yaml compute.gpu_pods`; pod specs in
   `rl_move/sim/coreweave_pods_mjx_scaleout.yaml`; fresh-pod setup via
   `bootstrap_train_pod.sh <pod>`.

## Notes

- A single run uses only ~19% of an H200; the binding constraint is CPU
  (each pod requests 24-26 cores). Raising slots/machine beyond 4 means
  smaller CPU requests per pod (see scale-out manifest header).
- CoreWeave `cw-hpc-verification` pods periodically hold all 8 GPUs on an
  idle node for diagnostics; train pods Pending on them schedule when the
  check releases. Normal, not an outage.
- The 7 relic CPU sweep pods (CPU-training era) were backed up to the
  controller (`/workspace/relic_backup/`) and deleted on 2026-08-09.
  Only the controller `hexapod-sweep-friction` remains, and it is not
  a slot.

- /dev/shm caveat (2026-08-18, walkcurr3 canary SIGBUS): the LIVE
  mjx-train pods were created before the 4Gi dshm mount landed in
  coreweave_pods_mjx_scaleout.yaml — they still have the 64M k8s
  default, which SIGBUS-kills MjxShardedVecEnv workers on hist16-wide
  layouts at n_envs 4096 (any21-class runs at n_envs 512 fit).
  hexapod-mjx-train-5 was recreated 08-18 from the fixed spec (4Gi
  tmpfs, verified) + re-bootstrapped + CUDA torch reinstalled
  (pod_torch_capability.py install). Recreate other IDLE pods the same
  way before scheduling wide sharded runs on them; note the pod-local
  /workspace is wiped (re-copy encoder/dataset artifacts).
