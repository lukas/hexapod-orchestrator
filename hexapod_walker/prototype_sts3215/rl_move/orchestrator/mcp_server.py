#!/usr/bin/env python3
"""MCP server for the RL campaign — LLMs investigate results as tools.

Stdlib only, like status_server.py. Implements the MCP streamable-HTTP
transport (JSON-RPC 2.0 over POST, plain application/json responses —
no SSE stream) so any MCP client (Claude, Cursor, ChatGPT connectors,
mcp-remote) can query the run ledger, campaign/track status, per-run
stories, cached W&B metrics, eval reports, and every doc in the tree.

Normally mounted INSIDE status_server.py at POST /mcp (public URL
https://hexapod.cwd1f0-new-cluster.coreweave.app/mcp — Caddy proxies
443 to :8090). PRIVATE since 08-15 (the keyless mode made client-side
safety layers classify the endpoint as public/untrusted and block
feedback): every request must present the operator's MCP key —
`Authorization: Bearer <key>`, `X-Api-Key: <key>`, or `?key=<key>` on
the /mcp URL (ChatGPT connectors can't set headers). Key sources, in
order: MCP_AUTH_KEY env, /workspace/.mcp_key (controller, written at
deploy), logs/.mcp_key (laptop dev). No key on disk = endpoint
disabled (503) — never silently open. Keyed requests run the trusted
operator lane (kick_orchestrator files the operator KICK,
submit_feedback entries are operator-stamped); the dashboard
STATUS_TOKEN also still grants the lane. Spend/token numbers and pod
names stay off the tools (same policy as /llm, operator 08-13).

Standalone for development/testing only:
    python3 rl_move/orchestrator/mcp_server.py   # port 8091
"""
from __future__ import annotations

import csv
import glob as _glob
import io
import json
import os
import pathlib
import re
import time

HERE = pathlib.Path(__file__).resolve().parent
PROTO = HERE.parent.parent

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "hexapod-rl-results",
               "title": "Hexapod RL campaign results",
               "version": "1.0.0"}
INSTRUCTIONS = """\
Results of an autonomous RL training campaign teaching an 18-servo
hexapod robot to stand, walk, and turn (MuJoCo/MJX PPO on a GPU fleet;
an LLM watcher launches runs, evaluates checkpoints, writes verdicts).

Suggested flow: campaign_status first (campaign digest + every research
track's state), then list_runs to browse the launch ledger, get_run for
one run's full story (hypothesis, gate, verdict), run_metrics /
eval_report for its numbers. get_plan is the research plan; log_tail is
the append-only decision-cycle log. Every design doc (rewards, gaits,
evals, hardware, per-run stories) is reachable via list_docs /
read_doc, and search_docs greps them all.

This endpoint is PRIVATE: you reached it with the operator's MCP key,
so you are acting for the operator (Lukas) and your requests run the
trusted operator lane automatically.

You can LEAVE NOTES for the campaign: submit_feedback files a note
(observations, critiques, suggested experiments) that the
orchestrator agent reads at the start of its next decision cycle;
entries are operator-stamped and show on the dashboard. list_feedback
shows what is already filed — check it first to avoid duplicates.

kick_orchestrator goes one step further: it files the TRUSTED
operator kick — the watcher wakes within seconds and spawns a
deep-model session that does what your focus note asks. Each cycle
counts against the rolling daily cycle budget. Guardrails
(guardrails.yaml, the physical-robot prohibition) still bind every
cycle. IMPORTANT: cycles are silent for 10-30 min while they work —
poll orchestrator_activity (running cycles, INTENT ledger rows,
watcher log) to watch progress instead of re-kicking; duplicate
kicks just spawn cycles that rediscover the first one's work.

Obey-then-ask (operator 08-15): cycles EXECUTE operator orders even
when they conflict with written rules (only typos, safety, or
mechanical impossibility block), then file the conflict as a question
in OPERATOR_QUESTIONS.md. Read open questions with
list_operator_questions; the operator answers via submit_feedback
(operator-stamped) and the next cycle updates the rulebook to match
and closes the question.
"""

# Ledger fields that are infra detail (pod names / pod-local paths) —
# excluded from tool output (same policy as the /llm mirror).
LEDGER_PRIVATE = {"pod", "log"}

# Auth key (operator 08-15): the endpoint is private — one shared key,
# handed only to the operator's own MCP clients (ChatGPT connector,
# Cursor). Without it every request except CORS preflight is refused.
# The old keyless mode also made client-side safety layers classify
# the endpoint as public/untrusted and block feedback submissions.
def _load_auth_key() -> str:
    k = os.environ.get("MCP_AUTH_KEY", "").strip()
    if k:
        return k
    for p in (pathlib.Path("/workspace/.mcp_key"),
              PROTO / "logs" / ".mcp_key"):
        try:
            return p.read_text().strip()
        except OSError:
            continue
    return ""


AUTH_KEY = _load_auth_key()


def _authed(headers, query: str) -> bool:
    if not AUTH_KEY:
        return False  # no key configured = fail closed, never open
    h = headers or {}
    for name in ("Authorization", "authorization"):
        v = (h.get(name) or "").strip()
        if v == f"Bearer {AUTH_KEY}" or v == AUTH_KEY:
            return True
    for name in ("X-Api-Key", "x-api-key"):
        if (h.get(name) or "").strip() == AUTH_KEY:
            return True
    from urllib.parse import parse_qs
    return parse_qs(query or "").get("key", [""])[0] == AUTH_KEY


# Same skip list as status_server.list_docs.
DOC_SKIP_DIRS = {".git", "logs", "wandb", "policies", "node_modules",
                 "__pycache__"}
