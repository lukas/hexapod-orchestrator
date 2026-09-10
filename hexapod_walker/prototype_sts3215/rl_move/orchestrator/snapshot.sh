#!/usr/bin/env bash
# snapshot.sh <run-name>       commit CODE, tag exp/<run-name>, push, then commit+push STATE, print hash
# snapshot.sh --sync <pod>     sync the prototype tree to a pod's /workspace
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# Runtime state (ledger, queue, run stories, RL_LOG.md) lives in its own
# repo, lukas/hexapod-state, cloned at <checkout>/.state or $HEXAPOD_STATE_DIR
# (state_dir.py). This script is its ONLY writer: every snapshot commits and
# pushes it right after the code push, so exp/<run> pairs with a state
# commit of the same name. Code commits below only happen when CODE changed.
STATE_DIR="${HEXAPOD_STATE_DIR:-$(pwd)/.state}"

# Guard (09-10 meta): called with no arg / a flag-looking arg, this used
# to tag the literal string (a real snapshot landed as "before --help",
# 09-10 07:01). Require a plain run-name.
if [ -z "${1:-}" ] || { [ "${1:0:1}" = "-" ] && [ "$1" != "--sync" ]; }; then
  echo "usage: snapshot.sh <run-name> | snapshot.sh --sync <pod>" >&2
  exit 2
fi

if [ "${1:-}" = "--sync" ]; then
  POD="$2"
  KC="${KUBECONFIG:-$HOME/.kube/coreweave.yaml}"
  # Unique per-invocation temp name (was a fixed /tmp/proto_sync.tgz on
  # BOTH the local controller and every remote pod): concurrent cycles
  # syncing at the same time raced on that one shared local path, one
  # process's tar truncating/replacing the file while kubectl cp was
  # still streaming it out from under it (manifests as a nonsensical
  # "tar: Cannot open: Permission denied" + "Broken pipe" on the
  # receiving end) — parked 3+ launches after 3 failed retries each
  # under concurrent-cycle load, 2026-08-10. $$ + pod name makes both
  # ends collision-free; cleaned up after extraction.
  TGZ="/tmp/proto_sync_$$_${POD}.tgz"
  trap 'rm -f "$TGZ"' EXIT
  tar -C hexapod_walker -czf "$TGZ" \
      --exclude='prototype_sts3215/logs' \
      --exclude='prototype_sts3215/rl_move/sim/policies' \
      --exclude='prototype_sts3215/wandb' \
      --exclude='prototype_sts3215/rl_move/wandb' \
      --exclude='prototype_sts3215/rl_move/dynamics/datasets' \
      --exclude='prototype_sts3215/rl_move/dynamics/models' \
      --exclude='prototype_sts3215/rl_move/dynamics/logs' \
      --exclude='prototype_sts3215/rl_move/hardware_traces' \
      --exclude='prototype_sts3215/rl_move/sim/logs' \
      --exclude='prototype_sts3215/video_state' \
      --exclude='prototype_sts3215/artifacts' \
      --exclude='*/__pycache__' \
      --exclude='*.stl' --exclude='*.mp4' \
      prototype_sts3215
  kubectl --kubeconfig="$KC" cp "$TGZ" "$POD":"$TGZ"
  # Dir->symlink conversions (2026-09-04): when a repo path that used to
  # be a real directory becomes a symlink (e.g. linux_control/vision_ui
  # -> ../hexapod-tracker/web/vision_ui after the AprilTag submodule
  # extraction), tar cannot extract the symlink over the stale non-empty
  # dir still sitting on the pod — every sync fails with "Cannot open:
  # File exists" (3 launch cycles lost to manual rm -rf on 09-03).
  # Pre-remove EXACTLY the symlink members' paths when the pod copy is a
  # real dir. Do NOT reach for tar --recursive-unlink: tested 09-04, it
  # deletes pod-side hierarchies like logs/ that the tar merely touches.
  LINKS="$(tar -tzvf "$TGZ" | awk '$1 ~ /^l/ {print $6}' | tr '\n' ' ')"
  kubectl --kubeconfig="$KC" exec "$POD" -- \
      bash -c "cd /workspace; for p in $LINKS; do if [ -d \"\$p\" ] && [ ! -L \"\$p\" ]; then rm -rf \"\$p\"; fi; done; tar -C /workspace -xzf '$TGZ' && rm -f '$TGZ'"
  # Code-version marker (2026-08-09): pods have no git, so the launcher
  # cannot ask them what code they run. Stale code on long5m silently
  # dropped cw-walk-lowent-dr03's --cfg-set reward package (the old
  # walk_task.py never read those keys) and trained 4M steps on the
  # wrong reward. Record what was synced; launch_run.py refuses to
  # launch when this marker is missing or != local HEAD. A dirty tree
  # gets a -dirty suffix, which the launcher also refuses — snapshot
  # (commit) BEFORE syncing, as the cycle protocol already requires.
  SHA="$(git rev-parse HEAD)"
  # Dirty check EXCLUDES the orchestrator's runtime state files
  # (ledger, backlog + parked items, lock files): the watcher rewrites
  # them every few minutes, so including them made the tree perpetually
  # "dirty" and the -dirty marker refused every drain launch while 9
  # GPUs idled (2026-08-09). They are operational state, not trainer
  # code — the marker exists to pin the CODE the pod runs.
  # ... and EXCLUDES markdown docs: cycles append to RL_LOG.md / RL_PLAN.md
  # between commits, and an uncommitted doc edit was re-blocking every
  # drain launch an hour after the state-file fix (2026-08-09). Docs are
  # not trainer code either.
  # ... and EXCLUDES eval/train artifacts + atomic-write temp files:
  # untracked logs/, checkpoint zips and ledger .tmp files from
  # concurrent cycles kept stamping transient -dirty markers that cost
  # a drain attempt each (cycle 54, 08-09).
  P=hexapod_walker/prototype_sts3215
  EXC=(":(exclude)$P/rl_move/orchestrator/*.lock"
       ":(exclude)$P/**/*.md" ":(exclude)$P/*.md"
       ":(exclude)$P/logs" ":(exclude)$P/wandb"
       ":(exclude)$P/rl_move/wandb"
       ":(exclude)$P/rl_move/sim/policies"
       ":(exclude)$P/**/*.tmp*" ":(exclude)$P/**/*.zip"
       ":(exclude)$P/**/*.mp4" ":(exclude)$P/**/*.png")
  if ! git diff --quiet HEAD -- "$P" "${EXC[@]}" || \
     [ -n "$(git status --porcelain -- "$P" "${EXC[@]}" | grep '^??' || true)" ]; then
    SHA="${SHA}-dirty"
  fi
  kubectl --kubeconfig="$KC" exec "$POD" -- \
      bash -c "echo '$SHA' > /workspace/prototype_sts3215/.code_sha"
  echo "synced -> $POD (code_sha $SHA)"
  exit 0
