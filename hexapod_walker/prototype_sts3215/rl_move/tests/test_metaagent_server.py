"""Synthetic HTTP/MCP/auth/accounting checks; no paid calls or live services."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient
import pytest

from rl_move.overseer import reviewer
from rl_move.overseer.journal import Journal
from rl_move.overseer.server import create_app, SESSION_COOKIE, MAX_BODY
from rl_move.overseer.store import Store

OPERATOR = "operator-secret-value-123456789012345"
VIEWER = "viewer-secret-value-12345678901234567"
HEADERS = {"Authorization": f"Bearer {OPERATOR}"}
VIEW_HEADERS = {"Authorization": f"Bearer {VIEWER}"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("HEXAPOD_MODEL_SOURCE", "mesh")
    for name in ("METAAGENT_PUBLIC_ORIGIN", "METAAGENT_SSO_SECRET_FILE", "METAAGENT_SSO_USERS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(reviewer, "review_once", lambda *a, **k: (_ for _ in ()).throw(AssertionError("paid call")))


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "state", api_token=OPERATOR, viewer_token=VIEWER), base_url="https://metaagent.test")


def call(client, name, arguments=None, headers=HEADERS):
    return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                    "params": {"name": name, "arguments": arguments or {}}})


def registered_record():
    return {"agent_id": "agent", "task_id": "task", "execution_owner": "owner", "goals": ["rl_only"],
            "scope": "simulation", "cost_status": "unknown", "status": "running"}


def test_public_health_and_shell_never_disclose_private_records(client, tmp_path):
    assert client.get("/healthz").json() == {"service": "hexapod-metaagent", "status": "ok", "scheduler_enabled": False}
    assert client.get("/").status_code == 200
    for path in ("/api/status", "/api/runs", "/api/runs/wake", "/api/costs", "/api/recommendations", "/api/session"):
        assert client.get(path).status_code == 401
    assert client.post("/mcp", json={}).status_code == 401
    assert not (tmp_path / "state").exists()


def test_read_only_empty_status_keeps_missing_costs_unknown_and_does_not_create_database(client, tmp_path):
    status = client.get("/api/status", headers=HEADERS)
    assert status.status_code == 200
    assert status.json()["authenticated_role"] == "operator"
    assert status.json()["budget"]["rolling_24h_actual_usd"] is None
    assert status.json()["data_available"] is False
    costs = call(client, "get_costs").json()["result"]["structuredContent"]
    assert costs["monitored_total_usd"] is None
    assert not (tmp_path / "state").exists()


def test_tokens_are_not_accepted_from_query_or_proxy_identity(client):
    assert client.get(f"/api/status?token={OPERATOR}").status_code == 401
    assert client.get("/api/status", headers={"X-Forwarded-User": "lukas", "X-Forwarded-Role": "admin"}).status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/status", headers=HEADERS).headers["cache-control"] == "no-store"


def test_mcp_initialization_read_tools_and_no_review_executor(client):
    response = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.json()["result"]["serverInfo"]["name"] == "hexapod-metaagent"
    listed = client.post("/mcp", headers=VIEW_HEADERS, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {"get_status", "list_runs", "get_run", "get_costs", "list_recommendations"}
    assert call(client, "run_review").json()["error"]["code"] == -32601


def test_viewer_cannot_register_or_record_costs(client, tmp_path):
    assert call(client, "register_agent", {"record": registered_record()}, headers=VIEW_HEADERS).status_code == 403
    assert not (tmp_path / "state").exists()


def test_operator_registration_checkpoint_and_idempotent_spend(client):
    result = call(client, "register_agent", {"record": registered_record()})
    assert result.json()["result"]["structuredContent"]["registration"] == "registered"
    result = call(client, "checkpoint_agent", {"agent_id": "agent", "record": {"status": "idle", "progress_evidence": ["Measured sim result"]}})
    assert result.json()["result"]["structuredContent"]["status"] == "idle"
    receipt = {"agent_id": "agent", "event_id": "event", "amount_usd": "12.50",
               "occurred_at": datetime.now(timezone.utc).isoformat(), "source": "provider receipt"}
    assert "result" in call(client, "record_agent_spend", receipt).json()
    assert "result" in call(client, "record_agent_spend", receipt).json()
    costs = client.get("/api/costs", headers=HEADERS).json()
    assert costs["agents"][0]["receipt_total_usd"] == "12.500000"
    assert costs["agents"][0]["total_cost_usd"] is None
    assert costs["unknown_cost_agents"] == 1
    assert costs["monitored_total_usd"] is None


def test_session_cookie_login_and_csrf_guard(client):
    logged = client.post("/api/session", json={"token": OPERATOR}, headers={"Origin": "https://metaagent.test"})
    assert logged.status_code == 200
    cookie = logged.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert client.get("/api/session").json()["method"] == "session"
    assert call(client, "register_agent", {"record": registered_record()}, headers={}).status_code == 403
    assert call(client, "register_agent", {"record": registered_record()},
                headers={"X-Metaagent-CSRF": "1", "Origin": "https://metaagent.test"}).status_code == 200
    assert call(client, "register_agent", {"record": registered_record()},
                headers={"X-Metaagent-CSRF": "1", "Origin": "https://evil.test"}).status_code == 403
    assert client.delete("/api/session").status_code == 200
    assert client.get("/api/status").status_code == 401


def test_tampered_or_expired_session_is_rejected(client):
    client.post("/api/session", json={"token": OPERATOR})
    cookie = client.cookies.get(SESSION_COOKIE)
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, cookie + "tampered")
    assert client.get("/api/status").status_code == 401


def test_loopback_http_cookie_and_cross_origin_login(tmp_path):
    client = TestClient(create_app(tmp_path, api_token=OPERATOR), base_url="http://127.0.0.1")
    response = client.post("/api/session", json={"token": OPERATOR})
    assert response.status_code == 200
    assert "Secure" not in response.headers["set-cookie"]
    assert client.post("/api/session", json={"token": OPERATOR}, headers={"Origin": "https://evil.test"}).status_code == 403


def test_existing_lab_sso_cookie_is_verified_and_mapped_to_role(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("shared-secret")
    client = TestClient(create_app(tmp_path / "state", api_token=OPERATOR, sso_secret_file=secret,
                                  sso_users="operator:lukas,viewer:guest"), base_url="https://metaagent.test")
    payload = f"lukas|{int(time.time()) + 600}".encode()
    cookie = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + hmac.new(b"shared-secret", payload, hashlib.sha256).hexdigest()
    client.cookies.set("hexapod_sso", cookie)
    assert client.get("/api/session").json() == {"authenticated": True, "role": "operator", "method": "sso"}
    secret.write_text("rotated-secret")
    assert client.get("/api/status").status_code == 401


def test_actual_cost_pending_reservation_and_redacted_review_are_separate(tmp_path):
    state = tmp_path / "state"
    store = Store(state / "overseer.sqlite3")
    now = datetime.now(timezone.utc)
    store.register_agent({**registered_record(), "cost_status": "known", "reported_cost_usd": "35.00"})
    wake = store.start_wake("manual review", now, wake_id="wake")
    store.reserve("wake", "settled", "4", now)
    store.settle("settled", "2.50", now)
    store.reserve("wake", "pending", "5", now)
    journal = Journal(store.path)
    journal.record("wake", {"generated_at": now.isoformat(), "notes": ["api_key=sk-private-credential"], "findings": [
        {"incident_id": "incident", "severity": "warning", "notify": True, "detail": "Fix repeated issue"}]}, "blocked")
    journal.begin_notification("incident")
    journal.end_notification("incident", submitted=True, receipt="Provider accepted the message")
    before = store.path.read_bytes()
    client = TestClient(create_app(state, api_token=OPERATOR))
    costs = client.get("/api/costs", headers=HEADERS).json()
    assert costs["metaagent"]["rolling_24h_actual_usd"] == "2.500000"
    assert costs["metaagent"]["pending_reserved_usd"] == "5.000000"
    assert costs["metaagent"]["rolling_24h_charged_usd"] == "7.500000"
    assert costs["monitored_total_usd"] == "35.000000"
    assert client.get("/api/runs", headers=HEADERS).json()["runs"][0]["actual_cost_usd"] == "2.500000"
    detail = client.get("/api/runs/wake", headers=HEADERS)
    assert detail.json()["reservations"][1]["actual_usd"] is None
    assert "sk-private-credential" not in detail.text
    recs = client.get("/api/recommendations", headers=HEADERS).json()
    assert recs["recommendations"][0]["notification_receipt"] == "Provider accepted the message"
    assert store.path.read_bytes() == before


def test_malformed_and_oversized_mcp_inputs_do_not_start_work(client):
    assert client.post("/mcp", content=b"x" * (MAX_BODY + 1), headers=HEADERS).status_code == 413
    malformed = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": ["bad"]}
    assert client.post("/mcp", headers=HEADERS, json=malformed).json()["error"]["code"] == -32602
    assert client.get("/api/runs/missing", headers=HEADERS).status_code == 404


def test_static_assets_are_public_but_private_data_stays_authenticated(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>Metaagent</title>")
    (static / "dashboard.js").write_text("const dashboard = true;")
    client = TestClient(create_app(tmp_path / "state", api_token=OPERATOR, static_dir=static))
    assert "Metaagent" in client.get("/").text
    assert client.get("/assets/dashboard.js").status_code == 200
    assert client.get("/api/status").status_code == 401


def test_metaagent_parent_and_children_are_not_double_counted_as_monitored_cost(tmp_path):
    store = Store(tmp_path / "overseer.sqlite3")
    store.register_agent({"agent_id": "meta", "is_overseer": True, "cost_status": "known", "reported_cost_usd": 3})
    store.register_agent({"agent_id": "child", "parent_id": "meta", "cost_status": "known", "reported_cost_usd": 2})
    store.register_agent({"agent_id": "worker", "cost_status": "known", "reported_cost_usd": 100})
    client = TestClient(create_app(tmp_path, api_token=OPERATOR))
    costs = client.get("/api/costs", headers=HEADERS).json()
    assert costs["monitored_total_usd"] == "100.000000"
    assert costs["metaagent_registry_records_excluded"] == 2


def test_https_public_origin_keeps_secure_cookie_behind_loopback_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("METAAGENT_PUBLIC_ORIGIN", "https://metaagent.example.test")
    client = TestClient(create_app(tmp_path, api_token=OPERATOR), base_url="http://127.0.0.1")
    response = client.post("/api/session", json={"token": OPERATOR}, headers={"Origin": "https://metaagent.example.test"})
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
