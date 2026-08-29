#!/usr/bin/env python3
"""Operator status page for the autonomous RL agent. Stdlib only.

Serves one auto-refreshing HTML page answering "what is the agent doing
RIGHT NOW" without kubectl spelunking: watcher on/paused/off, in-flight
decision cycles with their LIVE streamed narration, pending kicks,
per-pod fleet census, backlog queue, every launched run from the
ledger, Claude token usage (summed from ~/.claude transcripts), and
recent watcher log lines. Drill-downs (token-gated like the dashboard):
/cycle/<stamp> = one cycle's full narration + exact prompt + raw event
stream (auto-refreshes while the cycle runs); /run/<name> = a run's
complete ledger history, the cycles that worked on it, its story doc.

Run on the controller pod (tmux session `statusweb`):
    uv run python rl_move/orchestrator/status_server.py          # port 8090

View from the laptop:
    kubectl --kubeconfig=$HOME/.kube/coreweave.yaml \
        port-forward hexapod-sweep-friction 8090:8090
    open http://127.0.0.1:8090

LLM-readable mirror (for GPT/Claude web fetchers assessing the
campaign): /llms.txt is the index, /llm/{status,plan,log,runs,docs}.md
are plain markdown, /llm/doc/<path> serves any .md in the prototype
tree. Those paths need NO token: they mirror a public GitHub repo, and
GPT's URL-safety wrapper refuses keyed URLs. The dashboard and /json
(spend, infra) stay token-gated. /mcp is the same data as MCP tools
(mcp_server.py, streamable HTTP) — gated by the operator's MCP key
(MCP_AUTH_KEY / /workspace/.mcp_key, separate from STATUS_TOKEN;
operator 08-15). On the controller, a background
thread keeps the checkout synced to origin/main so pushed doc changes
go live within ~1 min.

Port 8090 on purpose: 5183/5173 are BuildViz (AGENTS.md), 8080 is the
robot API. Data collection runs in background threads; page loads are
always instant reads of the latest snapshot.
"""
from __future__ import annotations

import datetime
import glob
import hmac
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

import mcp_server as _mcp  # noqa: E402  (MCP endpoint at /mcp)
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


def _cycle_registry_entries() -> list[dict]:
    """watch_loop's cycle registry (cycles.json): one dict per spawned
    cycle with label/model/pid/log paths/status; [] when absent."""
    try:
        entries = json.loads((CYCLE_DIR / "cycles.json").read_text())
        return [e for e in entries if isinstance(e, dict)]
    except Exception:
        return []


def _registry_by_log() -> dict[str, dict]:
    return {pathlib.Path(e.get("log", "")).name: e
            for e in _cycle_registry_entries() if e.get("log")}


