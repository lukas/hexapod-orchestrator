"""Durable review and action outbox; no operational side effects on import."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


CLOSED = {'resolved', 'declined'}


def _history(db) -> dict:
    """One consistent projection for writable callers and read-only previews."""
    latest = db.execute('SELECT * FROM overseer_reports ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()
    if not latest:
        return {}
    rows = db.execute('SELECT * FROM overseer_outbox ORDER BY rowid').fetchall()
    current = {}
    for row in rows:
        item = json.loads(row['body'])
        base = item.get('base_incident_id', row['incident_id'])
        episode = item.get('episode', 1)
        if isinstance(episode, bool) or not isinstance(episode, int) or episode < 1:
            raise ValueError('invalid persisted incident episode')
        prior = current.get(base)
        if prior is None or episode > prior['episode']:
            current[base] = {'episode': episode, 'incident_id': row['incident_id'],
                             'status': row['status'],
                             'notification_status': row['notification_status']}
    opened = [item for item in current.values() if item['status'] not in CLOSED]
    body = json.loads(latest['body'])
    return {'last_review_at': latest['created_at'], 'last_outcome': latest['outcome'],
            'fingerprint': body.get('wake', {}).get('fingerprint'),
            'reviewed_incidents': sorted(item['incident_id'] for item in opened),
            'notified_incidents': sorted(item['incident_id'] for item in opened
                                        if item['notification_status'] in {'submitted', 'uncertain', 'sending'}),
            'incident_episodes': {base: {key: item[key] for key in ('episode', 'incident_id', 'status')}
                                  for base, item in sorted(current.items())}}


def _queue_recovery(db, row, receipt: dict, now: str) -> None:
    """A recovery is a separate proposal, never an implied message delivery."""
    if row['status'] != 'resolved' or row['notification_status'] != 'submitted':
        return
    original = json.loads(row['body'])
    if original.get('code') == 'incident_recovered':
        return
    recovery_id = hashlib.sha256(f"recovered:{row['incident_id']}".encode()).hexdigest()[:24]
    evidence = receipt['evidence']
    if not isinstance(evidence, list):
        evidence = [evidence]
    item = {'incident_id': recovery_id, 'base_incident_id': recovery_id, 'episode': 1,
            'code': 'incident_recovered', 'subject': original.get('subject', row['incident_id']),
            'severity': 'info', 'detail': 'The execution owner reports this incident resolved with evidence.',
            'proposed_action': 'Notify Lukas once that the previously reported incident recovered.',
            'execution_owner': receipt['owner'], 'evidence': evidence,
            'notify': True, 'executed': False, 'recovered_incident_id': row['incident_id']}
    db.execute('''INSERT OR IGNORE INTO overseer_outbox
        (incident_id,created_at,updated_at,status,body) VALUES (?,?,?,?,?)''',
        (recovery_id, now, now, 'proposed', json.dumps(item, sort_keys=True, allow_nan=False)))


class Journal:
    """Separate review history from agent spend and provider reservations.

    Planned actions never become executed simply because a review succeeded.
    An uncertain message submission is retained, not retried automatically.
    """
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS overseer_reports (
                    report_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    outcome TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS overseer_outbox (
                    incident_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, status TEXT NOT NULL,
                    notification_status TEXT NOT NULL DEFAULT 'not_sent',
                    body TEXT NOT NULL, receipt TEXT);
            ''')
            # Preserve delivery evidence separately when an owner later files
            # an action receipt. Keep the original receipt field for readers.
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(overseer_outbox)')}
            for column in ('notification_receipt', 'action_receipt'):
                if column not in columns:
                    db.execute(f'ALTER TABLE overseer_outbox ADD COLUMN {column} TEXT')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def history(self) -> dict:
        with self.connect() as db:
            db.execute('BEGIN')
            return _history(db)

    def record(self, report_id: str, report: dict, outcome: str) -> None:
        if outcome not in {'succeeded', 'blocked', 'no_change', 'idle'}:
            raise ValueError('invalid review outcome')
        body = json.dumps(report, sort_keys=True, allow_nan=False)
        created = report['generated_at']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT body,outcome FROM overseer_reports WHERE report_id=?', (report_id,)).fetchone()
            if existing:
                if existing['body'] != body or existing['outcome'] != outcome:
                    raise ValueError('report id reused for different content')
                return
            db.execute('INSERT INTO overseer_reports VALUES (?,?,?,?)', (report_id, created, outcome, body))
            for item in report.get('findings', []):
                if item['severity'] == 'info':
                    continue
                db.execute('''INSERT INTO overseer_outbox
                    (incident_id,created_at,updated_at,status,body) VALUES (?,?,?,?,?)
                    ON CONFLICT(incident_id) DO UPDATE SET updated_at=excluded.updated_at,body=excluded.body
                    WHERE overseer_outbox.status NOT IN ('resolved','declined')''',
                    (item['incident_id'], created, created, 'proposed', json.dumps(item, sort_keys=True)))

    def actions(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT * FROM overseer_outbox ORDER BY created_at,incident_id').fetchall()
        return [{**dict(row), 'body': json.loads(row['body'])} for row in rows]

    def begin_notification(self, incident_id: str) -> dict:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM overseer_outbox WHERE incident_id=?', (incident_id,)).fetchone()
            if row is None:
                raise ValueError('unknown incident; previews are not delivery records')
            if row['status'] in CLOSED:
                raise ValueError('incident is closed; do not send an outdated alert')
            if row['notification_status'] != 'not_sent':
                raise ValueError('notification already submitted or outcome uncertain; inspect receipt before retrying')
            body = json.loads(row['body'])
            if not body.get('notify'):
                raise ValueError('this finding does not request a notification')
            db.execute("UPDATE overseer_outbox SET notification_status='sending' WHERE incident_id=?", (incident_id,))
            return body

    def end_notification(self, incident_id: str, *, submitted: bool, receipt: str) -> None:
        if not isinstance(submitted, bool) or not isinstance(receipt, str) or not receipt.strip():
            raise ValueError('notification outcome must be boolean with a nonblank receipt')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('''UPDATE overseer_outbox SET notification_status=?,
                notification_receipt=?,receipt=COALESCE(action_receipt,?)
                WHERE incident_id=? AND notification_status='sending' ''',
                ('submitted' if submitted else 'uncertain', receipt[:1000], receipt[:1000], incident_id)).rowcount
            if changed != 1:
                raise ValueError('no notification is in flight')
            row = db.execute('SELECT * FROM overseer_outbox WHERE incident_id=?', (incident_id,)).fetchone()
            if row['action_receipt']:
                _queue_recovery(db, row, json.loads(row['action_receipt']), datetime.now(timezone.utc).isoformat())

    def acknowledge_action(self, incident_id: str, receipt: dict) -> None:
        if not isinstance(receipt, dict) or not receipt.get('owner') or not receipt.get('evidence'):
            raise ValueError('owner and evidence are required; an exit code alone is not a result')
        outcome = receipt.get('outcome')
        if outcome not in {'resolved', 'needs_attention', 'declined'}:
            raise ValueError('invalid owner receipt outcome')
        encoded = json.dumps(receipt, sort_keys=True, allow_nan=False)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM overseer_outbox WHERE incident_id=?', (incident_id,)).fetchone()
            if row is None:
                raise ValueError('unknown action')
            if row['status'] in CLOSED:
                if row['status'] != outcome or (row['action_receipt'] or row['receipt']) != encoded:
                    raise ValueError('closed incident already has a different owner receipt')
                return
            db.execute('UPDATE overseer_outbox SET status=?,receipt=?,action_receipt=?,updated_at=? WHERE incident_id=?',
                       (outcome, encoded, encoded, now, incident_id))
            row = db.execute('SELECT * FROM overseer_outbox WHERE incident_id=?', (incident_id,)).fetchone()
            _queue_recovery(db, row, receipt, now)


def read_history(path: Path | str) -> dict:
    """Preview reader: do not create databases or change their contents."""
    path = Path(path)
    if not path.exists():
        return {}
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='overseer_reports'").fetchone():
            return {}
        return _history(db)
    finally:
        db.close()