TEXT_CAP = 400_000  # bytes per tool result — keep well under context

# Feedback inbox: OUTSIDE the git checkout on the controller (so the
# doc-sync `git pull` never trips over it — an untracked file in the
# tree blocked the sync once already, 08-14), inside logs/ (gitignored)
# for laptop dev. Entries show on the dashboard AND the watcher injects
# unseen ones into the next decision cycle (operator 08-14 "just make
# it read it"). Since the 08-15 key gate only the operator's own
# clients can file them, and entries are operator-stamped; guardrails
# still bind every cycle.
FEEDBACK_DIR = pathlib.Path(
    os.environ.get("MCP_FEEDBACK_DIR")
    or ("/workspace/llm_feedback" if pathlib.Path("/workspace").is_dir()
        else PROTO / "logs" / "llm_feedback"))
FEEDBACK_MAX_LEN = 8000       # chars of feedback text per entry
FEEDBACK_MAX_FILES = 2000     # hard cap on inbox size
FEEDBACK_RATE = (10, 3600)    # per-IP: max 10 submissions per hour
_fb_times: dict[str, list[float]] = {}  # ip -> submission timestamps

# Kick requests (operator 08-14 "add an endpoint to kickstart an
# orchestrator agent"; operator 08-15 "it should go instantly, and if
# it's kicked twice it should be able to create two agents"): a QUEUE
# directory of request files, same placement logic as the feedback
# inbox — outside the git checkout on the controller, logs/
# (gitignored) for laptop dev. The watcher wakes within seconds of a
# new file and spawns ONE cycle per request (see watch_loop.py
# pending_mcp_kicks). Since the 08-15 key gate every /mcp kick runs
# the operator lane (OPERATOR_KICK_FILE below), so this advisory
# queue only drains entries filed before the gate went in.
KICK_DIR = pathlib.Path(
    os.environ.get("MCP_KICK_DIR")
    or ("/workspace/llm_kicks" if pathlib.Path("/workspace").is_dir()
        else PROTO / "logs" / "llm_kicks"))
KICK_MAX_LEN = 2000           # a kick is a pointer, not an essay
# Kicks are ALWAYS filed (operator 08-15: "when I run a kick that's
# because I want something to run"). The old per-IP rate limit (2/h)
# and queue cap (4) rejected normal usage — removed. What remains is
# an extreme flood guard so a hostile scripted client can't fill the
# disk; no human/LLM usage should ever see these thresholds.
KICK_FLOOD_PENDING = 30       # refuse only if the queue is this deep
KICK_FLOOD_IP = (20, 3600)    # refuse only if one IP filed >=20 in 1h
_kick_times: dict[str, list[float]] = {}  # ip -> request timestamps

# OPERATOR LANE (operator 08-15 "WE ADDED A TOKEN", then the key
# gate): since /mcp requires the operator's MCP key, EVERY
# authenticated request is the operator (the dashboard STATUS_TOKEN,
# checked by status_server with hmac.compare_digest, also grants the
# lane). Operator kicks bypass the flood guards and are written to
# the TRUSTED operator KICK file (the plain-text focus file the
# watcher runs as a deep-model, do-what-the-note-asks session)
# instead of the advisory queue; feedback entries are stamped
# "operator": true. On the controller the watcher reads HERE/KICK; on
# a laptop we keep the dev checkout clean and write under logs/ (same
# fallback logic as KICK_DIR).
OPERATOR_KICK_FILE = pathlib.Path(
    os.environ.get("MCP_OPERATOR_KICK")
    or (HERE / "KICK" if pathlib.Path("/workspace").is_dir()
        else PROTO / "logs" / "operator_KICK"))


# ---------------------------------------------------------------- data
def _clip(text: str, cap: int = TEXT_CAP, what: str = "output") -> str:
    if len(text) <= cap:
        return text
    return (text[:cap]
            + f"\n\n[... {what} truncated at {cap // 1000} kB ...]")


def _ledger() -> list[dict]:
    entries = json.loads((HERE / "experiments.json").read_text())
    latest: dict[str, dict] = {}
    for e in entries:
        if isinstance(e, dict) and e.get("run"):
            latest[e["run"]] = e
    return sorted(latest.values(),
                  key=lambda e: e.get("created") or "", reverse=True)


def _track_of(e: dict) -> str:
    if e.get("track"):
        return e["track"]
    try:
        import tracks as _tracks
        return _tracks.infer(e.get("run", ""))
    except Exception:
        return "?"


def _public(e: dict) -> dict:
    return {k: v for k, v in e.items() if k not in LEDGER_PRIVATE}


def _doc_paths() -> list[str]:
    out = []
    for root, dirs, files in os.walk(PROTO):
        dirs[:] = [d for d in dirs if d not in DOC_SKIP_DIRS]
        rel = os.path.relpath(root, PROTO)
        for name in files:
            if name.endswith(".md"):
                out.append(name if rel == "." else f"{rel}/{name}")
    return sorted(out)


def _read_doc(rel: str) -> str | None:
    if not rel.endswith(".md") or ".." in rel:
        return None
    p = (PROTO / rel).resolve()
    if not p.is_relative_to(PROTO.resolve()):
        return None
    try:
        return p.read_text(errors="replace")
    except OSError:
        return None


