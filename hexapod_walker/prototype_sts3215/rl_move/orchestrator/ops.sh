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

remote_ops() {  # re-run this ops.sh subcommand ON the controller pod.
  # The cycle logs / registry / watcher log live only there; these
  # observability commands (activity, cyclelog, waitcycle) work from
  # the operator Mac by re-execing themselves remotely. kubectl exec
  # streams stdout, so even the live-follow waitcycle works.
  exec kubectl exec hexapod-sweep-friction -- bash \
    /workspace/weird_objects/hexapod_walker/prototype_sts3215/rl_move/orchestrator/ops.sh "$@"
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
export LEDGER PROTO

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
  # NOTE: `kubectl cp` exits 0 even when the remote file is missing (the
  # remote tar fails internally and just warns to stderr) — check the
  # DEST FILE, never cp's own exit code (bit us silently before this fix).
  # --retries: a plain cp can TRUNCATE silently on a stream hiccup (bit us
  # 08-10 on cw-dep-quad1-c2: 2.16 of 2.27 MB arrived, md5 looked "fine"
  # because it's computed locally). Also print the size; compare against
  # the pod's `stat -c %s` when in doubt.
  kubectl cp --retries=5 "$pod:$POD_PROTO/rl_move/sim/policies/$name" "$dest" 2>/dev/null
  if [ -s "$dest" ]; then
    md5sum "$dest"
    wc -c < "$dest" | awk '{print "size: "$1" bytes"}'
  else
    rm -f "$dest"
    # Fallback (08-10, cw-stance-riseproof1): launch_run.py now always
    # injects --out-name, but older/hand-crafted launches without it fell
    # back to train_ppo_mjx's OWN default ppo_mjx_<task>_<run>.zip. Try the
    # joint_goal/joint_walk/goal variants before giving up.
    found=0
    for task in joint_goal joint_walk goal; do
      alt="ppo_mjx_${task}_${run}.zip"
      altdest="$PROTO/rl_move/sim/policies/$alt"
      kubectl cp "$pod:$POD_PROTO/rl_move/sim/policies/$alt" "$altdest" 2>/dev/null
      if [ -s "$altdest" ]; then
        echo "(fell back to trainer-default name: $alt)"
        md5sum "$altdest"
        found=1
        break
      fi
      rm -f "$altdest"
    done
    if [ "$found" != 1 ]; then
      echo "no checkpoint found under $name or any ppo_mjx_<task>_${run}.zip fallback on $pod"
      exit 1
    fi
  fi
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

podeval)  # podeval <run> [suffix] — run gate + own-DR evals ON the run's
  # own pod (idle CPUs, checkpoint already there), stream logs to
  # /tmp/eval_<run>*.log, copy artifacts back to logs/ckpt_eval/.
  # Blocking; wait for the SYNCED line. Idempotent per artifact dir.
  # Since 08-13 (WISHLIST 8e) also runs the interactive SESSION gate
  # for stance/walk candidates (stance seat vs deployed walk / walk
  # seat vs deployed stance) — informational, never fails the exit
  # code; result in /tmp/eval_<run>_session.log + <run>_session/.
  shift
  exec python3 "$HERE/pod_eval.py" "$@"
  ;;

evalcmd)  # evalcmd <run> — print the exact-path harness eval command
  run="$2"
  python3 - "$run" <<'EOF'
import json, os, sys
run = sys.argv[1]
# 08-13 fix: prefer an entry that actually ran (wandb_id/pid) over a
# later REFUSED re-launch stub with the same run name — a plain
# last-match scan silently picked the thin stub's near-empty
# extra_args (no --cfg-set), voiding the eval (obs-width mismatch).
entry = None
fallback = None
for e in json.load(open(os.environ["LEDGER"])):
    if isinstance(e, dict) and e.get("run") == run and e.get("extra_args"):
        fallback = e
        if e.get("wandb_id") or e.get("checks", {}).get("pid"):
            entry = e
