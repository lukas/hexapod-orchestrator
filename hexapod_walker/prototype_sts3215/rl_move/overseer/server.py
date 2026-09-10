"""Authenticated metaagent dashboard and MCP; reads never invoke a model.

The legacy overseer database remains the only registry/budget journal. This
service reports persisted scheduler/memory state, but never runs a scheduler,
review executor, operational control or notification itself.
"""
from __future__ import annotations

import base64
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .__main__ import default_state_dir
from .memory import read_memory
from .report import redact
from .reviewer import _validate_review
from .scheduler import scheduler_status
from .store import Store

SESSION_COOKIE = "metaagent_session"
MAX_BODY = 128 * 1024
MAX_RECORDS = 200
READ_TOOLS = (
    ("get_status", "Read recorded project agents and metaagent status.", {}),
    ("list_runs", "List recent review runs, including scheduled and manual reviews.", {}),
    ("get_run", "Read one review and its recorded report.", {"wake_id": {"type": "string"}}),
    ("get_costs", "Read actual spending, pending reservations, and unknown monitored costs separately.", {}),
    ("list_recommendations", "Read recommendations and owner/delivery receipts; this executes nothing.", {}),
    ("get_memory", "Read saved lessons and recent review context with their provenance; this executes nothing.", {}),
)
WRITE_TOOLS = (
    ("register_agent", "Register an agent's purpose and ownership; starts no work.", {"record": {"type": "object"}}),
    ("checkpoint_agent", "Record an agent checkpoint; a heartbeat is not proof of progress.",
     {"agent_id": {"type": "string"}, "record": {"type": "object"}}),
    ("record_agent_spend", "Record one nonoverlapping provider cost receipt with an idempotent event ID.",
     {"agent_id": {"type": "string"}, "event_id": {"type": "string"},
      "amount_usd": {"type": "string"}, "occurred_at": {"type": "string"}, "source": {"type": "string"}}),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _usd(value: int | None) -> str | None:
    return None if value is None else format(Decimal(value) / 1_000_000, ".6f")


def _decode(value: str | None) -> Any:
    return json.loads(value) if value else None


@contextmanager
def _reader(path: Path):
    if not path.is_file():
        yield None
        return
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)
    db.row_factory = sqlite3.Row
    deadline = time.monotonic() + 2
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        db.execute("BEGIN")
        yield db
    finally:
        db.close()


def _table(db, name: str) -> bool:
    return db is not None and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _budget(db) -> dict:
    available = _table(db, "limits") and _table(db, "reservations") and _table(db, "wakes")
    empty = {"data_available": False, "wake_limit_usd": "20.00", "daily_limit_usd": "80.00",
             "rolling_24h_actual_usd": None, "pending_reserved_usd": None,
             "rolling_24h_charged_usd": None, "rolling_24h_remaining_usd": None,
             "lifetime_actual_usd": None, "active_wake_id": None}
    if not available:
        return empty
    limits = db.execute("SELECT wake,daily FROM limits WHERE singleton=1").fetchone()
    if not limits:
        return empty
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="microseconds")
    costs = db.execute("SELECT COALESCE(SUM(actual),0) AS lifetime,"
                       "COALESCE(SUM(CASE WHEN settled_at>? THEN actual ELSE 0 END),0) AS recent,"
                       "COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END),0) AS pending "
                       "FROM reservations", (cutoff,)).fetchone()
    active = db.execute("SELECT wake_id FROM wakes WHERE status='active'").fetchone()
    charged = costs["recent"] + costs["pending"]
    return {"data_available": True, "wake_limit_usd": _usd(limits["wake"]), "daily_limit_usd": _usd(limits["daily"]),
            "rolling_24h_actual_usd": _usd(costs["recent"]), "pending_reserved_usd": _usd(costs["pending"]),
            "rolling_24h_charged_usd": _usd(charged), "rolling_24h_remaining_usd": _usd(max(0, limits["daily"] - charged)),
            "lifetime_actual_usd": _usd(costs["lifetime"]), "active_wake_id": active[0] if active else None}