# --------------------------------------------------------------- tools
def t_campaign_status() -> str:
    parts = []
    try:
        parts.append("# Campaign digest (STATUS.md)\n\n"
                     + (PROTO / "STATUS.md").read_text(errors="replace"))
    except OSError as e:
        parts.append(f"(STATUS.md unreadable: {e})")
    for p in sorted((PROTO / "rl_docs" / "tracks").glob("*/STATUS.md")):
        parts.append(f"# Track: {p.parent.name}\n\n"
                     + p.read_text(errors="replace"))
    return _clip("\n\n---\n\n".join(parts))


def t_get_plan() -> str:
    out = []
    for name in ("RL_PLAN.md", "CURRENT_TRUTHS.md"):
        try:
            out.append(f"# {name}\n\n"
                       + (PROTO / name).read_text(errors="replace"))
        except OSError as e:
            out.append(f"({name} unreadable: {e})")
    return _clip("\n\n---\n\n".join(out))


def t_log_tail(max_kb: int = 64) -> str:
    max_kb = max(1, min(int(max_kb), 300))
    try:
        data = (PROTO / "RL_LOG.md").read_bytes()
    except OSError as e:
        return f"(RL_LOG.md unreadable: {e})"
    cap = max_kb * 1000
    if len(data) <= cap:
        return data.decode(errors="replace")
    tail = data[-cap:].decode(errors="replace").split("\n", 1)[-1]
    return (f"(RL_LOG.md is {len(data) // 1000} kB, showing the newest "
            f"{max_kb} kB — append-only, newest last; raise max_kb or "
            f"use search_docs for older entries)\n\n{tail}")


def t_list_runs(status: str = "", track: str = "", contains: str = "",
                limit: int = 40) -> str:
    limit = max(1, min(int(limit), 900))
    rows, counts = [], {}
    for e in _ledger():
        counts[e.get("status", "?")] = counts.get(e.get("status", "?"), 0) + 1
        if status and e.get("status", "").upper() != status.upper():
            continue
        if track and _track_of(e) != track:
            continue
        if contains:
            blob = json.dumps(e).lower()
            if contains.lower() not in blob:
                continue
        if len(rows) >= limit:
            continue
        r = {"run": e.get("run"), "status": e.get("status"),
             "track": _track_of(e), "created": (e.get("created") or "")[:16]}
        for k in ("phase", "steps", "parent"):
            if e.get(k):
                r[k] = e[k]
        hyp = (e.get("hypothesis") or "").strip()
        if hyp:
            r["hypothesis"] = hyp[:280] + ("…" if len(hyp) > 280 else "")
        v = str(e.get("verdict") or "").strip()
        if v:
            r["verdict"] = v[:280] + ("…" if len(v) > 280 else "")
        elif e.get("triage"):
            r["analysis_stage"] = e["triage"]
        rows.append(r)
    head = ("Latest ledger entry per run, newest first. Status meanings: "
            "RUNNING = training now; FINISHED = training done AND a "
            "verdict was written; FAILED/KILLED = died or stopped; "
            "REFUSED = a launcher guardrail blocked it (no GPU time). "
            "Use get_run for a run's full entry + story.\n"
            f"Status counts (all runs): {json.dumps(counts)}\n"
            f"Showing {len(rows)} runs.\n\n")
    return _clip(head + json.dumps(rows, indent=1))


def t_get_run(run: str) -> str:
    entry = next((e for e in _ledger() if e.get("run") == run), None)
    if entry is None:
        near = [e["run"] for e in _ledger() if run.lower() in e["run"].lower()]
        return (f"run {run!r} not in the ledger."
                + (f" Near matches: {', '.join(near[:10])}" if near else ""))
    out = ["# Ledger entry (latest)", json.dumps(_public(entry), indent=1)]
    story = PROTO / "rl_docs" / "runs" / f"{run}.md"
    if story.is_file():
        out += ["", "# Run story (rl_docs/runs/%s.md)" % run,
                story.read_text(errors="replace")]
    out.append("\n(run_metrics gives cached W&B curves; eval_report the "
               "gate-eval numbers, when present on this host.)")
    return _clip("\n".join(out))


def t_run_metrics(run: str, history_rows: int = 30) -> str:
    history_rows = max(1, min(int(history_rows), 200))
    d = PROTO / "logs" / "experiments" / run
    if not d.is_dir():
        return (f"no cached W&B data for {run!r} on this host "
                f"(logs/experiments/{run}/ missing — it is written by "
                f"`ops.sh wandbdump` when a run finishes).")
    out = [f"# Cached W&B data for {run}"]
    for name in ("wandb_summary.json", "wandb_config.json"):
        p = d / name
        if p.is_file():
            out += ["", f"## {name}", p.read_text(errors="replace")[:60_000]]
    hist = d / "wandb_history.csv"
    if hist.is_file():
        rows = list(csv.reader(io.StringIO(
            hist.read_text(errors="replace"))))
        if rows:
            keep = [rows[0]] + rows[1:][-history_rows:]
            out += ["", f"## wandb_history.csv (last {len(keep) - 1} of "
                        f"{len(rows) - 1} rows)",
                    "\n".join(",".join(r) for r in keep)]
    other = [p.name for p in sorted(d.iterdir())
             if p.name not in ("wandb_summary.json", "wandb_config.json",
                               "wandb_history.csv")]
    if other:
        out += ["", "## other cached files: " + ", ".join(other)]
    return _clip("\n".join(out))


