"""Local registry and durable budget accounting for a manually invoked overseer.

No method launches work. Reserve the worst-case cost *before* each model or
child-agent call, and reuse the operation ID after a retry/restart. An unresolved
reservation is never automatically refunded, even when its wake has finished.
Monitored agents' reported spending is separate from the overseer's budget.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid


class BudgetExceeded(ValueError):
    """A reservation would exceed a durable wake or rolling-day budget."""


class WakeConflict(ValueError):
    """Another unfinished wake owns this store."""


def _money(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("USD amount must be a finite, nonnegative number")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000"):
            raise ValueError("USD amount must be finite and between 0 and 1000000000")
        if 0 < amount < Decimal("0.000001"):
            return 1
        with localcontext() as context:
            context.prec = 40
            return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid USD amount") from exc


def _usd(micros: int) -> str:
    return f"{micros // 1_000_000}.{micros % 1_000_000:06d}"


def _stamp(value: datetime | str | None = None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Timestamp must be timezone-aware ISO 8601") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware ISO 8601")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonblank string")
    return value


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Record must contain finite JSON-compatible values") from exc


class Store:
    """Process-safe SQLite store; USD returns are exact six-decimal strings.

    Limits can be lowered for a store but never exceed $20/wake or $80/day.
    They are persisted: opening the same database with different limits fails
    instead of resetting its budget. Each public operation owns a transaction.
    """

    def __init__(self, path: str | Path, wake_limit_usd=20, daily_limit_usd=80):
        self.path = Path(path)
        self.wake_limit = _money(wake_limit_usd)
        self.daily_limit = _money(daily_limit_usd)
        if self.wake_limit > _money(20) or self.daily_limit > _money(80):
            raise ValueError("Limits cannot exceed $20 per wake and $80 per rolling day")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as con:
            for statement in (
                "CREATE TABLE IF NOT EXISTS limits (singleton INTEGER PRIMARY KEY CHECK(singleton=1), wake INTEGER NOT NULL, daily INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS agents (agent_id TEXT PRIMARY KEY, record_json TEXT NOT NULL, reviewed_seq INTEGER NOT NULL DEFAULT 0, last_reviewed_at TEXT)",
                "CREATE TABLE IF NOT EXISTS spend_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, agent_id TEXT NOT NULL REFERENCES agents(agent_id), amount INTEGER NOT NULL CHECK(amount>=0), occurred_at TEXT NOT NULL, source TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS wakes (wake_id TEXT PRIMARY KEY, reason TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','finished')), started_at TEXT NOT NULL, finished_at TEXT, outcome TEXT, review_seq INTEGER NOT NULL, reviewed_agents_json TEXT)",
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active_wake ON wakes(status) WHERE status='active'",
                "CREATE TABLE IF NOT EXISTS reservations (operation_id TEXT PRIMARY KEY, wake_id TEXT NOT NULL REFERENCES wakes(wake_id), reserved INTEGER NOT NULL CHECK(reserved>=0), actual INTEGER CHECK(actual>=0), created_at TEXT NOT NULL, settled_at TEXT)",
                "CREATE INDEX IF NOT EXISTS spend_agent_seq ON spend_events(agent_id,seq)",
            ):
                con.execute(statement)
            con.execute("INSERT OR IGNORE INTO limits VALUES(1,?,?)", (self.wake_limit, self.daily_limit))
            saved = con.execute("SELECT wake,daily FROM limits WHERE singleton=1").fetchone()
            if (saved["wake"], saved["daily"]) != (self.wake_limit, self.daily_limit):
                raise ValueError("Existing store limits differ; budgets cannot be reset on reopen")
        self.path.chmod(0o600)

    @contextmanager
    def _transaction(self, *, write=True):
        con = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield con
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    @staticmethod
    def _agent(con, agent_id):
        row = con.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown agent: {agent_id}")
        return {**json.loads(row["record_json"]), "last_reviewed_at": row["last_reviewed_at"]}

    @staticmethod
    def _validate_agent(record):
        if not isinstance(record, dict):
            raise ValueError("Agent record must be an object")
        record = dict(record)
        _text(record.get("agent_id"), "agent_id")
        for name in ("name", "provider", "scope", "status", "cost_status"):
            if name in record:
                _text(record[name], name)
        for name in ("parent_id", "task_id"):
            if record.get(name) is not None:
                _text(record[name], name)
        for name in ("goals", "progress_evidence"):
            if name in record and not isinstance(record[name], list):
                raise ValueError(f"{name} must be a list")
        if any(not isinstance(goal, str) or not goal for goal in record.get("goals", [])):
            raise ValueError("goals must contain nonblank strings")
        for name in ("started_at", "last_heartbeat_at", "last_progress_at"):
            if record.get(name) is not None:
                record[name] = _stamp(record[name])
        if {"last_reviewed_at", "reviewed_seq", "unreviewed_cost_usd",
                "unreviewed_through_seq"} & record.keys():
            raise ValueError("Review acknowledgements and unreviewed spending are derived by the store")
        _json(record)
        return record

    def register_agent(self, record: dict) -> dict:
        """Upsert observed metadata without changing spend/review history."""
        record = self._validate_agent(record)
        agent_id = record["agent_id"]
        with self._transaction() as con:
            row = con.execute("SELECT record_json FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            saved = json.loads(row[0]) if row else {
                "agent_id": agent_id, "parent_id": None, "task_id": None,
                "name": agent_id, "provider": "unknown", "goals": [],
                "scope": "unknown", "status": "unknown", "started_at": None,
                "last_heartbeat_at": None, "last_progress_at": None,
                "progress_evidence": [], "cost_status": "unknown",
            }
            saved.update(record)
            con.execute("INSERT INTO agents(agent_id,record_json) VALUES(?,?) ON CONFLICT(agent_id) DO UPDATE SET record_json=excluded.record_json", (agent_id, _json(saved)))
            return self._agent(con, agent_id)

    def list_agents(self) -> list[dict]:
        with self._transaction(write=False) as con:
            return [self._agent(con, row[0]) for row in con.execute("SELECT agent_id FROM agents ORDER BY agent_id")]

    def heartbeat(self, agent_id: str, updates: dict, now=None) -> dict:
        if not isinstance(updates, dict):
            raise ValueError("Heartbeat updates must be an object")
        if "agent_id" in updates and updates["agent_id"] != agent_id:
            raise ValueError("Heartbeat cannot change agent identity")
        record = self._validate_agent({"agent_id": agent_id, **updates})
        record.setdefault("last_heartbeat_at", _stamp(now))
        with self._transaction() as con:
            saved = self._agent(con, agent_id)
            saved.pop("last_reviewed_at")
            saved.update(record)
            con.execute("UPDATE agents SET record_json=? WHERE agent_id=?", (_json(saved), agent_id))
            return self._agent(con, agent_id)

    def record_spend(self, agent_id, event_id, amount_usd, occurred_at, source="reported") -> dict:
        """Record one monitored-agent cost; global event IDs are idempotent."""
        event_id = _text(event_id, "event_id")
        amount, occurred_at, source = _money(amount_usd), _stamp(occurred_at), _text(source, "source")
        with self._transaction() as con:
            self._agent(con, agent_id)
            row = con.execute("SELECT * FROM spend_events WHERE event_id=?", (event_id,)).fetchone()
            reused = row is not None
            if reused and (row["agent_id"], row["amount"], row["occurred_at"], row["source"]) != (agent_id, amount, occurred_at, source):
                raise ValueError("Spend event ID already has different data")
            if not reused:
                con.execute("INSERT INTO spend_events(event_id,agent_id,amount,occurred_at,source) VALUES(?,?,?,?,?)", (event_id, agent_id, amount, occurred_at, source))
                row = con.execute("SELECT * FROM spend_events WHERE event_id=?", (event_id,)).fetchone()
            return {"agent_id": agent_id, "event_id": event_id, "amount_usd": _usd(amount), "occurred_at": occurred_at, "source": source, "seq": row["seq"], "reused": reused}

    def spending_since_review(self, agent_id) -> dict:
        with self._transaction(write=False) as con:
            agent = self._agent(con, agent_id)
            reviewed_seq = con.execute("SELECT reviewed_seq FROM agents WHERE agent_id=?", (agent_id,)).fetchone()[0]
            rows = con.execute("SELECT * FROM spend_events WHERE agent_id=? AND seq>? ORDER BY seq", (agent_id, reviewed_seq)).fetchall()
            amount = sum(row["amount"] for row in rows)
            return {"agent_id": agent_id, "amount_usd": _usd(amount), "cost_status": agent["cost_status"], "last_reviewed_at": agent["last_reviewed_at"], "event_count": len(rows), "through_seq": rows[-1]["seq"] if rows else reviewed_seq, "sources": sorted({row["source"] for row in rows})}

    @staticmethod
    def _wake(con, wake_id):
        row = con.execute("SELECT * FROM wakes WHERE wake_id=?", (wake_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown wake: {wake_id}")
        result = dict(row)
        result["reviewed_agent_ids"] = json.loads(result.pop("reviewed_agents_json") or "[]")
        return result

    def start_wake(self, reason, now=None, wake_id=None, *, review_seq=None) -> dict:
        """Create or resume a wake, retaining its budget and review cutoff.

        Pass the cost snapshot's ``review_seq`` when observations were collected
        before this transaction. Later-arriving costs must not be acknowledged
        merely because the wake began after their insertion.
        """
        reason, now = _text(reason, "reason"), _stamp(now)
        wake_id = _text(wake_id, "wake_id") if wake_id is not None else uuid.uuid4().hex
        if review_seq is not None and (isinstance(review_seq, bool)
                or not isinstance(review_seq, int) or review_seq < 0):
            raise ValueError("review_seq must be a nonnegative integer")
        with self._transaction() as con:
            current_seq = con.execute("SELECT COALESCE(MAX(seq),0) FROM spend_events").fetchone()[0]
            if review_seq is not None and review_seq > current_seq:
                raise ValueError("review_seq exceeds recorded spending history")
            existing = con.execute("SELECT reason,review_seq FROM wakes WHERE wake_id=?", (wake_id,)).fetchone()
            if existing:
                if existing["reason"] != reason:
                    raise ValueError("Wake ID already has a different reason")
                if review_seq is not None and review_seq != existing["review_seq"]:
                    raise ValueError("Wake ID already has a different review cutoff")
                return {**self._wake(con, wake_id), "reused": True}
            active = con.execute("SELECT wake_id FROM wakes WHERE status='active'").fetchone()
            if active:
                raise WakeConflict(f"Wake {active[0]} is still active; resume it explicitly")
            seq = current_seq if review_seq is None else review_seq
            con.execute("INSERT INTO wakes(wake_id,reason,status,started_at,review_seq) VALUES(?,?,'active',?,?)", (wake_id, reason, now, seq))
            return {**self._wake(con, wake_id), "reused": False}

    @staticmethod
    def _reservation(row):
        actual = row["actual"]
        return {"operation_id": row["operation_id"], "wake_id": row["wake_id"], "reserved_usd": _usd(row["reserved"]), "actual_usd": None if actual is None else _usd(actual), "charged_usd": _usd(row["reserved"] if actual is None else actual), "status": "reserved" if actual is None else "settled", "created_at": row["created_at"], "settled_at": row["settled_at"], "overrun_usd": _usd(max(0, (actual or 0) - row["reserved"]))}

    @staticmethod
    def _daily_charge(con, now):
        cutoff = (datetime.fromisoformat(now) - timedelta(hours=24)).isoformat(timespec="microseconds")
        # Pending requests have unknown outcomes, so they cannot age out. Future
        # recorded charges also remain counted after a wall-clock correction.
        return sum(row[0] for row in con.execute("SELECT COALESCE(actual,reserved) FROM reservations WHERE actual IS NULL OR settled_at>?", (cutoff,)))

    def reserve(self, wake_id, operation_id, max_cost_usd, now=None) -> dict:
        """Reserve every parent/child call against the SAME wake and daily cap.

        A reused reservation is not permission to issue a duplicate request:
        recover its original outcome or leave the unknown cost charged.
        """
        operation_id = _text(operation_id, "operation_id")
        amount, now = _money(max_cost_usd), _stamp(now)
        with self._transaction() as con:
            row = con.execute("SELECT * FROM reservations WHERE operation_id=?", (operation_id,)).fetchone()
            if row:
                if (row["wake_id"], row["reserved"]) != (wake_id, amount):
                    raise ValueError("Operation ID already has a different reservation")
                return {**self._reservation(row), "reused": True}
            wake = self._wake(con, wake_id)
            if wake["status"] != "active":
                raise WakeConflict("Cannot add operations to a finished wake")
            if now < wake["started_at"]:
                raise ValueError("Reservation predates its wake")
            charged = sum(row[0] for row in con.execute("SELECT COALESCE(actual,reserved) FROM reservations WHERE wake_id=?", (wake_id,)))
            if charged + amount > self.wake_limit:
                raise BudgetExceeded("Reservation exceeds the wake budget")
            if self._daily_charge(con, now) + amount > self.daily_limit:
                raise BudgetExceeded("Reservation exceeds the rolling 24-hour budget")
            con.execute("INSERT INTO reservations(operation_id,wake_id,reserved,created_at) VALUES(?,?,?,?)", (operation_id, wake_id, amount, now))
            row = con.execute("SELECT * FROM reservations WHERE operation_id=?", (operation_id,)).fetchone()
            return {**self._reservation(row), "reused": False}

    def settle(self, operation_id, actual_cost_usd, now=None) -> dict:
        """Settle a known cost, including overruns; unknown outcomes stay reserved."""
        actual, now = _money(actual_cost_usd), _stamp(now)
        with self._transaction() as con:
            row = con.execute("SELECT * FROM reservations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise ValueError(f"Unknown operation: {operation_id}")
            if row["actual"] is not None:
                if row["actual"] != actual:
                    raise ValueError("Operation already settled with a different cost")
                return {**self._reservation(row), "reused": True}
            if now < row["created_at"]:
                raise ValueError("Settlement predates its reservation")
            con.execute("UPDATE reservations SET actual=?,settled_at=? WHERE operation_id=?", (actual, now, operation_id))
            row = con.execute("SELECT * FROM reservations WHERE operation_id=?", (operation_id,)).fetchone()
            return {**self._reservation(row), "reused": False}

    def finish_wake(self, wake_id, outcome, reviewed_agent_ids=None, now=None) -> dict:
        """Close a wake without refunding unknown costs.

        Only ``outcome='succeeded'`` acknowledges reviews, and only events at
        or before this wake's saved review cutoff. Late events remain visible.
        An empty/omitted agent list never acknowledges all agents implicitly.
        """
        outcome, now = _text(outcome, "outcome"), _stamp(now)
        if reviewed_agent_ids is not None and not isinstance(reviewed_agent_ids, (list, tuple)):
            raise ValueError("reviewed_agent_ids must be a list")
        ids = sorted({_text(item, "reviewed agent ID") for item in (reviewed_agent_ids or [])})
        acknowledged = ids if outcome == "succeeded" else []
        with self._transaction() as con:
            wake = self._wake(con, wake_id)
            if wake["status"] == "finished":
                if wake["outcome"] != outcome or wake["reviewed_agent_ids"] != acknowledged:
                    raise ValueError("Wake already finished with a different outcome")
                return {**wake, "reused": True}
            if now < wake["started_at"]:
                raise ValueError("Completion predates its wake")
            for agent_id in acknowledged:
                self._agent(con, agent_id)
                con.execute("UPDATE agents SET reviewed_seq=MAX(reviewed_seq,?),last_reviewed_at=? WHERE agent_id=?", (wake["review_seq"], now, agent_id))
            con.execute("UPDATE wakes SET status='finished',outcome=?,finished_at=?,reviewed_agents_json=? WHERE wake_id=?", (outcome, now, _json(acknowledged), wake_id))
            return {**self._wake(con, wake_id), "reused": False}

    def snapshot(self, now=None) -> dict:
        now = _stamp(now)
        with self._transaction(write=False) as con:
            agents = [self._agent(con, row[0]) for row in con.execute("SELECT agent_id FROM agents ORDER BY agent_id")]
            wakes = [self._wake(con, row[0]) for row in con.execute("SELECT wake_id FROM wakes ORDER BY started_at,wake_id")]
            rows = con.execute("SELECT * FROM reservations ORDER BY created_at,operation_id").fetchall()
            active = next((wake for wake in wakes if wake["status"] == "active"), None)
            daily = self._daily_charge(con, now)
            active_charge = sum(row["reserved"] if row["actual"] is None else row["actual"] for row in rows if active and row["wake_id"] == active["wake_id"])
            pending = sum(row["reserved"] for row in rows if row["actual"] is None)
            return {"observed_at": now, "wake_limit_usd": _usd(self.wake_limit), "daily_limit_usd": _usd(self.daily_limit), "daily_charged_usd": _usd(daily), "daily_remaining_usd": _usd(max(0, self.daily_limit - daily)), "active_wake_charged_usd": _usd(active_charge), "active_wake_remaining_usd": _usd(max(0, self.wake_limit - active_charge)), "pending_reserved_usd": _usd(pending), "active_wake": active, "agents": agents, "wakes": wakes, "reservations": [self._reservation(row) for row in rows]}
