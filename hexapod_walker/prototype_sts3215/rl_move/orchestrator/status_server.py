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
    """Claude cycle subprocesses, with what each one is triaging."""
    out = []
    now = time.time()
    for d in glob.glob("/proc/[0-9]*"):
        try:
            cmd = open(d + "/cmdline", "rb").read()
        except OSError:
            continue
        parts = cmd.split(b"\0")
        if not parts or not parts[0].endswith(b"claude"):
            continue
        prompt = parts[-2].decode(errors="replace") if len(parts) > 1 else ""
        m = re.search(r"Runs that just finished: ([^\n]+)", prompt)
        about = m.group(1) if m else (
            "checkup findings" if "checkup findings" in prompt
            else "idle kick" if "idle kick" in prompt else "?")
        try:
            age = now - os.stat(d).st_mtime
        except OSError:
            age = 0
        out.append({"pid": int(d.split("/")[-1]),
                    "age_min": int(age / 60), "about": about})
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
                "verdict": bool(e.get("verdict"))}
            for r, e in latest.items()}
    return rows, counts, slim


def backlog_state() -> dict:
    def load(name):
        try:
            return json.loads((HERE / name).read_text())
        except Exception:
            return []
    return {"queued": load("backlog.json"), "failed": load("backlog_failed.json")}


# claude-fable-5 list rates, $/MTok (Anthropic pricing page, checked
# 2026-08-09): input 10, output 50, cache read 1, cache write 12.50
# (5-min TTL) / 20 (1-h TTL). Global inference (no US-only 1.1x).
RATES = {"in": 10.0, "out": 50.0, "cr": 1.0, "cw5": 12.5, "cw1h": 20.0}


def est_cost(s: dict) -> float:
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
                        u = (d.get("message") or {}).get("usage")
                        if not u:
                            continue
                        day = (d.get("timestamp") or "")[:10] or "unknown"
                        s = sums.setdefault(day, {"in": 0, "out": 0, "cw": 0,
                                                  "cr": 0, "cw5": 0, "cw1h": 0})
                        s["in"] += u.get("input_tokens", 0)
                        s["out"] += u.get("output_tokens", 0)
                        cw = u.get("cache_creation_input_tokens", 0)
                        s["cw"] += cw
                        s["cr"] += u.get("cache_read_input_tokens", 0)
                        det = u.get("cache_creation") or {}
                        h1 = det.get("ephemeral_1h_input_tokens", 0)
                        # no TTL breakdown -> price it all as 5-min writes
                        s["cw1h"] += h1
                        s["cw5"] += det.get("ephemeral_5m_input_tokens",
                                            cw - h1)
            except OSError:
                continue
            _token_cache[path] = (st.st_mtime, st.st_size, sums)
        for day, s in sums.items():
            t = days.setdefault(day, dict.fromkeys(
                ("in", "out", "cw", "cr", "cw5", "cw1h"), 0))
            for k in t:
                t[k] += s.get(k, 0)
    total = dict.fromkeys(("in", "out", "cw", "cr", "cw5", "cw1h"), 0)
    for s in days.values():
        for k in total:
            total[k] += s[k]
    today = days.get(datetime.date.today().isoformat(),
                     dict.fromkeys(("in", "out", "cw", "cr", "cw5", "cw1h"), 0))
    return {"total": total, "today": today, "n_days": len(days)}


def wandb_done_runs() -> list[dict]:
    """cw- runs W&B says are finished/crashed/failed, with created time
    (ground truth for the analysis pipeline — the ledger `triage` field
    alone misses runs that finish while the watcher is paused, which is
    exactly when the operator is staring at this page)."""
    import wandb
    api = wandb.Api()
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
                "orch_tail": read_tail(ORCH_LOG, 14),
                "rl_log_tail": read_tail(PROTO / "RL_LOG.md", 8),
            }
        except Exception as e:
            SNAP["fast_err"] = repr(e)
        time.sleep(FAST_S)


