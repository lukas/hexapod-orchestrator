"""An opt-in, deterministic timer gate. Idle checks never invoke a model.

The operating system invokes ``tick``; this is not a resident agent. Only the
existing reviewer may spend, using the original durable wake ledger. Scheduling
does not execute recommendations or control any worker, trainer or robot.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .policy import REVIEW_SECONDS, evaluate, timestamp
from .report import redact

CHECK_SECONDS = 300


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect(database):
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database, timeout=5)
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE IF NOT EXISTS metaagent_schedule (
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metaagent_checks (
          check_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
          outcome TEXT NOT NULL, detail TEXT, wake_id TEXT,
          paid_review_started INTEGER NOT NULL DEFAULT 0);
    ''')
    return db


def _configuration(db):
    row = db.execute('SELECT body FROM metaagent_schedule WHERE singleton=1').fetchone()
    return json.loads(row['body']) if row else {'enabled': False}


def _save(db, config):
    db.execute('INSERT INTO metaagent_schedule VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET body=excluded.body',
               (json.dumps(config),))


def configure(database, *, enabled, provider='claude', project_root=None, reviewer_config=None):
    """Explicit operator action; enabling also clears a failed-review hold."""
    if provider not in {'claude', 'codex'}:
        raise ValueError('provider must be claude or codex')
    if enabled and not project_root:
        raise ValueError('enabling requires a project root')
    with closing(_connect(database)) as db, db:
        config = _configuration(db)
        config.update(enabled=bool(enabled), configured_at=_now(), generation=uuid.uuid4().hex)
        if enabled:
            config.update(provider=provider, project_root=str(Path(project_root).resolve()),
                reviewer_config=str(Path(reviewer_config).resolve()) if reviewer_config else None,
                review_hold=None)
        _save(db, config)
    return scheduler_status(database)


def scheduler_status(database):
    """Read-only status; desired enablement is not proof an OS timer is loaded."""
    result = dict(enabled=False, mode='deterministic_gate', provider=None,
        check_interval_seconds=CHECK_SECONDS, review_interval_seconds=REVIEW_SECONDS,
        configured_at=None, last_check_at=None, next_check_at=None, last_outcome=None,
        last_detail=None, last_wake_id=None, active_check=False,
        active_check_started_at=None, checks_total=0, free_checks=0,
        paid_reviews_started=0, review_hold=None, recent_checks=[],
        limitations=['Enabled is the saved setting. Fresh checks establish runner health; an offline or sleeping host cannot check.',
                     'Missing source coverage remains unknown; a free idle check is not proof all agents are idle.'])
    database = Path(database)
    if not database.exists():
        return result
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='metaagent_schedule'").fetchone():
            return result
        config = _configuration(db)
        result.update({key: config.get(key) for key in ('provider', 'configured_at', 'review_hold')})
        result['enabled'] = bool(config.get('enabled'))
        count = db.execute('SELECT COUNT(*),COALESCE(SUM(paid_review_started),0) FROM metaagent_checks').fetchone()
        result.update(checks_total=count[0], paid_reviews_started=count[1], free_checks=count[0]-count[1])
        checks = [dict(row) for row in db.execute('SELECT * FROM metaagent_checks ORDER BY started_at DESC LIMIT 12')]
        for check in checks:
            check['paid_review_started'] = bool(check['paid_review_started'])
        result['recent_checks'] = checks
        if checks:
            last = checks[0]
            result.update(last_check_at=last['started_at'], last_outcome=last['outcome'],
                last_detail=last['detail'], last_wake_id=last['wake_id'],
                active_check=last['finished_at'] is None,
                active_check_started_at=last['started_at'] if last['finished_at'] is None else None)
        if result['enabled']:
            base = result['last_check_at'] or result['configured_at']
            result['next_check_at'] = (timestamp(base)+timedelta(seconds=CHECK_SECONDS)).isoformat()
    return redact(result)


def tick(database, *, collector=None, reviewer=None):
    """One bounded check, at most one paid call, no force/resume/retry path."""
    from .__main__ import collect, read_budget, read_json, run_review
    from .journal import read_history
    database = Path(database)
    if not scheduler_status(database)['enabled']:
        return {'outcome': 'disabled', 'paid_review_started': False}
    # OS releases this on process death; a timestamp lease could overlap a slow
    # provider. The budget store independently enforces exactly one active wake.
    with (database.parent/'metaagent-scheduler.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'outcome': 'already_running', 'paid_review_started': False}
        with closing(_connect(database)) as db, db:
            config = _configuration(db)
            if not config.get('enabled'):
                return {'outcome': 'disabled', 'paid_review_started': False}
            # Incomplete free checks from a crashed runner are visible. An
            # incomplete paid attempt also leaves its wake/reservation intact.
            if db.execute('SELECT 1 FROM metaagent_checks WHERE finished_at IS NULL AND paid_review_started=1').fetchone():
                config['review_hold'] = 'Previous scheduled paid attempt was interrupted. Inspect the wake and billing before explicitly enabling again.'
                _save(db, config)
            db.execute("UPDATE metaagent_checks SET finished_at=?,outcome='interrupted',detail='Previous process ended before recording completion; no automatic paid retry.' WHERE finished_at IS NULL", (_now(),))
            check_id = uuid.uuid4().hex
            db.execute('INSERT INTO metaagent_checks(check_id,started_at,outcome) VALUES(?,?,?)', (check_id,_now(),'checking'))
        paid = False
        wake_id = None

        def finish(outcome, detail, *, hold=False, fingerprint=None):
            with closing(_connect(database)) as db, db:
                current = _configuration(db)
                if hold:
                    current['review_hold'] = detail
                if fingerprint is not None:
                    current['last_paid_fingerprint'] = fingerprint
                    current['last_paid_at'] = _now()
                _save(db, current)
                db.execute('UPDATE metaagent_checks SET finished_at=?,outcome=?,detail=?,wake_id=?,paid_review_started=? WHERE check_id=?',
                    (_now(),outcome,str(redact(detail))[:2000],wake_id,int(paid),check_id))
            return dict(outcome=outcome, detail=detail, wake_id=wake_id, paid_review_started=paid)

        try:
            if config.get('review_hold'):
                return finish('held', config['review_hold'])
            if read_budget(database)['active_wake']:
                return finish('active_wake', 'An existing wake owns the ledger; no new review or automatic resumption.')
            last_paid = config.get('last_paid_at')
            if last_paid and (timestamp()-timestamp(last_paid)).total_seconds() < REVIEW_SECONDS:
                return finish('cooldown', 'Six-hour review interval has not elapsed; no model call.')
            # Constant paths bound disk use across indefinitely repeated gates.
            work = database.parent/'scheduled-current'
            work.mkdir(exist_ok=True)
            if collector is None:
                from .unattended_sources import collect_unattended
                collector = collect_unattended
            sources = collector(Path(config['project_root']), work/'sources', timeout_seconds=30)
            args = argparse.Namespace(command='review', project_root=config['project_root'],
                snapshot=None, cloud_activity=sources.get('cloud_activity'),
                codex_threads=sources.get('codex_threads'), self_agent=[],
                output=str(work/'report'), force=False, resume_wake=None,
                provider=config['provider'], reviewer_config=config.get('reviewer_config'))
            snapshot = collect(args, database)
            snapshot['errors'].extend(sources.get('errors', []))
            plan = evaluate(snapshot, history=read_history(database))
            # A new loop/auth threshold or first six-hour no-progress finding
            # can be meaningful even when the task's checkpoint is unchanged.
            findings = sorted(item['incident_id'] for item in plan['findings']
                              if item['severity'] in {'warning', 'review'})
            fingerprint = hashlib.sha256(json.dumps([plan['wake']['fingerprint'], findings]).encode()).hexdigest()
            coverage = len(snapshot['errors'])
            if not plan['wake']['eligible']:
                return finish('idle', f'No eligible observed work, new spending or incident. Source limitations: {coverage}. No model call.')
            if fingerprint == config.get('last_paid_fingerprint'):
                return finish('unchanged', f'No changed work evidence since the last scheduled review. Source limitations: {coverage}. No model call.')
            # Do not turn missing credentials into a new paid wake every timer.
            key_name = 'ANTHROPIC_API_KEY' if config['provider'] == 'claude' else 'OPENAI_API_KEY'
            if not os.environ.get(key_name, '').strip():
                return finish('credentials_missing', f'{config["provider"]} credential unavailable to timer. Restore the documented credential source, then explicitly enable to clear this hold.', hold=True)
            from .reviewer import ReviewConfig
            from decimal import Decimal
            profile = config.get('reviewer_config') or database.parent/'reviewers'/f'{config["provider"]}.json'
            settings = ReviewConfig(**read_json(profile))
            if settings.provider != config['provider']:
                return finish('configuration_error', 'Provider and verified pricing profile disagree; correct the configuration and enable again.', hold=True)
            budget = read_budget(database)
            if settings.reservation_usd > min(Decimal(budget['wake_limit_usd']), Decimal(budget['daily_remaining_usd']), Decimal('15')):
                return finish('budget_wait', 'The configured maximum reservation does not fit the remaining shared budget. No model call; uncertain charges remain reserved.')
            # Keep a single immutable observation for admission and the review.
            snapshot_path = work/'snapshot.json'
            snapshot_path.write_text(json.dumps(redact(snapshot)))
            args.snapshot = str(snapshot_path)
            args.cloud_activity = args.codex_threads = None
            # Persist the attempt before dispatch. Crash recovery may never
            # silently reopen/retry a possibly billed attempt. Configuration is
            # fenced in the same transaction: never dispatch a replaced profile.
            rejected = None
            with closing(_connect(database)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                current = _configuration(db)
                if not current.get('enabled'):
                    rejected = ('disabled', 'Scheduling was disabled while collecting; no model call.')
                elif current.get('generation') != config.get('generation'):
                    rejected = ('configuration_changed', 'Scheduling configuration changed while collecting; the next free check will use it. No model call.')
                else:
                    db.execute('UPDATE metaagent_checks SET paid_review_started=1 WHERE check_id=?', (check_id,))
            if rejected:
                return finish(*rejected)
            paid = True
            result = (reviewer or run_review)(args, database)
            wake_id = result.get('wake_id')
            outcome = result.get('outcome', 'blocked')
            if outcome == 'idle':
                paid = False
            return finish(outcome, f'Scheduled review {outcome}. Source limitations: {coverage}. Recommendations are advisory.',
                hold=outcome == 'blocked', fingerprint=fingerprint if paid else None)
        except Exception as exc:
            # Exception messages can contain provider/request secrets. Log only
            # the class; existing review artifacts retain sanitized diagnostics.
            return finish('error', f'{type(exc).__name__} during scheduled check. No automatic paid retry; inspect saved review and runner logs.', hold=paid)


def main(argv=None):
    from .__main__ import ROOT, default_state_dir
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir', default=str(default_state_dir()))
    commands = p.add_subparsers(dest='command', required=True)
    config = commands.add_parser('configure')
    group = config.add_mutually_exclusive_group(required=True)
    group.add_argument('--enable', action='store_true')
    group.add_argument('--disable', action='store_true')
    config.add_argument('--provider', choices=('claude','codex'), default='claude')
    config.add_argument('--project-root', default=str(ROOT))
    config.add_argument('--reviewer-config')
    commands.add_parser('tick')
    commands.add_parser('status')
    args = p.parse_args(argv)
    database = Path(args.state_dir).expanduser()/'overseer.sqlite3'
    if args.command == 'configure':
        result = configure(database, enabled=args.enable, provider=args.provider,
            project_root=args.project_root, reviewer_config=args.reviewer_config)
    elif args.command == 'tick':
        result = tick(database)
    else:
        result = scheduler_status(database)
    print(json.dumps(redact(result), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