def t_eval_report(run: str) -> str:
    snake = run.replace("-", "_")
    paths = sorted(
        _glob.glob(str(PROTO / "logs" / "ckpt_eval" / f"*{snake}*"
                       / "report.json")),
        key=os.path.getmtime, reverse=True)
    if not paths:
        return (f"no eval report matching {run!r} on this host "
                f"(logs/ckpt_eval/*{snake}*/report.json — reports are "
                f"copied back when the gate eval finishes).")
    out = []
    for p in paths[:3]:
        rel = os.path.relpath(p, PROTO)
        out += [f"# {rel}", pathlib.Path(p).read_text(errors="replace")]
    if len(paths) > 3:
        out.append(f"({len(paths) - 3} older matching reports not shown)")
    return _clip("\n\n".join(out))


def t_list_docs() -> str:
    by_dir: dict[str, list[str]] = {}
    n_runs = 0
    for rel in _doc_paths():
        if rel.startswith("rl_docs/runs/"):
            n_runs += 1
            continue
        try:
            size = (PROTO / rel).stat().st_size
        except OSError:
            size = 0
        d = os.path.dirname(rel) or "(root)"
        by_dir.setdefault(d, []).append(f"{rel} ({size // 1000} kB)")
    out = ["Every markdown doc in the prototype tree; fetch any of them "
           "with read_doc(path).", ""]
    for d in sorted(by_dir):
        out += [f"## {d}"] + [f"- {x}" for x in by_dir[d]] + [""]
    out.append(f"## rl_docs/runs — {n_runs} per-run stories, one per "
               f"launched run; read_doc('rl_docs/runs/<run>.md') or just "
               f"get_run(run).")
    return _clip("\n".join(out))


def t_read_doc(path: str) -> str:
    body = _read_doc(path)
    if body is None:
        return (f"{path!r} not found (must be a .md path relative to the "
                f"prototype tree — see list_docs).")
    return _clip(body, what=path)


def t_search_docs(query: str, regex: bool = False,
                  max_matches: int = 100) -> str:
    max_matches = max(1, min(int(max_matches), 400))
    try:
        pat = re.compile(query if regex else re.escape(query), re.I)
    except re.error as e:
        return f"bad regex: {e}"
    targets = _doc_paths()  # includes RL_LOG.md (root-level .md)
    hits, n = [], 0
    for rel in targets:
        text = _read_doc(rel)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:300]}")
                n += 1
                if n >= max_matches:
                    hits.append(f"[stopped at {max_matches} matches — "
                                f"narrow the query]")
                    return _clip("\n".join(hits))
    return _clip("\n".join(hits) if hits else f"no matches for {query!r}")


def _feedback_entries() -> list[dict]:
    out = []
    try:
        paths = sorted(FEEDBACK_DIR.glob("fb_*.json"), reverse=True)
    except OSError:
        return []
    for p in paths:
        try:
            out.append(json.loads(p.read_text(errors="replace")))
        except (OSError, ValueError):
            continue
    return out


def t_submit_feedback(feedback: str, topic: str = "", author: str = "",
                      _client_ip: str = "", _operator: bool = False) -> str:
    feedback = (feedback or "").strip()
    if not feedback:
        return "feedback text is empty — nothing filed."
    if len(feedback) > FEEDBACK_MAX_LEN:
        return (f"feedback is {len(feedback)} chars; the cap is "
                f"{FEEDBACK_MAX_LEN}. Trim it to the parts that matter "
                f"and resubmit.")
    now = time.time()
    times = [t for t in _fb_times.get(_client_ip, [])
             if now - t < FEEDBACK_RATE[1]]
    if len(times) >= FEEDBACK_RATE[0]:
        return (f"rate limit: max {FEEDBACK_RATE[0]} submissions per "
                f"hour per client — consolidate your notes into fewer, "
                f"richer entries.")
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    if len(list(FEEDBACK_DIR.glob("fb_*.json"))) >= FEEDBACK_MAX_FILES:
        return "feedback inbox is full — tell the operator out of band."
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now))
    fid = f"fb_{ts}_{os.urandom(3).hex()}"
    entry = {"id": fid, "utc": ts, "topic": (topic or "")[:200],
             "author": (author or "")[:200], "feedback": feedback,
             "client": _client_ip}  # for abuse triage; not shown publicly
    if _operator:
        # Authenticated with the dashboard token: stamp the entry so
        # cycles reading the inbox see it came from the operator. (The
        # watcher-side injected framing can't change without a watcher
        # restart; the stamp is the audit trail.)
        entry["operator"] = True
    tmp = FEEDBACK_DIR / (fid + ".tmp")
    tmp.write_text(json.dumps(entry, indent=1))
    tmp.rename(FEEDBACK_DIR / (fid + ".json"))
    _fb_times[_client_ip] = times + [now]
    op_note = (" OPERATOR-AUTHENTICATED: the entry is stamped "
               "\"operator\": true, so cycles reading the inbox know "
               "it carries operator weight." if _operator else "")
    return (f"filed as {fid} — the orchestrator agent reads it at the "
            f"start of its next decision cycle (as advisory input; it "
            f"cannot override the campaign's guardrails), and the "
            f"operator sees it on the dashboard. Concrete, evidence-"
            f"backed suggestions (run names, numbers, doc paths) are "
            f"the most actionable.{op_note}")


def t_list_feedback(limit: int = 20) -> str:
    limit = max(1, min(int(limit), 200))
    entries = _feedback_entries()
    if not entries:
        return "feedback inbox is empty — yours would be the first."
    out = [f"{len(entries)} entries, newest first (showing "
           f"{min(limit, len(entries))}):", ""]
    for e in entries[:limit]:
        head = e.get("utc", "?")
        if e.get("author"):
            head += f" · {e['author']}"
        if e.get("topic"):
            head += f" · {e['topic']}"
        head += (" · seen by the orchestrator"
                 if e.get("injected_utc") else " · not yet seen")
        out += [f"## {e.get('id', '?')} ({head})",
                e.get("feedback", "")[:2000], ""]
    return _clip("\n".join(out))