def slow_worker() -> None:
    while True:
        try:
            SNAP["slow"] = {"at": time.time(), "census": census(),
                            "tokens": token_totals(),
                            "wandb_done": wandb_done_runs()}
        except Exception as e:
            SNAP["slow_err"] = repr(e)
        time.sleep(SLOW_S)


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

    h = [f"<html><head><meta charset='utf-8'><meta http-equiv='refresh' "
         f"content='30'><title>hexapod RL agent</title><style>{CSS}</style>"
         f"</head><body>"]
    h.append(f"<h1>Hexapod RL agent <span class='pill {pill}'>{label}</span>"
             f"</h1><div class='dim'>refreshed "
             f"{datetime.datetime.now().strftime('%H:%M:%S')} · page "
             f"auto-reloads every 30 s · fleet/token data every "
             f"{SLOW_S} s{(' · ' + esc(sub)) if sub else ''}</div>")

    # finished on W&B but no verdict in the ledger = not yet analyzed.
    # W&B is the ground truth for "finished"; the triage field only adds
    # the awaiting/in-cycle detail (it's watcher-stamped and misses runs
    # that finish while the watcher is paused).
    final = {"FINISHED", "FAILED", "KILLED", "KILLED_BY_OPERATOR", "REFUSED"}
    latest = f.get("latest", {})
    training_now = {r for c in cen for r in (c.get("runs") or [])}
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=24)).isoformat()
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
                pipeline.append({"run": run, "state": "NOT IN LEDGER (bug?)"})
        elif e["status"] not in final and not e["verdict"]:
            pipeline.append({"run": run,
                             "state": e["triage"] or "awaiting (unassigned)"})
    pipeline.sort(key=lambda p: p["run"])
    n_pipe = len(pipeline)
    h.append("<div class='grid' style='margin-top:14px'>")
    pipe_cls = "" if n_pipe <= 3 else " style='border-color:#9e6a03'"
    h.append(f"<div class='card'{pipe_cls}><div class='n'>{n_pipe}</div>"
             f"<div class='l'>finished, NOT yet analyzed</div></div>")
    for n, l in [
        (len(busy), "pods training"), (len(idle), "pods idle"),
        (len(f.get("cycles", [])), "LLM cycles in flight"),
        (len(backlog["queued"]), "queued in backlog"),
        (counts.get("FINISHED", 0), "runs analyzed (verdicted)"),
    ]:
        h.append(f"<div class='card'><div class='n'>{n}</div>"
                 f"<div class='l'>{l}</div></div>")
    if tok:
        h.append(f"<div class='card'><div class='n'>"
                 f"${est_cost(tok['today']):,.0f}</div>"
                 f"<div class='l'>est. spend today</div></div>")
        h.append(f"<div class='card'><div class='n'>"
                 f"${est_cost(tok['total']):,.0f}</div>"
                 f"<div class='l'>est. spend total</div></div>")
    h.append("</div>")

    h.append("<h2>Analysis pipeline (finished on W&B, verdict not in yet)"
             "</h2>")
    if pipeline:
        h.append("<table><tr><th>run</th><th>state</th></tr>")
        for p in pipeline:
            cls = "ok" if p["state"].startswith("in-cycle") else "warn"
            h.append(f"<tr class='mono'><td>{esc(p['run'])}</td>"
                     f"<td class='{cls}'>{esc(p['state'])}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>empty — every finished run has a "
                 "verdict</div>")

    h.append("<h2>What it's thinking about (in-flight decision cycles)</h2>")
    if f.get("cycles"):
        h.append("<table><tr><th>pid</th><th>age</th><th>triaging</th></tr>")
        for c in f["cycles"]:
            h.append(f"<tr class='mono'><td>{c['pid']}</td>"
                     f"<td>{c['age_min']} min</td><td>{esc(c['about'])}</td></tr>")
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

    h.append("<h2>Fleet</h2><table>")
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
        h.append("<table><tr><th>run</th><th>steps</th><th>attempts</th></tr>")
        for it in backlog["queued"]:
            h.append(f"<tr class='mono'><td>{esc(it.get('run'))}</td>"
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
                 "<div class='dim'>list rates for claude-fable-5: $10/M in, "
                 "$50/M out, $1/M cache read, $12.50/M / $20/M cache write "
                 "(5-min / 1-h TTL), checked 2026-08-09</div>")

    h.append("<h2>Runs (latest ledger entry per run)</h2>"
             "<table><tr><th>run</th><th>status</th><th>pod</th>"
             "<th>created</th></tr>")
    for e in f.get("ledger", []):
        st = e.get("status", "?")
        cls = {"RUNNING": "ok", "FINISHED": "dim",
               "FAILED": "bad"}.get(st, "warn")
        h.append(f"<tr class='mono'><td>{esc(e.get('run'))}</td>"
                 f"<td class='{cls}'>{esc(st)}</td>"
                 f"<td>{esc(e.get('pod', ''))}</td>"
                 f"<td class='dim'>{esc((e.get('created') or '')[5:16])}</td></tr>")
    h.append("</table>")

    h.append("<h2>Watcher log (tail)</h2><pre>"
             + esc("\n".join(f.get("orch_tail", []))) + "</pre>")
    h.append("<h2>RL_LOG.md (tail)</h2><pre>"
             + esc("\n".join(f.get("rl_log_tail", []))) + "</pre>")
    h.append("</body></html>")
    return "".join(h)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
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
    threading.Thread(target=slow_worker, daemon=True).start()
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"status page on :{PORT}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
