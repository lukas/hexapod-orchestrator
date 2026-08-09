#!/usr/bin/env bash
# ops.sh — one-stop helpers for orchestrator cycles (2026-08-09).
# Born from transcript mining: cycles kept re-deriving these (pods have
# no ps; eval_checkpoint must run as a module; ledger holds pod/log
# paths; sleep-then-check is blocked by the harness). Use these instead
# of composing kubectl/python by hand. Docs: rl_docs/COMMANDS.md.
# If you figure out a new slow/tricky command, ADD IT HERE (standing
# rule in rl_docs/README.md).
set -uo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/coreweave.yaml}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROTO="$(cd "$HERE/../.." && pwd)"          # …/hexapod_walker/prototype_sts3215
LEDGER="$HERE/experiments.json"
WANDB_PROJECT="l2k2/hexapod-balance"
POD_PROTO=/workspace/prototype_sts3215      # pods' tree (NOT the controller's)

list_procs() {  # list_procs <pod> — training/eval processes (pods have NO ps)
  kubectl exec "$1" -- sh -c '
    for p in /proc/[0-9]*/cmdline; do
      c=$(tr "\0" " " < "$p" 2>/dev/null) || continue
      case "$c" in
        *train_ppo*|*eval_checkpoint*) echo "${p%/cmdline}: $c" | cut -c1-160;;
      esac
    done' 2>/dev/null || echo "(none or pod unreachable)"
}

entry_field() {  # entry_field <run> <field> — last LIVE entry wins
  # Prefer RUNNING/FINISHED/etc over REFUSED/KILLED husks: a late REFUSED
  # duplicate (pod race) otherwise poisons pod/log lookups (hit 08-09,
  # loadslip-s1 trainlog pointed at the wrong pod).
  python3 - "$1" "$2" <<'EOF'
import json, sys
run, field = sys.argv[1], sys.argv[2]
val = dead_val = ""
for e in json.load(open(__import__("os").environ["LEDGER"])):
    if isinstance(e, dict) and e.get("run") == run and e.get(field) is not None:
        if e.get("status") in ("REFUSED", "KILLED"):
            dead_val = e[field]
        else:
            val = e[field]
print(val if val != "" else dead_val)
EOF
}
export LEDGER

case "${1:-help}" in

status)  # fleet in one shot: active ledger entries, live procs, watcher tail
  python3 - <<'EOF'
import json, os
active = {}
for e in json.load(open(os.environ["LEDGER"])):
    if isinstance(e, dict) and e.get("status") in ("RUNNING", "INTENT"):
        active[e.get("run")] = (e.get("status"), e.get("pod"))
for r, (s, p) in active.items():
    print(f"{s:8s} {r}  pod={p}")
EOF
  for pod in $(python3 -c "
import json,os
pods={e.get('pod') for e in json.load(open(os.environ['LEDGER']))
      if isinstance(e,dict) and e.get('status')=='RUNNING'}
print(' '.join(sorted(p for p in pods if p)))"); do
    echo "--- $pod live procs:"
    list_procs "$pod"
  done
  echo "--- watcher:"
  tail -3 /workspace/orchestrator.log 2>/dev/null || true
  ;;

procs)  # procs <pod> — training/eval processes (pods have NO ps)
  list_procs "$2"
  ;;

census)  # census — every train pod's live trainer, straight from /proc.
  # THE ground truth for "what is actually running". W&B lags a fresh
  # launch by up to ~8 min (JAX/Warp compile) and `ps` doesn't exist on
  # the older pods — both misled a 2026-08-09 debugging session.
  for pod in $(python3 -c "
import yaml
print(' '.join(yaml.safe_load(open('$HERE/guardrails.yaml'))['compute']['gpu_pods']))"); do
    printf '%-24s ' "$pod:"
    kubectl exec "$pod" -- sh -c '
      found=""
      for p in /proc/[0-9]*/cmdline; do
        c=$(tr "\0" " " < "$p" 2>/dev/null) || continue
        case "$c" in python*train_ppo*) found="$c";; esac
      done
      if [ -n "$found" ]; then
        echo "$found" | sed "s/.*--run-name \([^ ]*\).*/\1/"
      else echo idle; fi' 2>/dev/null || echo unreachable
  done
  ;;