def _kick_state_note(n_ahead: int) -> str:
    """Honest queue/budget state for the acceptance message.

    Best-effort: the cycle-log dir and guardrails cap live on the
    controller pod; on a laptop (or any read failure) the missing
    pieces are just omitted. Never raises."""
    parts = [f"{n_ahead} kick{'s' if n_ahead != 1 else ''} queued "
             f"ahead of yours." if n_ahead else "No other kicks queued."]
    try:
        # Same file-based rolling-24h count as the watcher's
        # spawned_cycles_last_24h() — keep them matched.
        logs = pathlib.Path("/workspace/cycle_logs")
        if logs.is_dir():
            now = time.time()
            used = 0
            for p in logs.glob("cycle_*.log"):
                m = re.match(r"cycle_(\d{8}T\d{6})_", p.name)
                if not m:
                    continue
                try:
                    t = time.mktime(
                        time.strptime(m.group(1), "%Y%m%dT%H%M%S"))
                except ValueError:
                    continue
                if now - t < 86400:
                    used += 1
            cap = 96
            m = re.search(r"max_decision_cycles_per_day:\s*(\d+)",
                          (HERE / "guardrails.yaml").read_text())
            if m:
                cap = int(m.group(1))
            parts.append(
                f"Cycle budget: {used}/{cap} spawned in the rolling "
                f"24h" + (" — the budget is full, so this may wait "
                          "for it to roll over." if used >= cap
                          else "."))
    except OSError:
        pass
    return " ".join(parts)


def _file_operator_kick(focus: str, author: str) -> str:
    """Write (or append to) the TRUSTED operator KICK focus file."""
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    text = focus or ("(operator kick via MCP, no focus text — run a "
                     "normal deep review pass)")
    if author:
        text += f"\n[filed via MCP operator lane by: {author}, {ts}Z]"
    OPERATOR_KICK_FILE.parent.mkdir(parents=True, exist_ok=True)
    appended = OPERATOR_KICK_FILE.exists()
    if appended:
        # The watcher hasn't consumed the pending KICK yet (~2s
        # pickup) — append rather than clobber the earlier focus.
        old = OPERATOR_KICK_FILE.read_text(errors="replace").rstrip()
        text = f"{old}\n\n--- additional operator kick ({ts}Z) ---\n{text}"
    OPERATOR_KICK_FILE.write_text(text + "\n")
    return ("appended to the pending operator KICK file (the watcher "
            "hadn't consumed it yet — both focus notes ride in one "
            "deep session)" if appended
            else "trusted operator KICK file written")


def t_list_operator_questions() -> str:
    p = HERE / "OPERATOR_QUESTIONS.md"
    try:
        return _clip(p.read_text(errors="replace"))
    except OSError:
        return ("no OPERATOR_QUESTIONS.md yet — no cycle has hit a "
                "rule conflict while executing an operator order.")


# Watcher-side paths mirrored here for the live-activity view (same
# constants as watch_loop.py / status_server.py on the controller).
WATCHER_LOG = pathlib.Path("/workspace/orchestrator.log")
CYCLE_LOG_DIR = pathlib.Path("/workspace/cycle_logs")
PAUSE_FLAG = HERE / "PAUSE"

_SPAWN_RE = re.compile(
    r"^\[([^\]]+)\] cycle spawned pid=(\d+) model=(\S+) for: (.+?) "
    r"\(log: (\S+)\)")


def t_orchestrator_activity() -> str:
    """Live view: what the watcher and its decision cycles are doing
    RIGHT NOW — poll this after kick_orchestrator instead of
    re-kicking. (Operator 08-15: kicks were silently in-progress for
    10-30 min and impatient clients kept filing duplicates.)"""
    out = ["# Orchestrator activity (live)"]
    now = time.time()
    # Watcher heartbeat: the loop logs every poll, so a stale log
    # means the watcher is down or restarting.
    try:
        age = now - WATCHER_LOG.stat().st_mtime
        state = ("UP" if age < 400 else
                 f"SILENT for {int(age // 60)} min — down or restarting")
    except OSError:
        state, age = "no watcher log on this host (laptop dev?)", None
    if PAUSE_FLAG.exists():
        state += " · PAUSED (cycle spawns held; training unaffected)"
    out.append(f"watcher: {state}")

    # Pending (not yet consumed) kick requests.
    pending = []
    if OPERATOR_KICK_FILE.exists():
        pending.append("operator KICK filed, not yet consumed (watcher "
                       "picks it up within ~2 s when a slot is free)")
    try:
        q = len(list(KICK_DIR.glob("kick_*.json")))
        if q:
            pending.append(f"{q} advisory-queue kick(s) waiting")
    except OSError:
        pass
    out.append("pending kicks: " + ("; ".join(pending) or "none — every "
               "filed kick has been consumed by a cycle"))

    # Decision cycles: parse recent spawn lines, keep pids still alive.
    lines = []
    try:
        lines = WATCHER_LOG.read_bytes()[-60_000:].decode(
            errors="replace").splitlines()
    except OSError:
        pass
    alive, dead_recent = [], []
    for ln in lines:
        m = _SPAWN_RE.match(ln)
        if not m:
            continue
        ts, pid, model, label, logp = m.groups()
        entry = f"{label} (model {model}, spawned {ts})"
        if pathlib.Path(f"/proc/{pid}").exists():
            alive.append(entry + " — STILL RUNNING; cycles write their "
                         "summary only at exit")
        else:
            dead_recent.append(entry + " — finished (see log_tail for "
                               "its RL_LOG line)")
    out.append("\nactive cycles (%d):" % len(alive))
    out += ["- " + a for a in alive] or ["- none"]
    if dead_recent:
        out.append("\nrecently finished cycles:")
        out += ["- " + d for d in dead_recent[-5:]]

    # Freshest ledger rows — INTENT means a cycle is mid-launch for
    # that run RIGHT NOW (row appears before the process is verified).
    rows = _ledger()[:6]
    out.append("\nnewest ledger rows (INTENT = launch in progress, "
               "flips to RUNNING once the process + W&B id are "
               "verified):")
    for e in rows:
        out.append(f"- {e.get('run')}: {e.get('status')} "
                   f"(created {(e.get('created') or '')[:16]})")

    # Watcher log tail: spawn/wait/refusal lines tell you WHY a kick
    # is waiting (cycle cap, daily budget) without guessing.
    tail = [ln for ln in lines if ln.strip()][-12:]
    out.append("\nwatcher log tail:")
    out += ["  " + ln for ln in tail] or ["  (empty)"]
    out.append(
        "\nHOW TO WAIT ON A KICK: a deep operator-kick cycle takes "
        "10-30 min and is SILENT until it exits. If your kick's cycle "
        "shows above as STILL RUNNING, or your run shows INTENT, it "
        "is being worked on — do NOT re-kick (a duplicate cycle just "
        "burns budget rediscovering the first one's work). Re-kick "
        "only if the cycle finished without your item appearing "
        "anywhere above or in log_tail.")
    return _clip("\n".join(out))


