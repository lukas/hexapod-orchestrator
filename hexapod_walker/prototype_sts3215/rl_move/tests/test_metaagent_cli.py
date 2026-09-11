"""Public naming preserves the durable budget and provider admission rules."""
import json
from pathlib import Path
import pytest
from rl_move.overseer import __main__ as engine
from rl_move.metaagent import __main__ as metaagent


def test_metaagent_and_legacy_state_are_the_same(monkeypatch, tmp_path):
    monkeypatch.delenv('HEXAPOD_METAAGENT_DIR', raising=False)
    monkeypatch.setenv('HEXAPOD_OVERSEER_DIR', str(tmp_path/'existing'))
    assert engine.default_state_dir() == tmp_path/'existing'
    monkeypatch.setenv('HEXAPOD_METAAGENT_DIR', str(tmp_path/'explicit'))
    assert engine.default_state_dir() == tmp_path/'explicit'


def test_named_status_does_not_create_database(tmp_path, capsys):
    assert metaagent.main(['--state-dir',str(tmp_path/'absent'),'status']) == 0
    result=json.loads(capsys.readouterr().out)
    assert result['service']=='hexapod-metaagent'
    assert result['scheduler_enabled'] is False
    assert not (tmp_path/'absent').exists()


def test_provider_mismatch_rejected_before_collection(tmp_path,monkeypatch,capsys):
    cfg=tmp_path/'claude.json';cfg.write_text(json.dumps({'provider':'claude'}))
    monkeypatch.setattr(engine,'collect',lambda *_:pytest.fail('must reject before collection'))
    assert metaagent.main(['--state-dir',str(tmp_path/'state'),'review','--provider','codex','--reviewer-config',str(cfg)])==2
    assert 'differs' in capsys.readouterr().err
    assert not (tmp_path/'state').exists()


def test_failed_connector_export_is_disclosed(tmp_path):
    source=tmp_path/'codex.json'
    source.write_text(json.dumps({'collected_at':'2026-09-09T14:00:00Z','data':{'isError':True,'content':[{'text':'private provider error'}]}}))
    result=engine.supplement(str(source),'codex',tmp_path)
    assert result['agents']==[]
    assert result['errors'][0]['code']=='export_failed'
    assert 'private' not in json.dumps(result)


def test_strategy_export_becomes_bounded_portfolio_evidence(tmp_path):
    source = tmp_path / 'strategy.json'
    source.write_text(json.dumps({'collected_at': '2026-09-09T14:00:00Z', 'data': {
        'research_brief': 'current hypotheses', 'recent_runs': 'run-a then run-b',
        'ignored': 'not exported'}}))
    result = engine.supplement(str(source), 'strategy', tmp_path)
    campaign = result['portfolio_evidence']['rl_campaign']
    assert campaign['research_brief'] == 'current hypotheses'
    assert campaign['recent_runs'] == 'run-a then run-b'
    assert 'ignored' not in campaign
