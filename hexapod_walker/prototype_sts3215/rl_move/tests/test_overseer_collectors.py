from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from rl_move.overseer import collectors

NOW = "2026-09-09T04:00:00Z"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("HEXAPOD_MODEL_SOURCE", "mesh")
    monkeypatch.setattr(collectors, "_run", lambda argv: subprocess.CompletedProcess(argv, 0, "", ""))


def put_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_claude_discovery_uses_metadata_not_prompt_and_rejects_zombies(tmp_path, monkeypatch):
    home, root = tmp_path / "home", tmp_path / "hexapod"
    for index, status in ((1, "idle"), (2, "running"), (3, "running")):
        put_json(home / f".claude/sessions/{index}.json", {
            "pid": index, "sessionId": f"session-{index}", "cwd": str(home),
            "status": status, "name": f"agent-{index}", "updatedAt": NOW})
        transcript = home / f".claude/projects/home/session-{index}.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"type": "assistant", "timestamp": NOW,
                                         "cwd": str(root), "message": {"content": "secret full prompt"}}) + "\n")
    monkeypatch.setattr(collectors, "_processes", lambda errors: {1: "S", 2: "Z", 3: "S"})
    snapshot = collectors.collect_local(root, home=home, now=NOW)
    statuses = {agent["name"]: agent["status"] for agent in snapshot["agents"]}
    assert statuses == {"agent-1": "idle", "agent-2": "stopped", "agent-3": "running"}
    assert "secret full prompt" not in json.dumps(snapshot)
    assert all(agent["cost_status"] == "unknown" for agent in snapshot["agents"])
    assert all("last_progress_at" not in agent for agent in snapshot["agents"])


def test_stale_active_session_is_unknown_and_unrelated_sessions_are_omitted(tmp_path, monkeypatch):
    home, root = tmp_path / "home", tmp_path / "hexapod"
    put_json(home / ".claude/sessions/1.json", {"pid": 1, "sessionId": "one", "cwd": str(root),
                                                "status": "running", "updatedAt": "2026-09-08T00:00:00Z"})
    put_json(home / ".claude/sessions/2.json", {"pid": 2, "sessionId": "two", "cwd": "/unrelated", "status": "running"})
    monkeypatch.setattr(collectors, "_processes", lambda errors: {1: "S", 2: "S"})
    rows = collectors.collect_local(root, home=home, now=NOW)["agents"]
    assert len(rows) == 1
    assert rows[0]["status"] == "unknown"
    assert rows[0]["freshness"] == "stale"


def test_lab_read_only_handles_pause_expired_lease_and_cost_missing_attempt(tmp_path):
    lab = tmp_path / "lab"
    data = lab / "data"
    data.mkdir(parents=True)
    database = data / "lab.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE codex_queue_controls(sequence INTEGER,action TEXT,created_at TEXT);
            INSERT INTO codex_queue_controls VALUES(1,'pause','2026-09-09T03:00:00Z');
            CREATE TABLE codex_jobs(id TEXT,kind TEXT,experiment_id TEXT,status TEXT,
                attempts INTEGER,updated_at TEXT,lease_expires_at TEXT);
            INSERT INTO codex_jobs VALUES('live','analysis','exp','running',1,
                '2026-09-09T03:59:00Z','2026-09-09T04:05:00Z');
            INSERT INTO codex_jobs VALUES('expired','advance','exp','running',2,
                '2026-09-08T03:59:00Z','2026-09-08T04:05:00Z');
        """)
    original = database.read_bytes()
    (lab / "agent-provider").write_text("claude")
    put_json(data / "codex-runs/live/attempt-1/metadata.json", {"provider": "claude", "usage": {"cost_usd": 12.5}})
    put_json(data / "codex-runs/expired/attempt-1/metadata.json", {"provider": "claude", "usage": {"cost_usd": 9}})
    snapshot = collectors.collect_local(tmp_path / "hexapod", home=tmp_path / "home", lab_root=lab, now=NOW)
    rows = {a["agent_id"]: a for a in snapshot["agents"]}
    assert rows["lab:live"]["status"] == "running"
    assert rows["lab:live"]["reported_cost_usd"] == 12.5
    assert rows["lab:live"]["provider"] == "claude"
    assert rows["lab:expired"]["status"] == "stale"
    assert rows["lab:expired"]["cost_status"] == "unknown"
    assert "reported_cost_usd" not in rows["lab:expired"]
    assert next(s for s in snapshot["services"] if s["service_id"] == "lab:queue")["status"] == "paused"
    assert database.read_bytes() == original


def test_automation_prompt_is_not_exported_and_pause_preserved(tmp_path):
    home = tmp_path / "home"
    path = home / ".codex/automations/watch/automation.toml"
    path.parent.mkdir(parents=True)
    path.write_text('id="watch"\nname="Watch hexapod"\nstatus="PAUSED"\nkind="heartbeat"\nprompt="API_KEY=abcdef do this secret task"\n')
    snapshot = collectors.collect_local(tmp_path / "hexapod", home=home, now=NOW)
    assert snapshot["automations"][0]["status"] == "paused"
    assert "abcdef" not in json.dumps(snapshot)
    assert "secret task" not in json.dumps(snapshot)


@pytest.mark.parametrize("disabled_value", ["true", "disabled"])
def test_launchctl_only_exports_fixed_service_fields(monkeypatch, disabled_value):
    def run(argv):
        if "print-disabled" in argv:
            return subprocess.CompletedProcess(argv, 0, f'"com.lbiewald.hexapod-codex-orchestrator" => {disabled_value}', "")
        return subprocess.CompletedProcess(argv, 0, "state = running\nenvironment = { TOKEN = supersecret }", "")
    monkeypatch.setattr(collectors, "_run", run)
    errors = []
    rows = collectors._services(NOW, errors)
    assert rows[1]["status"] == "disabled"
    assert rows[0]["status"] == "running"
    assert "supersecret" not in json.dumps(rows)
    assert not errors


def test_cloud_no_active_cycles_does_not_promote_historical_zombie_or_expose_keys():
    text = """# Orchestrator activity (live)