def t_kick_orchestrator(focus: str = "", author: str = "",
                        _client_ip: str = "", _operator: bool = False) -> str:
    focus = (focus or "").strip()
    if len(focus) > KICK_MAX_LEN:
        return (f"focus note is {len(focus)} chars; the cap is "
                f"{KICK_MAX_LEN}. A kick is a pointer, not an essay — "
                f"put the long analysis in submit_feedback and "
                f"reference it here.")
    try:
        n_ahead = len(list(KICK_DIR.glob("kick_*.json")))
    except OSError:
        n_ahead = 0
    if _operator:
        # Authenticated with the dashboard token: this is the OPERATOR.
        # No flood guards; file the trusted KICK the watcher runs as a
        # deep-model, do-what-the-focus-note-asks session.
        how = _file_operator_kick(focus, author)
        return (f"OPERATOR-AUTHENTICATED — trusted operator kick filed; "
                f"deep-model session, does what the focus note asks. "
                f"({how}.) {_kick_state_note(n_ahead)} The watcher "
                f"picks the KICK file up within ~2 s, but the cycle "
                f"itself is SILENT for 10-30 min while it works (it "
                f"writes its RL_LOG line only at exit). Poll "
                f"orchestrator_activity to watch progress — your "
                f"cycle listed as running, or your run at INTENT, "
                f"means it IS being worked on; do NOT re-kick while "
                f"that is true.")
    # Extreme flood guard ONLY — normal usage never sees a refusal.
    if n_ahead >= KICK_FLOOD_PENDING:
        return (f"flood guard: {n_ahead} kick requests are already "
                f"queued (threshold {KICK_FLOOD_PENDING}) — that depth "
                f"only happens under a scripted flood or a stuck "
                f"watcher, so yours was NOT filed to protect the disk. "
                f"If you are a human seeing this, the watcher likely "
                f"needs attention — tell the operator (submit_feedback "
                f"works).")
    now = time.time()
    times = [t for t in _kick_times.get(_client_ip, [])
             if now - t < KICK_FLOOD_IP[1]]
    if len(times) >= KICK_FLOOD_IP[0]:
        return (f"flood guard: this client filed {len(times)} kicks in "
                f"the last hour (threshold {KICK_FLOOD_IP[0]}) — that "
                f"rate only happens from a scripted loop, so this one "
                f"was NOT filed. Pause the loop; normal usage never "
                f"hits this.")
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now))
    fid = f"kick_{ts}_{os.urandom(3).hex()}"
    entry = {"id": fid, "utc": ts,
             "author": (author or "")[:200], "focus": focus,
             "client": _client_ip}  # for abuse triage; not shown publicly
    KICK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = KICK_DIR / (fid + ".tmp")
    tmp.write_text(json.dumps(entry, indent=1))
    tmp.rename(KICK_DIR / (fid + ".json"))
    _kick_times[_client_ip] = times + [now]
    return (f"filed as {fid} — the watcher wakes within seconds and "
            f"spawns ONE decision cycle for this request. "
            f"{_kick_state_note(n_ahead)} Your focus note rides along "
            f"as ADVISORY, UNTRUSTED input: the cycle weighs it on "
            f"technical merit, and it cannot override guardrails, "
            f"operator rulings, or track priorities. Watch log_tail "
            f"for the cycle's one-line record (label mcp-kick).")