def recent_cycle_logs(n: int = 10) -> list[dict]:
    logs = sorted(CYCLE_DIR.glob("cycle_*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)[:n]
    reg = _registry_by_log()
    out = []
    for p in logs:
        st = p.stat()
        tail = [t for t in read_tail(p, 6) if t.strip()]
        # Since 08-21 cycles STREAM their narration into the log as
        # they work; the renderer's last line "=== CYCLE END: <how>"
        # is the done marker (registry status is the second witness).
        # Legacy pre-streaming logs wrote only at exit: content but
        # no marker and no registry row = done.
        e = reg.get(p.name, {})
        rstat = e.get("status", "")
        try:
            with p.open("rb") as fh:
                streaming_fmt = b"=== CYCLE START" in fh.read(400)
        except OSError:
            streaming_fmt = False
        if (tail and tail[-1].startswith("=== CYCLE END")) \
                or rstat in ("done", "failed", "timeout"):
            state = rstat if rstat in ("failed", "timeout") else "done"
        elif rstat == "running" or streaming_fmt or st.st_size == 0:
            state = "running"
        else:
            state = "done"
        parts = p.stem.split("_", 2)
        out.append({
            "stamp": parts[1] if len(parts) > 2 else p.stem,
            "label": parts[-1],
            "when": datetime.datetime.fromtimestamp(st.st_mtime)
                    .strftime("%H:%M"),
            "state": state,
            "model": (e.get("model") or "").replace("claude-", ""),
            "dur_s": e.get("duration_s"),
            "trigger": e.get("trigger", ""),
            "started": e.get("started", ""),
            "pid": e.get("pid"),
            "tail": tail[-3:],
            # bigger live window for the dashboard's in-flight section
            "live_tail": [t for t in read_tail(p, 12) if t.strip()]
                         if state == "running" else [],
        })
    return out


# Pending kick files: the operator KICK focus note (HERE/KICK, consumed
# by the watcher within ~2 s of its next wake) and the advisory MCP
# kick queue. Mirrors watch_loop.KICK / mcp_server.KICK_DIR.
KICK_FILE = HERE / "KICK"
MCP_KICK_DIR = pathlib.Path(
    os.environ.get("MCP_KICK_DIR")
    or ("/workspace/llm_kicks" if pathlib.Path("/workspace").is_dir()
        else PROTO / "logs" / "llm_kicks"))


def pending_kicks() -> dict:
    out = {"operator": "", "advisory": []}
    try:
        if KICK_FILE.exists():
            out["operator"] = KICK_FILE.read_text(errors="replace")[:800]
    except OSError:
        pass
    try:
        out["advisory"] = sorted(
            p.name for p in MCP_KICK_DIR.glob("kick_*.json"))
    except OSError:
        pass
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
    # Track dirs tracks.json doesn't know yet: a new track's docs often
    # land before its registration (operator 08-12, dynrep) — show them
    # anyway rather than silently hiding a whole line of research.
    try:
        for p in sorted((PROTO / "rl_docs" / "tracks").glob("*/STATUS.md")):
            tid = p.parent.name
            if tid not in docs:
                docs[tid] = {"name": f"{tid} — (unregistered track)",
                             "text": p.read_text(errors="replace")}
    except OSError:
        pass
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
                "kicks": pending_kicks(),
                "feedback": _mcp._feedback_entries()[:15],
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
    if SNAP.get("git_sync_err"):
        warns.append(f"git doc sync failing: {SNAP['git_sync_err']} — "
                     "the LLM mirror may serve stale docs")
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
.cpy{background:#21262d;color:#c9d1d9;border:1px solid #30363d;
border-radius:6px;padding:2px 10px;font-size:12px;cursor:pointer}
.cpy:hover{background:#30363d}
a{color:#58a6ff;text-decoration:none}a:hover{text-decoration:underline}
.tailpre{max-height:230px;overflow:auto;margin:4px 0 14px}
.cychead{margin:14px 0 2px;font-size:13.5px}
"""


def run_link(name) -> str:
    """Run name -> drill-down link (ledger history, story, cycles)."""
    return f"<a href='/run/{esc(name)}'>{esc(name)}</a>"


def esc(s) -> str:
    return html.escape(str(s))


def fmt_tok(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    return f"{n / 1e3:.0f}k"


def llm_url_groups(base: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Labeled URL bundle for the dashboard's copy-paste section (the
    curated list the operator hands to GPT/Claude, 08-14)."""
    def docs(entries):
        return [(label, f"{base}/llm/doc/{rel}")
                for label, rel in entries if (PROTO / rel).is_file()]
    groups = [
        ("Start here (live index pages)", [
            ("LLM index — hand an agent THIS one", f"{base}/llms.txt"),
            ("MCP endpoint (streamable HTTP — add as a remote MCP "
             "server WITH the operator MCP key; tools for "
             "ledger/metrics/docs)", f"{base}/mcp"),
            ("Campaign + all per-track STATUS", f"{base}/llm/status.md"),
            ("Research plan (RL_PLAN.md)", f"{base}/llm/plan.md"),
            ("Cycle log (RL_LOG.md)", f"{base}/llm/log.md"),
            ("Run ledger — hypotheses & verdicts", f"{base}/llm/runs.md"),
            ("Index of every doc below + more", f"{base}/llm/docs.md"),
        ]),
        ("Core campaign docs", docs([
            ("Campaign digest", "STATUS.md"),
            ("Current truths", "CURRENT_TRUTHS.md"),
            ("Goals", "RL_GOALS.md"),
            ("Research rules", "RESEARCH_RULES.md"),
            ("Run interpretation rules", "RUN_INTERPRETATION_RULES.md"),
        ]) + [(f"Review bundle {p.stem.split('_')[-1]}",
               f"{base}/llm/doc/{p.name}")
              for p in sorted(PROTO.glob("RL_REVIEW_BUNDLE_*.md"))]),
        ("Per-track STATUS", [
            (p.parent.name, f"{base}/llm/doc/rl_docs/tracks/"
                            f"{p.parent.name}/STATUS.md")
            for p in sorted((PROTO / "rl_docs" / "tracks")
                            .glob("*/STATUS.md"))]),
        ("Deep-dive research docs", docs([
            ("AMP locomotion charter", "rl_docs/AMP_LOCOMOTION.md"),
            ("Download answer", "rl_docs/DOWNLOAD_ANSWER.md"),
            ("Skills table", "rl_docs/SKILLS.md"),
            ("Reward design", "rl_docs/REWARD.md"),
            ("Gait", "rl_docs/GAIT.md"),
            ("Sim", "rl_docs/SIM.md"),
            ("Evals", "rl_docs/EVALS.md"),
            ("Hardware", "rl_docs/HARDWARE.md"),
            ("W&B usage", "rl_docs/WANDB.md"),
        ])),
        ("Hardware / build / infra", docs([
            ("Prototype build story", "PROTOTYPE.md"),
            ("BOM", "docs/BOM.md"),
            ("Wiring", "firmware/WIRING.md"),
            ("Robot HTTP API", "rl_move/API.md"),
            ("Orchestrator architecture", "rl_move/orchestrator/README.md"),
            ("Orchestrator prompt", "rl_move/orchestrator/ORCHESTRATOR_PROMPT.md"),
            ("Sysid", "sysid/README.md"),
        ])),
    ]
    return [(g, items) for g, items in groups if items]


def render(base: str = "") -> str:
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
    kicks = f.get("kicks", {"operator": "", "advisory": []})
    n_kicks = ((1 if kicks.get("operator") else 0)
               + len(kicks.get("advisory", [])))
    if n_kicks:
        h.append(f"<div class='card' style='border-color:#9e6a03'>"
                 f"<div class='n'>{n_kicks}</div>"
                 f"<div class='l'>kick(s) filed, waiting for a cycle"
                 f"</div></div>")
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
                     f"<td class='mono'>{run_link(e.get('run'))}</td>"
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
            h.append(f"<tr class='mono'><td>{run_link(p['run'])}</td>"
                     f"<td class='dim'>{esc(p.get('track', ''))}</td>"
                     f"<td class='{cls}'>{esc(p['state'])}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>empty — every finished run has a "
                 "verdict</div>")

    h.append("<h2>What it's thinking about (in-flight decision cycles, "
             "live)</h2>")
    h.append("<div class='dim'>Each block is one live AI session (a "
             "“cycle”) streaming its narration — every thought and tool "
             "call — as it works. The excerpt below is its newest output; "
             "click the cycle name for the full log, its exact prompt, "
             "and the raw event stream.</div>")
    if n_kicks:
        h.append("<div class='card' style='border-color:#9e6a03;"
                 "margin-top:8px'><b class='warn'>kick(s) waiting for a "
                 "cycle:</b>")
        if kicks.get("operator"):
            h.append(f"<pre style='margin:6px 0 0'>operator KICK:\n"
                     f"{esc(kicks['operator'])}</pre>")
        if kicks.get("advisory"):
            h.append(f"<div class='dim mono'>advisory queue: "
                     f"{esc(', '.join(kicks['advisory'][:8]))}</div>")
        h.append("</div>")
    running_rows = [c for c in f.get("cycle_logs", [])
                    if c["state"] == "running"]
    proc_by_pid = {c["pid"]: c for c in f.get("cycles", [])}
    now_dt = datetime.datetime.now()
    for c in running_rows:
        age = ""
        try:
            mins = int((now_dt - datetime.datetime.fromisoformat(
                c.get("started", ""))).total_seconds() // 60)
            age = f" · running {mins} min"
        except ValueError:
            pass
        pr = proc_by_pid.get(c.get("pid"), {})
        doing = (f" · <b>{esc(pr['doing'])}</b>"
                 if pr.get("doing") else "")
        h.append(f"<div class='cychead mono'>"
                 f"<a href='/cycle/{esc(c['stamp'])}'>{esc(c['label'])}"
                 f"</a> <span class='dim'>· {esc(c.get('model') or '?')}"
                 f"{age}</span>{doing}</div>")
        if c.get("trigger"):
            h.append(f"<div class='dim' style='font-size:12px'>trigger: "
                     f"{esc(c['trigger'][:200])}</div>")
        h.append(f"<pre class='tailpre'>"
                 f"{esc(chr(10).join(c.get('live_tail', [])))}</pre>")
    # cycle processes with no registry row (pre-registry watcher, or a
    # cycle spawned outside the watcher): keep the old /proc-scan view.
    reg_pids = {c.get("pid") for c in running_rows}
    extra = [c for c in f.get("cycles", []) if c["pid"] not in reg_pids]
    if extra:
        h.append("<table><tr><th>pid</th><th>age</th>"
                 "<th>runs it's analyzing</th><th>doing now</th></tr>")
        for c in extra:
            cmd = (f"<br><span class='dim mono'>{esc(c['cmd'])}</span>"
                   if c.get("cmd") else "")
            h.append(f"<tr><td class='mono'>{c['pid']}</td>"
                     f"<td>{c['age_min']} min</td>"
                     f"<td class='mono'>{esc(c['about'])}</td>"
                     f"<td><b>{esc(c.get('doing', ''))}</b>{cmd}</td></tr>")
        h.append("</table>")
    if not running_rows and not extra:
        h.append("<div class='dim'>none — watcher is between cycles</div>")

    h.append("<h2>Recent cycles</h2>")
    h.append("<div class='dim'>Cycles stream their narration live "
             "(every thought/tool call); a running row's “last output” "
             "is what it is doing right now. Click a cycle for its full "
             "narration, prompt, and raw event stream (also: "
             "<span class='mono'>ops.sh cyclelog</span> / the MCP "
             "<span class='mono'>cycle_log</span> tool).</div>")
    h.append("<table><tr><th>time</th><th>state</th><th>model</th>"
             "<th>took</th><th>cycle</th><th>last output</th></tr>")
    for c in f.get("cycle_logs", []):
        cls = ("warn" if c["state"] == "running"
               else "bad" if c["state"] in ("failed", "timeout") else "ok")
        tail = esc(" / ".join(t.strip() for t in c["tail"] if t.strip())[-160:])
        dur = (f"{int(c['dur_s']) // 60}m" if c.get("dur_s")
               else "…" if c["state"] == "running" else "")
        h.append(f"<tr><td>{c['when']}</td><td class='{cls}'>{c['state']}"
                 f"</td><td class='dim'>{esc(c.get('model') or '')}</td>"
                 f"<td class='dim'>{dur}</td>"
                 f"<td class='mono'><a href='/cycle/{esc(c['stamp'])}'>"
                 f"{esc(c['label'][:70])}</a></td>"
                 f"<td class='dim'>{tail}</td></tr>")
    h.append("</table>")

    # Feedback filed via the keyed /mcp submit_feedback tool (operator
    # 08-14; key-gated 08-15 so entries come from the operator's own
    # clients). The watcher injects unseen entries into the next
    # decision cycle ("agent" column shows NEW vs when a cycle saw it).
    fb = f.get("feedback", [])
    h.append("<h2>LLM feedback inbox (/mcp submit_feedback, "
             "operator-keyed — injected into the next cycle)</h2>")
    if fb:
        h.append("<table><tr><th>when (UTC)</th><th>author</th>"
                 "<th>topic</th><th>agent</th><th>feedback</th></tr>")
        for e in fb:
            seen = e.get("injected_utc", "")
            agent = (f"<span class='dim'>seen {esc(seen[9:11])}:"
                     f"{esc(seen[11:13])}</span>" if len(seen) >= 13
                     else "<span class='warn'>NEW</span>")
            h.append(f"<tr><td class='mono dim' style='white-space:"
                     f"nowrap'>{esc(e.get('utc', '?'))}</td>"
                     f"<td class='dim'>{esc(e.get('author', ''))}</td>"
                     f"<td>{esc(e.get('topic', ''))}</td>"
                     f"<td>{agent}</td>"
                     f"<td><details><summary>"
                     f"{esc(e.get('feedback', '')[:120])}&#8230;</summary>"
                     f"<pre>{esc(e.get('feedback', ''))}</pre>"
                     f"</details></td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>empty — external LLMs can file notes "
                 "via the MCP endpoint's submit_feedback tool</div>")

    h.append("<h2>Fleet</h2>")
    if not cen:
        h.append("<div class='warn'>no census data — see the warning box "
                 "at the top; this does NOT mean the pods are idle</div>")
    h.append("<table>")
    for c in cen:
        if c.get("runs"):
            h.append(f"<tr class='mono'><td>{c['pod']}</td>"
                     f"<td class='ok'>"
                     f"{', '.join(run_link(r) for r in c['runs'])}</td></tr>")
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
        h.append(f"<tr class='mono'><td>{run_link(e.get('run'))}</td>"
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

    # LLM URL bundle (operator 08-14): the labeled links handed to
    # GPT/Claude, each with a copy button, so the operator never has to
    # remember or re-derive them. Keyless by design (see llm_body).
    if base:
        groups = llm_url_groups(base)
        all_txt = "\n".join(f"{label}: {url}"
                            for _, items in groups for label, url in items)
        h.append("<h2>LLM-readable URLs (give these to GPT/Claude)</h2>"
                 "<div class='dim'>Plain-text mirrors of everything above "
                 "— no login, no key, crawlable. Hand an agent the LLM "
                 "index and it can find the rest itself. "
                 "<button class='cpy' onclick='cpy(ALLURLS,this)'>copy "
                 "all</button></div>")
        for gname, items in groups:
            h.append(f"<h2 style='font-size:13px;border:none;margin:16px 0 "
                     f"4px'>{esc(gname)}</h2><table>")
            for label, url in items:
                h.append(f"<tr><td class='dim' style='white-space:nowrap'>"
                         f"{esc(label)}</td>"
                         f"<td class='mono'><a href='{esc(url)}' "
                         f"style='color:#58a6ff'>{esc(url)}</a></td>"
                         f"<td><button class='cpy' data-u='{esc(url)}' "
                         f"onclick='cpy(this.dataset.u,this)'>copy"
                         f"</button></td></tr>")
            h.append("</table>")
        h.append(
            "<script>var ALLURLS=" + json.dumps(all_txt) + ";"
            "function cpy(t,b){navigator.clipboard.writeText(t).then("
            "function(){var o=b.textContent;b.textContent='copied \u2713';"
            "setTimeout(function(){b.textContent=o},1200)},"
            "function(){b.textContent='copy failed'})}</script>")

    h.append("</body></html>")
    return "".join(h)


# ---------------------------------------------------- drill-down pages
# /cycle/<stamp-or-label> — one cycle's full streamed narration, exact
# prompt, and raw event stream. /run/<name> — a run's complete ledger
# history, related cycles, and its story doc. Both are token-gated like
# the dashboard (operator 08-22: "more visibility + dig in").
_SAFE_PART = re.compile(r"^[A-Za-z0-9._-]{2,120}$")


def _page(title: str, body: list[str], refresh: int = 0,
          scroll_end: bool = False) -> str:
    meta = (f"<meta http-equiv='refresh' content='{refresh}'>"
            if refresh else "")
    tail = ("<script>window.scrollTo(0,document.body.scrollHeight);"
            "</script>" if scroll_end else "")
    return (f"<html><head><meta charset='utf-8'>{meta}"
            f"<title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body><div class='dim' style='margin-bottom:8px'>"
            f"<a href='/'>&larr; dashboard</a></div>"
            + "".join(body) + f"{tail}</body></html>")


def _file_text(fp: pathlib.Path, cap: int | None) -> tuple[str, str]:
    """(text, note). Reads the whole file, or the newest `cap` bytes
    with a truncation note — narration logs are append-only so the
    tail is the interesting end."""
    try:
        size = fp.stat().st_size
    except OSError:
        return "", f"({fp.name} not found)"
    if cap is None or size <= cap:
        return fp.read_text(errors="replace"), ""
    with fp.open("rb") as fh:
        fh.seek(size - cap)
        text = fh.read().decode(errors="replace")
    text = text.split("\n", 1)[-1]
    return text, (f"(showing the newest {cap // 1000} kB of "
                  f"{size // 1000} kB — append ?full=1 for everything)")


def render_cycle_page(needle: str, part: str = "log",
                      full: bool = False) -> str | None:
    if not _SAFE_PART.match(needle):
        return None
    logs = sorted(CYCLE_DIR.glob("cycle_*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    p = next((x for x in logs if needle in x.name), None)
    if p is None:
        return None
    e = _registry_by_log().get(p.name, {})
    status = e.get("status", "")
    if not status:
        t = [x for x in read_tail(p, 4) if x.strip()]
        status = ("done" if any(x.startswith("=== CYCLE END") for x in t)
                  else "?")
    running = status == "running"
    parts = p.stem.split("_", 2)
    stamp, label = (parts[1], parts[2]) if len(parts) > 2 \
        else (p.stem, p.stem)
    prompt_p = p.with_name(p.stem + ".prompt.md")
    raw_p = p.with_name(p.stem + ".jsonl")

    if part == "prompt":
        fp, cap = prompt_p, 300_000
    elif part == "raw":
        fp, cap = raw_p, (None if full else 300_000)
    else:
        part, fp, cap = "log", p, (None if full else 400_000)
    text, note = _file_text(fp, cap)

    cls = ("warn" if running
           else "bad" if status in ("failed", "timeout") else "ok")
    dur = e.get("duration_s")
    took = f"{int(dur) // 60}m{int(dur) % 60:02d}s" if dur else ""
    rc = e.get("rc")
    body = [f"<h1 class='mono' style='font-size:17px'>cycle {esc(label)} "
            f"<span class='{cls}'>[{esc(status)}"
            f"{'' if rc in (None, 0) else f' rc={rc}'}]</span></h1>"]
    meta_bits = [b for b in (
        e.get("model", ""), f"started {e.get('started', '?')}",
        f"took {took}" if took else "", f"pid {e.get('pid')}"
        if running and e.get("pid") else "") if b]
    body.append(f"<div class='dim'>{esc(' · '.join(meta_bits))}</div>")
    if e.get("runs"):
        body.append("<div class='dim'>runs: "
                    + ", ".join(run_link(r) for r in e["runs"]) + "</div>")
    if e.get("trigger"):
        body.append(f"<div class='dim'>trigger: "
                    f"{esc(e['trigger'][:300])}</div>")
    nav = []
    for pid, plabel in (("log", "narration"), ("prompt", "exact prompt"),
                        ("raw", "raw events")):
        cur = " style='font-weight:700;color:#c9d1d9'" if pid == part else ""
        nav.append(f"<a href='/cycle/{esc(stamp)}?part={pid}'{cur}>"
                   f"{plabel}</a>")
    body.append("<div style='margin:8px 0'>" + " · ".join(nav)
                + (" <span class='dim'>· live, auto-refreshes every 15 s"
                   "</span>" if running and part == "log" else "")
                + "</div>")
    if note:
        body.append(f"<div class='warn'>{esc(note)}</div>")
    body.append(f"<pre>{esc(text)}</pre>")
    if running and part == "log":
        body.append("<div class='dim'>… cycle still running — newest "
                    "output is above this line.</div>")
    return _page(f"cycle {label}", body,
                 refresh=15 if running and part == "log" else 0,
                 scroll_end=part == "log")


def render_run_page(run: str) -> str | None:
    if not _SAFE_PART.match(run):
        return None
    try:
        entries = json.loads((HERE / "experiments.json").read_text())
    except Exception:
        entries = []
    rows = [e for e in entries
            if isinstance(e, dict) and e.get("run") == run]
    story = PROTO / "rl_docs" / "runs" / f"{run}.md"
    cyc = [e for e in _cycle_registry_entries()
           if run in (e.get("runs") or []) or run in (e.get("label") or "")]
    if not rows and not cyc and not story.is_file():
        return None
    latest = rows[-1] if rows else {}
    st = latest.get("status", "?")
    cls = {"RUNNING": "ok", "FINISHED": "dim", "FAILED": "bad"}.get(st, "warn")
    body = [f"<h1 class='mono' style='font-size:17px'>{esc(run)} "
            f"<span class='{cls}'>[{esc(st)}]</span></h1>"]
    bits = [f"track {track_of_entry(latest)}" if rows else "",
            f"pod {latest.get('pod')}" if latest.get("pod") else "",
            f"{len(rows)} ledger entr{'y' if len(rows) == 1 else 'ies'}"]
    wandb_id = next((r.get("wandb_id") for r in reversed(rows)
                     if r.get("wandb_id")), "")
    body.append(f"<div class='dim'>{esc(' · '.join(b for b in bits if b))}"
                + (f" · <a href='https://wandb.ai/l2k2/hexapod-balance/"
                   f"runs/{esc(wandb_id)}'>W&amp;B run</a>"
                   if wandb_id else "") + "</div>")

    body.append("<h2>Ledger history (newest first — each entry is one "
                "launch attempt / status change)</h2>")
    for e in reversed(rows):
        head = " · ".join(str(x) for x in (
            e.get("created", "?")[:16], e.get("status", "?"),
            f"{e.get('steps'):,} steps" if e.get("steps") else "",
            "smoke" if e.get("smoke") else "",
            e.get("phase", "")) if x)
        body.append(f"<div class='card' style='margin:8px 0'>"
                    f"<div class='mono'>{esc(head)}</div>")
        for key, name in (("hypothesis", "hypothesis"), ("gate", "gate"),
                          ("verdict", "verdict"), ("triage", "triage"),
                          ("stop_reason", "stop reason"),
                          ("hardware_ready", "hardware ready")):
            v = str(e.get(key) or "").strip()
            if v:
                body.append(f"<div style='margin-top:4px'><span class="
                            f"'dim'>{name}:</span> {esc(v)}</div>")
        if e.get("parent"):
            body.append(f"<div class='dim' style='margin-top:4px'>parent: "
                        f"{run_link(e['parent'])}</div>")
        body.append(f"<details><summary class='dim'>full entry (JSON)"
                    f"</summary><pre>"
                    f"{esc(json.dumps(e, indent=1)[:20000])}</pre>"
                    f"</details></div>")
    if not rows:
        body.append("<div class='dim'>not in the ledger</div>")

    body.append("<h2>Cycles that worked on this run</h2>")
    if cyc:
        body.append("<table><tr><th>started</th><th>cycle</th>"
                    "<th>model</th><th>status</th><th>took</th></tr>")
        for e in reversed(cyc):
            dur = e.get("duration_s")
            body.append(
                f"<tr><td class='dim mono'>{esc(e.get('started', '?'))}"
                f"</td><td class='mono'><a href='/cycle/"
                f"{esc(e.get('stamp', ''))}'>{esc(e.get('label', '?'))}"
                f"</a></td><td class='dim'>{esc(e.get('model', ''))}</td>"
                f"<td>{esc(e.get('status', '?'))}</td>"
                f"<td class='dim'>{f'{int(dur) // 60}m' if dur else ''}"
                f"</td></tr>")
        body.append("</table>")
    else:
        body.append("<div class='dim'>none recorded in the cycle registry "
                    "(it only tracks cycles since 08-22)</div>")

    if story.is_file():
        body.append(f"<h2>Run story (rl_docs/runs/{esc(run)}.md)</h2>"
                    f"<pre>{esc(story.read_text(errors='replace')[:300000])}"
                    f"</pre>")
    return _page(run, body)


# -------------------------------------------------------- git doc sync
# Keep the controller checkout tracking origin/main so every doc the
# LLM mirror serves goes live within a minute of the operator pushing
# from the laptop — no manual `git pull` (operator 08-12). Serialized
# against snapshot.sh's commit/rebase/push with the same host-wide
# lock; `flock -n` SKIPS the round instead of blocking when a decision
# cycle holds it. NOTE: this updates docs only — a status_server.py
# change still needs the runbook's tmux kill+restart to take effect.
REPO = PROTO.parent.parent
GIT_SYNC_S = 60
GIT_LOCK = "/workspace/git_snapshot.lock"


def git_sync_worker() -> None:
    def git(*args, timeout=60):
        return subprocess.run(["git", "-C", str(REPO), *args],
                              capture_output=True, text=True,
                              timeout=timeout)
    while True:
        time.sleep(GIT_SYNC_S)
        try:
            git("fetch", "-q", "origin", "main")
            if git("rev-parse", "HEAD").stdout == \
                    git("rev-parse", "origin/main").stdout:
                SNAP.pop("git_sync_err", None)
                continue
            r = subprocess.run(
                ["flock", "-n", GIT_LOCK, "git", "-C", str(REPO), "pull",
                 "--rebase", "--autostash", "-q", "origin", "main"],
                capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                SNAP.pop("git_sync_err", None)
            # flock -n exits 1 while a cycle holds the lock: not an
            # error, just try again next round
            elif r.returncode != 1:
                SNAP["git_sync_err"] = (r.stderr or r.stdout)[:300]
        except Exception as e:
            SNAP["git_sync_err"] = repr(e)[:300]


# ------------------------------------------------------- LLM endpoints
# Plain-text/markdown mirror of the campaign state so GPT/Claude web
# fetchers can read it without parsing the HTML dashboard (operator
# 08-12). /llms.txt follows the llmstxt.org convention: a short index
# whose links embed the access key, so a fetcher that was given the
# llms.txt URL can follow them statelessly. Deliberately excluded:
# spend/token numbers and pod names (infra detail an external reader
# doesn't need) — those stay on the HTML page and /json.

def llm_status_md() -> str:
    """Campaign STATUS.md + every per-track STATUS.md, concatenated."""
    parts = []
    for d in status_docs().values():
        parts.append(f"# {d['name']}\n\n{d['text'].rstrip()}\n")
    return "\n\n".join(parts)


def llm_plan_md() -> str:
    try:
        return (PROTO / "RL_PLAN.md").read_text(errors="replace")
    except OSError as e:
        return f"(RL_PLAN.md unreadable: {e})"


LLM_LOG_CAP = 300_000  # bytes; keep a fetch well under context limits


def llm_log_md() -> str:
    try:
        data = (PROTO / "RL_LOG.md").read_bytes()
    except OSError as e:
        return f"(RL_LOG.md unreadable: {e})"
    if len(data) <= LLM_LOG_CAP:
        return data.decode(errors="replace")
    tail = data[-LLM_LOG_CAP:].decode(errors="replace")
    tail = tail.split("\n", 1)[-1]  # drop the partial first line
    return (f"(RL_LOG.md truncated: showing the newest {LLM_LOG_CAP // 1000} kB "
            f"of {len(data) // 1000} kB — the log is append-only, newest last)"
            f"\n\n{tail}")


def llm_runs_md(base: str, key: str) -> str:
    f = SNAP.get("fast", {})
    rows = f.get("ledger", [])
    out = ["# Launched runs — latest ledger entry per run, newest first",
           "",
           "Status meanings: RUNNING = training now. FINISHED = training "
           "done AND an analysis cycle wrote a verdict. FAILED/KILLED = "
           "died or was stopped. REFUSED = a launcher guardrail blocked "
           "it before it started (no GPU time spent).", ""]
    if not rows:
        out.append("(ledger snapshot not collected yet — the server just "
                   "restarted; retry in ~30 s)")
    for e in rows:
        run = e.get("run", "?")
        out.append(f"## {run} — {e.get('status', '?')}")
        created = (e.get("created") or "")[:16]
        out.append(f"- track: {track_of_entry(e)} · phase: "
                   f"{e.get('phase', '?')} · created: {created} UTC")
        hyp = (e.get("hypothesis") or "").strip()
        if hyp:
            out.append(f"- hypothesis: {hyp}")
        if e.get("parent"):
            out.append(f"- parent run: {e['parent']}")
        verdict = str(e.get("verdict") or "").strip()
        if verdict:
            out.append(f"- verdict: {verdict}")
        elif e.get("triage"):
            out.append(f"- analysis stage: {e['triage']}")
        if (PROTO / "rl_docs" / "runs" / f"{run}.md").is_file():
            out.append(f"- full story: {base}/llm/doc/rl_docs/runs/"
                       f"{run}.md{key}")
        out.append("")
    return "\n".join(out)


# Directories never descended into when indexing docs (artifacts, not
# documentation — logs/ alone can hold thousands of files).
DOC_SKIP_DIRS = {".git", "logs", "wandb", "policies", "node_modules",
                 "__pycache__"}


def list_docs() -> list[str]:
    """Every .md under the prototype tree, PROTO-relative, sorted."""
    out = []
    for root, dirs, files in os.walk(PROTO):
        dirs[:] = [d for d in dirs if d not in DOC_SKIP_DIRS]
        rel = os.path.relpath(root, PROTO)
        for name in files:
            if name.endswith(".md"):
                out.append(name if rel == "." else f"{rel}/{name}")
    return sorted(out)


def git_head() -> str:
    try:
        r = subprocess.run(["git", "-C", str(PROTO), "log", "-1",
                            "--format=%h (%cd)", "--date=format:%Y-%m-%d "
                            "%H:%M UTC"], capture_output=True, text=True,
                           timeout=15)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


def llm_docs_md(base: str, key: str) -> str:
    n_runs = 0
    by_dir: dict[str, list[tuple[str, int]]] = {}
    for rel in list_docs():
        if rel.startswith("rl_docs/runs/"):
            n_runs += 1
            continue
        try:
            size = (PROTO / rel).stat().st_size
        except OSError:
            size = 0
        d = os.path.dirname(rel) or "(root)"
        by_dir.setdefault(d, []).append((rel, size))
    out = ["# All documentation files",
           "",
           f"Every markdown doc in the prototype tree, served live from "
           f"the git checkout at {git_head()} (auto-synced from origin/"
           f"main, so a push goes live within ~{GIT_SYNC_S} s). URLs are "
           f"plain text (some LLM fetchers fail on markdown links); no "
           f"authentication is required.", ""]
    for d in sorted(by_dir):
        out.append(f"## {d}")
        out.append("")
        for rel, size in by_dir[d]:
            out.append(f"- {rel} ({size // 1000} kB): "
                       f"{base}/llm/doc/{rel}{key}")
        out.append("")
    out.append("## rl_docs/runs — per-run stories")
    out.append("")
    out.append(f"{n_runs} files, one per launched training run, at "
               f"{base}/llm/doc/rl_docs/runs/<run>.md — run names are "
               f"in the run ledger ({base}/llm/runs.md{key}), which "
               f"gives each run's story URL directly.")
    return "\n".join(out)


def llm_doc_file(rel: str) -> bytes | None:
    """One doc by PROTO-relative path; None = not found/not allowed."""
    if not rel.endswith(".md") or ".." in rel:
        return None
    p = (PROTO / rel).resolve()
    if not p.is_relative_to(PROTO.resolve()):
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None


def llms_txt(base: str, key: str) -> str:
    f = SNAP.get("fast", {})
    w = f.get("watcher", {})
    counts = f.get("counts", {})
    if not w:
        live = "server just restarted — live snapshot still collecting"
    else:
        state = ("PAUSED" if w.get("pause")
                 else "ON" if w.get("tmux") else "OFF")
        live = (f"watcher {state} · "
                f"{len(f.get('cycles', []))} LLM analysis cycle(s) in "
                f"flight · "
                f"{len(f.get('backlog', {}).get('queued', []))} queued in "
                f"backlog · "
                f"{counts.get('RUNNING', 0)} run(s) marked RUNNING · "
                f"{counts.get('FINISHED', 0)} run(s) verdicted")
    return f"""# Hexapod RL training orchestrator — live status

> Autonomous RL training campaign teaching an 18-servo hexapod robot to
> stand, walk, and turn (MuJoCo/MJX PPO on a GPU fleet). An LLM watcher
> launches runs, evaluates checkpoints, and writes verdicts; the
> documents below are its working state, mirrored as plain markdown for
> LLM readers assessing how the campaign is going.

Live state: {live}.

## Status documents

URLs are given as plain text (some LLM fetchers fail to follow
markdown-style links). No authentication is required on any /llm URL.

Campaign + per-track STATUS — the campaign digest plus each research
track's current state; read this first for an overall assessment:
{base}/llm/status.md{key}

Research plan — RL_PLAN.md, the plan the autonomous agents work from
(goals, phases, guardrails):
{base}/llm/plan.md{key}

Cycle log — RL_LOG.md, the append-only decision-cycle log (newest
entries at the end):
{base}/llm/log.md{key}

Run ledger — every launched training run with its hypothesis, status,
and verdict, plus the URL of its full story document:
{base}/llm/runs.md{key}

All documentation — index of every other markdown doc in the tree
(hardware, sim, rewards, evals, per-run stories, …), each fetchable
at {base}/llm/doc/<path>{key}:
{base}/llm/docs.md{key}

## MCP server

The same results are queryable as tools over the MCP streamable-HTTP
transport (run ledger with filters, per-run stories, cached W&B
metrics, eval reports, doc search) at {base}/mcp — but that endpoint
is private: it requires the operator's MCP key (Authorization: Bearer
<key>, X-Api-Key, or ?key=<key>). The keyless /llm pages above carry
the same public data.
"""


LLM_PAGES = {
    "/llm/status.md": lambda base, key: llm_status_md(),
    "/llm/plan.md": lambda base, key: llm_plan_md(),
    "/llm/log.md": lambda base, key: llm_log_md(),
    "/llm/runs.md": llm_runs_md,
    "/llm/docs.md": llm_docs_md,
}


def llm_body(path: str, base: str) -> tuple[bytes, str] | None:
    from urllib.parse import unquote
    # Keyless URLs: the LLM mirror needs no token (see do_GET), and
    # GPT's URL-safety wrapper refuses to follow keyed child links
    # anyway (operator 08-13).
    key = ""
    # Everything is text/plain, NOT text/markdown: GPT's web fetcher
    # reaches text/markdown responses but refuses to expose the body
    # (operator 08-12). The content is unchanged, only the label.
    ctype = "text/plain; charset=utf-8"
    if path in ("/llms.txt", "/llm", "/llm/"):
        return llms_txt(base, key).encode(), ctype
    if path.startswith("/llm/doc/"):
        body = llm_doc_file(unquote(path[len("/llm/doc/"):]))
        if body is None:
            return None
        return body, ctype
    fn = LLM_PAGES.get(path)
    if fn is None:
        return None
    return fn(base, key).encode(), ctype


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
    # MCP endpoint (mcp_server.py): PRIVATE since 08-15 — every
    # request must present the operator's MCP key (MCP_AUTH_KEY /
    # /workspace/.mcp_key; checked inside mcp_server.handle_http) or
    # the dashboard STATUS_TOKEN (checked here, _mcp_operator).
    # Authenticated requests run the trusted operator lane:
    # kick_orchestrator files the operator KICK (deep model) and
    # submit_feedback stamps entries operator:true. No valid
    # credential = 401; no key configured on the host = 503.
    def _is_mcp(self) -> bool:
        return self.path.split("?")[0].rstrip("/") == "/mcp"

    def _mcp_operator(self) -> bool:
        """Does this /mcp request present the operator token?"""
        if not TOKEN:
            return False  # no token configured = no operator lane
        from urllib.parse import parse_qs, urlparse
        cands = [parse_qs(urlparse(self.path).query).get("key", [""])[0]]
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            cands.append(auth[7:].strip())
        cands.append(self.headers.get("X-API-Key", "") or "")
        return any(c and hmac.compare_digest(c, TOKEN) for c in cands)

    def _serve_mcp(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        # Caddy proxies from localhost; the real client is in
        # X-Forwarded-For (first hop) — used only for rate limiting.
        ip = (self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
              or self.client_address[0])
        query = (self.path.split("?", 1) + [""])[1]
        status, headers, out = _mcp.handle_http(
            self.command, body, ip, operator=self._mcp_operator(),
            headers=self.headers, query=query)
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):  # noqa: N802
        if self._is_mcp():
            return self._serve_mcp()
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_OPTIONS = do_DELETE = do_POST  # noqa: N815 — /mcp CORS + session end

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
        if self._is_mcp():  # GET /mcp -> 405 hint (POST-only transport)
            return self._serve_mcp()
        # robots.txt must bypass the token gate: LLM fetchers (ChatGPT
        # etc.) check it before any visit, and the gate's 403 there made
        # them treat the ENTIRE site as disallowed (operator 08-12).
        if self.path.split("?")[0] == "/robots.txt":
            body = (b"User-agent: *\nAllow: /\n\n"
                    b"# Status docs for LLM readers: /llms.txt\n")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        # The LLM mirror is keyless (operator 08-13): the git repo it
        # mirrors is PUBLIC on GitHub, so the token gated nothing there,
        # and GPT's URL-safety wrapper refuses keyed URLs outright.
        # Spend + infra stay gated: the dashboard and /json still need
        # the token.
        is_llm = u.path == "/llms.txt" or u.path.rstrip("/") == "/llm" \
            or u.path.startswith("/llm/")
        if not is_llm and not self._authed():
            body = b"403: append ?key=<token> to the URL"
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if TOKEN and not is_llm \
                and parse_qs(u.query).get("key", [""])[0] == TOKEN:
            # set the cookie, drop the key from the URL
            self.send_response(302)
            self.send_header("Set-Cookie",
                             f"status_token={TOKEN}; Path=/; Max-Age=31536000")
            self.send_header("Location", u.path or "/")
            self.end_headers()
            return
        host = self.headers.get("Host") or f"127.0.0.1:{PORT}"
        scheme = ("http" if host.split(":")[0] in
                  ("127.0.0.1", "localhost") else "https")
        base = f"{scheme}://{host}"
        if is_llm:
            out = llm_body(u.path, base)
            if out is None:
                body = b"404: see /llms.txt for the LLM-readable index"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body, ctype = out
        elif u.path.startswith(("/cycle/", "/run/")):
            from urllib.parse import unquote
            q = parse_qs(u.query)
            if u.path.startswith("/cycle/"):
                page = render_cycle_page(
                    unquote(u.path[len("/cycle/"):]).strip("/"),
                    q.get("part", ["log"])[0],
                    q.get("full", ["0"])[0] == "1")
            else:
                page = render_run_page(
                    unquote(u.path[len("/run/"):]).strip("/"))
            if page is None:
                body = b"404: no such cycle/run"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = page.encode()
            ctype = "text/html; charset=utf-8"
        elif self.path.startswith("/json"):
            body = json.dumps(SNAP, default=str).encode()
            ctype = "application/json"
        else:
            body = render(base).encode()
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
    # Only on the controller: never auto-pull a laptop checkout (a dev
    # running this locally has uncommitted work in the working tree).
    if str(REPO) == "/workspace/hexapod":
        threading.Thread(target=git_sync_worker, daemon=True).start()
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"status page on :{PORT}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
