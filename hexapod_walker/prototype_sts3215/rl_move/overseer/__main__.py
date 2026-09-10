"""Manual metaagent reviews. Serving its history never schedules a review."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

from .collectors import collect_local, normalize_cloud_activity, normalize_codex_threads
from .journal import Journal, read_history
from .memory import fit_memory, read_memory, remember_lesson
from .policy import age_seconds, evaluate, status, timestamp
from .report import redact, write_report
from .store import Store

ROOT = Path(__file__).resolve().parents[4]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state_dir() -> Path:
    if os.environ.get('HEXAPOD_METAAGENT_DIR'):
        return Path(os.environ['HEXAPOD_METAAGENT_DIR']).expanduser()
    if os.environ.get('HEXAPOD_OVERSEER_DIR'):
        return Path(os.environ['HEXAPOD_OVERSEER_DIR']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Hexapod Lab/overseer'
    return Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state')) / 'hexapod-overseer'


def scheduling_status(database: Path) -> dict:
    """Optional scheduler integration; reading status never initializes it."""
    try:
        from .scheduler import scheduler_status
    except ModuleNotFoundError as exc:
        if exc.name != __package__ + '.scheduler':
            raise
        return {'enabled': False, 'configured': False}
    return scheduler_status(database)


def read_json(path: str | Path, limit: int = 2_000_000):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('input exceeds the bounded JSON read limit')
    return json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def read_registry(path: Path) -> list[dict]:
    """Read-only inventory with unacknowledged receipts; preview creates nothing."""
    if not path.exists():
        return []
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='agents'").fetchone():
            return []
        result = []
        cutoff = db.execute('SELECT COALESCE(MAX(seq),0) FROM spend_events').fetchone()[0]
        for row in db.execute('SELECT * FROM agents'):
            item = json.loads(row['record_json'])
            item.pop('unreviewed_cost_usd', None)
            cost = db.execute('SELECT COUNT(*),COALESCE(SUM(amount),0) FROM spend_events WHERE agent_id=? AND seq>?',
                              (row['agent_id'], row['reviewed_seq'])).fetchone()
            if cost[0]:
                item['unreviewed_cost_usd'] = str(Decimal(cost[1])/1_000_000)
            item['unreviewed_through_seq'] = cutoff
            item['last_reviewed_at'] = row['last_reviewed_at']
            result.append(item)
        return result
    finally:
        db.close()


def read_budget(path: Path) -> dict:
    """A status/preview must not initialize or mutate the budget database."""
    empty = {'wake_limit_usd':'20.00','daily_limit_usd':'80.00',
             'daily_charged_usd':'0.00','daily_remaining_usd':'80.00',
             'pending_reserved_usd':'0.00','active_wake':None}
    if not path.exists():
        return empty
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    db.row_factory = sqlite3.Row
    usd = lambda amount: format(Decimal(amount)/1_000_000, '.6f')
    try:
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='limits'").fetchone():
            return empty
        limits = db.execute('SELECT wake,daily FROM limits WHERE singleton=1').fetchone()
        cutoff = (datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(timespec='microseconds')
        daily = db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM reservations WHERE actual IS NULL OR settled_at>?',(cutoff,)).fetchone()[0]
        pending = db.execute('SELECT COALESCE(SUM(reserved),0) FROM reservations WHERE actual IS NULL').fetchone()[0]
        active = db.execute("SELECT wake_id,started_at,review_seq FROM wakes WHERE status='active'").fetchone()
        return {'wake_limit_usd':usd(limits['wake']),'daily_limit_usd':usd(limits['daily']),
                'daily_charged_usd':usd(daily),'daily_remaining_usd':usd(max(0,limits['daily']-daily)),
                'pending_reserved_usd':usd(pending),'active_wake':dict(active) if active else None}
    finally:
        db.close()


def merge_registry(observations: list[dict], registered: list[dict]) -> list[dict]:
    merged = {item['agent_id']: dict(item) for item in registered}
    identity = {'task_id', 'parent_id', 'goals', 'scope', 'execution_owner', 'resources',
                'assessment', 'progress_evidence', 'last_progress_at', 'started_at',
                'is_overseer', 'overseer_wake_id', 'registration'}
    for observed in observations:
        aid = observed['agent_id']
        saved = merged.get(aid, {})
        item = {**saved, **observed}
        # Discovery updates liveness; it cannot erase registered purpose/ownership.
        item.update({key: saved[key] for key in identity if key in saved})
        if 'unreviewed_cost_usd' in saved:
            item['unreviewed_cost_usd'] = saved['unreviewed_cost_usd']
        if 'unreviewed_through_seq' in saved:
            item['unreviewed_through_seq'] = saved['unreviewed_through_seq']
        item.setdefault('registration', 'discovered')
        merged[aid] = item
    return sorted(merged.values(), key=lambda item: item['agent_id'])


def supplement(path: str, kind: str, root: Path) -> dict:
    envelope = read_json(path)
    if not isinstance(envelope, dict) or not envelope.get('collected_at') or 'data' not in envelope:
        raise ValueError('source exports need {collected_at: ISO timestamp, data: tool result}; timestamps must reflect actual collection')
    if isinstance(envelope['data'], dict) and envelope['data'].get('isError'):
        return {'agents': [], 'services': [], 'errors': [{'source': kind, 'code': 'export_failed', 'message': 'Authenticated source export returned an error; coverage is unavailable.'}]}
    if kind == 'cloud':
        return normalize_cloud_activity(envelope['data'], now=envelope['collected_at'])
    return {'agents': normalize_codex_threads(envelope['data'], root, now=envelope['collected_at'])}


def collect(args, database: Path) -> dict:
    root = Path(args.project_root).resolve()
    snapshot = read_json(args.snapshot) if args.snapshot else collect_local(root)
    if not isinstance(snapshot, dict):
        raise ValueError('snapshot must be an object')
    for key in ('agents', 'services', 'automations', 'errors'):
        snapshot.setdefault(key, [])
    for attr, kind in [('cloud_activity', 'cloud'), ('codex_threads', 'codex')]:
        path = getattr(args, attr)
        if path:
            addition = supplement(path, kind, root)
            for key in ('agents', 'services', 'errors'):
                snapshot[key].extend(addition.get(key, []))
        elif not args.snapshot:
            snapshot['errors'].append({'source': kind, 'code': 'not_supplied',
                                      'message': 'Fresh authenticated source export was not supplied; coverage is incomplete.'})
    for item in snapshot['agents']:
        item.pop('unreviewed_through_seq', None)
    snapshot['agents'] = merge_registry(snapshot['agents'], read_registry(database))
    for aid in args.self_agent:
        for agent in snapshot['agents']:
            if agent['agent_id'] == aid:
                agent['is_overseer'] = True
    # Include dated documentation as evidence, never automatically declare a goal done.
    documents = []
    for name in ('RL_GOALS.md', 'STATUS.md', 'CURRENT_TRUTHS.md'):
        source = root/'hexapod_walker/prototype_sts3215'/name
        if source.is_file():
            with source.open('r', encoding='utf-8') as stream:
                excerpt = stream.read(16000)
            documents.append({'path': str(source), 'excerpt': excerpt,
                              'basis': 'repository document, not a fresh robot observation'})
    snapshot['goal_documents'] = documents
    return redact(snapshot)


def model_observation(agent: dict, reviewed_at: str) -> dict:
    """Project saved observations as historical when current liveness is unknown."""
    observed_at = agent.get('observed_at')
    age = age_seconds(observed_at, timestamp(reviewed_at)) if isinstance(observed_at, str) else None
    reported = status(agent)
    fresh = age is not None and age <= 15 * 60
    if fresh:
        result = dict(agent)
        basis = 'Observed within 15 minutes of this review; relative evidence ages are anchored to observed_at.'
    else:
        # Old free-text evidence/assessments can say "active" or "27 seconds
        # ago" without a timestamp. Keep them in the archival report, not in
        # the model's current-state input. Durable cost receipts still matter.
        historical_fields = {
            'agent_id', 'name', 'provider', 'task_id', 'parent_id', 'scope', 'goals',
            'execution_owner', 'registration', 'observed_at', 'started_at',
            'last_progress_at', 'last_heartbeat_at', 'last_reviewed_at',
            'cost_status', 'cost_usd', 'cumulative_cost_usd', 'unreviewed_cost_usd',
            'unreviewed_through_seq', 'source',
        }
        result = {key: value for key, value in agent.items() if key in historical_fields}
        basis = ('Historical observation older than 15 minutes; current status is unknown. '
                 'Stale liveness evidence is omitted.' if age is not None else
                 'Missing, invalid, or future observation timestamp; current status is unknown. '
                 'Undated liveness evidence is omitted.')
    result.update(status=reported if fresh else 'unknown', last_reported_status=reported,
                  observation_age_seconds=None if age is None else round(age, 3),
                  observation_basis=basis, observation_fresh=fresh)
    return result


def compact_for_review(report: dict, snapshot: dict) -> dict:
    """Reserve the prompt for current work; terminal job history remains in JSON."""
    due = set(report['wake']['spend_due_agents'])
    excluded = {a['agent_id'] for a in report['agents'] if a.get('is_overseer') or a.get('overseer_wake_id')}
    while True:
        descendants = {a['agent_id'] for a in report['agents'] if a.get('parent_id') in excluded}
        if descendants <= excluded:
            break
        excluded.update(descendants)
    agents = [a for a in report['agents'] if a['agent_id'] not in excluded]
    current = [a for a in agents if a['agent_id'] in due]
    current += [a for a in agents if a['agent_id'] not in due and a.get('status') not in {'succeeded','completed','failed','dead','unknown'}]
    projected = [model_observation(agent, report['generated_at']) for agent in current[:60]]
    stale = {a['agent_id']: a for a in projected if not a['observation_fresh']}
    findings = []
    for item in report['findings']:
        if item.get('code') == 'stale_observation':
            observation = stale.get(item.get('subject'), {})
            observed_at = observation.get('observed_at') or 'unknown'
            observation_age = observation.get('observation_age_seconds')
            item = {**item, 'evidence': [
                f"Last observation: {observed_at}; "
                f"age at review: {observation_age if observation_age is not None else 'unknown'} seconds. "
                'Current status is unknown; refresh the source before claiming live activity.'
            ]}
        findings.append(item)
    return {'generated_at': report['generated_at'], 'wake': report['wake'],
            'agents': projected, 'findings': findings,
            'source_errors': report['source_errors'], 'notes': report['notes'],
            'goal_documents': snapshot.get('goal_documents', []),
            'memory': snapshot.get('memory', {}),
            'metaagent_budget': report.get('budget', {}).get('ledger', {}),
            'historical_states': dict(Counter(a.get('status','unknown') for a in agents)),
            'historical_states_basis': 'Last reported statuses across retained records, not current activity. '
                                       'Use observation_fresh and wake.active_agent_count for current activity.'}


def prior_attempts(database: Path, wake_id: str) -> list[dict]:
    """Read immutable earlier reports; continuation never replaces their rows."""
    if not database.exists():
        raise ValueError('Cannot resume a wake from a missing budget database')
    db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='overseer_reports'").fetchone():
            return []
        prefix = wake_id + ':review:'
        rows = db.execute('''SELECT report_id,created_at,outcome,body FROM overseer_reports
            WHERE report_id=? OR substr(report_id,1,?)=? ORDER BY created_at,rowid''',
            (wake_id, len(prefix), prefix))
        result = []
        for row in rows:
            body = json.loads(row['body'])
            if body.get('wake', {}).get('wake_id') != wake_id:
                raise ValueError('Prior report has a conflicting wake identity')
            result.append({'report_id': row['report_id'], 'generated_at': row['created_at'],
                           'outcome': row['outcome'], 'llm_review': body.get('llm_review')})
        return redact(result)
    finally:
        db.close()


def fit_review_memory(model_snapshot: dict, config) -> dict:
    """Do not let retained history overflow an otherwise valid current prompt."""
    from .reviewer import REVIEW_SYSTEM_PROMPT
    bounded = {**model_snapshot, 'memory': {}}
    base_bytes = len(json.dumps(bounded, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf-8'))
    available = config.max_prompt_bytes - len(REVIEW_SYSTEM_PROMPT.encode('utf-8')) - base_bytes + 2
    bounded['memory'] = fit_memory(model_snapshot.get('memory', {}), max(2, min(65536, available)))
    return bounded


def run_review(args, database: Path) -> dict:
    provider = getattr(args, 'provider', None)
    resume_id = getattr(args, 'resume_wake', None)
    if provider:
        if not args.reviewer_config:
            args.reviewer_config = str(database.parent/'reviewers'/f'{provider}.json')
        configured = read_json(args.reviewer_config)
        if configured.get('provider', 'claude') != provider:
            raise ValueError('Selected provider differs from reviewer configuration')
    if resume_id and not args.reviewer_config:
        raise ValueError('--resume-wake requires an explicit paid reviewer configuration')
    snapshot = collect(args, database)
    # Never accept authority/status claims from an imported snapshot's memory.
    snapshot['memory'] = read_memory(database)
    history = read_history(database)
    if resume_id:
        # An explicit continuation must still include unreviewed cost-bearing
        # terminal agents; automatic unchanged-blocker suppression does not apply.
        history = {key: value for key, value in history.items() if key != 'last_outcome'}
    report = evaluate(snapshot, history=history, force=args.force or bool(resume_id))
    report['mode'] = args.command
    report['memory'] = snapshot['memory']
    report['scheduler'] = scheduling_status(database)
    report['scheduler_enabled'] = report['scheduler']['enabled']
    report['budget']['ledger'] = read_budget(database)
    report['goal_document_sources'] = [d['path'] for d in snapshot.get('goal_documents', [])]
    output = Path(args.output) if args.output else Path(args.project_root)/'artifacts/metaagent'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if args.command == 'preview':
        return {'mode': 'preview', 'paths': write_report(report, output),
                'wake': report['wake'], 'additional_model_cost_usd': '0.00'}
    # No eligibility means no database mutation and, importantly, no paid call.
    if not report['wake']['eligible']:
        return {'mode': 'review', 'outcome': 'idle', 'paths': write_report(report, output)}
    config = None
    if args.reviewer_config:
        from .reviewer import ReviewConfig, review_once
        config = ReviewConfig(**read_json(args.reviewer_config))
    if resume_id and not database.exists():
        raise ValueError('Cannot resume a wake from a missing budget database')
    store = Store(database)
    cutoff = max((a.get('unreviewed_through_seq',0) for a in snapshot['agents']), default=0)
    if resume_id:
        operation_id = resume_id + ':review:' + uuid.uuid4().hex
        wake = store.resume_wake(resume_id, operation_id)
        report_id = operation_id
    else:
        wake = store.start_wake('; '.join(report['wake']['reasons']), review_seq=cutoff)
        operation_id = wake['wake_id'] + ':review'
        report_id = wake['wake_id']
    report['report_id'] = report_id
    report['wake'].update(wake_id=wake['wake_id'], started_at=wake['started_at'],
                          reason=wake['reason'], review_seq=wake['review_seq'])
    if resume_id:
        report['wake'].update(resumed_at=wake['resumed_at'], previous_finished_at=wake['previous_finished_at'])
    outcome = 'no_change'
    reviewed = []
    try:
        if resume_id:
            # Claim first: another completed continuation must not slip between
            # reading prior reports and acquiring this wake's exclusive owner.
            report['prior_attempts'] = prior_attempts(database, resume_id)
        for item in snapshot['agents']:
            item = dict(item)
            item.pop('last_reviewed_at', None)
            item.pop('unreviewed_cost_usd', None)  # receipts, not observations, own spend
            item.pop('unreviewed_through_seq', None)
            store.register_agent(item)
        if config is not None:
            before = store.snapshot()
            if Decimal(before['active_wake_charged_usd']) >= 15:
                raise ValueError('wrap-up threshold reached; no more review calls')
            report['budget']['ledger'] = {key: value for key, value in before.items()
                                          if key not in {'agents', 'wakes', 'reservations'}}
            model_snapshot = fit_review_memory(compact_for_review(report, snapshot), config)
            report['memory_context'] = {
                'recent_review_ids': [item['report_id'] for item in model_snapshot['memory'].get('recent_reviews', [])],
                'lesson_ids': [item['lesson_id'] for item in model_snapshot['memory'].get('lessons', [])],
                'truncated': model_snapshot['memory'].get('truncated', bool(snapshot['memory'])),
            }
            result = review_once(store, wake['wake_id'], operation_id, model_snapshot, config)
            report['llm_review'] = result
            if result.get('status') == 'completed':
                outcome = 'succeeded'
                included = {a['agent_id'] for a in model_snapshot['agents']}
                # Never clear a task whose cost-bearing members were omitted.
                complete_tasks = {a.get('task_id') or a['agent_id'] for a in model_snapshot['agents']}
                complete_tasks -= {a.get('task_id') or a['agent_id'] for a in report['agents']
                                   if a['agent_id'] in report['wake']['spend_due_agents'] and a['agent_id'] not in included}
                reviewed = [a['agent_id'] for a in model_snapshot['agents']
                            if a['agent_id'] in report['wake']['spend_due_agents']
                            and (a.get('task_id') or a['agent_id']) in complete_tasks]
            else:
                outcome = 'blocked'
        else:
            report['notes'].append('Deterministic review only. Spend receipts are not acknowledged until a completed model review or an explicit human review receipt.')
        totals = store.snapshot()
        attempt = next((row for row in totals['reservations'] if row['operation_id'] == operation_id), None)
        report['budget']['additional_model_cost_usd'] = attempt['charged_usd'] if attempt else '0.000000'
        report['budget']['wake_charged_usd'] = totals['active_wake_charged_usd']
        report['budget']['ledger'] = {k:v for k,v in totals.items() if k not in {'agents','wakes','reservations'}}
        Journal(database).record(report_id, report, outcome)
        store.finish_wake(wake['wake_id'], outcome, reviewed_agent_ids=reviewed)
    except Exception:
        # Keep uncertain reservations charged; finishing cannot erase them.
        store.finish_wake(wake['wake_id'], 'blocked')
        raise
    return {'mode': 'review', 'outcome': outcome, 'wake_id': wake['wake_id'],
            'paths': write_report(report, output)}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir', default=str(default_state_dir()))
    sub = p.add_subparsers(dest='command', required=True)
    for command in ('preview', 'review'):
        item = sub.add_parser(command)
        item.add_argument('--project-root', default=str(ROOT))
        item.add_argument('--snapshot')
        item.add_argument('--cloud-activity')
        item.add_argument('--codex-threads')
        item.add_argument('--self-agent', action='append', default=[])
        item.add_argument('--output')
        item.add_argument('--force', action='store_true', help='request one manual review even without an automatic trigger')
        if command == 'review':
            item.add_argument('--reviewer-config', help='explicit verified model/pricing JSON; enables one paid call')
            item.add_argument('--provider', choices=('claude', 'codex'), help='select state-dir/reviewers/PROVIDER.json, or validate an explicit config')
            item.add_argument('--resume-wake', metavar='ID', help='explicitly continue one finished blocked wake using its remaining budget; makes at most one new call')
    sub.add_parser('status')
    sub.add_parser('memory', help='read bounded historical reviews and explicit corrections without changing state')
    item = sub.add_parser('remember-lesson')
    item.add_argument('record', help='explicit operator lesson JSON with source, evidence and status')
    sub.add_parser('actions')
    item = sub.add_parser('register')
    item.add_argument('record', help='JSON file with stable agent_id, task_id, execution_owner, goals and scope')
    item = sub.add_parser('heartbeat')
    item.add_argument('agent_id')
    item.add_argument('record', help='JSON status/checkpoint update; heartbeat alone is not progress')
    item = sub.add_parser('spend')
    item.add_argument('agent_id')
    item.add_argument('event_id')
    item.add_argument('amount_usd')
    item.add_argument('--occurred-at', required=True)
    item.add_argument('--source', required=True)
    item = sub.add_parser('acknowledge')
    item.add_argument('incident_id')
    item.add_argument('receipt', help='owner, outcome and evidence JSON for the actual execution result')
    item = sub.add_parser('acknowledge-review')
    item.add_argument('receipt', help='human review JSON: owner, evidence and reviewed_agent_ids')
    item = sub.add_parser('finish-wake')
    item.add_argument('wake_id')
    item.add_argument('--outcome', choices=('blocked', 'no_change'), required=True)
    item = sub.add_parser('reconcile-cost')
    item.add_argument('operation_id')
    item.add_argument('amount_usd')
    item = sub.add_parser('notify')
    item.add_argument('incident_id')
    item.add_argument('--recipient', required=True)
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    database = Path(args.state_dir).expanduser()/'overseer.sqlite3'
    try:
        if args.command in {'preview','review'}:
            result = run_review(args, database)
        elif args.command == 'status':
            scheduler = scheduling_status(database)
            result = {'service': 'hexapod-metaagent', 'scheduler_enabled': scheduler['enabled'], 'scheduler': scheduler, 'budget':read_budget(database),
                      'agents': read_registry(database), 'history': read_history(database)}
        elif args.command == 'memory':
            result = read_memory(database)
        elif args.command == 'remember-lesson':
            result = remember_lesson(database, read_json(args.record), operator=True)
        else:
            store = Store(database)
            if args.command == 'register':
                record = read_json(args.record)
                for field in ('agent_id','task_id','execution_owner','goals','scope'):
                    if not record.get(field):
                        raise ValueError(f'registration requires {field}')
                record['registration'] = 'registered'
                result = store.register_agent(redact(record))
            elif args.command == 'heartbeat':
                record = redact(read_json(args.record))
                record.setdefault('observed_at', now())
                result = store.heartbeat(args.agent_id, record)
            elif args.command == 'spend':
                result = store.record_spend(args.agent_id,args.event_id,args.amount_usd,args.occurred_at,args.source)
            elif args.command == 'actions':
                result = Journal(database).actions()
            elif args.command == 'acknowledge':
                Journal(database).acknowledge_action(args.incident_id, redact(read_json(args.receipt)))
                result = {'acknowledged': args.incident_id}
            elif args.command == 'acknowledge-review':
                receipt = redact(read_json(args.receipt))
                if not receipt.get('owner') or not receipt.get('evidence') or not receipt.get('reviewed_agent_ids') or 'review_seq' not in receipt:
                    raise ValueError('owner, evidence, reviewed_agent_ids and the reviewed snapshot review_seq are required')
                wake = store.start_wake('Human review receipt: ' + json.dumps(receipt, sort_keys=True), review_seq=receipt['review_seq'])
                result = store.finish_wake(wake['wake_id'], 'succeeded', reviewed_agent_ids=receipt['reviewed_agent_ids'])
            elif args.command == 'finish-wake':
                result = store.finish_wake(args.wake_id, args.outcome)
            elif args.command == 'reconcile-cost':
                result = store.settle(args.operation_id, args.amount_usd)
            elif args.command == 'notify':
                from .notifications import send_notification
                result = send_notification(Journal(database), args.incident_id, args.recipient)
            else:
                raise ValueError('unsupported command')
        print(json.dumps(redact(result), indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, sqlite3.Error, TypeError, KeyError) as exc:
        print(json.dumps({'error': redact(str(exc)), 'type': type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