entry = entry or fallback
args = entry["extra_args"] if entry else []
def val(flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default
task = val("--task", "joint_walk")
ep = val("--episode-seconds", "15" if task == "joint_walk" else None)
cfg = " ".join(f"--cfg-set {args[i+1]}" for i, a in enumerate(args) if a == "--cfg-set")
goal_mix = val("--goal-mix")
if goal_mix:
    mix_modes = []
    for kv in goal_mix.split(","):
        if not kv.strip():
            continue
        k, _, v = kv.partition("=")
        if float(v or 0) > 0:
            mix_modes.append(k.strip())
    modes = "--modes " + " ".join(mix_modes) if mix_modes else "--modes walk"
elif task == "joint_walk":
    modes = "--modes walk"
else:
    modes = ""
name = "ppo_goal_" + run.replace("-", "_")
out = f"logs/ckpt_eval/{run.replace('-', '_')}_gate"
print(f"# run from the PROTO dir; ALWAYS as a module (-m), never the .py path")
print(f"nohup python3 -m rl_move.sim.eval_checkpoint rl_move/sim/policies/{name}.zip \\")
print(f"  --task {task} {modes} --per-mode 6 --dr-scale 0.0 --seed 0 --stochastic \\")
if ep: print(f"  --episode-seconds {ep} \\")
if cfg: print(f"  {cfg} \\")
print(f"  --video-every 1 --out {out} > /tmp/eval_{run}.log 2>&1 &")
print(f"# then: ops.sh waitlog /tmp/eval_{run}.log 'artifacts|Traceback' 1800")
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

report)  # report <run|report.json> — the standard triage table from a
  # harness eval. Transcript mining (08-09): cycles hand-wrote this
  # exact json-parse >100 times. Accepts a run name (newest matching
  # logs/ckpt_eval/*<run>*/report.json wins) or an explicit path.
  python3 - "$2" <<'EOF'
import glob, json, os, statistics, sys
arg = sys.argv[1]
proto = os.environ["PROTO"]
if arg.endswith(".json"):
    paths = [arg]
else:
    snake = arg.replace("-", "_").removeprefix("cw_walk_")
    paths = sorted(glob.glob(f"{proto}/logs/ckpt_eval/*{snake}*/report.json"),
                   key=os.path.getmtime)
if not paths:
    sys.exit(f"no report.json matching {arg} under logs/ckpt_eval/")
for p in paths[-2:]:
    d = json.load(open(p))
    print(f"== {os.path.relpath(p, proto)}  dr={d.get('dr_scale')} "
          f"std={round(d.get('policy_std', 0), 3)}")
    for mode, eps in d["episodes"].items():
        for i, e in enumerate(eps):
            cells = [f"{mode}/{i}"]
            for k, fmt in (("progress_ratio", "prog {:.2f}"),
                           ("slip_per_m", "slip {:.2f}"),
                           ("forward_dist_m", "fwd {:.2f}m"),
                           ("gait_valid", "gv {}"),
                           ("sacrificed_legs", "sac {}"),
                           ("success", "ok {}")):
                if e.get(k) is not None:
                    cells.append(fmt.format(e[k]))
            if e.get("terminated"):
                cells.append(f"TERM {e.get('term_reason')}")
            print("  " + "  ".join(str(c) for c in cells))
        med = lambda k: (statistics.median(x[k] for x in eps if x.get(k)
                         is not None) if any(x.get(k) is not None
                                             for x in eps) else None)
        agg = [f"{mode}: n={len(eps)}"]
        if med("progress_ratio") is not None:
            agg.append(f"prog med {med('progress_ratio'):.2f}")
        if med("slip_per_m") is not None:
            agg.append(f"slip med {med('slip_per_m'):.2f}")
        if med("forward_dist_m") is not None:
            agg.append(f"fwd med {med('forward_dist_m'):.2f}m")
        gv = [x.get("gait_valid") for x in eps]
        if any(v is not None for v in gv):
            agg.append(f"gait_valid {sum(bool(v) for v in gv)}/{len(gv)}")
        agg.append(f"terms {sum(bool(x.get('terminated')) for x in eps)}")
        print("  -- " + "  ".join(agg))
EOF
  ;;

review)  # review <run> — THE standard triage read in one command:
  # ledger status+gate, W&B state/steps/reward-quarters, newest eval
  # report table, video/contact-sheet paths, OUTCOME-note check.
  # If this output plus one video answers pass/fail, you are DONE —
  # record the verdict; dig in only on a trigger (prompt §dig-in).
  run="$2"
  echo "##### ledger"
  st=$(entry_field "$run" status); gate=$(entry_field "$run" gate)
  echo "status=$st  pod=$(entry_field "$run" pod)"
  echo "gate: $gate"
  echo "##### wandb"
  bash "$0" wandb "$run" || true
  echo "##### eval report"
  bash "$0" report "$run" 2>/dev/null || echo "(no harness report yet — ops.sh evalcmd $run)"
  echo "##### videos / contact sheets"
  snake=$(echo "$run" | tr - _ | sed 's/^cw_walk_//')
  ls -t "$PROTO"/logs/ckpt_eval/*${snake}*/*.mp4 "$PROTO"/logs/ckpt_eval/*${snake}*/*.png 2>/dev/null | head -8 \
    || echo "(none)"
  ;;

