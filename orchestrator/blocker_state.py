#!/usr/bin/env python3
"""Small, concurrency-safe runtime ledger for operator-blocking issues."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid


HERE = Path(__file__).resolve().parent
DEFAULT_PATH = Path(
    os.environ.get(
        "ORCHESTRATOR_BLOCKERS_FILE",
        "/workspace/orchestrator_blockers.json"
        if Path("/workspace/hexapod").is_dir()
        else str(HERE / "blockers.runtime.json"),
    )
)


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _load(path: Path) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read blocker ledger {path}: {exc}") from exc
    if not isinstance(value, list):
        raise RuntimeError(f"blocker ledger {path} must contain a JSON list")
    return [item for item in value if isinstance(item, dict)]


def _write(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(entries, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def list_blockers(path: Path = DEFAULT_PATH, include_resolved: bool = False) -> list[dict]:
    entries = _load(path)
    if not include_resolved:
        entries = [item for item in entries if not item.get("resolved_at")]
    return sorted(entries, key=lambda item: item.get("created_at", ""), reverse=True)


def report_blocker(
    source: str,
    summary: str,
    details: str = "",
    path: Path = DEFAULT_PATH,
) -> dict:
    source, summary, details = source.strip(), summary.strip(), details.strip()
    if not source or not summary:
        raise ValueError("source and summary are required")
    if len(source) > 120 or len(summary) > 500 or len(details) > 4000:
        raise ValueError("blocker source/summary/details exceeds its size limit")
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = _load(path)
        for item in reversed(entries):
            if (
                not item.get("resolved_at")
                and item.get("source") == source
                and item.get("summary") == summary
            ):
                return item
        entry = {
            "id": "blk_" + uuid.uuid4().hex[:12],
            "source": source,
            "summary": summary,
            "details": details,
            "created_at": utcnow(),
            "resolved_at": None,
            "resolution": "",
        }
        entries.append(entry)
        _write(path, entries)
        return entry


def resolve_blocker(blocker_id: str, resolution: str = "", path: Path = DEFAULT_PATH) -> dict:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = _load(path)
        for item in entries:
            if item.get("id") != blocker_id:
                continue
            if not item.get("resolved_at"):
                item["resolved_at"] = utcnow()
                item["resolution"] = resolution.strip()[:4000]
                _write(path, entries)
            return item
    raise KeyError(f"unknown blocker id: {blocker_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_PATH)
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report")
    report.add_argument("--source", required=True)
    report.add_argument("--summary", required=True)
    report.add_argument("--details", default="")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("id")
    resolve.add_argument("--resolution", default="")
    listing = commands.add_parser("list")
    listing.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.command == "report":
        value = report_blocker(args.source, args.summary, args.details, args.file)
    elif args.command == "resolve":
        value = resolve_blocker(args.id, args.resolution, args.file)
    else:
        value = list_blockers(args.file, include_resolved=args.all)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
