from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ORCH = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCH))

import mcp_server  # noqa: E402
import status_server  # noqa: E402


@pytest.fixture
def cycle_files(monkeypatch, tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    cycles = tmp_path / "cycles"
    cycles.mkdir()
    entries = []
    for pid, label, process_state in (
            (101, "live", "S"), (102, "zombie", "Z"),
            (103, "missing", None), (104, "finished", "Z")):
        stamp = f"20260908T00{pid:04d}"
        log = cycles / f"cycle_{stamp}_{label}.log"
        log.write_text("=== CYCLE START ===\nworking\n" + (
            "=== CYCLE END: success ===\n" if label == "finished" else ""))
        entries.append({"stamp": stamp, "label": label, "pid": pid,
                        "status": "running", "log": str(log)})
        if process_state:
            directory = proc / str(pid)
            directory.mkdir()
            # Linux comm may contain spaces and parentheses.
            (directory / "stat").write_text(
                f"{pid} (claude (worker)) {process_state} 1 0 0 0\n")
            (directory / "cmdline").write_bytes(b"claude\0-p\0prompt\0")
    registry = cycles / "cycles.json"
    registry.write_text(json.dumps(entries))
    original_registry = registry.read_bytes()
    monkeypatch.setattr(mcp_server, "PROC_ROOT", proc)
    monkeypatch.setattr(mcp_server, "CYCLE_REGISTRY", registry)
    monkeypatch.setattr(mcp_server, "WATCHER_LOG", tmp_path / "watcher.log")
    monkeypatch.setattr(mcp_server, "PAUSE_FLAG", tmp_path / "PAUSE")
    monkeypatch.setattr(mcp_server, "OPERATOR_KICK_FILE", tmp_path / "KICK")
    monkeypatch.setattr(mcp_server, "KICK_DIR", tmp_path / "kicks")
    monkeypatch.setattr(mcp_server, "_ledger", lambda: [])
    monkeypatch.setattr(status_server, "CYCLE_DIR", cycles)
    return proc, cycles, registry, original_registry


def test_mcp_excludes_zombie_and_missing_cycles_without_rewriting_history(
        cycle_files):
    _, _, registry, original = cycle_files
    output = mcp_server.t_orchestrator_activity()
    assert "active cycles (1):" in output
    active, history = output.split("recently finished cycles", 1)
    assert "## live " in active
    assert "## zombie " not in active
    assert "## missing " not in active
    assert "## finished " not in active
    assert "_zombie: inactive (zombie)" in history
    assert "_missing: inactive (PID gone)" in history
    assert "_finished: inactive (zombie)" in history
    assert registry.read_bytes() == original


def test_dashboard_excludes_dead_cycles_and_preserves_known_completion(
        cycle_files):
    _, _, registry, original = cycle_files
    rows = {row["label"]: row for row in status_server.recent_cycle_logs()}
    assert rows["live"]["state"] == "running"
    assert rows["zombie"]["state"] == "inactive (zombie)"
    assert rows["missing"]["state"] == "inactive (PID gone)"
    assert rows["finished"]["state"] == "done"
    assert not rows["zombie"]["live_tail"]
    assert not rows["missing"]["live_tail"]
    assert registry.read_bytes() == original


def test_live_process_scan_does_not_count_zombies(cycle_files):
    assert [row["pid"] for row in status_server.live_cycles()] == [101]


def test_mcp_without_registry_filters_zombies_in_watcher_log(cycle_files):
    _, _, registry, _ = cycle_files
    registry.unlink()
    mcp_server.WATCHER_LOG.write_text("\n".join(
        f"[2026-09-08T00:00:00] cycle spawned pid={pid} model=test "
        f"for: {label} (log: /tmp/cycle_{label}.log)"
        for pid, label in ((101, "live"), (102, "zombie"), (103, "missing"))))
    output = mcp_server.t_orchestrator_activity()
    assert "active cycles (1, from watcher-log fallback" in output
    active, history = output.split("recently finished cycles", 1)
    assert "live (model test" in active
    assert "zombie (model test" not in active
    assert "missing (model test" not in active
    assert "zombie (model test" in history
    assert "missing (model test" in history


def test_unavailable_proc_does_not_invent_a_completion(cycle_files):
    proc, _, _, _ = cycle_files
    mcp_server.PROC_ROOT = proc / "unavailable"
    output = mcp_server.t_orchestrator_activity()
    assert "active cycles (4):" in output
    rows = {row["label"]: row for row in status_server.recent_cycle_logs()}
    assert rows["live"]["state"] == "running"
    assert rows["zombie"]["state"] == "running"
    assert rows["missing"]["state"] == "running"
    assert rows["finished"]["state"] == "done"


@pytest.mark.parametrize("stat_text", [None, "unreadable stat format"])
def test_missing_or_malformed_stat_is_not_a_missing_process(
        cycle_files, stat_text):
    proc, _, _, _ = cycle_files
    stat = proc / "101" / "stat"
    if stat_text is None:
        stat.unlink()
    else:
        stat.write_text(stat_text)
    output = mcp_server.t_orchestrator_activity()
    assert "active cycles (1):" in output
    assert "## live " in output