frames)  # frames <video.mp4> [n] — n evenly-spaced frames -> one
  # contact-sheet PNG beside the video. NOTE the harness already
  # writes walk_*.png sheets next to every eval video — check those
  # first; this is for train-log or W&B videos only.
  v="$2"; n="${3:-8}"
  python3 - "$v" "$n" <<'EOF'
import sys
import cv2
import numpy as np
v, n = sys.argv[1], int(sys.argv[2])
cap = cv2.VideoCapture(v)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
frames = []
for i in np.linspace(0, max(total - 1, 0), n).astype(int):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
    ok, f = cap.read()
    if ok:
        frames.append(cv2.resize(f, (f.shape[1] // 2, f.shape[0] // 2)))
out = v.rsplit(".", 1)[0] + "_sheet.png"
cv2.imwrite(out, np.hstack(frames))
print(out)
EOF
  ;;

logline)  # logline "text" — append ONE timestamped line to RL_LOG.md
  # under the git lock. This is the ONLY sanctioned way to write
  # RL_LOG from a cycle: free-form `cat >> RL_LOG.md` blocks bloated
  # it from 200 to 580 lines in half a day (operator cleanup, 08-09).
  # Detail belongs in the ledger verdict (auto-renders
  # rl_docs/runs/<run>.md) and the W&B OUTCOME note, not here.
  text="$2"
  [ -n "$text" ] || { echo "usage: ops.sh logline \"one line\""; exit 1; }
  (
    command -v flock >/dev/null && { exec 9>>/workspace/git_snapshot.lock; flock 9; }
    printf '%s %s\n' "- $(date -u +%m-%d\ %H:%M)" "$(echo "$text" | tr '\n' ' ')" \
      >> "$PROTO/RL_LOG.md"
  )
  tail -1 "$PROTO/RL_LOG.md"
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

wandbnote)  # wandbnote <run> "paragraph" — put the human OUTCOME
  # paragraph at the TOP of the run's W&B notes (operator, 08-10: the
  # first thing anyone sees on a run page must be what happened, in
  # plain English — the 08-09 append-at-bottom rule buried it under
  # the spec dump and the operator could not tell what a run was even
  # trying to learn). Re-running replaces the previous OUTCOME block;
  # everything below the marker line is preserved.
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
marker = "--- details below ---"
old = r.notes or ""
# strip a previous top OUTCOME block (and the legacy bottom one)
body = old.split(marker, 1)[1] if marker in old else old
body = body.split("--- OUTCOME ---")[0].rstrip()
text = text.strip()
if text.upper().startswith("OUTCOME:"):
    text = text[len("OUTCOME:"):].strip()
r.notes = f"OUTCOME: {text}\n\n{marker}\n{body.lstrip()}"
r.update()
print(f"notes updated: {r.url}")
EOF
  ;;

verdict)  # verdict <run> <status> "<verdict text>" ["logline text"] —
  # ONE-SHOT verdict fan-out (operator 08-22: recording one verdict by
  # hand averaged ~17 separate bookkeeping commands per cycle). Does,
  # in order: ledger update (status + verdict), W&B OUTCOME note (same
  # text), RL_LOG logline (arg 4, or auto-composed
  # "[track] run -> status: text…"). Track STATUS.md / CURRENT_TRUTHS
  # edits stay manual — those are judgment, not bookkeeping.
  run="${2:-}"; st="${3:-}"; text="${4:-}"; line="${5:-}"
  [ -n "$run" ] && [ -n "$st" ] && [ -n "$text" ] || {
    echo "usage: ops.sh verdict <run> <status> \"<verdict>\" [\"logline\"]"
    exit 1
  }
  python3 "$HERE/launch_run.py" update --run "$run" \
    --set "status=$st" --set "verdict=$text" || exit 1
  bash "$0" wandbnote "$run" "$text" \
    || echo "(wandbnote failed — ledger verdict is recorded; continue)"
  if [ -z "$line" ]; then
    tr="$(entry_field "$run" track)"; tr="${tr:-joystick}"
    line="[$tr] $run -> $st: $(printf '%s' "$text" | tr '\n' ' ' | head -c 220)"
  fi
  bash "$0" logline "$line"
  ;;

