from __future__ import annotations

import json
import sys
from pathlib import Path


ORCH = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCH))

import mcp_server  # noqa: E402


def _install_run(monkeypatch, run: str = "cw-feedback-demo") -> None:
    monkeypatch.setattr(
        mcp_server,
        "_ledger",
        lambda: [{
            "run": run,
            "status": "FINISHED",
            "track": "demo",
            "created": "2026-09-04T12:00:00+00:00",
            "verdict": "mechanical gate passed",
        }],
    )


def test_run_feedback_is_persisted_and_discoverable(
        monkeypatch, tmp_path: Path) -> None:
    run = "cw-feedback-demo"
    _install_run(monkeypatch, run)
    monkeypatch.setattr(mcp_server, "FEEDBACK_DIR", tmp_path)
    mcp_server._fb_times.clear()

    result, is_error = mcp_server.call_tool(
        "submit_run_feedback",
        {"run": run,
         "feedback": "Looks smooth, but the left arc drifts outward.",
         "topic": "subjective motion review",
         "author": "test operator"},
        client_ip="127.0.0.1",
        operator=True,
    )

    assert is_error is False
    assert "filed as fb_" in result
    files = list(tmp_path.glob("fb_*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text())
    assert saved["scope"] == "run"
    assert saved["run"] == run
    assert saved["operator"] is True

    focused = mcp_server.t_list_run_feedback(run)
    assert "left arc drifts outward" in focused
    assert "not yet seen" in focused

    run_context = mcp_server.t_get_run(run)
    assert "# Saved run feedback" in run_context
    assert "left arc drifts outward" in run_context

    listing = json.loads(mcp_server.t_list_runs().split("\n\n", 1)[1])
    assert listing[0]["feedback_count"] == 1


def test_run_feedback_rejects_unknown_run_without_writing(
        monkeypatch, tmp_path: Path) -> None:
    _install_run(monkeypatch)
    monkeypatch.setattr(mcp_server, "FEEDBACK_DIR", tmp_path)
    mcp_server._fb_times.clear()

    result = mcp_server.t_submit_run_feedback(
        "cw-feedback-dem", "note", _client_ip="127.0.0.1")

    assert "not in the ledger" in result
    assert "Near matches: cw-feedback-demo" in result
    assert "Nothing was filed" in result
    assert not list(tmp_path.iterdir())


def test_run_feedback_tools_are_advertised() -> None:
    specs = {tool["name"]: tool for tool in mcp_server.tool_specs()}

    assert specs["submit_run_feedback"]["inputSchema"]["required"] == [
        "run", "feedback",
    ]
    assert specs["list_run_feedback"]["inputSchema"]["required"] == ["run"]
