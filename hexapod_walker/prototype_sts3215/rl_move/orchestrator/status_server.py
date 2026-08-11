#!/usr/bin/env python3
"""Operator status page for the autonomous RL agent. Stdlib only.

Serves one auto-refreshing HTML page answering "what is the agent doing
RIGHT NOW" without kubectl spelunking: watcher on/paused/off, in-flight
decision cycles (and what they're triaging), per-pod fleet census,
backlog queue, every launched run from the ledger, Claude token usage
(summed from ~/.claude transcripts), and recent watcher log lines.

Run on the controller pod (tmux session `statusweb`):
    python3 rl_move/orchestrator/status_server.py          # port 8090

View from the laptop:
    kubectl --kubeconfig=$HOME/.kube/coreweave.yaml \
        port-forward hexapod-sweep-friction 8090:8090
    open http://127.0.0.1:8090

Port 8090 on purpose: 5183/5173 are BuildViz (AGENTS.md), 8080 is the
robot API. Data collection runs in background threads; page loads are
always instant reads of the latest snapshot.
"""
from __future__ import annotations

import datetime
import glob
import html
import http.server
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
PROTO = HERE.parent.parent
sys.path.insert(0, str(HERE))
from launch_run import KUBECONFIG, load_guardrails, pod_trainers  # noqa: E402

import tracks as _tracks  # noqa: E402  (research-track registry)

PORT = int(os.environ.get("STATUS_PORT", "8090"))
ORCH_LOG = pathlib.Path("/workspace/orchestrator.log")
CYCLE_DIR = pathlib.Path("/workspace/cycle_logs")
CLAUDE_PROJECTS = pathlib.Path("/root/.claude/projects")
FAST_S = 20    # watcher/cycles/backlog/ledger/logs
SLOW_S = 120   # census (12 kubectl execs) + token scan

SNAP: dict = {"fast": {}, "slow": {}}
_token_cache: dict[str, tuple[float, int, dict]] = {}  # path -> (mtime, size, sums)