triage)  # triage — "is anything being lost/ignored?" in one table:
  # every W&B run from the last N hours (default 6) vs ledger verdict,
  # W&B OUTCOME note, and watcher processed-state. Built 08-09 after
  # the operator had to reverse-engineer this twice.
  hrs="${2:-6}"
  python3 - "$hrs" <<'EOF'
import datetime as dt, json, os, sys
import wandb
hrs = float(sys.argv[1])
cut = (dt.datetime.now(dt.timezone.utc)
       - dt.timedelta(hours=hrs)).isoformat()
led = {}
for e in json.load(open(os.environ["LEDGER"])):
    if isinstance(e, dict) and e.get("run"):
        if e.get("status") not in ("REFUSED",):
            led[e["run"]] = e
try:
    proc = set(json.load(open("/workspace/orchestrator_state.json"))
               ["processed"])
except Exception:
    proc = set()
api = wandb.Api()
rows = []
for r in api.runs("l2k2/hexapod-balance",
                  filters={"created_at": {"$gt": cut}}):
    e = led.get(r.name, {})
    rows.append((r.name, r.state,
                 "yes" if e.get("verdict") else "-",
                 "yes" if "OUTCOME" in (r.notes or "") else "-",
                 "yes" if r.name in proc else "-"))
print(f"{'run':30s} {'wandb':9s} {'verdict':7s} {'note':5s} processed")
for row in sorted(rows):
    print(f"{row[0]:30s} {row[1]:9s} {row[2]:7s} {row[3]:5s} {row[4]}")
print("\nfinished + verdict '-' = triage queue; finished + processed '-' "
      "= watcher hasn't seen it end yet. Anything old in either state "
      "is a real leak — say so in RL_LOG.")
EOF
  ;;

drain)  # drain — push backlog onto free pods, DETACHED + creds sourced.
  # launch_run.py drain is slow BY DESIGN (two-phase verify waits out
  # each pod's ~5-8 min JAX/Warp compile) and dies without W&B creds
  # (dedupe check). Both bit the operator on 08-09: run it nohup'd so
  # an interrupted terminal can't kill verifications, with env sourced.
  log=/tmp/drain_$(date +%H%M%S).log
  nohup bash -c '
    set -a
    source "'"$PROTO"'/rl_move/sim/wandb.env" 2>/dev/null
    source /root/orchestrator.env 2>/dev/null
    set +a
    cd "'"$PROTO"'" && python3 rl_move/orchestrator/launch_run.py drain
  ' > "$log" 2>&1 &
  echo "drain running detached (pid $!) -> $log; check: tail $log"
  ;;

killrun)  # killrun <run> — kill a run's training procs on its pod.
  # Pods have no pkill, and a naive /proc scan matches ITSELF (the
  # scanning shell's own cmdline contains the run name — a cycle killed
  # its own kill command this way on 08-09). MUST skip $$.
  # 08-18: match ONLY the "--run-name <run>" token, never a bare
  # substring — respec embeds the PARENT run's name inside --notes
  # ("respec of <parent>: ..."), so a bare-substring killrun against a
  # parent name would also kill every child respec'd from it.
  run="$2"
  pod="$(entry_field "$run" pod)"
  [ -n "$pod" ] || { echo "no pod in ledger for $run"; exit 1; }
  kubectl exec "$pod" -- bash -c '
    for d in /proc/[0-9]*; do
      p=${d#/proc/}; [ "$p" = "$$" ] && continue
      c=$(tr "\0" " " < "$d/cmdline" 2>/dev/null)
      case "$c" in *"--run-name $1 "*|*"--run-name=$1 "*|*"--run-name $1"|*"--run-name=$1") echo "kill $p: ${c:0:80}"; kill "$p";; esac
    done' _ "$run"
  echo "remember: launch_run.py update --run $run --set status=KILLED 'verdict=...'"
  ;;

