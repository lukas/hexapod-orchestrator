"""Synthetic HTTP/MCP/auth/accounting checks; no paid calls or live services."""
import base64
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import sqlite3
import time

from fastapi.testclient import TestClient
import pytest

from rl_move.overseer import reviewer
from rl_move.overseer import scheduler
from rl_move.overseer.journal import Journal
from rl_move.overseer.memory import remember_lesson
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


def model_advice(summary, actions=None):
    return {"summary": summary, "risks": [], "recommended_actions": actions or [],
            "goal_assessment": {goal: {"sim": "Unknown", "physical": "Unknown", "next_step": "Read current evidence"}
                                for goal in ("any_means", "rl_only")}}


def test_public_health_and_shell_never_disclose_private_records(client, tmp_path):
    assert client.get("/healthz").json() == {"service": "hexapod-metaagent", "status": "ok", "scheduler_enabled": False}
    assert client.get("/").status_code == 200
    for path in ("/api/status", "/api/runs", "/api/runs/wake", "/api/costs", "/api/recommendations", "/api/memory", "/api/session"):
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
    assert client.get("/api/status", headers=HEADERS).json()["scheduler"]["configured_at"] is None
    assert call(client, "get_memory").json()["result"]["structuredContent"]["lessons"] == []
    assert client.get("/api/memory", headers=VIEW_HEADERS).json()["recent_reviews"] == []
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
    assert names == {"get_status", "list_runs", "get_run", "get_costs", "list_recommendations", "get_memory"}
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


def test_continuation_displays_latest_advice_and_preserves_all_wake_costs(tmp_path):
    store = Store(tmp_path / "overseer.sqlite3")
    now = datetime.now(timezone.utc)
    store.start_wake("manual review", now, wake_id="wake")
    store.reserve("wake", "original", "10.15", now)
    store.reserve("wake", "continuation", "4.04", now)
    store.settle("continuation", "0.12", now)
    journal = Journal(store.path)
    original = {"generated_at": now.isoformat(), "wake": {"wake_id": "wake"},
                "llm_review": {"provider": "claude", "model": "original-model", "status": "blocked"}}
    journal.record("wake", original, "blocked")
    latest = {"generated_at": (now + timedelta(seconds=1)).isoformat(), "wake": {"wake_id": "wake"},
              "prior_attempts": [{"report_id": "wake", "llm_review": original["llm_review"]}],
              "llm_review": {"provider": "claude", "model": "continuation-model", "status": "completed"}}
    journal.record("wake:continuation", latest, "succeeded")
    client = TestClient(create_app(tmp_path, api_token=OPERATOR))
    runs = client.get("/api/runs", headers=HEADERS).json()["runs"]
    assert len(runs) == 1
    assert runs[0]["model"] == "continuation-model"
    assert runs[0]["actual_cost_usd"] == "0.120000"
    assert runs[0]["pending_reserved_usd"] == "10.150000"
    detail = call(client, "get_run", {"wake_id": "wake"}).json()["result"]["structuredContent"]
    assert detail["report"] == latest
    assert len(detail["reservations"]) == 2
    with journal.connect() as db:
        assert json.loads(db.execute("SELECT body FROM overseer_reports WHERE report_id='wake'").fetchone()[0]) == original


def test_recommendations_include_latest_model_advice_without_an_outbox_incident(tmp_path):
    store = Store(tmp_path / "overseer.sqlite3")
    stamp = datetime.now(timezone.utc)
    store.start_wake("Review changed evidence", stamp, wake_id="wake")
    journal = Journal(store.path)
    action = {"action": "inspect", "target": "walking run", "reason": "Read changed evidence",
              "evidence": ["run receipt"]}
    journal.record("wake", {"generated_at": stamp.isoformat(), "wake": {"wake_id": "wake"}, "llm_review": {
        "status": "completed", "provider": "test", "model": "old-model",
        "review": model_advice("Superseded advice", [action])}}, "succeeded")
    journal.record("wake:continuation", {"generated_at": (stamp + timedelta(seconds=1)).isoformat(), "wake": {"wake_id": "wake"}, "llm_review": {
        "status": "completed", "provider": "test", "model": "current-model",
        "review": model_advice("Current advice", [action])}}, "succeeded")
    # A failed/invalid model response must not become accepted advice.
    journal.record("invalid", {"generated_at": stamp.isoformat(), "llm_review": {"status": "blocked", "review": {
        "summary": "Do not display as validated advice", "recommended_actions": [action]}}}, "blocked")
    before = store.path.read_bytes()
    client = TestClient(create_app(tmp_path, api_token=OPERATOR))
    result = client.get("/api/recommendations", headers=HEADERS).json()
    assert result["recommendations"] == []
    assert len(result["model_recommendations"]) == 1
    advice = result["model_recommendations"][0]
    assert advice["wake_id"] == "wake" and advice["report_id"] == "wake:continuation"
    assert advice["summary"] == "Current advice" and advice["model"] == "current-model"
    assert advice["recommended_actions"] == [action]
    assert advice["execution_status"] == "proposal_only"
    assert call(client, "list_recommendations").json()["result"]["structuredContent"] == result
    assert store.path.read_bytes() == before