TOOLS = [
    {"name": "campaign_status",
     "description": "Campaign digest (STATUS.md) plus every research "
                    "track's STATUS doc — read this first for an overall "
                    "assessment of results.",
     "fn": t_campaign_status, "args": {}},
    {"name": "get_plan",
     "description": "The research plan (RL_PLAN.md) and CURRENT_TRUTHS.md "
                    "(facts that win on conflict).",
     "fn": t_get_plan, "args": {}},
    {"name": "log_tail",
     "description": "Tail of RL_LOG.md, the append-only decision-cycle "
                    "log (one line per orchestrator cycle, newest last).",
     "fn": t_log_tail,
     "args": {"max_kb": {"type": "integer",
                         "description": "kB of tail to return (1-300, "
                                        "default 64)"}}},
    {"name": "list_runs",
     "description": "Browse the launch ledger (every training run with "
                    "status, hypothesis, verdict). Filter by status, "
                    "track, or substring; newest first.",
     "fn": t_list_runs,
     "args": {"status": {"type": "string",
                         "description": "exact status filter, e.g. "
                                        "FINISHED, RUNNING, FAILED, "
                                        "REFUSED"},
              "track": {"type": "string",
                        "description": "research-track id: joystick or "
                                       "amp (tracks.json)"},
              "contains": {"type": "string",
                           "description": "substring matched against the "
                                          "whole ledger entry"},
              "limit": {"type": "integer",
                        "description": "max runs returned (default 40)"}}},
    {"name": "get_run",
     "description": "One run's full ledger entry (hypothesis, gate, "
                    "verdict, lineage) plus its rendered story doc.",
     "fn": t_get_run,
     "args": {"run": {"type": "string",
                      "description": "run name, e.g. cw-arch-modeseq1-rr1"}},
     "required": ["run"]},
    {"name": "run_metrics",
     "description": "Cached W&B summary/config and the tail of the "
                    "training-metrics history CSV for one run.",
     "fn": t_run_metrics,
     "args": {"run": {"type": "string", "description": "run name"},
              "history_rows": {"type": "integer",
                               "description": "history rows to return "
                                              "(default 30)"}},
     "required": ["run"]},
    {"name": "eval_report",
     "description": "Gate-eval report.json for a run or checkpoint "
                    "(deterministic + stochastic episode metrics).",
     "fn": t_eval_report,
     "args": {"run": {"type": "string",
                      "description": "run or checkpoint name"}},
     "required": ["run"]},
    {"name": "list_docs",
     "description": "Index of every design/research doc (rewards, gait, "
                    "evals, sim, hardware, per-run stories).",
     "fn": t_list_docs, "args": {}},
    {"name": "read_doc",
     "description": "Read one doc by path relative to the prototype "
                    "tree, e.g. rl_docs/REWARD.md or STATUS.md.",
     "fn": t_read_doc,
     "args": {"path": {"type": "string", "description": "doc path"}},
     "required": ["path"]},
    {"name": "search_docs",
     "description": "Search every doc plus RL_LOG.md for a string or "
                    "regex; returns path:line matches.",
     "fn": t_search_docs,
     "args": {"query": {"type": "string", "description": "search text"},
              "regex": {"type": "boolean",
                        "description": "treat query as a regex "
                                       "(default false)"},
              "max_matches": {"type": "integer",
                              "description": "cap on matches "
                                             "(default 100)"}},
     "required": ["query"]},
    {"name": "submit_feedback",
     "description": "File feedback on the campaign (observations, "
                    "critiques, suggested experiments) into the "
                    "operator-reviewed inbox. Not auto-executed; the "
                    "human reads it on the dashboard. Cite run names, "
                    "numbers, and doc paths so it's actionable — this "
                    "endpoint is private (operator-keyed), so those "
                    "details are fine. Entries are operator-stamped "
                    "so cycles weight them accordingly.",
     "fn": t_submit_feedback,
     "args": {"feedback": {"type": "string",
                           "description": "the feedback text (markdown "
                                          "fine, max 8000 chars)"},
              "topic": {"type": "string",
                        "description": "short subject line, e.g. a run "
                                       "name or track"},
              "author": {"type": "string",
                         "description": "who/what you are, e.g. "
                                        "'GPT-5 via ChatGPT, asked by "
                                        "Lukas'"}},
     "required": ["feedback"]},
    {"name": "list_feedback",
     "description": "Read the feedback inbox (newest first) — check "
                    "before filing to avoid duplicating an existing "
                    "note.",
     "fn": t_list_feedback,
     "args": {"limit": {"type": "integer",
                        "description": "entries to show (default 20)"}}},
    {"name": "orchestrator_activity",
     "description": "Live watcher/cycle status: pending kicks, decision "
                    "cycles currently running (with age/model/label), "
                    "newest ledger rows including mid-launch INTENT "
                    "entries, and the watcher log tail. POLL THIS after "
                    "kick_orchestrator instead of re-kicking — deep "
                    "cycles are silent for 10-30 min while they work.",
     "fn": t_orchestrator_activity, "args": {}},
    {"name": "list_operator_questions",
     "description": "The obey-then-ask log (OPERATOR_QUESTIONS.md): "
                    "rule conflicts that cycles hit while executing "
                    "operator orders — each executed anyway and filed "
                    "here as a question. The operator answers via "
                    "submit_feedback WITH the dashboard token; the "
                    "next cycle updates the rulebook to match and "
                    "closes the question.",
     "fn": t_list_operator_questions, "args": {}},
    {"name": "kick_orchestrator",
     "description": "Request an on-demand orchestrator decision cycle "
                    "(the LLM that triages runs and refills the "
                    "pipeline). This endpoint is operator-keyed, so "
                    "the kick files the TRUSTED operator KICK: the "
                    "watcher wakes within seconds and spawns a "
                    "deep-model session that does what the focus note "
                    "asks. Each cycle counts against the campaign's "
                    "daily cycle budget, so for observations that "
                    "don't need a cycle NOW, consider submit_feedback "
                    "instead.",
     "fn": t_kick_orchestrator,
     "args": {"focus": {"type": "string",
                        "description": "what the cycle should look at "
                                       "— run names, doc paths, a "
                                       "question (max 2000 chars; "
                                       "empty = normal review pass)"},
              "author": {"type": "string",
                         "description": "who/what you are, e.g. "
                                        "'GPT-5 via ChatGPT, asked by "
                                        "Lukas'"}}},
]