oplaunch)  # oplaunch <launch_run.py args...> — run a launcher command ON
  # THE CONTROLLER, detached, creds sourced, result polled. The
  # controller's git is the code-sha truth the pods sync from; a laptop
  # clone is usually stale or dirty, so launching from one gets refused
  # (bit the operator's assistant 08-10: a by-hand kubectl-cp + tmux +
  # LAUNCH_HOLD-juggling dance). Works from the operator Mac OR the
  # controller itself. Typical use — continue a finished run during an
  # operator hold (--operator-override is OPERATOR-ONLY):
  #   ops.sh oplaunch respec --from cw-arch-hist16-r7 \
  #     --run cw-arch-hist16-r7-c1 --init-from-source --now \
  #     --operator-override 'operator asked in chat, 08-10' \
  #     --hypothesis '<plain English: what/why/if-true/if-false — this
  #                    LEADS the W&B notes>' --gate '<gate>'
  # Afterwards record it: ops.sh logline (on the controller).
  shift
  ts=$(date +%Y%m%d_%H%M%S); runner=/tmp/oplaunch_$ts.sh; log=/tmp/oplaunch_$ts.log
  {
    echo '#!/usr/bin/env bash'
    echo 'cd /workspace/weird_objects/hexapod_walker/prototype_sts3215 || exit 1'
    echo 'source /root/orchestrator.env 2>/dev/null'
    echo 'set -a; source rl_move/sim/wandb.env 2>/dev/null; set +a'
    # Run the freshest tooling: pull under the same lock snapshot.sh uses.
    echo 'flock /workspace/git_snapshot.lock -c "git -C /workspace/weird_objects pull --rebase --autostash origin main" >/dev/null 2>&1'
    printf 'exec python3 rl_move/orchestrator/launch_run.py'
    printf ' %q' "$@"
    echo
  } > "$runner"
  done_pat='VERIFIED RUNNING|REFUSED|VERIFICATION FAILED|Traceback|snapshot failed|self-repair failed|no free GPU pod|queued '
  if [ -d /workspace/weird_objects ]; then   # already on the controller
    nohup bash "$runner" > "$log" 2>&1 < /dev/null &
    echo "oplaunch running (pid $!) -> $log"
    bash "$0" waitlog "$log" "$done_pat" 1800 || exit 1
    tail -15 "$log"
  else
    CTL=hexapod-sweep-friction
    kubectl cp "$runner" "$CTL:$runner" || exit 1
    kubectl exec "$CTL" -- bash -c "nohup bash '$runner' > '$log' 2>&1 < /dev/null &"
    echo "oplaunch running on $CTL -> $log (launch verification takes minutes)"
    el=0
    until kubectl exec "$CTL" -- grep -qE "$done_pat" "$log" 2>/dev/null; do
      sleep 20; el=$((el+20))
      [ "$el" -ge 1800 ] && { echo "TIMEOUT after ${el}s; tail:"; kubectl exec "$CTL" -- tail -8 "$log"; exit 1; }
    done
    kubectl exec "$CTL" -- tail -15 "$log"
    echo "record it: kubectl exec $CTL -- bash -c 'cd /workspace/weird_objects/hexapod_walker/prototype_sts3215 && ./rl_move/orchestrator/ops.sh logline \"...\"'"
  fi
  ;;

cycle)  # cycle ["focus text"] — OPERATOR: kick one decision session now.
  # Writes orchestrator/KICK (optional focus note inside); the watcher
  # spawns a deep-model session on its next poll (<=5 min), allowed ONE
  # slot past MAX_CONCURRENT_CYCLES (temporary overflow session) and
  # counted in the daily cycle budget. Works from the operator Mac or
  # the controller. The file survives polls until a slot/budget frees.
  shift
  note="${*:-}"
  KICKPATH=/workspace/weird_objects/hexapod_walker/prototype_sts3215/rl_move/orchestrator/KICK
  if [ -d /workspace/weird_objects ]; then      # already on the controller
    printf '%s\n' "$note" > "$KICKPATH"
  else
    CTL=hexapod-sweep-friction
    printf '%s\n' "$note" | kubectl exec -i "$CTL" -- bash -c "cat > '$KICKPATH'" || exit 1
  fi
  echo "KICK written — watcher picks it up within ~2 s"
  echo "watch it live: ops.sh waitcycle operator-kick   (streams the session's narration until it ends)"
  echo "or one-shot:   ops.sh activity | ops.sh cyclelog operator-kick"
  ;;