fi

RUN_NAME="${1:?usage: snapshot.sh <run-name> | snapshot.sh --sync <pod>}"
TAG="exp/${RUN_NAME}"

# Decision cycles run CONCURRENTLY (08-08 evening); the commit/tag/push
# section is the one part that must not interleave. Serialize it with a
# host-wide lock; a short wait here is normal when two cycles snapshot
# at the same time.
LOCK=/workspace/git_snapshot.lock
if command -v flock >/dev/null; then
  exec 9>"$LOCK"
  flock 9
fi

# JOURNALS live in the state repo; the prototype tree holds SYMLINKS into it:
# RL_LOG.md, rl_docs/SKILLS.md, rl_move/orchestrator/OPERATOR_QUESTIONS.md,
# rl_docs/tracks/*/STATUS.md (and rl_docs/runs as a directory link). A cycle
# that creates a NEW track's STATUS.md, or an editor that saves via rename,
# leaves a regular file at one of these paths -- and `git add -A` would then
# commit the journal back into main. Move such content into the state repo
# and re-link before staging.
P=hexapod_walker/prototype_sts3215
relink_journal() {  # relink_journal <path-in-code-tree> <path-in-state>
  local code="$1" state="$STATE_DIR/$2"
  [ -e "$code" ] && [ ! -L "$code" ] || return 0
  echo "NOTE: $code is a regular file; moving it into the state repo ($2) and re-linking" >&2
  mkdir -p "$(dirname "$state")"
  if [ -f "$state" ] && ! cmp -s "$code" "$state"; then
    cp "$state" "$state.pre-relink.$(date -u +%Y%m%dT%H%M%SZ)"   # keep the state copy too; a human reconciles
  fi
  mv "$code" "$state"
  ln -s "$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], os.path.dirname(sys.argv[2])))' "$state" "$code")" "$code"
}
relink_journal "$P/RL_LOG.md" "RL_LOG.md"
relink_journal "$P/rl_docs/SKILLS.md" "rl_docs/SKILLS.md"
relink_journal "$P/rl_move/orchestrator/OPERATOR_QUESTIONS.md" "OPERATOR_QUESTIONS.md"
for T in "$P"/rl_docs/tracks/*/; do
  T="${T%/}"; [ -e "$T/STATUS.md" ] || continue
  relink_journal "$T/STATUS.md" "rl_docs/tracks/$(basename "$T")/STATUS.md"
done

git add -A hexapod_walker/prototype_sts3215
if ! git diff --cached --quiet; then
  git commit -m "orchestrator snapshot before ${RUN_NAME}"
fi
# Integrate anything the operator pushed from elsewhere before we push.
git pull --rebase --autostash origin main
# Retry-safe tagging (08-23, s1r1-c1 retry dig-in): a `respec --now`
# launch that snapshots and THEN gets REFUSED (e.g. the pod code-marker
# TOCTOU race) leaves exp/<run> behind, and the old hard-exit here made
# every retry of the same run name mechanically impossible. Tags are
# append-only provenance — never delete/move one; a retry gets a
# suffixed tag exp/<run>-snapN instead. The ledger's code_sha_local is
# the authoritative launch SHA either way.
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  N=2
  while git rev-parse -q --verify "refs/tags/${TAG}-snap${N}" >/dev/null; do
    N=$((N + 1))
  done
  echo "tag ${TAG} already exists (earlier refused/failed launch attempt); tagging ${TAG}-snap${N}" >&2
  TAG="${TAG}-snap${N}"
fi
git tag "${TAG}"
# One retry: an operator push can still land between the rebase and the
# push (concurrent cycles can't — they wait on the lock above).
git push origin HEAD --tags || {
  git pull --rebase --autostash origin main
  git push origin HEAD --tags
}
CODE_SHA="$(git rev-parse HEAD)"

# ---- STATE: commit + push the state repo (best effort, loud on failure) ----
# JSON-validity guard (2026-09-06 ledger-corruption incident): never commit
# a runtime-state JSON that fails to parse -- restore the last committed
# copy instead (loses at most a seconds-old delta from a mid-write writer;
# save_ledger() writes atomically so this should not trigger).
if [ -d "$STATE_DIR/.git" ]; then
  for RS in experiments.json backlog.json backlog_failed.json pending_evals.json; do
    RSP="$STATE_DIR/$RS"
    if [ -f "$RSP" ] && ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$RSP" 2>/dev/null; then
      echo "WARNING: $RSP fails to parse as JSON -- restoring last committed copy" >&2
      git -C "$STATE_DIR" checkout -q -- "$RS" 2>/dev/null || echo "  (no committed copy either -- left as-is, needs manual repair)" >&2
    fi
  done
  git -C "$STATE_DIR" add -A
  if ! git -C "$STATE_DIR" diff --cached --quiet; then
    git -C "$STATE_DIR" commit -q -m "state before ${RUN_NAME} (code ${CODE_SHA:0:9})"
  fi
  git -C "$STATE_DIR" push -q origin HEAD 2>/dev/null || {
    git -C "$STATE_DIR" pull -q --rebase --autostash origin main 2>/dev/null || true
    git -C "$STATE_DIR" push -q origin HEAD 2>/dev/null || \
      echo "WARNING: state push failed (network?); state is committed locally in $STATE_DIR and the next snapshot will push it" >&2
  }
else
  echo "WARNING: $STATE_DIR is not a git clone -- state NOT durable. Clone lukas/hexapod-state there (setup_controller.sh does this)." >&2
fi

echo "$CODE_SHA"