def _agents(db) -> tuple[list[dict], bool]:
    if not _table(db, "agents"):
        return [], False
    rows = db.execute("SELECT agent_id,record_json,last_reviewed_at FROM agents ORDER BY agent_id LIMIT ?", (MAX_RECORDS + 1,)).fetchall()
    receipts = {}
    if _table(db, "spend_events"):
        receipts = {row["agent_id"]: row for row in db.execute(
            "SELECT agent_id,SUM(amount) AS amount,MAX(occurred_at) AS last_receipt_at,COUNT(*) AS count FROM spend_events GROUP BY agent_id")}
    agents = []
    for row in rows[:MAX_RECORDS]:
        item = _decode(row["record_json"])
        item["agent_id"] = row["agent_id"]
        receipt = receipts.get(row["agent_id"])
        item.update(receipt_total_usd=_usd(receipt["amount"]) if receipt else None,
                    last_receipt_at=receipt["last_receipt_at"] if receipt else None,
                    last_reviewed_at=row["last_reviewed_at"])
        # Receipts may be partial. A known cumulative cost is an explicit
        # registered observation; never infer it from a missing receipt.
        value = item.get("reported_cost_usd")
        try:
            total = Decimal(str(value))
            known = item.get("cost_status") == "known" and total.is_finite() and total >= 0
        except Exception:
            known = False
        item["total_cost_usd"] = format(total, ".6f") if known else None
        item["cost_status"] = "known" if known else "unknown"
        agents.append(item)
    return agents, len(rows) > MAX_RECORDS


def _latest_report(db, wake_id: str):
    # Continuations have immutable report IDs of their own, but share one
    # wake and its spending cap. Legacy reports used the wake ID directly.
    return db.execute(
        "SELECT report_id,body,"
        "json_extract(body,'$.llm_review.model') AS model,"
        "json_extract(body,'$.llm_review.provider') AS provider FROM overseer_reports "
        "WHERE report_id=? OR json_extract(body,'$.wake.wake_id')=? "
        "ORDER BY created_at DESC,rowid DESC LIMIT 1",
        (wake_id, wake_id)).fetchone() if _table(db, "overseer_reports") else None


def _run_row(db, row) -> dict:
    report = _latest_report(db, row["wake_id"])
    report_available = report is not None
    model = report["model"] if report else None
    provider = report["provider"] if report else None
    if not provider and model and str(model).startswith("claude-"):
        provider = "Anthropic"
    if report is not None and model is None:
        provider = "Deterministic"
    actual, pending = None, None
    if _table(db, "reservations"):
        costs = db.execute("SELECT COALESCE(SUM(actual),0),COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END),0) FROM reservations WHERE wake_id=?", (row["wake_id"],)).fetchone()
        actual, pending = costs
    return {key: row[key] for key in ("wake_id", "status", "outcome", "reason", "started_at", "finished_at")} | {
        "actual_cost_usd": _usd(actual), "pending_reserved_usd": _usd(pending), "report_available": report_available,
        "provider": provider, "model": model}


def _runs(db) -> dict:
    rows = db.execute("SELECT * FROM wakes ORDER BY started_at DESC LIMIT 101").fetchall() if _table(db, "wakes") else []
    return {"runs": [_run_row(db, row) for row in rows[:100]], "limit": 100, "truncated": len(rows) > 100}


def _run_detail(db, wake_id: str) -> dict:
    row = db.execute("SELECT * FROM wakes WHERE wake_id=?", (wake_id,)).fetchone() if _table(db, "wakes") else None
    if row is None:
        raise HTTPException(404, "Unknown review run")
    report_row = _latest_report(db, wake_id)
    reservations = []
    if _table(db, "reservations"):
        for reservation in db.execute("SELECT * FROM reservations WHERE wake_id=? ORDER BY created_at LIMIT ?", (wake_id, MAX_RECORDS)):
            reservations.append({"operation_id": reservation["operation_id"], "reserved_usd": _usd(reservation["reserved"]),
                                 "actual_usd": _usd(reservation["actual"]), "status": "pending" if reservation["actual"] is None else "settled",
                                 "created_at": reservation["created_at"], "settled_at": reservation["settled_at"]})
    return {"run": _run_row(db, row), "report": _decode(report_row["body"]) if report_row else None, "reservations": reservations}