trainlog)  # trainlog <run> [lines] — tail the run's train log on its pod
  run="$2"; n="${3:-30}"
  pod=$(entry_field "$run" pod); log=$(entry_field "$run" log)
  [ -z "$log" ] && log="/tmp/train_${run}.log"
  [ -z "$pod" ] && { echo "no ledger entry for $run"; exit 1; }
  echo "== $pod:$log =="
  kubectl exec "$pod" -- tail -n "$n" "$log"
  ;;

entry)  # entry <run> — all ledger entries for the run, pretty-printed
  python3 - "$2" <<'EOF'
import json, os, sys
for e in json.load(open(os.environ["LEDGER"])):
    if isinstance(e, dict) and e.get("run") == sys.argv[1]:
        print(json.dumps(e, indent=1))
EOF
  ;;

wandb)  # wandb <run> — state, steps, reward trend (quarters), std, url
  python3 - "$2" <<'EOF'
import sys
import wandb
api = wandb.Api()
name = sys.argv[1]
runs = [r for r in api.runs("l2k2/hexapod-balance",
                            filters={"display_name": name})]
if not runs:
    sys.exit(f"no W&B run named {name}")
r = sorted(runs, key=lambda x: x.created_at)[-1]
s = r.summary
print(f"{r.name} [{r.id}] state={r.state} steps={s.get('global_step') or s.get('_step')}")
print(f"ep_rew_mean={s.get('rollout/ep_rew_mean')} std={s.get('train/std')} "
      f"fps={s.get('time/fps')}")
hist = r.history(keys=["rollout/ep_rew_mean"], pandas=False, samples=200)
vals = [h["rollout/ep_rew_mean"] for h in hist if h.get("rollout/ep_rew_mean") is not None]
if len(vals) >= 8:
    q = len(vals) // 4
    print("reward quarters:", [round(sum(vals[i*q:(i+1)*q])/q, 1) for i in range(4)])
print(r.url)
EOF
  ;;

pullckpt)  # pullckpt <run> — fetch the run's checkpoint from its pod; md5
  run="$2"; pod=$(entry_field "$run" pod)
  [ -z "$pod" ] && { echo "no ledger entry for $run"; exit 1; }
  name="ppo_goal_$(echo "$run" | tr - _).zip"
  dest="$PROTO/rl_move/sim/policies/$name"
  kubectl cp "$pod:$POD_PROTO/rl_move/sim/policies/$name" "$dest" && \
    md5sum "$dest"
  ;;

pushckpt)  # pushckpt <pod> <ckpt.zip> — copy a checkpoint TO a pod; md5 both
  # snapshot.sh --sync EXCLUDES rl_move/sim/policies (large files), so a
  # warm-start parent must be pushed explicitly. cw-walk-longdist (operator
  # launch, 2026-08-09) died at init on exactly this: FileNotFoundError on
  # the champion zip, pod had code but no checkpoints. ALWAYS pushckpt +
  # compare md5 before launching --init-from on a pod that didn't train
  # the parent.
  pod="$2"; src="$3"
  [ -f "$src" ] || src="$PROTO/$3"
  [ -f "$src" ] || src="$PROTO/rl_move/sim/policies/$(basename "$3")"
  [ -f "$src" ] || { echo "no such checkpoint: $3"; exit 1; }
  # dest dir is excluded from snapshot.sh --sync; may not exist yet (c37)
  kubectl exec "$pod" -- mkdir -p "$POD_PROTO/rl_move/sim/policies"
  name=$(basename "$src")
  kubectl cp "$src" "$pod:$POD_PROTO/rl_move/sim/policies/$name" && \
    md5sum "$src" && \
    kubectl exec "$pod" -- md5sum "$POD_PROTO/rl_move/sim/policies/$name"
  ;;

evalcmd)  # evalcmd <run> — print the exact-path harness eval command
  run="$2"
  python3 - "$run" <<'EOF'
import json, os, sys
run = sys.argv[1]
entry = None
for e in json.load(open(os.environ["LEDGER"])):
    if isinstance(e, dict) and e.get("run") == run and e.get("extra_args"):
        entry = e
