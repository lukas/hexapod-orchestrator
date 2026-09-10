"""Timer admission must not turn idle checks or failures into paid loops."""
from datetime import timedelta
import json
from pathlib import Path
import sqlite3

import pytest

from rl_move.overseer import scheduler
from rl_move.overseer.policy import timestamp


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('HEXAPOD_MODEL_SOURCE', 'mesh')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-secret')
    database = tmp_path/'state'/'overseer.sqlite3'
    scheduler.configure(database, enabled=True, project_root=tmp_path)
    profiles = database.parent/'reviewers'
    profiles.mkdir()
    profiles.joinpath('claude.json').write_text((Path(scheduler.__file__).parent/'reviewers/claude.json').read_text())
    from rl_move.overseer import __main__ as cli
    state = {'collected_at': timestamp().isoformat(), 'agents': [], 'services': [], 'errors': []}
    monkeypatch.setattr(cli, 'collect', lambda *a: state)
    calls = []
    def reviewer(args, db):
        calls.append(args)
        return {'outcome': 'succeeded', 'wake_id': 'test-wake'}
    collector = lambda *a, **kw: {'errors': []}
    return database, state, calls, collector, reviewer


def active(state):
    state['agents'] = [{'agent_id': 'worker', 'status': 'running',
        'observed_at': timestamp().isoformat(), 'goals': ['rl_only']}]


def age_check(database):
    with sqlite3.connect(database) as db:
        config = json.loads(db.execute('SELECT body FROM metaagent_schedule').fetchone()[0])
        config['last_paid_at'] = (timestamp()-timedelta(hours=7)).isoformat()
        db.execute('UPDATE metaagent_schedule SET body=?', (json.dumps(config),))


def test_status_and_disabled_tick_do_not_create_database(tmp_path):
    database = tmp_path/'absent'/'state.sqlite3'
    assert scheduler.scheduler_status(database)['enabled'] is False
    assert scheduler.tick(database)['outcome'] == 'disabled'
    assert not database.parent.exists()


def test_idle_gate_records_free_check_without_reviewer(setup):
    database, state, calls, collector, reviewer = setup
    assert scheduler.tick(database, collector=collector, reviewer=reviewer)['outcome'] == 'idle'
    assert calls == []
    status = scheduler.scheduler_status(database)
    assert status['free_checks'] == 1 and status['paid_reviews_started'] == 0
    assert status['next_check_at'] and not status['active_check']


def test_cadence_and_unchanged_success_never_rebuy_review(setup):
    database, state, calls, collector, reviewer = setup
    active(state)
    tick = lambda: scheduler.tick(database, collector=collector, reviewer=reviewer)
    assert tick()['outcome'] == 'succeeded'
    assert calls[0].force is False and calls[0].resume_wake is None
    assert tick()['outcome'] == 'cooldown'
    age_check(database)
    assert tick()['outcome'] == 'unchanged'
    state['agents'][0]['progress_evidence'] = ['new reproducible joystick demo']
    assert tick()['outcome'] == 'succeeded'
    assert len(calls) == 2


def test_failure_holds_even_when_agents_change(setup):
    database, state, calls, collector, reviewer = setup
    active(state)
    def blocked(*args):
        calls.append(True)
        return {'outcome': 'blocked', 'wake_id': 'failed-wake'}
    assert scheduler.tick(database, collector=collector, reviewer=blocked)['outcome'] == 'blocked'
    age_check(database)
    state['agents'][0]['progress_evidence'] = ['new activity']
    assert scheduler.tick(database, collector=collector, reviewer=reviewer)['outcome'] == 'held'
    assert len(calls) == 1


def test_missing_key_is_free_visible_hold(setup, monkeypatch):
    database, state, calls, collector, reviewer = setup
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    active(state)
    result = scheduler.tick(database, collector=collector, reviewer=reviewer)
    assert result['outcome'] == 'credentials_missing' and not result['paid_review_started']
    assert scheduler.scheduler_status(database)['review_hold']
    assert calls == []


def test_active_wake_not_reopened_or_replaced(setup):
    from rl_move.overseer.store import Store
    database, state, calls, collector, reviewer = setup
    store = Store(database)
    wake = store.start_wake('manual existing wake')
    active(state)
    assert scheduler.tick(database, collector=collector, reviewer=reviewer)['outcome'] == 'active_wake'
    assert store.snapshot()['active_wake']['wake_id'] == wake['wake_id']
    assert calls == []


def test_interrupted_paid_attempt_fails_closed(setup):
    database, state, calls, collector, reviewer = setup
    with sqlite3.connect(database) as db:
        db.execute('INSERT INTO metaagent_checks(check_id,started_at,outcome,paid_review_started) VALUES(?,?,?,1)',
                   ('crashed', timestamp().isoformat(), 'checking'))
    active(state)
    assert scheduler.tick(database, collector=collector, reviewer=reviewer)['outcome'] == 'held'
    assert calls == []


def test_disabling_during_collection_prevents_paid_dispatch(setup):
    database, state, calls, collector, reviewer = setup
    active(state)
    def disable(*a, **kw):
        scheduler.configure(database, enabled=False)
        return {'errors': []}
    assert scheduler.tick(database, collector=disable, reviewer=reviewer)['outcome'] == 'disabled'
    assert calls == []


def test_exception_after_dispatch_holds_without_secret_log(setup):
    database, state, calls, collector, reviewer = setup
    active(state)
    def fail(*args):
        raise RuntimeError('Bearer private-value')
    assert scheduler.tick(database, collector=collector, reviewer=fail)['outcome'] == 'error'
    status = scheduler.scheduler_status(database)
    assert status['review_hold'] and 'private-value' not in json.dumps(status)


def test_unknown_reserved_cost_can_make_check_wait_without_new_wake(setup):
    from rl_move.overseer.store import Store
    database, state, calls, collector, reviewer = setup
    store = Store(database)
    for index in range(4):
        wake = store.start_wake('previous uncertain cost')
        store.reserve(wake['wake_id'], f'operation-{index}', '20')
        store.finish_wake(wake['wake_id'], 'blocked')
    active(state)
    assert scheduler.tick(database, collector=collector, reviewer=reviewer)['outcome'] == 'budget_wait'
    assert len(store.snapshot()['wakes']) == 4
    assert calls == []


def test_overlap_cannot_collect_or_dispatch_twice(setup):
    import fcntl
    database, state, calls, collector, reviewer = setup
    with (database.parent/'metaagent-scheduler.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert scheduler.tick(database, collector=collector, reviewer=reviewer)['outcome'] == 'already_running'
    assert calls == []


def test_source_failure_remains_free_and_does_not_invent_idle(setup):
    database, state, calls, collector, reviewer = setup
    def broken(*a, **kw):
        raise TimeoutError('unavailable source')
    assert scheduler.tick(database, collector=broken, reviewer=reviewer)['outcome'] == 'error'
    assert scheduler.scheduler_status(database)['free_checks'] == 1
    assert calls == []