def _recommendations(db) -> dict:
    rows = db.execute("SELECT * FROM overseer_outbox ORDER BY created_at DESC LIMIT 101").fetchall() if _table(db, "overseer_outbox") else []
    items = []
    for row in rows[:100]:
        item = {key: row[key] for key in ("incident_id", "status", "notification_status", "created_at", "updated_at")}
        for key in ("body", "action_receipt"):
            item[key] = _decode(row[key]) if key in row.keys() else None
        item["notification_receipt"] = row["notification_receipt"] if "notification_receipt" in row.keys() else None
        items.append(item)
    # A model's advice is stored in its report, not necessarily in the
    # deterministic incident outbox. Keep those distinct, and show only the
    # latest report for each wake so a resumed attempt cannot duplicate advice.
    reports = db.execute(
        "WITH ranked AS (SELECT report_id,body,created_at,"
        "COALESCE(NULLIF(json_extract(body,'$.wake.wake_id'),''),report_id) AS wake_id,"
        "ROW_NUMBER() OVER (PARTITION BY COALESCE(NULLIF(json_extract(body,'$.wake.wake_id'),''),report_id) "
        "ORDER BY created_at DESC,rowid DESC) AS position FROM overseer_reports) "
        "SELECT report_id,body,created_at,wake_id FROM ranked WHERE position=1 "
        "ORDER BY created_at DESC,report_id DESC LIMIT 101"
    ).fetchall() if _table(db, "overseer_reports") else []
    advice = []
    for row in reports[:100]:
        report = _decode(row["body"])
        model = report.get("llm_review") or {}
        if not isinstance(model, dict) or model.get("status") != "completed":
            continue
        try:
            assessment = _validate_review(model.get("review"))
        except (ValueError, TypeError):
            continue
        advice.append({"wake_id": row["wake_id"], "report_id": row["report_id"],
                       "created_at": row["created_at"], "provider": model.get("provider"),
                       "model": model.get("model"), "summary": assessment.get("summary"),
                       "recommended_actions": assessment.get("recommended_actions") or [],
                       "source": "model_advice", "execution_status": "proposal_only"})
    return {"recommendations": items, "limit": 100, "truncated": len(rows) > 100,
            "model_recommendations": advice, "model_limit": 100,
            "model_truncated": len(reports) > 100}


def _projection(path: Path, name: str, role: str, wake_id: str | None = None) -> dict:
    if name == "memory":
        return redact(read_memory(path))
    with _reader(path) as db:
        if name == "runs":
            result = _runs(db)
        elif name == "run":
            result = _run_detail(db, wake_id)
        elif name == "recommendations":
            result = _recommendations(db)
        elif name == "costs":
            agents, truncated = _agents(db)
            excluded = {item["agent_id"] for item in agents if item.get("is_overseer") or item.get("overseer_wake_id")
                        or item.get("is_metaagent") or item.get("metaagent_wake_id")}
            while True:
                children = {item["agent_id"] for item in agents if item.get("parent_id") in excluded}
                if children <= excluded:
                    break
                excluded.update(children)
            agents = [item for item in agents if item["agent_id"] not in excluded]
            rows = [{key: item.get(key) for key in ("agent_id", "name", "cost_status", "receipt_total_usd", "total_cost_usd", "last_receipt_at")} for item in agents]
            known = [Decimal(item["total_cost_usd"]) for item in rows if item["total_cost_usd"] is not None]
            receipts = [Decimal(item["receipt_total_usd"]) for item in rows if item["receipt_total_usd"] is not None]
            result = {"metaagent": _budget(db), "agents": rows, "truncated": truncated,
                      "metaagent_registry_records_excluded": len(excluded),
                      "unknown_cost_agents": sum(item["cost_status"] == "unknown" for item in rows),
                      "monitored_total_usd": format(sum(known), ".6f") if rows and len(known) == len(rows) and not truncated else None,
                      "monitored_receipt_total_usd": format(sum(receipts), ".6f") if receipts and not truncated else None}
        else:
            agents, truncated = _agents(db)
            runs = _runs(db)["runs"]
            schedule = scheduler_status(path)
            result = {"service": "hexapod-metaagent", "scheduler_enabled": schedule["enabled"],
                      "scheduler": schedule,
                      "review_execution": "scheduler_or_cli" if schedule["enabled"] else "cli_only",
                      "authenticated_role": role, "generated_at": _now(), "source": "durable_records",
                      "data_available": db is not None, "agents": agents, "agents_truncated": truncated,
                      "agent_counts": dict(Counter(item.get("status", "unknown") for item in agents)),
                      "latest_run": runs[0] if runs else None, "budget": _budget(db)}
        return redact(result)


