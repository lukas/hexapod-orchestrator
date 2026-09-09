"""Manual entry points must not quietly activate monitoring or paid work."""
import json
from pathlib import Path

from rl_move.overseer.__main__ import main, merge_registry, read_registry, compact_for_review
from rl_move.overseer.policy import evaluate
from rl_move.overseer.report import write_report
from rl_move.overseer.store import Store

NOW = '2026-09-09T04:00:00+00:00'


def fixture_snapshot(tmp_path, **changes):
    path = tmp_path/'snapshot.json'
    path.write_text(json.dumps({'collected_at': NOW, 'agents': [], 'services': [], **changes}))
    return path


def test_preview_does_not_create_registry_or_invoke_reviewer(tmp_path, monkeypatch):
    from rl_move.overseer import reviewer
    monkeypatch.setattr(reviewer, 'review_once', lambda *a,**kw: (_ for _ in ()).throw(AssertionError('paid call')))
    snapshot = fixture_snapshot(tmp_path)
    state, output = tmp_path/'state', tmp_path/'report'
    assert main(['--state-dir', str(state), 'preview','--snapshot',str(snapshot),'--output',str(output)]) == 0
    assert not state.exists()
    report = json.loads((output/'report.json').read_text())
    assert report['actions_executed'] == report['notifications_sent'] == []
    assert report['scheduler_enabled'] is False
    assert report['budget']['additional_model_cost_usd'] == '0.00'


def test_preview_does_not_acknowledge_cost_or_change_existing_database(tmp_path):
    state = tmp_path/'state'
    store = Store(state/'overseer.sqlite3')
    store.register_agent({'agent_id':'a','task_id':'a','cost_status':'known'})
    store.record_spend('a','e','101',NOW)
    before = (state/'overseer.sqlite3').read_bytes()
    snapshot = fixture_snapshot(tmp_path)
    assert main(['--state-dir',str(state),'preview','--snapshot',str(snapshot),'--output',str(tmp_path/'out')]) == 0
    assert (state/'overseer.sqlite3').read_bytes() == before
    assert read_registry(state/'overseer.sqlite3')[0]['unreviewed_cost_usd'] == '101'


def test_idle_review_creates_no_wake(tmp_path):
    state = tmp_path/'state'
    assert main(['--state-dir',str(state),'review','--snapshot',str(fixture_snapshot(tmp_path)),
                 '--output',str(tmp_path/'out')]) == 0
    assert not state.exists()


def test_rules_review_is_durable_but_does_not_clear_spend(tmp_path):
    state = tmp_path/'state'
    store = Store(state/'overseer.sqlite3')
    store.register_agent({'agent_id':'a','task_id':'a','cost_status':'known'})
    store.record_spend('a','e','101',NOW)
    snapshot = fixture_snapshot(tmp_path)
    assert main(['--state-dir',str(state),'review','--snapshot',str(snapshot),'--output',str(tmp_path/'out')]) == 0
    assert store.snapshot()['active_wake'] is None
    assert store.spending_since_review('a')['amount_usd'] == '101.000000'
    assert store.snapshot()['reservations'] == []


def test_discovery_updates_liveness_preserves_registered_purpose_and_spend():
    saved = {'agent_id':'a','task_id':'logical','goals':['rl_only'],'status':'running',
             'registration':'registered','unreviewed_cost_usd':'100'}
    live = {'agent_id':'a','task_id':'a','goals':[],'status':'idle'}
    merged = merge_registry([live],[saved])[0]
    assert merged['status'] == 'idle'
    assert merged['task_id'] == 'logical' and merged['goals'] == ['rl_only']
    assert merged['unreviewed_cost_usd'] == '100'


def test_task_spend_groups_children_and_does_not_rebuy_unchanged_blocker():
    agents = [{'agent_id':name,'task_id':'task','status':'idle','cost_status':'known',
               'unreviewed_cost_usd':'60','observed_at':NOW} for name in ['parent','child']]
    result = evaluate({'agents':agents},now=NOW)
    assert result['wake']['spend_due_agents'] == ['parent','child']
    assert len([f for f in result['findings'] if f['code']=='spend_review']) == 1
    again = evaluate({'agents':list(reversed(agents))},now=NOW,
                     history={'last_outcome':'blocked','fingerprint':result['wake']['fingerprint']})
    assert not again['wake']['eligible']


def test_redaction_applies_to_both_artifact_formats(tmp_path):
    report = evaluate({'agents':[]},now=NOW)
    report['notes'] = ['api_key=sk-dangersecret abc https://site/path?key=secretvalue',
                       'api_key="a secret with spaces"', 'https://name:password123@site.test/path']
    report['extra'] = {'authorization':'credential-value'}
    paths = write_report(report,tmp_path/'out')
    for path in paths.values():
        contents = Path(path).read_text()
        assert 'sk-dangersecret' not in contents
        assert 'secretvalue' not in contents
        assert 'credential-value' not in contents
        assert 'secret with spaces' not in contents
        assert 'password123' not in contents


def test_source_exports_require_real_collection_timestamp(tmp_path):
    path = tmp_path/'tool.json'
    path.write_text('{}')
    assert main(['--state-dir',str(tmp_path/'state'),'preview','--snapshot',str(fixture_snapshot(tmp_path)),
                 '--cloud-activity',str(path),'--output',str(tmp_path/'out')]) == 2
    assert not (tmp_path/'state').exists()


def test_terminal_task_due_for_spend_review_is_included_before_active_work():
    report = evaluate({'agents':[{'agent_id':'terminal','status':'completed','unreviewed_cost_usd':'101'}]},now=NOW)
    assert compact_for_review(report,{})['agents'][0]['agent_id'] == 'terminal'


def test_overseer_attribution_follows_parent_chain():
    report = evaluate({'agents':[{'agent_id':'root','is_overseer':True},
        {'agent_id':'child','parent_id':'root'}, {'agent_id':'grandchild','parent_id':'child',
         'status':'running','observed_at':NOW,'unreviewed_cost_usd':'200'}]},now=NOW)
    assert not report['wake']['eligible']
    assert report['wake']['active_agent_count'] == 0


def test_changed_service_dependency_can_unblock_active_review():
    snapshot = {'agents':[{'agent_id':'a','status':'running','observed_at':NOW}],
                'services':[{'service_id':'dependency','status':'failed'}]}
    first = evaluate(snapshot,now=NOW)
    snapshot['services'][0]['status'] = 'healthy'
    next_report = evaluate(snapshot,now=NOW,history={'last_outcome':'blocked',
                         'fingerprint':first['wake']['fingerprint']})
    assert next_report['wake']['eligible']