args = entry["extra_args"] if entry else []
def val(flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default
task = val("--task", "joint_walk")
ep = val("--episode-seconds", "15" if task == "joint_walk" else None)
cfg = " ".join(f"--cfg-set {args[i+1]}" for i, a in enumerate(args) if a == "--cfg-set")
modes = "--modes walk" if task == "joint_walk" else ""
name = "ppo_goal_" + run.replace("-", "_")
out = f"logs/ckpt_eval/{run.replace('-', '_')}_gate"
print(f"# run from the PROTO dir; ALWAYS as a module (-m), never the .py path")
print(f"nohup python3 -m rl_move.sim.eval_checkpoint rl_move/sim/policies/{name}.zip \\")
print(f"  --task {task} {modes} --per-mode 6 --dr-scale 0.0 --seed 0 --stochastic \\")
if ep: print(f"  --episode-seconds {ep} \\")
if cfg: print(f"  {cfg} \\")
print(f"  --video-every 1 --out {out} > /tmp/eval_{run}.log 2>&1 &")
print(f"# then: ops.sh waitlog /tmp/eval_{run}.log 'WROTE|Traceback' 1800")
EOF
  ;;

expdir)  # expdir <run> — per-experiment log dir with summary.md template
  run="$2"; d="$PROTO/logs/experiments/$run"
  mkdir -p "$d"
  if [ ! -f "$d/summary.md" ]; then
    cat > "$d/summary.md" <<TEMPLATE
# $run — <one-line outcome, fill at verdict time>

## What we tried and why (plain English, 2-4 sentences)
<for a human who knows nothing about the codebase: what robot
behavior problem this attacks, what we changed, what we hoped for>

## What happened
<plain result: did the hoped-for thing occur; what the video showed;
verdict PASS/FAIL and why>

## Details
- W&B: <url>   parent: <run>   ckpt md5: <md5>
- gate: <gate + numbers>
- eval artifacts: <paths>
TEMPLATE
  fi
  echo "$d"
  ;;

wandbdump)  # wandbdump <run> — cache W&B summary/config/history locally
  run="$2"; d="$PROTO/logs/experiments/$run"; mkdir -p "$d"
  python3 - "$run" "$d" <<'EOF'
import csv, json, sys
import wandb
name, d = sys.argv[1], sys.argv[2]
api = wandb.Api()
runs = [r for r in api.runs("l2k2/hexapod-balance",
                            filters={"display_name": name})]
if not runs:
    sys.exit(f"no W&B run named {name}")
r = sorted(runs, key=lambda x: x.created_at)[-1]
json.dump({"id": r.id, "state": r.state, "url": r.url, "notes": r.notes,
           "config": dict(r.config),
           "summary": {k: v for k, v in r.summary.items()
                       if not k.startswith("_") and isinstance(v, (int, float, str))}},
          open(f"{d}/wandb_summary.json", "w"), indent=1, default=str)
hist = list(r.scan_history())
if hist:
    keys = sorted({k for h in hist for k in h if not k.startswith("system")})
    with open(f"{d}/wandb_history.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(hist)
print(f"cached {len(hist)} history rows -> {d}/")
EOF
  ;;

wandbnote)  # wandbnote <run> "paragraph" — append the human OUTCOME
  # paragraph to the BOTTOM of the run's W&B notes (operator, 08-09:
  # notes open with the plain-English plan; they should CLOSE with what
  # happened and what was learned, targeted at a human).
  run="$2"; text="$3"
  python3 - "$run" "$text" <<'EOF'
import sys
import wandb
name, text = sys.argv[1], sys.argv[2]
api = wandb.Api()
runs = [r for r in api.runs("l2k2/hexapod-balance",
                            filters={"display_name": name})]
if not runs:
    sys.exit(f"no W&B run named {name}")
r = sorted(runs, key=lambda x: x.created_at)[-1]
marker = "--- OUTCOME"
base = (r.notes or "").split(marker)[0].rstrip()
r.notes = f"{base}\n\n{marker} ---\n{text.strip()}\n"
r.update()
print(f"notes updated: {r.url}")
EOF
  ;;

waitlog)  # waitlog <file> <regex> [timeout_s] — poll instead of sleep-and-pray
  f="$2"; pat="$3"; t="${4:-900}"; el=0
  until grep -qE "$pat" "$f" 2>/dev/null; do
    sleep 15; el=$((el+15))
    [ "$el" -ge "$t" ] && { echo "TIMEOUT after ${t}s; tail:"; tail -5 "$f" 2>/dev/null; exit 1; }
  done
  echo "matched after ~${el}s:"; grep -E "$pat" "$f" | tail -3
  ;;

*)
  sed -n '2,6p' "$0"
  echo "subcommands: status | procs <pod> | trainlog <run> [n] | entry <run> |"
  echo "  wandb <run> | pullckpt <run> | pushckpt <pod> <ckpt> | evalcmd <run> |"
  echo "  waitlog <file> <regex> [t] |"
  echo "  expdir <run> | wandbdump <run> | wandbnote <run> \"paragraph\""
  ;;
esac