async def _body(request: Request) -> dict:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise HTTPException(413, "Request body is too large")
        chunks.append(chunk)
    try:
        value = json.loads(b"".join(chunks), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Expected a JSON object")
    if not isinstance(value, dict):
        raise HTTPException(400, "Expected a JSON object")
    return value


def create_app(state_dir: Path | None = None, api_token: str | None = None,
               viewer_token: str | None = None, static_dir: Path | None = None,
               sso_secret_file: Path | None = None, sso_users: str | None = None) -> FastAPI:
    """Construct the service without creating a database or starting workers."""
    directory = Path(state_dir) if state_dir is not None else default_state_dir()
    database = directory / "overseer.sqlite3"
    operator_token = api_token if api_token is not None else os.environ.get("METAAGENT_API_TOKEN", "")
    read_token = viewer_token if viewer_token is not None else os.environ.get("METAAGENT_VIEWER_TOKEN", "")
    if operator_token and read_token and hmac.compare_digest(operator_token, read_token):
        raise ValueError("Operator and viewer credentials must differ")
    secret = sso_secret_file or os.environ.get("METAAGENT_SSO_SECRET_FILE")
    users = sso_users if sso_users is not None else os.environ.get("METAAGENT_SSO_USERS", "")
    sso = None
    if secret and users:
        from hexapod_lab.sso import SsoAuth
        sso = SsoAuth(Path(secret), users)
    signing_key = hashlib.sha256(("metaagent/session/v1:" + operator_token + ":" + read_token).encode()).digest()
    app = FastAPI(title="Hexapod metaagent", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.database = database

    def token_role(token: str) -> str | None:
        if not token or len(token) > 4096:
            return None
        if operator_token and hmac.compare_digest(token.encode(), operator_token.encode()):
            return "operator"
        if read_token and hmac.compare_digest(token.encode(), read_token.encode()):
            return "viewer"
        return None

    def cookie_role(value: str) -> str | None:
        if not (operator_token or read_token) or not value or len(value) > 1024:
            return None
        try:
            payload, signature = value.rsplit(".", 1)
            expected = hmac.new(signing_key, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                return None
            data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return data["role"] if data["expires"] > time.time() and data["role"] in {"operator", "viewer"} else None
        except (ValueError, KeyError, TypeError, UnicodeError):
            return None

    def authenticate(request: Request) -> dict:
        auth = request.headers.get("authorization", "")
        if auth:
            scheme, _, value = auth.partition(" ")
            role = token_role(value) if scheme.lower() == "bearer" else None
            if role:
                return {"role": role, "method": "bearer"}
            raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
        role = cookie_role(request.cookies.get(SESSION_COOKIE, ""))
        if role:
            return {"role": role, "method": "session"}
        if sso is not None:
            principal = sso.authenticate(request.cookies.get("hexapod_sso", ""))
            if principal is not None:
                return {"role": "operator" if principal.role in {"admin", "operator"} else "viewer", "method": "sso"}
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})

    def same_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        public_origin = os.environ.get("METAAGENT_PUBLIC_ORIGIN", "").rstrip("/")
        expected = public_origin or str(request.base_url).rstrip("/")
        if origin and origin != expected:
            raise HTTPException(403, "Cross-origin request rejected")

    def operator(request: Request, identity: dict) -> None:
        if identity["role"] != "operator":
            raise HTTPException(403, "Operator role required")
        if identity["method"] != "bearer":
            same_origin(request)
            if request.headers.get("x-metaagent-csrf") != "1":
                raise HTTPException(403, "Session writes require a CSRF header")

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        return JSONResponse({"detail": "Metaagent records are temporarily unavailable"}, status_code=503)

    @app.get("/healthz")
    def health():
        return {"service": "hexapod-metaagent", "status": "ok",
                "scheduler_enabled": scheduler_status(database)["enabled"]}

    @app.get("/api/session")
    def session(identity: dict = Depends(authenticate)):
        return {"authenticated": True, **identity}

    @app.post("/api/session")
    async def login(request: Request):
        same_origin(request)
        body = await _body(request)
        role = token_role(body.get("token")) if isinstance(body.get("token"), str) else None
        if not role:
            raise HTTPException(401, "Authentication required")
        # Remote browser sessions require HTTPS; only literal loopback HTTP is
        # eligible for the local dashboard. Never trust forwarded identity.
        local = request.url.hostname in {"127.0.0.1", "localhost", "::1"}
        secure = (request.url.scheme == "https" or not local or
                  os.environ.get("METAAGENT_PUBLIC_ORIGIN", "").startswith("https://"))
        if request.url.scheme != "https" and not local and not os.environ.get("METAAGENT_PUBLIC_ORIGIN", "").startswith("https://"):
            raise HTTPException(400, "Remote browser sessions require HTTPS")
        payload = base64.urlsafe_b64encode(json.dumps({"role": role, "expires": int(time.time()) + 28800}).encode()).decode().rstrip("=")
        value = payload + "." + hmac.new(signing_key, payload.encode(), hashlib.sha256).hexdigest()
        response = JSONResponse({"authenticated": True, "role": role, "method": "session"})
        response.set_cookie(SESSION_COOKIE, value, max_age=28800, httponly=True, secure=secure, samesite="strict", path="/")
        return response

    @app.delete("/api/session")
    def logout(request: Request):
        same_origin(request)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/api/status")
    def status(identity: dict = Depends(authenticate)):
        return _projection(database, "status", identity["role"])

    @app.get("/api/runs")
    def runs(identity: dict = Depends(authenticate)):
        return _projection(database, "runs", identity["role"])

    @app.get("/api/runs/{wake_id}")
    def run_detail(wake_id: str, identity: dict = Depends(authenticate)):
        return _projection(database, "run", identity["role"], wake_id)

    @app.get("/api/costs")
    def costs(identity: dict = Depends(authenticate)):
        return _projection(database, "costs", identity["role"])

    @app.get("/api/recommendations")
    def recommendations(identity: dict = Depends(authenticate)):
        return _projection(database, "recommendations", identity["role"])

    @app.get("/api/memory")
    def memory(identity: dict = Depends(authenticate)):
        return _projection(database, "memory", identity["role"])

    @app.post("/mcp")
    async def mcp(request: Request, identity: dict = Depends(authenticate)):
        body = await _body(request)
        ident = body.get("id")
        if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32600, "message": "Invalid request"}}
        method = body["method"]
        if method.startswith("notifications/"):
            return Response(status_code=202)
        try:
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "hexapod-metaagent", "version": "1.0"}}
            elif method == "tools/list":
                tools = READ_TOOLS + (WRITE_TOOLS if identity["role"] == "operator" else ())
                result = {"tools": [{"name": name, "description": description,
                                     "inputSchema": {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False},
                                     "annotations": {"readOnlyHint": name in {t[0] for t in READ_TOOLS}, "destructiveHint": False}}
                                    for name, description, fields in tools]}
            elif method == "tools/call":
                params = body.get("params") or {}
                if not isinstance(params, dict):
                    raise ValueError("Tool parameters must be an object")
                name, arguments = params.get("name"), params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object")
                projections = {"get_status": "status", "list_runs": "runs", "get_run": "run", "get_costs": "costs", "list_recommendations": "recommendations", "get_memory": "memory"}
                if name in projections:
                    value = _projection(database, projections[name], identity["role"], arguments.get("wake_id"))
                elif name in {t[0] for t in WRITE_TOOLS}:
                    operator(request, identity)
                    store = Store(database)
                    if name == "register_agent":
                        record = redact(arguments["record"])
                        if not isinstance(record, dict) or any(not record.get(field) for field in ("agent_id", "task_id", "execution_owner", "goals", "scope")):
                            raise ValueError("Registration requires identity, logical task, execution owner, goals and scope")
                        value = store.register_agent({**record, "registration": "registered"})
                    elif name == "checkpoint_agent":
                        value = store.heartbeat(arguments["agent_id"], redact(arguments["record"]))
                    else:
                        value = store.record_spend(arguments["agent_id"], arguments["event_id"], arguments["amount_usd"], arguments["occurred_at"], arguments.get("source", "reported"))
                    value = redact(value)
                else:
                    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Unknown tool"}}
                result = {"content": [{"type": "text", "text": json.dumps(value, allow_nan=False)}], "structuredContent": value, "isError": False}
            else:
                return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Unknown method"}}
        except (ValueError, KeyError, TypeError):
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "Invalid parameters or conflicting receipt"}}
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    assets = Path(static_dir) if static_dir is not None else Path(__file__).with_name("static")
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/mcp-info")
    def mcp_info():
        return FileResponse(assets / "mcp-info.html")

    @app.get("/")
    def index():
        path = assets / "index.html"
        return FileResponse(path) if path.is_file() else HTMLResponse("<!doctype html><title>Metaagent</title><p>Metaagent dashboard assets are not installed.</p>")

    return app