def test_status_reports_persisted_schedule_hold_and_free_checks_without_running_them(tmp_path, monkeypatch):
    store = Store(tmp_path / "overseer.sqlite3")
    scheduler.configure(store.path, enabled=True, project_root=tmp_path)
    stamp = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(store.path)) as db, db:
        config = json.loads(db.execute("SELECT body FROM metaagent_schedule").fetchone()[0])
        config["review_hold"] = "Review failed; owner must inspect the retained charge"
        db.execute("UPDATE metaagent_schedule SET body=?", (json.dumps(config),))
        db.execute("INSERT INTO metaagent_checks(check_id,started_at,finished_at,outcome,detail,paid_review_started) VALUES(?,?,?,?,?,?)",
                   ("check", stamp, stamp, "held", "No model called while held", 0))
    store.start_wake("Separate retained wake", wake_id="active")
    monkeypatch.setattr(scheduler, "tick", lambda *a, **k: pytest.fail("HTTP read ran the scheduler"))
    before = store.path.read_bytes()
    client = TestClient(create_app(tmp_path, api_token=OPERATOR, viewer_token=VIEWER))
    status = client.get("/api/status", headers=VIEW_HEADERS).json()
    assert status["scheduler_enabled"] is True
    schedule = status["scheduler"]
    assert schedule["last_check_at"] == stamp and schedule["last_outcome"] == "held"
    assert schedule["last_detail"] == "No model called while held"
    assert schedule["free_checks"] == 1 and schedule["paid_reviews_started"] == 0
    assert schedule["review_hold"] == config["review_hold"]
    assert datetime.fromisoformat(schedule["next_check_at"]) > datetime.fromisoformat(stamp)
    assert status["budget"]["active_wake_id"] == "active"
    assert client.get("/healthz").json()["scheduler_enabled"] is True
    assert call(client, "get_status", headers=VIEW_HEADERS).json()["result"]["structuredContent"]["scheduler"] == schedule
    assert store.path.read_bytes() == before
    scheduler.configure(store.path, enabled=False)
    status = client.get("/api/status", headers=HEADERS).json()
    assert status["scheduler_enabled"] is False and status["scheduler"]["next_check_at"] is None


def test_memory_views_preserve_provenance_corrections_unknown_costs_and_database(tmp_path):
    store = Store(tmp_path / "overseer.sqlite3")
    store.register_agent(registered_record())
    remember_lesson(store.path, {"lesson_id": "hypothesis", "source": "review:wake",
        "lesson": "Try a smaller observation set", "evidence": ["Synthetic review"], "status": "model_hypothesis"})
    remember_lesson(store.path, {"lesson_id": "correction", "source": "Owner receipt", "owner": "operator",
        "lesson": "Do not infer hardware readiness from sim; api_key=sk-private-credential", "evidence": ["Physical inspection receipt"],
        "status": "owner_verified", "corrects": ["hypothesis"]}, operator=True)
    store.start_wake("Recorded advice", wake_id="wake")
    Journal(store.path).record("wake", {"generated_at": datetime.now(timezone.utc).isoformat(), "wake": {"wake_id": "wake"},
        "llm_review": {"status": "completed", "provider": "test", "model": "test-model",
                       "review": model_advice("Read the recorded corrections")}}, "succeeded")
    before = store.path.read_bytes()
    client = TestClient(create_app(tmp_path, api_token=OPERATOR, viewer_token=VIEWER))
    response = client.get("/api/memory", headers=VIEW_HEADERS)
    memory = response.json()
    assert response.status_code == 200 and "sk-private-credential" not in response.text
    assert memory["lessons"][0]["status"] == "owner_verified"
    assert memory["lessons"][0]["provenance"] == "operator"
    assert memory["lessons"][0]["corrects"] == ["hypothesis"]
    assert memory["lessons"][1]["status"] == "model_hypothesis"
    assert memory["recent_reviews"][0]["wake_id"] == "wake"
    assert memory["recent_reviews"][0]["status"] == "model_hypothesis"
    assert call(client, "get_memory", headers=VIEW_HEADERS).json()["result"]["structuredContent"] == memory
    assert client.get("/api/costs", headers=HEADERS).json()["unknown_cost_agents"] == 1
    for name in ("run_review", "configure_schedule", "remember_lesson"):
        assert call(client, name).json()["error"]["code"] == -32601
    assert client.post("/api/memory", headers=HEADERS, json={}).status_code == 405
    assert client.post("/api/schedule", headers=HEADERS, json={}).status_code == 404
    assert store.path.read_bytes() == before


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