def read_tail(path: pathlib.Path, lines: int) -> list[str]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200 * lines))
            return f.read().decode(errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def live_cycles() -> list[dict]:
    """Claude cycle subprocesses: what each triages + its live tool call."""
    now = time.time()
    procs: dict[int, tuple[int, bytes, float]] = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            with open(d + "/cmdline", "rb") as fh:
                cmd = fh.read()
            with open(d + "/stat") as fh:
                stat = fh.read()
            mtime = os.stat(d).st_mtime
        except OSError:
            continue
        try:  # stat: "pid (comm) state ppid ..." — comm may contain spaces
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (IndexError, ValueError):
            continue
        procs[int(d.split("/")[-1])] = (ppid, cmd, mtime)

    def activity(cycle_pid: int) -> tuple[str, int] | None:
        """Newest child tool process of a cycle: (command text, age s)."""
        kids = [(c, m) for p, (pp, c, m) in procs.items() if pp == cycle_pid]
        for cmd, mtime in sorted(kids, key=lambda k: -k[1]):
            text = cmd.replace(b"\0", b" ").decode(errors="replace")
            if not text.strip():
                continue  # reaped/zombie child
            text = text.replace("'\"'\"'", "'")
            # claude's bash tool wraps the real command in eval '...'
            m = re.search(r"eval '(.*?)' < /dev/null", text, re.S)
            return " ".join((m.group(1) if m else text).split()), \
                int(now - mtime)
        return None

    def describe(cmd: str, runs: str) -> str:
        """Plain-English guess at what a tool command is doing, and to
        which of the cycle's assigned runs it applies."""
        target = ""
        for r in sorted((x.strip() for x in runs.split(",")),
                        key=len, reverse=True):
            if r and (r in cmd or r.replace("-", "_") in cmd):
                target = r
                break
        on = f" for {target}" if target else ""
        for pat, what in (
            (r"waitlog|until |/tmp/eval_|sleep .*report\.json|tail -f",
             "waiting on eval results"),
            (r"eval_checkpoint|drive_policy|episodes", "running an eval"),
            (r"ffmpeg|contact_sheet|frames|strip|\.png|\.mp4",
             "reviewing eval video/frames"),
            (r"ops\.sh review|report\.json|ops\.sh report",
             "reading eval results"),
            (r"launch_run\.py update", "recording a verdict"),
            (r"wandbnote", "writing the W&B outcome note"),
            (r"logline", "writing the RL_LOG cycle line"),
            (r"SKILLS\.md", "updating the skills table"),
            (r"ops\.sh wandb|wandb", "reading W&B training curves"),
            (r"RL_PLAN|RL_LOG|COMMANDS|WISHLIST|guardrails|runs/",
             "reading plan/docs"),
            (r"git |snapshot\.sh", "committing/syncing git"),
            (r"launch_run\.py|backlog|respec|capacity",
             "checking launcher/capacity (launches are held)"),
        ):
            if re.search(pat, cmd):
                return what + on
        return "running a command" + on

    out = []
    for pid, (ppid, cmd, mtime) in procs.items():
        parts = cmd.split(b"\0")
        if not parts or not parts[0].endswith(b"claude"):
            continue
        prompt = parts[-2].decode(errors="replace") if len(parts) > 1 else ""
        m = re.search(r"Runs that just finished: ([^\n]+)", prompt)
        about = m.group(1) if m else (
            "checkup findings" if "checkup findings" in prompt
            else "idle kick" if "idle kick" in prompt else "?")
        act = activity(pid)
        if act:
            cmdtxt, age = act
            doing = describe(cmdtxt, about)
            cmdline = f"$ {cmdtxt[:160]}  [{age // 60}m{age % 60:02d}s]"
        else:
            doing, cmdline = "thinking / writing its analysis", ""
        out.append({"pid": pid, "age_min": int((now - mtime) / 60),
                    "about": about, "doing": doing, "cmd": cmdline})
    return sorted(out, key=lambda c: -c["age_min"])


def watcher_state() -> dict:
    pause = (HERE / "PAUSE").exists()
    tmux = subprocess.run(["tmux", "has-session", "-t", "orchestrator"],
                          capture_output=True).returncode == 0
    restart = read_tail(pathlib.Path("/workspace/restart_watcher.log"), 1)
    return {"pause": pause, "tmux": tmux,
            "restart_last": restart[0] if pause and restart else ""}


def recent_cycle_logs(n: int = 8) -> list[dict]:
    logs = sorted(CYCLE_DIR.glob("cycle_*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)[:n]
    out = []
    for p in logs:
        st = p.stat()
        out.append({
            "label": p.stem.split("_", 2)[-1],
            "when": datetime.datetime.fromtimestamp(st.st_mtime)
                    .strftime("%H:%M"),
            # claude -p writes output only at exit: empty file = in flight
            "state": "running" if st.st_size == 0 else "done",
            "tail": read_tail(p, 3) if st.st_size else [],
        })
    return out


def ledger_rows(n: int = 40) -> tuple[list[dict], dict, dict]:
    try:
        entries = json.loads((HERE / "experiments.json").read_text())
    except Exception:
        return [], {}, {}
    latest: dict[str, dict] = {}
    for e in entries:
        if isinstance(e, dict) and e.get("run"):
            latest[e["run"]] = e
    counts: dict[str, int] = {}
    for e in latest.values():
        s = e.get("status", "?")
        counts[s] = counts.get(s, 0) + 1
    rows = sorted(latest.values(),
                  key=lambda e: e.get("created", ""), reverse=True)[:n]
    # slim latest-per-run map for the analysis-pipeline computation
    slim = {r: {"status": e.get("status", ""), "triage": e.get("triage", ""),
                "verdict": bool(e.get("verdict")),
                "track": track_of_entry(e)}
            for r, e in latest.items()}
    return rows, counts, slim


def status_docs() -> dict:
    """Campaign STATUS.md + every per-track STATUS.md, for the
    dropdown viewer (operator, 08-11)."""
    docs = {"main": {"name": "Campaign digest (STATUS.md)", "text": ""}}
    try:
        docs["main"]["text"] = (PROTO / "STATUS.md").read_text(
            errors="replace")
    except OSError as e:
        docs["main"]["text"] = f"(unreadable: {e})"
    try:
        for tid, v in _tracks.load().items():
            p = PROTO / v["doc"]
            try:
                text = p.read_text(errors="replace")
            except OSError:
                text = f"({v['doc']} missing)"
            docs[tid] = {"name": f"{tid} — {v['name']}", "text": text}
    except Exception as e:
        docs["tracks_err"] = {"name": "error", "text": repr(e)}
    return docs


def track_of_entry(e: dict) -> str:
    return e.get("track") or _tracks.infer(e.get("run", ""))


def cycle_budget() -> dict:
    """How many decision cycles are left in the rolling-24h budget.

    Mirrors watch_loop.py's enforcement (cycle_times, MAX_CYCLES_PER_DAY)
    but reconstructs the window from cycle-log spawn stamps
    (cycle_YYYYMMDDTHHMMSS_label.log), which survive watcher restarts —
    the watcher's own in-memory list resets to 0 on restart, so this
    count is the conservative truth.
    """
    comp = load_guardrails()["compute"]
    cap = int(comp.get("max_decision_cycles_per_day", 0))
    conc = int(comp.get("max_concurrent_cycles", 0))
    cutoff = datetime.datetime.now() - datetime.timedelta(days=1)
    used = 0
    for p in CYCLE_DIR.glob("cycle_*.log"):
        m = re.match(r"cycle_(\d{8}T\d{6})_", p.name)
        if not m:
            continue  # auto_continue_*.log etc. don't count
        try:
            if datetime.datetime.strptime(
                    m.group(1), "%Y%m%dT%H%M%S") >= cutoff:
                used += 1
        except ValueError:
            continue
    return {"cap": cap, "used_24h": used,
            "left": max(0, cap - used), "concurrent_cap": conc}


def backlog_state() -> dict:
    def load(name):
        try:
            return json.loads((HERE / name).read_text())
        except Exception:
            return []
    return {"queued": load("backlog.json"), "failed": load("backlog_failed.json")}


# List rates, $/MTok (Anthropic pricing page, checked 2026-08-10).
# fable-5: input 10, output 50, cache read 1, cache write 12.50 (5-min
# TTL) / 20 (1-h TTL). sonnet-5 INTRO pricing through 2026-08-31:
# input 2, output 10, cache read 0.20, cache write 2.50 / 4 — standard
# from 2026-09-01 is 3 / 15 / 0.30 / 3.75 / 6, UPDATE THIS TABLE THEN.
# Global inference (no US-only 1.1x).
MODEL_RATES = {
    "sonnet": {"in": 2.0, "out": 10.0, "cr": 0.20, "cw5": 2.5, "cw1h": 4.0},
    "fable": {"in": 10.0, "out": 50.0, "cr": 1.0, "cw5": 12.5, "cw1h": 20.0},
}
RATES = MODEL_RATES["fable"]  # unknown models priced at the ceiling


def rates_for(model: str) -> dict:
    for key, rates in MODEL_RATES.items():
        if key in (model or ""):
            return rates
    return RATES


def est_cost(s: dict) -> float:
    # token_totals() sums a per-message, per-model-priced "usd" field;
    # the flat-rate fallback only covers dicts that predate it.
    if "usd" in s:
        return s["usd"]
    return (s["in"] * RATES["in"] + s["out"] * RATES["out"]
            + s["cr"] * RATES["cr"] + s.get("cw5", 0) * RATES["cw5"]
            + s.get("cw1h", 0) * RATES["cw1h"]) / 1e6


def token_totals() -> dict:
    """Sum usage across all Claude transcripts, cached per finished file."""
    days: dict[str, dict] = {}
    for path in glob.glob(str(CLAUDE_PROJECTS / "*" / "*.jsonl")):
        try:
            st = os.stat(path)
        except OSError:
            continue
        cached = _token_cache.get(path)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            sums = cached[2]
        else:
            sums = {}
            try:
                with open(path, errors="replace") as f:
                    for line in f:
                        if '"usage"' not in line:
                            continue
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        msg = d.get("message") or {}
                        u = msg.get("usage")
                        if not u:
                            continue
                        day = (d.get("timestamp") or "")[:10] or "unknown"
                        s = sums.setdefault(day, {"in": 0, "out": 0, "cw": 0,
                                                  "cr": 0, "cw5": 0,
                                                  "cw1h": 0, "usd": 0.0})
                        s["in"] += u.get("input_tokens", 0)
                        s["out"] += u.get("output_tokens", 0)
                        cw = u.get("cache_creation_input_tokens", 0)
                        s["cw"] += cw
                        s["cr"] += u.get("cache_read_input_tokens", 0)
                        det = u.get("cache_creation") or {}
                        h1 = det.get("ephemeral_1h_input_tokens", 0)
                        # no TTL breakdown -> price it all as 5-min writes
                        cw5 = det.get("ephemeral_5m_input_tokens", cw - h1)
                        s["cw1h"] += h1
                        s["cw5"] += cw5
                        r = rates_for(msg.get("model") or "")
                        s["usd"] += (u.get("input_tokens", 0) * r["in"]
                                     + u.get("output_tokens", 0) * r["out"]
                                     + u.get("cache_read_input_tokens", 0)
                                     * r["cr"]
                                     + cw5 * r["cw5"]
                                     + h1 * r["cw1h"]) / 1e6
            except OSError:
                continue
            _token_cache[path] = (st.st_mtime, st.st_size, sums)
        for day, s in sums.items():
            t = days.setdefault(day, dict.fromkeys(
                ("in", "out", "cw", "cr", "cw5", "cw1h", "usd"), 0))
            for k in t:
                t[k] += s.get(k, 0)
    total = dict.fromkeys(("in", "out", "cw", "cr", "cw5", "cw1h", "usd"), 0)
    for s in days.values():
        for k in total:
            total[k] += s[k]
    today = days.get(datetime.date.today().isoformat(),
                     dict.fromkeys(("in", "out", "cw", "cr", "cw5", "cw1h",
                                    "usd"), 0))
    return {"total": total, "today": today, "n_days": len(days)}


def wandb_done_runs() -> list[dict]:
    """cw- runs W&B says are finished/crashed/failed, with created time
    (ground truth for the analysis pipeline — the ledger `triage` field
    alone misses runs that finish while the watcher is paused, which is
    exactly when the operator is staring at this page)."""
    import wandb

    # timeout: the default client blocks/retries indefinitely on a dead
    # link — a hang here must become an error the page can display, not
    # an eternally-empty snapshot (operator saw exactly that, 08-10 pm).
    api = wandb.Api(timeout=30)
    return [{"run": r.name, "created": str(r.created_at)}
            for r in api.runs(
                "l2k2/hexapod-balance",
                filters={"state": {"$in": ["finished", "crashed", "failed"]}})
            if r.name.startswith("cw-")]


def census() -> list[dict]:
    pods = load_guardrails()["compute"]["gpu_pods"]

    def one(pod):
        try:
            return {"pod": pod, "runs": pod_trainers(pod)}
        except Exception as e:
            return {"pod": pod, "runs": None, "err": str(e)[:80]}
    with ThreadPoolExecutor(max_workers=12) as ex:
        return list(ex.map(one, pods))


def fast_worker() -> None:
    while True:
        try:
            rows, counts, slim = ledger_rows()
            SNAP["fast"] = {
                "latest": slim,
                "at": time.time(),
                "watcher": watcher_state(),
                "cycles": live_cycles(),
                "cycle_logs": recent_cycle_logs(),
                "ledger": rows, "counts": counts,
                "backlog": backlog_state(),
                "cycle_budget": cycle_budget(),
                "orch_tail": read_tail(ORCH_LOG, 14),
                "rl_log_tail": read_tail(PROTO / "RL_LOG.md", 8),
                "rl_plan": (PROTO / "RL_PLAN.md").read_text(errors="replace"),
                "status_docs": status_docs(),
            }
        except Exception as e:
            SNAP["fast_err"] = repr(e)
        time.sleep(FAST_S)


# Each slow component runs on ITS OWN thread and publishes into
# SNAP["slow"] independently. The old single-pass slow_worker set the
# snapshot only after census AND tokens AND wandb all succeeded — one
# hung W&B call (2026-08-10 pm) meant NO costs, an empty fleet table,
# and the error invisible in SNAP["slow_err"]. Now a dead component
# stales/errors alone, keeps its last good data, and the page says so.
SLOW_PARTS = (("census", census), ("tokens", token_totals),
              ("wandb_done", wandb_done_runs))


def part_worker(key: str, fn) -> None:
    s = SNAP["slow"]
    while True:
        try:
            val = fn()
            s[key] = val
            s[key + "_at"] = time.time()
            s.pop(key + "_err", None)
        except Exception as e:
            s[key + "_err"] = repr(e)[:300]
            s[key + "_err_at"] = time.time()
        s["at"] = time.time()
        time.sleep(SLOW_S)


def data_health(f: dict, s: dict) -> list[str]:
    """Operator-facing reasons any page section is empty or stale."""
    now = time.time()
    warns = []
    if SNAP.get("fast_err"):
        warns.append(f"status collector error: {SNAP['fast_err']}")
    if f.get("at") and now - f["at"] > 3 * FAST_S:
        warns.append(f"watcher/ledger data is {int((now - f['at']) / 60)} "
                     "min stale — collector thread wedged?")
    for key, label, impact in (
        ("census", "fleet census (kubectl per pod)",
         "pod training/idle counts and the Fleet table are blank — it "
         "does NOT mean nothing is running"),
        ("tokens", "Claude transcript scan",
         "cost / token cards are hidden"),
        ("wandb_done", "W&B finished-runs query",
         "the analysis pipeline section may miss finished runs"),
    ):
        err, at = s.get(key + "_err"), s.get(key + "_at")
        if err:
            when = datetime.datetime.fromtimestamp(
                s.get(key + "_err_at", now)).strftime("%H:%M")
            last = (" (showing data from "
                    + datetime.datetime.fromtimestamp(at).strftime("%H:%M")
                    + ")") if at else ""
            warns.append(f"{label} FAILING since {when}: {err} — "
                         f"{impact}{last}")
        elif at is None:
            warns.append(f"{label} still collecting its first pass "
                         f"(server just restarted?) — {impact} until it "
                         "lands")
        elif now - at > 3 * SLOW_S:
            warns.append(f"{label} last succeeded "
                         f"{int((now - at) / 60)} min ago — {impact}")
    return warns


# ---------------------------------------------------------------- html
CSS = """
body{background:#0d1117;color:#c9d1d9;font:14px/1.5 -apple-system,Segoe UI,
sans-serif;margin:0;padding:24px;max-width:1100px;margin:auto}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;color:#8b949e;
border-bottom:1px solid #21262d;padding-bottom:4px;margin:28px 0 10px}
.pill{display:inline-block;padding:2px 12px;border-radius:12px;
font-weight:600;font-size:13px}
.on{background:#1a7f37;color:#fff}.paused{background:#9e6a03;color:#fff}
.off{background:#da3633;color:#fff}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{padding:3px 10px 3px 0;text-align:left;vertical-align:top}
th{color:#8b949e;font-weight:600}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.dim{color:#8b949e}.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}
pre{background:#161b22;border:1px solid #21262d;border-radius:6px;
padding:10px;font-size:11.5px;overflow-x:auto;white-space:pre-wrap}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
gap:10px}.card{background:#161b22;border:1px solid #21262d;border-radius:6px;
padding:10px 14px}.card .n{font-size:22px;font-weight:700}
.card .l{color:#8b949e;font-size:12px}
"""


def esc(s) -> str:
    return html.escape(str(s))


def fmt_tok(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    return f"{n / 1e3:.0f}k"


def render() -> str:
    f, s = SNAP.get("fast", {}), SNAP.get("slow", {})
    w = f.get("watcher", {})
    if not w:
        return "<html><body>collecting first snapshot…</body></html>"
    if w["pause"]:
        pill, label = "paused", "PAUSED"
        sub = w.get("restart_last", "")
    elif w["tmux"]:
        pill, label, sub = "on", "ON", ""
    else:
        pill, label, sub = "off", "OFF — watcher tmux session missing!", ""

    cen = s.get("census", [])
    busy = [c for c in cen if c.get("runs")]
    idle = [c for c in cen if c.get("runs") == []]
    unreach = [c for c in cen if c.get("runs") is None]
    tok = s.get("tokens", {})
    counts = f.get("counts", {})
    backlog = f.get("backlog", {"queued": [], "failed": []})

    icon = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' "
            "viewBox='0 0 100 100'><text y='.9em' font-size='90'>"
            "&#128375;&#65039;</text></svg>")
    h = [f"<html><head><meta charset='utf-8'><meta http-equiv='refresh' "
         f"content='30'><title>hexapod RL agent</title>"
         f"<link rel='icon' href=\"{icon}\"><style>{CSS}</style>"
         f"</head><body>"]
    h.append(f"<h1>Hexapod RL agent <span class='pill {pill}'>{label}</span>"
             f"</h1><div class='dim'>refreshed "
             f"{datetime.datetime.now().strftime('%H:%M:%S')} · page "
             f"auto-reloads every 30 s · fleet/token data every "
             f"{SLOW_S} s{(' · ' + esc(sub)) if sub else ''}</div>")

    # Why-is-this-blank box: every silent failure mode gets a sentence.
    for wmsg in data_health(f, s):
        h.append(f"<div class='card' style='border-color:#da3633;"
                 f"margin-top:10px'><span class='bad'>&#9888; "
                 f"{esc(wmsg)}</span></div>")

    # finished on W&B but no verdict in the ledger = not yet analyzed.
    # W&B is the ground truth for "finished"; the triage field only adds
    # the awaiting/in-cycle detail (it's watcher-stamped and misses runs
    # that finish while the watcher is paused).
    final = {"FINISHED", "FAILED", "KILLED", "KILLED_BY_OPERATOR", "REFUSED"}
    latest = f.get("latest", {})
    training_now = {r for c in cen for r in (c.get("runs") or [])}
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=24)).isoformat()
    # Runs claimed by a live decision cycle: their evals are being run /
    # reviewed RIGHT NOW (operator 08-10: "trained but evals pending" is
    # its own lifecycle stage and must not read as finished).
    cyc_runs = {r.strip() for c in f.get("cycles", [])
                for r in (c.get("about") or "").split(",")
                if r.strip() and r.strip() != "?"}
    pipeline = []
    for d in s.get("wandb_done", []):
        run = d["run"]
        if run in training_now:  # stale W&B duplicate of a live run
            continue
        e = latest.get(run)
        if e is None:
            # pre-ledger history (analyzed in archived RL_LOG) — only a
            # RECENT unledgered run is a real pipeline item (and a bug)
            if d.get("created", "") >= cutoff:
                pipeline.append({"run": run, "state": "NOT IN LEDGER (bug?)",
                                 "track": _tracks.infer(run)})
        elif e["status"] not in final and not e["verdict"]:
            if run in cyc_runs:
                state = "EVALUATING (claimed by a live cycle)"
            else:
                state = e["triage"] or "trained — awaiting an agent cycle"
            pipeline.append({"run": run, "state": state,
                             "track": e.get("track") or _tracks.infer(run)})
    pipeline.sort(key=lambda p: p["run"])
    pending = {p["run"]: p["state"] for p in pipeline}
    n_pipe = len(pipeline)
    h.append("<div class='grid' style='margin-top:14px'>")
    pipe_cls = "" if n_pipe <= 3 else " style='border-color:#9e6a03'"
    h.append(f"<div class='card'{pipe_cls}><div class='n'>{n_pipe}</div>"
             f"<div class='l'>trained, evals/verdict pending</div></div>")
    # census never landed -> "?" cards, not a false "0 pods training"
    have_census = "census_at" in s
    cb = f.get("cycle_budget", {})
    conc = cb.get("concurrent_cap", 0)
    for n, l in [
        (len(busy) if have_census else "?", "pods training"),
        (len(idle) if have_census else "?", "pods idle"),
        (f"{len(f.get('cycles', []))}/{conc}" if conc
         else len(f.get("cycles", [])), "LLM cycles in flight (cap)"),
        (len(backlog["queued"]), "queued in backlog"),
        (counts.get("FINISHED", 0), "runs analyzed (verdicted)"),
    ]:
        h.append(f"<div class='card'><div class='n'>{n}</div>"
                 f"<div class='l'>{l}</div></div>")
    if cb.get("cap"):
        # amber when the rolling-24h budget is nearly spent — the watcher
        # idles an hour at a time once it hits the cap
        low = " style='border-color:#9e6a03'" if cb["left"] < 10 else ""
        h.append(f"<div class='card'{low}><div class='n'>{cb['left']}</div>"
                 f"<div class='l'>decision cycles left "
                 f"(rolling 24 h, {cb['used_24h']}/{cb['cap']} used)"
                 f"</div></div>")
    if tok:
        h.append(f"<div class='card'><div class='n'>"
                 f"${est_cost(tok['today']):,.0f}</div>"
                 f"<div class='l'>est. spend today</div></div>")
        h.append(f"<div class='card'><div class='n'>"
                 f"${est_cost(tok['total']):,.0f}</div>"
                 f"<div class='l'>est. spend total</div></div>")
    h.append("</div>")

    # Last 10 launches (operator, 08-11): what the orchestrator fired
    # off, when, and WHY — the hypothesis the launching cycle recorded.
    # REFUSED entries never started a trainer, so they don't count as
    # "fired off"; FAILED ones do (they started, then died/were killed).
    h.append("<h2>Last 10 launches — what the orchestrator fired, and "
             "why</h2>"
             "<div class='dim'>Newest first, from the launch ledger "
             "(experiments.json). “Why” is the hypothesis recorded at "
             "launch time; [parent: …] marks a continuation of that "
             "lineage. Times are UTC.</div>")
    fired = [e for e in f.get("ledger", [])
             if e.get("status") != "REFUSED"][:10]
    if fired:
        h.append("<table><tr><th>launched (UTC)</th><th>run</th>"
                 "<th>track</th><th>phase</th><th>status</th>"
                 "<th>why it was launched</th></tr>")
        for e in fired:
            when = e.get("created") or ""
            try:
                when = datetime.datetime.fromisoformat(when).strftime(
                    "%b %d %H:%M")
            except ValueError:
                pass
            why = (e.get("hypothesis") or "").strip()
            if not why:
                why = ("smoke validation run (no W&B, no hypothesis)"
                       if e.get("smoke") else "(no hypothesis recorded)")
            if e.get("parent"):
                why += f" [parent: {e['parent']}]"
            if len(why) > 320:
                why = why[:320] + "…"
            st = e.get("status", "?")
            cls = {"RUNNING": "ok", "FINISHED": "dim",
                   "FAILED": "bad"}.get(st, "warn")
            h.append(f"<tr><td class='mono dim' style='white-space:nowrap'>"
                     f"{esc(when)}</td>"
                     f"<td class='mono'>{esc(e.get('run'))}</td>"
                     f"<td class='dim'>{esc(track_of_entry(e))}</td>"
                     f"<td class='dim'>{esc(e.get('phase', ''))}</td>"
                     f"<td class='{cls}'>{esc(st)}</td>"
                     f"<td>{esc(why)}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>no launches in the ledger yet</div>")

    # STATUS viewer: campaign digest by default, dropdown for the five
    # per-track STATUS.md files (operator, 08-11). All docs ship in the
    # page (they're small); JS just toggles visibility, and the choice
    # survives the 30 s auto-refresh via localStorage.
    docs = f.get("status_docs", {})
    if docs:
        h.append("<h2>STATUS — campaign &amp; research tracks</h2>")
        h.append("<select id='statussel' onchange='showStatus(this.value)' "
                 "style='background:#161b22;color:#c9d1d9;"
                 "border:1px solid #21262d;border-radius:6px;"
                 "padding:4px 8px;font-size:13px;margin-bottom:8px'>")
        for key, d in docs.items():
            h.append(f"<option value='{esc(key)}'>{esc(d['name'])}</option>")
        h.append("</select>")
        for key, d in docs.items():
            hide = "" if key == "main" else " style='display:none'"
            h.append(f"<div class='statusdoc' id='statusdoc-{esc(key)}'"
                     f"{hide}><pre style='max-height:440px;overflow:auto'>"
                     f"{esc(d['text'])}</pre></div>")
        h.append(
            "<script>function showStatus(v){"
            "document.querySelectorAll('.statusdoc').forEach("
            "e=>e.style.display='none');"
            "var el=document.getElementById('statusdoc-'+v);"
            "if(el){el.style.display='block';}"
            "try{localStorage.setItem('statusdoc',v);}catch(e){}}"
            "try{var sv=localStorage.getItem('statusdoc');"
            "if(sv&&document.getElementById('statusdoc-'+sv)){"
            "document.getElementById('statussel').value=sv;showStatus(sv);}}"
            "catch(e){}</script>")

    h.append("<h2>Analysis pipeline (training done, evals/verdict pending "
             "— not finished yet)</h2>"
             "<div class='dim'>A run is only “finished” once an agent "
             "cycle has run the full eval harness (det + stochastic "
             "passes, videos) and written a verdict. These runs are past "
             "training but still in that stage.</div>")
    if pipeline:
        h.append("<table><tr><th>run</th><th>track</th><th>state</th></tr>")
        for p in pipeline:
            cls = ("ok" if p["state"].startswith(("in-cycle", "EVALUATING"))
                   else "warn")
            h.append(f"<tr class='mono'><td>{esc(p['run'])}</td>"
                     f"<td class='dim'>{esc(p.get('track', ''))}</td>"
                     f"<td class='{cls}'>{esc(p['state'])}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>empty — every finished run has a "
                 "verdict</div>")

    h.append("<h2>What it's thinking about (in-flight decision cycles)</h2>")
    h.append("<div class='dim'>Each row is one live AI analysis session "
             "(a “cycle”). It is assigned a few finished training runs, "
             "reviews each one's eval numbers and videos, and writes a "
             "pass/fail verdict to the ledger. “Doing now” is its current "
             "step; the grey line is the actual command running.</div>")
    if f.get("cycles"):
        h.append("<table><tr><th>pid</th><th>age</th>"
                 "<th>runs it's analyzing</th><th>doing now</th></tr>")
        for c in f["cycles"]:
            cmd = (f"<br><span class='dim mono'>{esc(c['cmd'])}</span>"
                   if c.get("cmd") else "")
            h.append(f"<tr><td class='mono'>{c['pid']}</td>"
                     f"<td>{c['age_min']} min</td>"
                     f"<td class='mono'>{esc(c['about'])}</td>"
                     f"<td><b>{esc(c.get('doing', ''))}</b>{cmd}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>none — watcher is between cycles</div>")

    h.append("<h2>Recent cycles</h2><table><tr><th>time</th><th>state</th>"
             "<th>runs</th><th>last output</th></tr>")
    for c in f.get("cycle_logs", []):
        cls = "warn" if c["state"] == "running" else "ok"
        tail = esc(" / ".join(t.strip() for t in c["tail"] if t.strip())[-160:])
        h.append(f"<tr><td>{c['when']}</td><td class='{cls}'>{c['state']}"
                 f"</td><td class='mono'>{esc(c['label'][:70])}</td>"
                 f"<td class='dim'>{tail}</td></tr>")
    h.append("</table>")

    h.append("<h2>Fleet</h2>")
    if not cen:
        h.append("<div class='warn'>no census data — see the warning box "
                 "at the top; this does NOT mean the pods are idle</div>")
    h.append("<table>")
    for c in cen:
        if c.get("runs"):
            h.append(f"<tr class='mono'><td>{c['pod']}</td>"
                     f"<td class='ok'>{esc(', '.join(c['runs']))}</td></tr>")
        elif c.get("runs") == []:
            h.append(f"<tr class='mono'><td>{c['pod']}</td>"
                     f"<td class='warn'>idle</td></tr>")
        else:
            h.append(f"<tr class='mono'><td>{c['pod']}</td>"
                     f"<td class='bad'>unreachable: {esc(c.get('err'))}</td></tr>")
    h.append("</table>")
    if unreach:
        h.append(f"<div class='bad'>{len(unreach)} pod(s) unreachable</div>")

    h.append("<h2>Backlog queue</h2>")
    if backlog["queued"]:
        h.append("<table><tr><th>run</th><th>track</th><th>steps</th>"
                 "<th>attempts</th></tr>")
        for it in backlog["queued"]:
            h.append(f"<tr class='mono'><td>{esc(it.get('run'))}</td>"
                     f"<td class='dim'>{esc(track_of_entry(it))}</td>"
                     f"<td>{it.get('steps')}</td>"
                     f"<td>{it.get('attempts', 0)}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>empty — free slots get refilled by the "
                 "next triage cycle</div>")
    if backlog["failed"]:
        h.append(f"<div class='bad'>{len(backlog['failed'])} parked in "
                 f"backlog_failed.json: "
                 f"{esc(', '.join(i.get('run', '?') for i in backlog['failed'][-5:]))}"
                 f"</div>")

    if tok:
        t, td = tok["total"], tok["today"]
        h.append("<h2>Claude token usage + est. spend (all decision cycles)"
                 "</h2><table><tr><th></th><th>output</th><th>input</th>"
                 "<th>cache write</th><th>cache read</th>"
                 "<th>est. cost</th></tr>"
                 f"<tr><td>today</td><td>{fmt_tok(td['out'])}</td>"
                 f"<td>{fmt_tok(td['in'])}</td><td>{fmt_tok(td['cw'])}</td>"
                 f"<td>{fmt_tok(td['cr'])}</td>"
                 f"<td>${est_cost(td):,.2f}</td></tr>"
                 f"<tr><td>total ({tok['n_days']} days)</td>"
                 f"<td>{fmt_tok(t['out'])}</td><td>{fmt_tok(t['in'])}</td>"
                 f"<td>{fmt_tok(t['cw'])}</td><td>{fmt_tok(t['cr'])}</td>"
                 f"<td>${est_cost(t):,.2f}</td></tr></table>"
                 "<div class='dim'>priced per message at each model's list "
                 "rate — fable-5: $10/M in, $50/M out, $1/M cache read, "
                 "$12.50/$20/M cache write (5m/1h TTL); sonnet-5 (intro thru "
                 "08-31): $2/M in, $10/M out, $0.20/M cache read, $2.50/$4/M "
                 "cache write. Checked 2026-08-10.</div>")

    # Research tracks (operator, 08-11): every run belongs to a track
    # (tracks.json); show it and a per-track tally so each line of
    # research reads separately.
    tcounts: dict[str, int] = {}
    for e in f.get("ledger", []):
        t = track_of_entry(e)
        tcounts[t] = tcounts.get(t, 0) + 1
    h.append("<h2>Runs (latest ledger entry per run)</h2>")
    if tcounts:
        h.append("<p class='dim'>by track: " + " · ".join(
            f"{esc(t)} {n}" for t, n in sorted(tcounts.items(),
                                               key=lambda kv: -kv[1]))
                 + " — track goals in rl_docs/tracks/</p>")
    h.append("<table><tr><th>run</th><th>track</th><th>status</th>"
             "<th>pod</th><th>created</th></tr>")
    for e in f.get("ledger", []):
        st = e.get("status", "?")
        cls = {"RUNNING": "ok", "FINISHED": "dim",
               "FAILED": "bad"}.get(st, "warn")
        # Training done but unverdicted: the raw ledger status (often a
        # stale RUNNING) misreads as either live or finished — show the
        # eval-stage state instead.
        if e.get("run") in pending:
            st = ("EVALUATING" if e["run"] in cyc_runs
                  else "TRAINED, EVAL PENDING")
            cls = "warn"
        h.append(f"<tr class='mono'><td>{esc(e.get('run'))}</td>"
                 f"<td class='dim'>{esc(track_of_entry(e))}</td>"
                 f"<td class='{cls}'>{esc(st)}</td>"
                 f"<td>{esc(e.get('pod', ''))}</td>"
                 f"<td class='dim'>{esc((e.get('created') or '')[5:16])}</td></tr>")
    h.append("</table>")

    h.append("<h2>RL_PLAN.md (what the CW agents are working from)</h2>"
             "<details open><summary class='dim'>collapse/expand</summary>"
             "<pre>" + esc(f.get("rl_plan", "")) + "</pre></details>")
    h.append("<h2>Watcher log (tail)</h2><pre>"
             + esc("\n".join(f.get("orch_tail", []))) + "</pre>")
    h.append("<h2>RL_LOG.md (tail)</h2><pre>"
             + esc("\n".join(f.get("rl_log_tail", []))) + "</pre>")
    h.append("</body></html>")
    return "".join(h)


# Optional access token (STATUS_TOKEN env): needed once the page is on a
# public LoadBalancer IP (operator 08-10) — it shows spend and infra.
# First visit with ?key=<token> sets a cookie and redirects clean;
# afterwards the cookie carries auth. Unset token = open (local
# port-forward use unchanged).
def _load_token() -> str:
    t = os.environ.get("STATUS_TOKEN", "")
    if t:
        return t
    # Fallback so a bare restart on the controller can't silently
    # expose the page: the token file is written at deploy time.
    try:
        return pathlib.Path("/workspace/.status_token").read_text().strip()
    except OSError:
        return ""


TOKEN = _load_token()


class Handler(http.server.BaseHTTPRequestHandler):
    def _authed(self) -> bool:
        if not TOKEN:
            return True
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        if q.get("key", [""])[0] == TOKEN:
            return True
        cookies = self.headers.get("Cookie", "")
        return any(c.strip() == f"status_token={TOKEN}"
                   for c in cookies.split(";"))

    def do_GET(self):  # noqa: N802
        if not self._authed():
            body = b"403: append ?key=<token> to the URL"
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        if TOKEN and parse_qs(u.query).get("key", [""])[0] == TOKEN:
            # set the cookie, drop the key from the URL
            self.send_response(302)
            self.send_header("Set-Cookie",
                             f"status_token={TOKEN}; Path=/; Max-Age=31536000")
            self.send_header("Location", u.path or "/")
            self.end_headers()
            return
        if self.path.startswith("/json"):
            body = json.dumps(SNAP, default=str).encode()
            ctype = "application/json"
        else:
            body = render().encode()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quiet
        pass


def main() -> int:
    threading.Thread(target=fast_worker, daemon=True).start()
    for key, fn in SLOW_PARTS:
        threading.Thread(target=part_worker, args=(key, fn),
                         daemon=True).start()
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"status page on :{PORT}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