watcher: UP
active cycles (0):
recently finished cycles:
- 20260908T010000_cycle: inactive (zombie)
watcher log tail:
[2026-09-09T03:00:00] AuthenticationError: invalid x-api-key sk-private-credential
"""
    result = collectors.normalize_cloud_activity({"content": [{"type": "text", "text": text}]}, NOW)
    assert result["agents"] == []
    assert result["errors"][0]["code"] == "authentication_failure"
    assert result["errors"][0]["freshness"] == "fresh"
    assert "sk-private" not in json.dumps(result)


def test_cloud_advancing_cycle_and_stale_cycle_are_distinguished():
    text = """watcher: UP
active cycles (2):
## useful (model claude-sonnet-5, started 2026-09-09T03:55:00, pid 42)
   live narration (last write 30 s ago; full log: hidden):
## old (model claude-sonnet-5, started 2026-09-08T00:00:00, pid 41)
   live narration (last write 100000 s ago; full log: hidden):
recently finished cycles:
"""
    result = collectors.normalize_cloud_activity(text, NOW)
    assert [a["status"] for a in result["agents"]] == ["running", "unknown"]
    assert all("last_progress_at" not in a for a in result["agents"])


def test_codex_real_schema_nested_mcp_duplicate_and_project_filter(tmp_path):
    root = tmp_path / "hexapod"
    row = {"id": "one", "kind": "codex", "status": "active", "cwd": str(root),
           "updatedAt": 1788925888, "title": "Fix API_KEY=secretthing"}
    data = {"schemaVersion": 4, "pinnedThreads": [row], "threads": [row, {"id": "other", "cwd": "/other", "title": "Unrelated"}]}
    result = collectors.normalize_codex_threads({"content": [{"type": "text", "text": json.dumps(data)}]}, root, NOW)
    assert len(result) == 1
    assert result[0]["agent_id"] == "codex:one"
    assert result[0]["status"] == "running"
    assert "secretthing" not in json.dumps(result)
    assert result[0]["cost_status"] == "unknown"


def test_missing_sources_are_explicit_and_do_not_create_databases(tmp_path):
    snapshot = collectors.collect_local(tmp_path / "hexapod", home=tmp_path / "home", now=NOW)
    assert snapshot["agents"] == []
    assert len(snapshot["errors"]) >= 3
    assert list(tmp_path.rglob("*.sqlite3")) == []


def test_metadata_and_transcript_reads_are_bounded(tmp_path):
    path = tmp_path / "large.json"
    path.write_text(" " * (collectors.MAX_JSON_BYTES + 1))
    with pytest.raises(ValueError, match="bounded"):
        collectors._read_json(path)
    path.write_text("huge incomplete line" * 5000 + "\n" + json.dumps({"type": "assistant", "cwd": "/hexapod"}) + "\n")
    assert collectors._tail_events(path) == [{"type": "assistant", "cwd": "/hexapod"}]


def test_cloud_footer_does_not_turn_live_cycle_into_stopped():
    text = """watcher: UP
active cycles (1):
## useful (model claude-sonnet-5, started 2026-09-09T03:55:00, pid 42)
   live narration (last write 30 s ago; full log: hidden):
newest ledger rows:
watcher log tail:
HOW TO WAIT: A finished cycle has (=== CYCLE END).
"""
    assert collectors.normalize_cloud_activity(text, NOW)["agents"][0]["status"] == "running"


def test_attempt_cost_scan_budget_and_malformed_usage_stay_unknown(tmp_path):
    put_json(tmp_path / "codex-runs/job/attempt-1/metadata.json", {"provider": "claude", "usage": []})
    assert collectors._job_cost(tmp_path, "job", 1, [10])[0] == "unknown"
    assert collectors._job_cost(tmp_path, "job", 1, [0])[0] == "unknown"
