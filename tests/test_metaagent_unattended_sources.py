from __future__ import annotations

import io
import json
from pathlib import Path
import stat
import subprocess
import time
from types import SimpleNamespace

import pytest

from rl_move.overseer import unattended_sources as sources
from rl_move.overseer.collectors import normalize_codex_threads, normalize_cloud_activity


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("HEXAPOD_MODEL_SOURCE", "mesh")
    monkeypatch.delenv("METAAGENT_CODEX_BIN", raising=False)
    monkeypatch.delenv("METAAGENT_CODEX_CONTROL_SOCKET", raising=False)
    monkeypatch.setattr(sources.subprocess, "Popen", lambda *a, **k: pytest.fail("Unexpected subprocess"))
    monkeypatch.setattr(sources.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected network"))


def thread(root, ident="one", status=None):
    return {"id": ident, "name": "Hexapod work", "cwd": str(root), "updatedAt": 1788920000,
            "status": status or {"type": "active", "activeFlags": []},
            "preview": "full private prompt", "turns": [{"text": "secret message"}]}


def fake_client(monkeypatch, pages, calls):
    class Client:
        def __init__(self, argv, deadline):
            calls.append(("argv", argv))

        def initialize(self):
            calls.append(("initialize", {}))

        def request(self, method, params):
            calls.append((method, params))
            return pages.pop(0)

        def close(self):
            calls.append(("close", {}))
    monkeypatch.setattr(sources, "_AppServer", Client)


def test_proxy_inventory_metadata_whitelist_and_read_only_pagination(tmp_path, monkeypatch):
    calls = []
    fake_client(monkeypatch, [{"data": [thread(tmp_path)], "nextCursor": "two"},
                             {"data": [thread(tmp_path, "two", {"type": "active", "activeFlags": ["waitingOnApproval"]})], "nextCursor": None}], calls)
    path, status, errors = sources._codex_source(tmp_path, tmp_path / "codex.json", 5, "/fake/codex", "/fake/socket")
    envelope = json.loads(Path(path).read_text())
    assert status == "available" and not errors
    assert calls[0][1] == ["/fake/codex", "app-server", "proxy", "--sock", "/fake/socket"]
    requests = [params for method, params in calls if method == "thread/list"]
    assert len(requests) == 2
    assert all(item["useStateDbOnly"] is True and "appServer" in item["sourceKinds"] for item in requests)
    assert requests[1]["cursor"] == "two"
    agents = normalize_codex_threads(envelope["data"], tmp_path, now=envelope["collected_at"])
    assert [item["status"] for item in agents] == ["running", "blocked"]
    assert "full private prompt" not in json.dumps(envelope)
    assert "secret message" not in json.dumps(envelope)
    assert stat.S_IMODE(Path(path).stat().st_mode) == 0o600


def test_stdio_fallback_never_claims_liveness(tmp_path, monkeypatch):
    calls = []

    def inventory(argv, root, deadline, *, live):
        calls.append(argv)
        if live:
            raise sources.SourceUnavailable("app_server_unavailable")
        return [sources._thread_metadata(thread(root), live=live)], False

    monkeypatch.setattr(sources, "_inventory", inventory)
    path, status, errors = sources._codex_source(tmp_path, tmp_path / "codex.json", 5, "/fake/codex", None)
    envelope = json.loads(Path(path).read_text())
    assert calls[-1] == ["/fake/codex", "app-server", "--stdio"]
    assert status == "partial" and errors[0]["code"] == "runtime_status_unavailable"
    assert envelope["runtime_status_available"] is False
    assert envelope["data"]["threads"][0]["status"] == "unknown"
    agents = normalize_codex_threads(envelope["data"], tmp_path, now=envelope["collected_at"])
    assert agents[0]["status"] == "unknown"


def test_thread_limit_is_explicit_coverage_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "MAX_THREADS", 2)
    calls = []
    fake_client(monkeypatch, [{"data": [thread(tmp_path, "a"), thread(tmp_path, "b")], "nextCursor": "more"}], calls)
    _, status, errors = sources._codex_source(tmp_path, tmp_path / "codex.json", 5, "/fake/codex", None)
    assert status == "partial" and errors[0]["code"] == "truncated"
    assert len([method for method, _ in calls if method == "thread/list"]) == 1


