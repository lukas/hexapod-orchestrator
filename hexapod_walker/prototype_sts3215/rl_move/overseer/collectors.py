"""Bounded, read-only discovery for the manual project overseer.

Discovery is not registration or authority to control a process. Source status,
activity and measured progress remain distinct. No collector starts an agent,
reads credentials, sends a message, accesses the network or changes a service.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import itertools
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import tomllib
from typing import Any

MAX_FILES = 200
MAX_JOBS = 200
MAX_JSON_BYTES = 65536
MAX_TAIL_BYTES = 65536
MAX_LAB_HISTORY = 30
FRESH_SECONDS = 6 * 3600
SERVICE_LABELS = (
    "com.lbiewald.hexapod-lab",
    "com.lbiewald.hexapod-lab2",
    "com.lbiewald.hexapod-camera-tunnel",
    "com.lukas.hexapod-web-8898",
    "com.lukas.hexapod-vision-8766",
)
_SECRET = re.compile(
    r"(?i)(?:bearer\s+\S+|\b(?:sk-[\w-]+)|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|authorization)"
    r"[\s\"']*[:=][\s\"']*[^\s,;\"']+)"
)
_URL = re.compile(r"https?://[^\s<>]+")


def sanitize(value: Any, limit: int = 240) -> str:
    """Defense in depth for selected metadata; never pass full prompts here."""
    text = str(value).replace("\x00", " ")
    text = _SECRET.sub("[redacted]", text)
    text = _URL.sub(lambda m: m.group(0).split("?", 1)[0].split("#", 1)[0]
                    if "@" not in m.group(0) else "[redacted-url]", text)
    return " ".join(text.split())[:limit]


def _time(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _stamp(value: Any = None) -> str:
    dt = _time(value) if value is not None else datetime.now(timezone.utc)
    if dt is None:
        raise ValueError("Invalid observation time")
    return dt.isoformat().replace("+00:00", "Z")


def _freshness(updated: Any, now: str) -> dict:
    dt = _time(updated)
    if dt is None:
        return {"source_updated_at": None, "source_age_seconds": None, "freshness": "unknown"}
    age = max(0, (_time(now) - dt).total_seconds())
    return {"source_updated_at": _stamp(dt.isoformat()), "source_age_seconds": age,
            "freshness": "fresh" if age <= FRESH_SECONDS else "stale"}


def _error(source: Any, code: str, message: str) -> dict:
    return {"source": sanitize(source), "code": code, "message": sanitize(message)}


def _read_json(path: Path) -> dict:
    with path.open("rb") as handle:
        raw = handle.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("metadata exceeds bounded read size")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("metadata is not an object")
    return result


def _tail_events(path: Path) -> list[dict]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        offset = max(0, size - MAX_TAIL_BYTES)
        handle.seek(offset)
        raw = handle.read(MAX_TAIL_BYTES)
    lines = raw.splitlines()
    if offset:
        lines = lines[1:]
    events = []
    for line in lines[-200:]:
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except (ValueError, UnicodeError):
            continue
    return events


def _project_path(value: Any, project_root: Path, lab_root: Path | None = None) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value).expanduser()
    try:
        resolved = path.resolve()
        if resolved.is_relative_to(project_root.resolve()):
            return True
        if lab_root and resolved.is_relative_to(lab_root.resolve()):
            return True
    except (OSError, ValueError):
        pass
    # The repository has independent clones and /tmp worktrees. Their recorded
    # cwd is project evidence, not permission to act or proof of installed CAD.
    return any(part.lower() == "hexapod" or part.lower().startswith("hexapod-")
               or part.lower() == "hexapod project" for part in path.parts)


def _agent(agent_id: str, name: Any, provider: str, scope: str,
           status: str, source: Any, now: str, **extra: Any) -> dict:
    return {"agent_id": sanitize(agent_id), "task_id": sanitize(agent_id),
            "name": sanitize(name), "provider": provider, "scope": scope,
            "status": status, "goals": ["unknown"], "source": sanitize(source),
            "observed_at": now, "cost_status": "unknown", "evidence": [], **extra}


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=3, check=False)


def _processes(errors: list[dict]) -> dict[int, str] | None:
    try:
        result = _run(["ps", "-axo", "pid=,stat=,comm="])
        if result.returncode:
            raise OSError("process inventory unavailable")
        # comm contains executable names, not argv/prompts/environment; only the
        # PID and state leave this function.
        return {int(row[0]): row[1] for line in result.stdout.splitlines()
                if len(row := line.split(None, 2)) == 3 and row[0].isdigit()}
    except (OSError, subprocess.SubprocessError):
        errors.append(_error("ps", "unavailable", "Process state could not be read; liveness unknown"))
        return None


def _claude(home: Path, project_root: Path, lab_root: Path, now: str,
            processes: dict[int, str] | None, errors: list[dict]) -> list[dict]:
    directory = home / ".claude/sessions"
    if not directory.is_dir():
        errors.append(_error(directory, "unavailable", "Claude session metadata directory unavailable"))
        return []
    paths = list(itertools.islice(directory.glob("*.json"), MAX_FILES + 1))
    if len(paths) > MAX_FILES:
        errors.append(_error(directory, "truncated", "Claude session scan reached its file limit"))
    agents = []
    for path in paths[:MAX_FILES]:
        try:
            meta = _read_json(path)
            sid = str(meta.get("sessionId", ""))
            if not re.fullmatch(r"[\w-]{1,100}", sid):
                continue
            events = []
            candidates = list(itertools.islice((home / ".claude/projects").glob(f"*/{sid}.jsonl"), 2))
            for transcript in candidates:
                events.extend(_tail_events(transcript))
            related = _project_path(meta.get("cwd"), project_root, lab_root) or any(
                _project_path(event.get("cwd"), project_root, lab_root) for event in events)
            if not related:
                continue
            freshness = _freshness(meta.get("updatedAt"), now)
            reported = str(meta.get("status", "unknown")).lower()
            status = {"working": "running", "active": "running", "busy": "running"}.get(reported, reported)
            if status not in {"running", "idle", "blocked", "completed", "succeeded", "failed", "stopped"}:
                status = "unknown"
            pid = meta.get("pid")
            pid = int(pid) if str(pid).isdigit() else None
            process_state = processes.get(pid) if processes is not None else None
            if processes is not None and (not process_state or "Z" in process_state):
                status = "stopped"
            elif status == "running" and (processes is None or freshness["freshness"] != "fresh"):
                status = "unknown"
            timestamps = [_time(e.get("timestamp")) for e in events if e.get("type") in {"assistant", "result"}]
            timestamps = [t for t in timestamps if t is not None]
            evidence = [f"Session reports {sanitize(reported)}; process state {sanitize(process_state or 'unknown')}.",
                        "Transcript read is a bounded metadata sample; activity is not verified goal progress."]
            if timestamps:
                evidence.append(f"Latest sampled assistant event: {_stamp(max(timestamps).isoformat())}.")
            agent = _agent(f"claude:{sid}", meta.get("name") or sid, "claude", "interactive", status,
                           path, now, **freshness, reported_status=sanitize(reported), evidence=evidence)
            # A bounded transcript tail cannot establish cumulative lifetime cost.
            for key in ("total_cost_usd", "totalCostUSD", "costUSD"):
                value = meta.get(key)
                if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                    agent.update(cost_status="known", reported_cost_usd=float(value))
                    break
            agents.append(agent)
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(_error(path, "unavailable", f"Session metadata unreadable ({type(exc).__name__})"))
    return agents


def _automations(home: Path, project_root: Path, now: str, errors: list[dict]) -> list[dict]:
    directory = home / ".codex/automations"
    if not directory.is_dir():
        errors.append(_error(directory, "unavailable", "Codex automation metadata unavailable"))
        return []
    rows = []
    paths = list(itertools.islice(directory.glob("*/automation.toml"), MAX_FILES + 1))
    if len(paths) > MAX_FILES:
        errors.append(_error(directory, "truncated", "Automation scan reached its file limit"))
    for path in paths[:MAX_FILES]:
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise ValueError("automation metadata too large")
            data = tomllib.loads(raw.decode())
            # Prompts are inspected only for project association and never emitted.
            association = " ".join(str(data.get(key, "")) for key in ("name", "prompt", "cwds"))
            if "hexapod" not in association.lower() and str(project_root) not in association:
                continue
            rows.append({"automation_id": sanitize(data.get("id", path.parent.name)),
                         "name": sanitize(data.get("name", path.parent.name)),
                         "status": sanitize(data.get("status", "unknown")).lower(),
                         "kind": sanitize(data.get("kind", "unknown")),
                         "source": str(path), "observed_at": now,
                         **_freshness(data.get("updated_at", path.stat().st_mtime), now)})
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(_error(path, "unavailable", f"Automation metadata unreadable ({type(exc).__name__})"))
    return rows


def _services(now: str, errors: list[dict]) -> list[dict]:
    rows = []
    domain = f"gui/{os.getuid()}"
    try:
        disabled = _run(["launchctl", "print-disabled", domain])
        if disabled.returncode:
            raise OSError("disabled-state query failed")
    except (OSError, subprocess.SubprocessError):
        errors.append(_error("launchctl", "unavailable", "Service enablement unavailable on this host"))
        return rows
    for label in SERVICE_LABELS:
        match = re.search(r'"' + re.escape(label) + r'"\s*=>\s*(true|false|enabled|disabled)', disabled.stdout)
        enabled = match.group(1) in {"false", "enabled"} if match else None
        status = "disabled" if enabled is False else "unknown"
        try:
            result = _run(["launchctl", "print", f"{domain}/{label}"])
            state = re.search(r"^\s*state = ([\w ]+)$", result.stdout, re.MULTILINE)
            if result.returncode == 0:
                if enabled is not False:
                    status = "running" if state and state.group(1) == "running" else "loaded"
            elif enabled is not False:
                if "Could not find service" in result.stderr or "Could not find service" in result.stdout:
                    status = "not_loaded"
                else:
                    status = "unknown"
                    errors.append(_error(label, "unavailable", "Service query failed; load state is unknown"))
            rows.append({"service_id": label, "name": label, "status": status,
                         "enabled": enabled, "source": f"launchctl:{label}", "observed_at": now,
                         "evidence": ["Service state is not evidence that its agents are making progress."]})
        except (OSError, subprocess.SubprocessError):
            errors.append(_error(label, "unavailable", "Service state query timed out or failed"))
    return rows


def _elapsed_seconds(started: Any, finished: Any) -> float | None:
    start, finish = _time(started), _time(finished)
    if start is None or finish is None or finish < start:
        return None
    return round((finish - start).total_seconds(), 3)


def _lab2(lab_root: Path, now: str, errors: list[dict]) -> tuple[list[dict], dict]:
    """Export bounded Robot Lab v2 throughput and findings, not artifact paths or logs.

    v2 is the only lab since 2026-09-11; the original lab's lab.sqlite3 job
    tables are history and are not read.
    """
    data_dir = lab_root / "v2"
    database = data_dir / "lab2.sqlite3"
    if not database.is_file():
        errors.append(_error(database, "unavailable", "Robot Lab v2 database unavailable"))
        return [], {}
    services: list[dict] = []
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)) as connection:
            connection.row_factory = sqlite3.Row
            deadline = time.monotonic() + 1
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"plans", "runs"}.issubset(tables):
                raise ValueError("Robot Lab v2 schema unavailable")
            plan_counts = {sanitize(row["status"]): row["count"] for row in connection.execute(
                "SELECT status,COUNT(*) AS count FROM plans GROUP BY status LIMIT 20")}
            run_counts = {sanitize(row["status"]): row["count"] for row in connection.execute(
                "SELECT status,COUNT(*) AS count FROM runs GROUP BY status LIMIT 20")}
            updated = connection.execute(
                "SELECT MAX(COALESCE(finished_at,started_at)) FROM runs").fetchone()[0]
            services.extend([
                {"service_id": "lab2:plans", "name": "Robot Lab v2 plans",
                 "status": "paused" if (data_dir / "PAUSE").exists() else "observed",
                 "source": str(database), "observed_at": now, "source_updated_at": updated,
                 "counts": plan_counts},
                {"service_id": "lab2:runs", "name": "Robot Lab v2 runs", "status": "observed",
                 "source": str(database), "observed_at": now, "source_updated_at": updated,
                 "counts": run_counts},
            ])
            rows = connection.execute(
                "SELECT runs.id,runs.started_at,runs.finished_at,runs.status,runs.exit_code,"
                "runs.summary_json,plans.title,plans.why,plans.protocol,plans.kind,plans.source "
                "FROM runs JOIN plans ON plans.id=runs.plan_id "
                f"ORDER BY runs.started_at DESC,runs.rowid DESC LIMIT {MAX_LAB_HISTORY}"
            ).fetchall()
            recent_runs = []
            for row in rows:
                item = dict(row)
                finding = None
                if "learnings" in tables:
                    learned = connection.execute(
                        "SELECT text FROM learnings WHERE run_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                        (item["id"],)).fetchone()
                    finding = learned[0] if learned else None
                summary = None
                try:
                    parsed = json.loads(item.get("summary_json") or "null")
                    if isinstance(parsed, dict):
                        summary = sanitize(json.dumps(parsed, sort_keys=True), 700)
                except (TypeError, ValueError):
                    pass
                recent_runs.append({
                    "run_id": sanitize(item["id"]), "title": sanitize(item["title"], 300),
                    "protocol": sanitize(item.get("protocol") or item.get("kind"), 200),
                    "why": sanitize(item.get("why"), 400), "status": sanitize(item["status"]),
                    "started_at": item.get("started_at"), "finished_at": item.get("finished_at"),
                    "wall_seconds": _elapsed_seconds(item.get("started_at"), item.get("finished_at")),
                    "exit_code": item.get("exit_code"), "source": sanitize(item.get("source")),
                    "finding": sanitize(finding, 500) if finding else None,
                    "runner_summary": summary,
                })
            spend = []
            if "spend" in tables:
                spend = [{"kind": sanitize(row["kind"]), "usd": row["usd"],
                          "created_at": row["created_at"]} for row in connection.execute(
                    "SELECT kind,usd,created_at FROM spend ORDER BY created_at DESC,rowid DESC LIMIT 60")]
            events = []
            if "events" in tables:
                events = [{"kind": sanitize(row["kind"]), "created_at": row["created_at"],
                           "text": sanitize(row["text"], 700)} for row in connection.execute(
                    "SELECT kind,created_at,text FROM events ORDER BY created_at DESC,rowid DESC LIMIT 20")]
            return services, {"robot_lab_v2": {"source": str(database),
                "queue_counts": plan_counts, "run_counts": run_counts,
                "recent_runs": recent_runs, "recent_spend": spend, "recent_events": events,
                "timing_contract": {"health_seconds": 10, "postrun_seconds": 60,
                                    "planning_seconds": 120, "run_timeout_seconds": 900}}}
    except (OSError, sqlite3.Error, ValueError) as exc:
        errors.append(_error(database, "unavailable", f"Read-only Robot Lab v2 query failed ({type(exc).__name__})"))
        return services, {}


def collect_local(project_root: Path, home: Path | None = None,
                  lab_root: Path | None = None, now: str | None = None) -> dict:
    """Collect local project observations with bounded reads and explicit gaps."""
    project_root, home = Path(project_root), Path(home) if home is not None else Path.home()
    lab_root = Path(lab_root) if lab_root is not None else home / "Library/Application Support/Hexapod Lab"
    observed = _stamp(now)
    result = {"collected_at": observed, "agents": [], "services": [], "automations": [],
              "portfolio_evidence": {}, "errors": []}
    errors = result["errors"]
    processes = _processes(errors)
    result["agents"] = _claude(home, project_root, lab_root, observed, processes, errors)
    lab2_services, lab2_portfolio = _lab2(lab_root, observed, errors)
    result["services"] = lab2_services + _services(observed, errors)
    result["portfolio_evidence"].update(lab2_portfolio)
    for service in result["services"]:
        service.setdefault("state", service["status"])
        service.setdefault("kind", "queue" if service["service_id"] == "lab2:plans" else "service")
        service.setdefault("domain", "robot_lab" if service["service_id"].startswith("lab2:") else "local")
        service.setdefault("desired_state", "paused" if service["status"] == "paused" else
                           "disabled" if service.get("enabled") is False else "unknown")
    result["automations"] = _automations(home, project_root, observed, errors)
    return result


def _unwrap(value: Any) -> Any:
    for _ in range(6):
        if isinstance(value, str):
            try:
                value = json.loads(value)
                continue
            except ValueError:
                return value
        if isinstance(value, dict) and "structuredContent" in value:
            value = value["structuredContent"]
        elif isinstance(value, dict) and isinstance(value.get("content"), list):
            value = "\n".join(str(item.get("text", "")) for item in value["content"] if isinstance(item, dict))
        elif isinstance(value, dict) and "result" in value:
            value = value["result"]
        else:
            return value
    return value


def normalize_cloud_activity(text: Any, now: str | None = None) -> dict:
    """Normalize authenticated activity output; never promote historical PIDs."""
    observed = _stamp(now)
    text = _unwrap(text)
    result = {"collected_at": observed, "agents": [], "services": [], "errors": []}
    if not isinstance(text, str):
        result["errors"].append(_error("rl:mcp:orchestrator_activity", "unrecognized", "Expected activity text"))
        return result
    text = text[:131072]
    watcher = re.search(r"^watcher:\s*([^\n]+)", text, re.MULTILINE)
    watcher_service = None
    if watcher:
        watcher_state = watcher.group(1)
        status = "paused" if "PAUSED" in watcher_state else "running" if watcher_state.startswith("UP") else "unknown"
        watcher_service = {"service_id": "cloud:watcher", "name": "Cloud RL watcher",
                           "status": status, "state": status, "kind": "controller", "domain": "cloud_rl",
                           "desired_state": "paused" if "PAUSED" in watcher_state else "unknown",
                           "source": "rl:mcp:orchestrator_activity", "observed_at": observed,
                           "evidence": ["Watcher liveness alone does not establish active reasoning or training."]}
        result["services"].append(watcher_service)
    active_match = re.search(r"^active cycles \((\d+)[^\n]*\):", text, re.MULTILINE)
    if watcher_service is not None:
        watcher_service["active_cycle_count"] = int(active_match.group(1)) if active_match else None
    if not active_match:
        result["errors"].append(_error("rl:mcp:orchestrator_activity", "unrecognized", "Active cycle section unavailable"))
    else:
        active = re.split(r"^(?:recently finished cycles|newest ledger rows|watcher log tail:|HOW TO WAIT)",
                          text[active_match.end():], maxsplit=1, flags=re.MULTILINE)[0]
        for match in re.finditer(r"^## (.+?) \(model ([^,\n]+), started ([^,\n]+), pid (\d+)\)(.*?)(?=^## |\Z)", active, re.MULTILINE | re.DOTALL):
            label, model, started, pid, body = match.groups()
            status = "running"
            if re.search(r"inactive|zombie|PID gone|=== CYCLE END", body, re.IGNORECASE):
                status = "stopped"
            age_match = re.search(r"last write (\d+) s ago", body)
            age = int(age_match.group(1)) if age_match else None
            if status == "running" and (age is None or age > FRESH_SECONDS):
                status = "unknown"
            result["agents"].append(_agent(f"rl:{started}:{pid}", label, "claude" if "claude" in model.lower() else "unknown",
                                          "cloud_rl", status, "rl:mcp:orchestrator_activity", observed,
                                          task_id=f"rl:{sanitize(label)}", model=sanitize(model),
                                          source_age_seconds=age,
                                          evidence=[f"Active-section record; last narration age {age if age is not None else 'unknown'} seconds.",
                                                    "Narration activity is not measured goal progress."]))
        if len(result["agents"]) != int(active_match.group(1)):
            result["errors"].append(_error("rl:mcp:orchestrator_activity", "incomplete", "Some reported active cycles could not be normalized"))
    # Authentication diagnostics belong to the watcher log, not quoted text in
    # an agent's narration. Export only error counts and normalized timestamps.
    watcher_tail = text.split("watcher log tail:", 1)[1].split("HOW TO WAIT", 1)[0] if "watcher log tail:" in text else ""
    auth_lines = [line for line in watcher_tail.splitlines() if re.search(
        r"AuthenticationError|invalid.?api.?key|invalid x-api-key|authentication failed|401 Unauthorized", line, re.IGNORECASE)]
    if auth_lines:
        samples = []
        for line in auth_lines:
            match = re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?", line)
            parsed = _time(match.group(0)) if match else None
            samples.append(_stamp(parsed.isoformat()) if parsed else None)
        latest = samples[-1]
        freshness = _freshness(latest, observed)
        evidence = (f"Authentication failure appears in {len(auth_lines)} sampled watcher log lines; "
                    "current credential health and recovery status are unknown.")
        result["errors"].append({**_error("cloud:watcher", "authentication_failure", evidence), **freshness})
        if watcher_service is not None:
            watcher_service.update(auth_failure=True, auth_failure_count=len(auth_lines),
                                   last_auth_failure_at=latest,
                                   auth_failure_freshness=freshness["freshness"],
                                   auth_failure_source_age_seconds=freshness["source_age_seconds"],
                                   auth_failure_timestamps=samples,
                                   auth_recovery_status="unknown")
            watcher_service["evidence"].append(evidence)
    if re.search(r"ConnectionError|TimeoutError|Traceback \(most recent call last\)", watcher_tail):
        result["errors"].append(_error("cloud:watcher", "service_error_observed", "A service exception appears in the bounded watcher log sample; current failure and recovery state need verification."))
    return result


def normalize_codex_threads(tool_text: Any, project_root: Path,
                            now: str | None = None) -> list[dict]:
    """Normalize Codex app listing metadata; titles are untrusted labels only."""
    data, observed = _unwrap(tool_text), _stamp(now)
    if not isinstance(data, dict):
        return []
    rows = [*data.get("pinnedThreads", []), *data.get("threads", [])]
    result, seen = [], set()
    for row in rows[:MAX_FILES]:
        if not isinstance(row, dict) or row.get("kind", "codex") != "codex":
            continue
        project = row.get("project") or row.get("projectContext") or {}
        if not isinstance(project, dict):
            project = {}
        paths = [row.get(key) for key in ("cwd", "projectPath", "workingDirectory")]
        paths.extend(project.get(key) for key in ("path", "cwd", "rootPath"))
        context = " ".join(str(row.get(key, "")) for key in ("title", "projectName"))
        if not any(_project_path(path, Path(project_root)) for path in paths) and "hexapod" not in context.lower():
            continue
        ident = row.get("threadId") or row.get("id")
        if not isinstance(ident, str) or not ident or ident in seen:
            continue
        seen.add(ident)
        status = row.get("status", "unknown")
        if isinstance(status, dict):
            status = status.get("type", status.get("status", "unknown"))
        status = str(status).lower().replace("_", "")
        status = {"inprogress": "running", "active": "running", "working": "running",
                  "needsattention": "blocked", "complete": "completed"}.get(status, status)
        if status not in {"running", "idle", "blocked", "completed", "succeeded", "failed", "stopped", "queued"}:
            status = "unknown"
        result.append(_agent(f"codex:{ident}", row.get("title", ident), "codex", "interactive", status,
                             "codex:list_threads", observed,
                             **_freshness(row.get("updatedAt") or row.get("updated_at"), observed),
                             evidence=[("Persisted task metadata only; runtime activity is unknown. " if status == 'unknown' else "App-reported task status. ") +
                                       "Cost and measured goal progress are unavailable from this listing."]))
    return result
