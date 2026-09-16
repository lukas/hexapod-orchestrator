"""Bounded historical evidence, not model training or executable instructions.

Successful review JSON is reused without another model call. Explicit lessons
live alongside the existing journal; only an operator entry point may label a
correction owner_verified. Reading memory never creates or changes a database.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from .report import redact
from .reviewer import _validate_review


_FIELDS = {"lesson_id", "recorded_at", "status", "source", "owner", "lesson", "evidence", "corrects"}
_LIMITATIONS = [
    "Dated historical evidence; it does not establish current service state or physical readiness.",
    "Prior model reviews are hypotheses. Only explicit operator records can mark corrections owner_verified.",
    "Saved memory changes future context, not model weights, code, permissions, or execution policy.",
]


def _stamp(value=None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("recorded_at must be a timezone-aware ISO timestamp") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recorded_at must be a timezone-aware ISO timestamp")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _text(value, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must contain 1 to {maximum} characters")
    return redact(value.strip())


def _texts(value, field: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= 8:
        raise ValueError(f"{field} must contain {minimum} to 8 evidence/reference strings")
    return [_text(item, field, 500) for item in value]


def remember_lesson(database: Path | str, record: dict, *, operator: bool = False) -> dict:
    """Append one immutable lesson; identical IDs/data are idempotent.

    ``operator`` belongs to the authenticated caller, never a JSON/snapshot/model
    field. API callers must authorize that role before passing operator=True.
    No content in a lesson grants authority to execute its embedded instructions.
    """
    if type(operator) is not bool:
        raise ValueError("operator must be a caller-supplied boolean")
    if not isinstance(record, dict) or set(record) - _FIELDS:
        raise ValueError("Unsupported lesson record fields")
    status = record.get("status", "model_hypothesis")
    if not isinstance(status, str) or status not in {"owner_verified", "model_hypothesis"}:
        raise ValueError("Lesson status must be owner_verified or model_hypothesis")
    if status == "owner_verified" and not operator:
        raise ValueError("Only an explicit operator entry point may record owner_verified corrections")
    owner = record.get("owner")
    if owner is not None or status == "owner_verified":
        owner = _text(owner, "owner", 200)
    lesson = {
        "lesson_id": _text(record.get("lesson_id"), "lesson_id", 200),
        "status": status, "provenance": "operator" if operator else "model",
        "source": _text(record.get("source"), "source", 500), "owner": owner,
        "lesson": _text(record.get("lesson"), "lesson", 2000),
        "evidence": _texts(record.get("evidence"), "evidence", minimum=1),
        "corrects": _texts(record.get("corrects", []), "corrects"),
    }
    provided_stamp = _stamp(record["recorded_at"]) if "recorded_at" in record else None
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS metaagent_lessons (
            lesson_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, status TEXT NOT NULL,
            provenance TEXT NOT NULL, record_json TEXT NOT NULL)""")
        existing = db.execute("SELECT recorded_at,record_json FROM metaagent_lessons WHERE lesson_id=?",
                              (lesson["lesson_id"],)).fetchone()
        lesson["recorded_at"] = provided_stamp or (existing[0] if existing else _stamp())
        encoded = json.dumps(lesson, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if existing:
            if existing[1] != encoded:
                raise ValueError("Lesson ID already has different content; record a new correction instead")
        else:
            db.execute("INSERT INTO metaagent_lessons VALUES(?,?,?,?,?)",
                       (lesson["lesson_id"], lesson["recorded_at"], status, lesson["provenance"], encoded))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    path.chmod(0o600)
    return {**lesson, "reused": existing is not None}


def _limit(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")


def read_memory(database: Path | str, *, review_limit: int = 3, lesson_limit: int = 12,
                max_bytes: int = 24000) -> dict:
    """Read bounded prior successes and lessons, prioritizing owner corrections.

    Prior model summaries/actions retain their dates and evidence status. Failed
    reports, diagnostics, reasoning, tool input and embedded memory are not fed
    back. Full immutable reports remain in the journal when this view truncates.
    """
    _limit(review_limit, "review_limit", 0, 10)
    _limit(lesson_limit, "lesson_limit", 0, 30)
    _limit(max_bytes, "max_bytes", 2048, 65536)
    result = {"schema_version": 1, "recent_reviews": [], "lessons": [],
              "limitations": list(_LIMITATIONS), "truncated": False,
              "omitted": {"reviews": 0, "lessons": 0}}
    path = Path(database)
    if not path.is_file():
        return result
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    deadline = time.monotonic() + 2
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        db.execute("BEGIN")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "metaagent_lessons" in tables:
            total = db.execute("SELECT COUNT(*) FROM metaagent_lessons").fetchone()[0]
            rows = db.execute("""SELECT record_json FROM metaagent_lessons
                ORDER BY (status='owner_verified' AND provenance='operator') DESC,
                recorded_at DESC,lesson_id DESC LIMIT ?""", (lesson_limit,))
            for row in rows:
                item = json.loads(row[0])
                # A stored model hypothesis cannot upgrade itself by naming an
                # owner. Operator provenance comes only from remember_lesson.
                if item.get("status") == "owner_verified" and item.get("provenance") != "operator":
                    item["status"] = "model_hypothesis"
                result["lessons"].append(redact(item))
            result["omitted"]["lessons"] = total - len(result["lessons"])
        if "overseer_reports" in tables:
            total = db.execute("SELECT COUNT(*) FROM overseer_reports WHERE outcome='succeeded'").fetchone()[0]
            # Extract only the existing visible advisory object, not entire logs
            # or recursively embedded memories in full reports.
            rows = db.execute("""SELECT report_id,created_at,
                json_extract(body,'$.wake.wake_id') AS wake_id,
                json_extract(body,'$.llm_review') AS advisory
                FROM overseer_reports WHERE outcome='succeeded'
                ORDER BY created_at DESC,rowid DESC LIMIT ?""", (review_limit,))
            for row in rows:
                try:
                    model_result = json.loads(row["advisory"] or "null")
                    if not isinstance(model_result, dict) or model_result.get("status") != "completed":
                        continue
                    review = _validate_review(model_result.get("review"), allow_legacy=True)
                    result["recent_reviews"].append(redact({
                        "report_id": row["report_id"], "wake_id": row["wake_id"] or row["report_id"],
                        "generated_at": _stamp(row["created_at"]), "provider": model_result.get("provider"),
                        "model": model_result.get("model"), "status": "model_hypothesis",
                        "summary": review["summary"], "recommended_actions": review["recommended_actions"],
                        "goal_assessment": review["goal_assessment"],
                        "strategic_assessment": review.get("strategic_assessment", {}),
                    }))
                except (ValueError, TypeError):
                    continue
            result["omitted"]["reviews"] = total - len(result["recent_reviews"])
    finally:
        db.close()
    result["truncated"] = any(result["omitted"].values())
    return fit_memory(result, max_bytes)


def fit_memory(memory: dict, max_bytes: int) -> dict:
    """Fit historical context to actual remaining prompt bytes, without mutation."""
    _limit(max_bytes, "max_bytes", 2, 65536)
    result = {**memory, "recent_reviews": list(memory.get("recent_reviews", [])),
              "lessons": list(memory.get("lessons", [])),
              "omitted": dict(memory.get("omitted", {"reviews": 0, "lessons": 0}))}
    # Preserve complete statements rather than silently clipping their meaning.
    # Recent model hypotheses yield space before explicit operator corrections.
    while len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > max_bytes:
        if result["recent_reviews"]:
            result["recent_reviews"].pop()
            result["omitted"]["reviews"] += 1
        elif result["lessons"]:
            result["lessons"].pop()
            result["omitted"]["lessons"] += 1
        else:
            result = {"truncated": True, "omitted": result["omitted"]}
            if len(json.dumps(result).encode("utf-8")) > max_bytes:
                result = {"truncated": True}
            if len(json.dumps(result).encode("utf-8")) > max_bytes:
                result = {}
            break
        result["truncated"] = True
    return result