def credentials(home, text=None):
    path = home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text or f'[mcp_servers.rl_orchestrator]\nurl = "{sources.RL_ENDPOINT}"\nhttp_headers = {{ Authorization = "Bearer private-credential" }}\n')


def cloud_response(text="watcher: UP\nactive cycles (0):\nrecently finished cycles:\n"):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


def fake_curl(monkeypatch, response, capture, returncode=0):
    def run(argv, **kwargs):
        capture.append((argv, kwargs))
        config = Path(argv[argv.index("--config") + 1])
        assert stat.S_IMODE(config.stat().st_mode) == 0o600
        assert "private-credential" not in " ".join(argv)
        Path(argv[argv.index("-o") + 1]).write_text(json.dumps(response))
        return SimpleNamespace(returncode=returncode)
    monkeypatch.setattr(sources.subprocess, "run", run)


def test_authenticated_cloud_read_is_bounded_sanitized_and_private(tmp_path, monkeypatch):
    credentials(tmp_path)
    capture = []
    fake_curl(monkeypatch, cloud_response("watcher: UP\nactive cycles (0):\nwatcher log tail:\nAuthenticationError private-credential\n"), capture)
    path, status, errors = sources._cloud_source(tmp_path / "cloud.json", 8, tmp_path)
    argv, kwargs = capture[0]
    assert argv[:4] == ["curl", "-q", "-f", "-sS"]
    assert kwargs["timeout"] == 9 and "--max-filesize" in argv
    assert json.loads(argv[argv.index("--data") + 1])["params"] == {"name": "orchestrator_activity", "arguments": {}}
    assert not Path(argv[argv.index("--config") + 1]).exists()
    exported = Path(path).read_text()
    assert "private-credential" not in exported
    assert status == "available" and not errors
    envelope = json.loads(exported)
    normalized = normalize_cloud_activity(envelope["data"], now=envelope["collected_at"])
    assert normalized["services"][0]["active_cycle_count"] == 0
    assert normalized["services"][0]["auth_failure"] is True


def test_public_strategy_read_is_bounded_sanitized_and_private(tmp_path, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        url = next(value for value in argv if value.startswith("https://"))
        body = ("brief password=private-secret" if url.endswith("brief.md")
                else "run ledger Authorization: Bearer private-token")
        Path(argv[argv.index("-o") + 1]).write_text(body)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sources.subprocess, "run", run)
    path, status, errors = sources._strategy_source(tmp_path / "strategy.json", 8)
    envelope = json.loads(Path(path).read_text())
    assert status == "available" and not errors
    assert set(envelope["data"]) == {"research_brief", "recent_runs"}
    assert envelope["source_mode"] == "public_read_only"
    assert "private-secret" not in json.dumps(envelope)
    assert "private-token" not in json.dumps(envelope)
    assert all("--max-filesize" in argv for argv, _ in calls)
    assert not list(tmp_path.glob(".metaagent-strategy-*"))


@pytest.mark.parametrize("response,code", [
    ({"id": 1, "error": {"message": "private-credential"}}, "mcp_request_failed"),
    ({"id": 1, "result": {"isError": True, "content": [{"type": "text", "text": "private-credential"}]}}, "mcp_request_failed"),
    ({"id": 1, "result": {"content": []}}, "invalid_mcp_response"),
])
def test_cloud_tool_errors_are_not_fresh_empty_inventory(tmp_path, monkeypatch, response, code):
    credentials(tmp_path)
    fake_curl(monkeypatch, response, [])
    with pytest.raises(sources.SourceUnavailable, match=code):
        sources._cloud_source(tmp_path / "cloud.json", 5, tmp_path)
    assert not (tmp_path / "cloud.json").exists()