def tool_specs() -> list[dict]:
    return [{"name": t["name"], "description": t["description"],
             "inputSchema": {"type": "object",
                             "properties": t["args"],
                             "required": t.get("required", [])}}
            for t in TOOLS]


def call_tool(name: str, args: dict, client_ip: str = "",
              operator: bool = False) -> tuple[str, bool]:
    """Returns (text, is_error). Raises KeyError for unknown tools."""
    tool = next(t for t in TOOLS if t["name"] == name)
    kwargs = {k: v for k, v in (args or {}).items() if k in tool["args"]}
    if tool["name"] in ("submit_feedback", "kick_orchestrator"):
        kwargs["_client_ip"] = client_ip  # rate limiting / abuse triage
        kwargs["_operator"] = operator    # token-authenticated lane
    try:
        return tool["fn"](**kwargs), False
    except Exception as e:  # tool errors go IN the result per MCP spec
        return f"tool {name} failed: {e!r}", True


# ------------------------------------------------------------- JSON-RPC
SESSION_ID = f"hexapod-{int(time.time()):x}"  # stateless; any id accepted


def _rpc_one(msg: dict, client_ip: str = "",
             operator: bool = False) -> dict | None:
    """One JSON-RPC message -> response dict (None for notifications)."""
    rid, method = msg.get("id"), msg.get("method", "")
    params = msg.get("params") or {}
    if rid is None:  # notification (notifications/initialized etc.)
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": code, "message": text}}

    if method == "initialize":
        want = params.get("protocolVersion", "")
        ver = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return ok({"protocolVersion": ver,
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": SERVER_INFO,
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_specs()})
    if method == "tools/call":
        name = params.get("name", "")
        if not any(t["name"] == name for t in TOOLS):
            return err(-32602, f"unknown tool: {name}")
        text, is_err = call_tool(name, params.get("arguments") or {},
                                 client_ip, operator)
        return ok({"content": [{"type": "text", "text": text}],
                   "isError": is_err})
    if method in ("resources/list", "resources/templates/list"):
        key = "resourceTemplates" if "templates" in method else "resources"
        return ok({key: []})
    if method == "prompts/list":
        return ok({"prompts": []})
    return err(-32601, f"method not found: {method}")


CORS = {"Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS, DELETE",
        "Access-Control-Allow-Headers":
            "Content-Type, Accept, Authorization, Mcp-Session-Id, "
            "Mcp-Protocol-Version, Last-Event-ID",
        "Access-Control-Expose-Headers": "Mcp-Session-Id"}


def handle_http(method: str, body: bytes, client_ip: str = "",
                operator: bool = False, headers=None,
                query: str = "") -> tuple[int, dict, bytes]:
    """Transport-agnostic entry: (status, headers, body) for /mcp.

    Every request must present the operator's MCP key (checked here
    against AUTH_KEY) or arrive with operator=True (the transport
    verified the dashboard STATUS_TOKEN — status_server._mcp_operator).
    Either way the caller is one of the operator's own clients, so all
    authenticated requests run the trusted operator lane."""
    h = dict(CORS)
    if method == "OPTIONS":  # CORS preflight cannot carry credentials
        return 204, h, b""
    if not (operator or _authed(headers, query)):
        if not AUTH_KEY:
            return 503, h, (b"503: no MCP auth key configured on this "
                            b"host (MCP_AUTH_KEY env or key file) - "
                            b"endpoint disabled.")
        h["WWW-Authenticate"] = "Bearer"
        return 401, h, (b"401: this is the operator's private MCP "
                        b"endpoint. Send the operator-issued key as "
                        b"'Authorization: Bearer <key>', 'X-Api-Key: "
                        b"<key>', or '?key=<key>' on the /mcp URL.")
    operator = True  # past the gate = the operator's own client
    if method == "DELETE":  # client ended its session — nothing to drop
        return 200, h, b""
    if method != "POST":
        h["Allow"] = "POST, OPTIONS, DELETE"
        return 405, h, b"MCP endpoint: POST JSON-RPC here (streamable " \
                       b"HTTP, no server event stream)."
    try:
        msg = json.loads(body.decode())
    except ValueError:
        h["Content-Type"] = "application/json"
        return 400, h, json.dumps(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32700, "message": "parse error"}}).encode()
    msgs = msg if isinstance(msg, list) else [msg]
    replies = [r for m in msgs if isinstance(m, dict)
               for r in [_rpc_one(m, client_ip, operator)] if r is not None]
    if any(isinstance(m, dict) and m.get("method") == "initialize"
           for m in msgs):
        h["Mcp-Session-Id"] = SESSION_ID
    if not replies:  # notifications only
        return 202, h, b""
    out = replies if isinstance(msg, list) else replies[0]
    h["Content-Type"] = "application/json"
    return 200, h, json.dumps(out).encode()


# ------------------------------------------------- standalone (dev only)
def main() -> int:
    import http.server

    port = int(os.environ.get("MCP_PORT", "8091"))

    class Handler(http.server.BaseHTTPRequestHandler):
        def _serve(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            query = (self.path.split("?", 1) + [""])[1]
            status, headers, out = handle_http(self.command, body,
                                               self.client_address[0],
                                               headers=self.headers,
                                               query=query)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = do_OPTIONS = do_DELETE = _serve

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"MCP server (dev standalone) on :{port} — POST /mcp or /")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