activity)  # activity — what the orchestrator is doing RIGHT NOW, in one
  # shot: watcher heartbeat, pending kicks, every running cycle WITH
  # the tail of its live narration (cycles stream every thought/tool
  # call as they work — 2026-08-21 observability pass), recently
  # finished cycles, newest ledger rows, watcher log tail. Works from
  # the operator Mac or the controller. Same view as the MCP
  # orchestrator_activity tool — one implementation, two doors.
  [ -d /workspace/weird_objects ] || remote_ops "$@"
  PYTHONPATH="$HERE" python3 -c \
    "import mcp_server; print(mcp_server.t_orchestrator_activity())"
  ;;

cyclelog)  # cyclelog [pattern] [lines] — tail one cycle's live narration
  # log (default: newest cycle, 60 lines). The log STREAMS while the
  # cycle runs and ends with '=== CYCLE END: <how> ==='. pattern is a
  # substring of the log name, e.g. operator-kick or 20260821T032518.
  # Companion files: same name .prompt.md (exact prompt the cycle
  # got) and .jsonl (raw stream-json events).
  [ -d /workspace/weird_objects ] || remote_ops "$@"
  pat="${2:-}"; n="${3:-60}"
  f=$(ls -t /workspace/cycle_logs/cycle_*${pat}*.log 2>/dev/null | head -1)
  [ -n "$f" ] || { echo "no cycle log matching '${pat:-any}'"; exit 1; }
  echo "== $f =="
  tail -n "$n" "$f"
  tail -n 2 "$f" | grep -q '^=== CYCLE END' \
    || echo "== (cycle still running — log is streaming; ops.sh waitcycle '${pat}' follows it live) =="
  ;;

waitcycle)  # waitcycle [pattern] [timeout_s] — FOLLOW a cycle's live
  # narration until it ends (the fix for kick-then-blind-poll loops:
  # `ops.sh cycle "focus"` then `ops.sh waitcycle operator-kick`
  # streams everything the session does and returns when it exits).
  # Picks the newest matching log without an END marker, waiting up
  # to 120 s for one to spawn. Ctrl-C detaches; the cycle keeps
  # running. Works from the operator Mac (kubectl exec streams).
  [ -d /workspace/weird_objects ] || remote_ops "$@"
  pat="${2:-}"; t="${3:-5400}"
  find_active() {
    for f in $(ls -t /workspace/cycle_logs/cycle_*${pat}*.log 2>/dev/null | head -5); do
      tail -n 2 "$f" 2>/dev/null | grep -q '^=== CYCLE END' || { echo "$f"; return 0; }
    done
    return 1
  }
  el=0
  until f=$(find_active); do
    [ "$el" -eq 0 ] && echo "no active cycle matching '${pat:-any}' — waiting for one to spawn (KICK pickup is ~2 s)"
    sleep 5; el=$((el+5))
    [ "$el" -ge 120 ] && { echo "none appeared in 120 s; is a kick filed? (ops.sh activity)"; exit 1; }
  done
  echo "== following $f (Ctrl-C detaches; the cycle keeps running) =="
  off=0; start=$(date +%s)
  while :; do
    size=$(wc -c < "$f" 2>/dev/null || echo 0)
    [ "$size" -gt "$off" ] && { tail -c +"$((off+1))" "$f"; off=$size; }
    tail -n 2 "$f" 2>/dev/null | grep -q '^=== CYCLE END' && { echo "== cycle ended =="; exit 0; }
    [ $(( $(date +%s) - start )) -ge "$t" ] && { echo "TIMEOUT after ${t}s (cycle still running; re-run to keep following)"; exit 1; }
    sleep 5
  done
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
  echo "subcommands: review <run> (START HERE for triage) | report <run|json> |"
  echo "  status | census | triage [hours] | procs <pod> | trainlog <run> [n] |"
  echo "  entry <run> | wandb <run> | pullckpt <run> | pushckpt <pod> <ckpt> |"
  echo "  podeval <run> [sfx] | evalcmd <run> | drain | killrun <run> |"
  echo "  waitlog <file> <regex> [t] |"
  echo "  logline \"line\" | frames <mp4> [n] | expdir <run> | wandbdump <run> |"
  echo "  wandbnote <run> \"paragraph\" | oplaunch <launch_run.py args...> |"
  echo "  cycle [\"focus text\"] (operator: kick a decision session now) |"
  echo "  activity (live watcher+cycle view w/ narration) |"
  echo "  cyclelog [pat] [n] (tail one cycle's live narration) |"
  echo "  waitcycle [pat] [t] (follow a cycle live until it ends)"
  ;;
esac