def test_cloud_credentials_environment_and_endpoint_allowlist(tmp_path, monkeypatch):
    credentials(tmp_path, f'[mcp_servers.rl_orchestrator]\nurl="{sources.RL_ENDPOINT}"\nbearer_token_env_var="TEST_RL_TOKEN"\n')
    monkeypatch.setenv("TEST_RL_TOKEN", "private-credential")
    config, secrets = sources._curl_configuration(tmp_path)
    assert b"Bearer private-credential" in config and "private-credential" in secrets
    monkeypatch.delenv("TEST_RL_TOKEN")
    with pytest.raises(sources.SourceUnavailable, match="authentication_configuration_unavailable"):
        sources._curl_configuration(tmp_path)
    path = tmp_path / ".codex/config.toml"
    path.write_text(path.read_text().replace(sources.RL_ENDPOINT, "https://elsewhere.invalid/mcp"))
    with pytest.raises(sources.SourceUnavailable, match="unexpected_rl_endpoint"):
        sources._curl_configuration(tmp_path)


def test_missing_sources_cannot_reuse_old_exports_or_leak_exception(tmp_path, monkeypatch):
    for name in ("codex-threads.json", "cloud-activity.json", "strategy-evidence.json"):
        (tmp_path / name).write_text("stale export")

    def failed(*args):
        raise OSError("private-credential")

    monkeypatch.setattr(sources, "_codex_source", failed)
    monkeypatch.setattr(sources, "_cloud_source", failed)
    monkeypatch.setattr(sources, "_strategy_source", failed)
    result = sources.collect_unattended(tmp_path, tmp_path, home=tmp_path)
    assert (result["codex_threads"] is None and result["cloud_activity"] is None
            and result["strategy_evidence"] is None)
    assert set(result["source_status"].values()) == {"unavailable"}
    assert "private-credential" not in json.dumps(result)
    assert not (tmp_path / "codex-threads.json").exists()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


def test_one_source_failure_does_not_suppress_independent_fresh_source(tmp_path, monkeypatch):
    def failed(*args):
        raise sources.SourceUnavailable("timeout")

    monkeypatch.setattr(sources, "_codex_source", failed)
    monkeypatch.setattr(sources, "_cloud_source", lambda *a: ("fresh-cloud.json", "available", []))
    monkeypatch.setattr(sources, "_strategy_source", lambda *a: ("fresh-strategy.json", "available", []))
    result = sources.collect_unattended(tmp_path, tmp_path)
    assert result["cloud_activity"] == "fresh-cloud.json"
    assert result["strategy_evidence"] == "fresh-strategy.json"
    assert result["source_status"]["codex_threads"] == "unavailable"


def test_protocol_ignores_unsolicited_requests_and_rejects_non_read_methods(monkeypatch):
    client = sources._AppServer.__new__(sources._AppServer)
    client.deadline, client.ident, client.received, client.buffer = time.monotonic() + 1, 0, 0, b""
    client.process = SimpleNamespace(stdin=io.BytesIO(), stdout=SimpleNamespace(fileno=lambda: 42))
    client.selector = SimpleNamespace(select=lambda timeout: [1])
    chunks = [b'{"id":99,"method":"item/commandExecution/requestApproval","params":{}}\n',
              b'{"id":1,"result":{"data":[],"nextCursor":null}}\n']
    monkeypatch.setattr(sources.os, "read", lambda fd, limit: chunks.pop(0))
    assert client.request("thread/list", {})["data"] == []
    sent = client.process.stdin.getvalue().decode().splitlines()
    assert len(sent) == 1 and json.loads(sent[0])["method"] == "thread/list"
    with pytest.raises(ValueError, match="Only inventory methods"):
        client.request("turn/start", {})


def test_protocol_timeout_is_bounded(monkeypatch):
    client = sources._AppServer.__new__(sources._AppServer)
    client.deadline, client.ident, client.received, client.buffer = time.monotonic() + 1, 0, 0, b""
    client.process = SimpleNamespace(stdin=io.BytesIO())
    client.selector = SimpleNamespace(select=lambda timeout: [])
    with pytest.raises(sources.SourceUnavailable, match="timeout"):
        client.request("thread/list", {})


@pytest.mark.parametrize("timeout", [0, -1, 61, float("inf"), float("nan")])
def test_invalid_timeout_never_starts_sources(tmp_path, timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        sources.collect_unattended(tmp_path, tmp_path, timeout_seconds=timeout)
