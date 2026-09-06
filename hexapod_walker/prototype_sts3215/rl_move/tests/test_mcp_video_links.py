from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ORCH = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCH))

import mcp_server
import status_server


@pytest.fixture
def videos(monkeypatch, tmp_path):
    root = tmp_path / "logs" / "ckpt_eval"
    for directory, filename, data in [
        ("cw_demo_gate", "walk_det_0.mp4", b"video0123456789"),
        ("cw_demo_gate", "walk_sto_0.mp4", b"stochastic"),
        ("cw_demo_s1_gate", "walk_det_0.mp4", b"other seed"),
    ]:
        path = root / directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "cw_demo_gate" / "report.json").write_text("{}")
    monkeypatch.setattr(mcp_server, "PROTO", tmp_path)
    monkeypatch.setattr(mcp_server, "AUTH_KEY", "test-mcp-key")
    monkeypatch.setattr(mcp_server, "_ledger", lambda: [
        {"run": "cw-demo"}, {"run": "cw-demo-s1"}])
    monkeypatch.setattr(status_server, "EVAL_VIDEO_DIR", root)
    monkeypatch.setattr(status_server, "TOKEN", "test-dashboard-key")
    monkeypatch.delenv("STATUS_PUBLIC_BASE_URL", raising=False)
    return root


def test_tool_returns_direct_resource_links_scoped_to_exact_run(videos):
    response = mcp_server._rpc_one({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "get_run_videos", "arguments": {"run": "cw-demo"}},
    })["result"]
    data = response["structuredContent"]
    assert len(data["videos"]) == 2
    assert data["videos"][0]["path"] == "cw_demo_gate/walk_det_0.mp4"
    assert response["content"][1]["type"] == "resource_link"
    assert response["content"][1]["mimeType"] == "video/mp4"
    assert "test-mcp-key" not in json.dumps(response)
    assert "test-dashboard-key" not in json.dumps(response)
    assert "cw_demo_s1" not in json.dumps(response)
    assert 3590 < data["expires_at"] - time.time() <= 3600
    spec = next(t for t in mcp_server.tool_specs() if t["name"] == "get_run_videos")
    assert spec["annotations"]["readOnlyHint"] is True


def _request(path, *, method="GET", headers=None):
    """Exercise the real HTTP handler without binding a network socket."""
    handler = object.__new__(status_server.Handler)
    handler.path = path
    handler.headers = headers or {}
    handler.wfile = io.BytesIO()
    handler.status = None
    handler.response_headers = {}
    handler.send_response = lambda status: setattr(handler, "status", status)
    handler.send_header = lambda k, v: handler.response_headers.update({k: v})
    handler.end_headers = lambda: None
    getattr(handler, "do_" + method)()
    return handler


def test_link_plays_and_seeks_without_dashboard_cookie(videos):
    uri = mcp_server.t_get_run_videos("cw-demo")["videos"][0]["uri"]
    parsed = urlsplit(uri)
    path = parsed.path + "?" + parsed.query
    full = _request(path)
    assert full.status == 200
    assert full.wfile.getvalue() == b"video0123456789"
    assert "Set-Cookie" not in full.response_headers
    assert full.response_headers["Content-Type"] == "video/mp4"
    partial = _request(path, headers={"Range": "bytes=5-8"})
    assert partial.status == 206
    assert partial.wfile.getvalue() == b"0123"
    head = _request(path, method="HEAD")
    assert head.status == 200
    assert head.wfile.getvalue() == b""


def test_video_signature_cannot_unlock_other_files_or_dashboard(videos):
    uri = mcp_server.t_get_run_videos("cw-demo")["videos"][0]["uri"]
    parsed = urlsplit(uri)
    for path in ["/now", "/json", "/media/cw_demo_gate/walk_sto_0.mp4",
                 "/media/cw_demo_gate/report.json"]:
        assert _request(path + "?" + parsed.query).status == 403
    assert _request(parsed.path).status == 403
    assert _request(parsed.path, method="HEAD").status == 403


def test_expired_link_fails_and_existing_dashboard_auth_still_works(videos, monkeypatch):
    uri = mcp_server.t_get_run_videos("cw-demo")["videos"][0]["uri"]
    parsed = urlsplit(uri)
    future = time.time() + 3700
    monkeypatch.setattr(mcp_server.media_access.time, "time", lambda: future)
    assert _request(parsed.path + "?" + parsed.query).status == 403
    assert _request(parsed.path, headers={"Cookie": "status_token=test-dashboard-key"}).status == 200


def test_unknown_run_and_symlink_escape_are_not_returned(videos, tmp_path):
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"private")
    (videos / "cw_demo_gate" / "escape.mp4").symlink_to(outside)
    assert len(mcp_server.t_get_run_videos("cw-demo")["videos"]) == 2
    result, error = mcp_server.call_tool("get_run_videos", {"run": "cw-unknown"})
    assert error is True
    assert "not in the ledger" in result
