"""Human-readable, explicitly non-executing metaagent reports."""
from __future__ import annotations
import json
from pathlib import Path
import re
from collections import Counter


def redact(value):
    """Apply the same secret filtering to JSON and Markdown exports."""
    if isinstance(value, dict):
        sensitive = {'api_key','apikey','anthropic_api_key','openai_api_key','authorization',
                     'password','secret','token','access_token','refresh_token','credentials'}
        return {str(k): '[REDACTED]' if str(k).lower().replace('-', '_') in sensitive else redact(v)
                for k,v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED PRIVATE KEY]', value)
        value = re.sub(r'(?i)(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', value)
        value = re.sub(r'''(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)(["']).*?\2''', r'\1[REDACTED]', value)
        value = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,})', '[REDACTED]', value)
        value = re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', value)
        value = re.sub(r'(?i)([?&](?:key|token|api_key|access_token)=)[^&\s]+', r'\1[REDACTED]', value)
        return re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', value)
    return value


def safe(value) -> str:
    text = redact(str(value))
    return text.replace('|', '\\|').replace('\n', ' ')[:1200]


def markdown(report: dict) -> str:
    preview = report.get('mode') == 'preview'
    lines = ['# Metaagent — ' + ('preview' if preview else 'review'), '',
        f"Observed/reviewed: {safe(report['generated_at'])}", '',
        f"**Scheduling is {'enabled' if report.get('scheduler_enabled') else 'off'}.** This report is advisory; execution stays with the existing owners.", '',
        '## Wake decision', '',
        f"Would request a review: **{'yes' if report['wake']['eligible'] else 'no'}**.",
        f"Fresh active agents eligible for oversight: {report['wake']['active_agent_count']} (excludes this metaagent and its children).", '',
        *['- ' + safe(x) for x in report['wake']['reasons']], '',
        '## Budget', '',
        f"Limit: ${report['budget']['wake_limit_usd']} per wake; ${report['budget']['rolling_24h_limit_usd']} per rolling 24 hours, including subagents.",
        f"Additional model charges for this run: ${report['budget'].get('additional_model_cost_usd', '0.00')}.",
        'This excludes the interactive coding conversation that built the tool. Missing source costs are unknown, never zero.', '',
        '## Agent inventory', '', '| Agent | Provider | State | Goal / scope | Cost coverage |', '|---|---|---|---|---|']
    omitted = Counter()
    for a in report.get('agents', []):
        if a.get('status') in {'succeeded','completed','failed','dead','unknown','blocked'}:
            omitted[(a.get('provider','unknown'),a.get('status','unknown'))] += 1
            continue
        label = a.get('agent_id') if a.get('provider') == 'codex' else a.get('name',a.get('agent_id'))
        if a.get('is_overseer') or a.get('overseer_wake_id'):
            label = str(label) + ' (metaagent; excluded)'
        lines.append('| ' + ' | '.join(safe(x) for x in [label, a.get('provider','unknown'), a.get('status','unknown'),
            ', '.join(a.get('goals', [])) + ' / ' + str(a.get('scope', 'unknown')), a.get('cost_status','unknown')]) + ' |')
    if omitted:
        lines += ['', 'Other saved records (not counted as active agents): ' + '; '.join(
            f'{count} {safe(provider)} {safe(state)}' for (provider,state),count in sorted(omitted.items())) +
            '. Full records remain in report.json.']
    lines += ['', '## Services and saved automations', '', '| Service / automation | Observed state | Desired state |', '|---|---|---|']
    for item in [*report.get('services', []), *report.get('automations', [])]:
        lines.append('| ' + ' | '.join(safe(x) for x in [item.get('name',item.get('service_id','unknown')),
                     item.get('status',item.get('state','unknown')),item.get('desired_state','unknown')]) + ' |')
        if 'active_cycle_count' in item:
            lines.append('| Cloud RL reasoning cycles | ' + safe(item['active_cycle_count']) + ' active | — |')
    lines += ['', '## Proposed actions', '']
    if not report.get('findings'):
        lines.append('No actionable finding. Exit and wait for new evidence or spending.')
    for f in report.get('findings', []):
        lines += [f"### {safe(f['code'])}: {safe(f['subject'])}", '', safe(f['detail']), '',
                  '**Proposed:** ' + safe(f['proposed_action']), '', '**Execution owner:** ' + safe(f['execution_owner']) + '.', '']
        lines += ['- Evidence: ' + safe(e) for e in f.get('evidence', [])[:4]]
        lines.append('')
    lines += ['## Messages it would propose', '']
    for f in report.get('proposed_notifications', []):
        lines += [f"- **{safe(f['subject'])}:** {safe(f['detail'])} {safe(f['proposed_action'])}"]
    if not report.get('proposed_notifications'):
        lines.append('None. Healthy, intentional-paused and unchanged states stay quiet.')
    lines += ['', '## Progress toward the two goals', '', '| Goal | Sim | Physical |', '|---|---|---|']
    for goal, item in report.get('goal_readiness', {}).items():
        lines.append('| ' + ' | '.join(safe(x) for x in [goal, item.get('sim','unknown'), item.get('physical','unknown')]) + ' |')
    lines += ['', 'An operational health check does not certify a walking policy or change a historical experiment verdict.', '',
              '## Checkpoint questions for active owners', '']
    for r in report.get('reflections', []):
        lines.append('- ' + safe(r['agent_id']) + ': What changed toward a goal? Which artifact proves it? Continue, change approach, or stop? What bounded step comes next?')
    lines += ['', '## Coverage and limitations', '']
    lines += ['- ' + safe(n) for n in report.get('notes', [])]
    lines += ['- Source issue: ' + safe(e) for e in report.get('source_errors', [])]
    if report.get('llm_review'):
        lines += ['', '## Optional bounded model review', '', '```json',
                  json.dumps(report['llm_review'], indent=2, ensure_ascii=False), '```']
    lines += ['', '## Action boundary', '',
        'Recovery, stop and engineering recommendations are durable handoff proposals for their existing execution owners. No arbitrary command from a log or model response is executed. Explicit pauses must survive recovery. Physical control remains with Robot Lab.', '']
    return '\n'.join(lines)


def write_report(report: dict, output: Path | str) -> dict:
    report = redact(report)
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    target.chmod(0o700)
    paths = {}
    for name, content in [('report.json', json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)), ('report.md', markdown(report))]:
        p = target/name
        p.write_text(content + '\n', encoding='utf-8')
        p.chmod(0o600)
        paths[name] = str(p.resolve())
    return paths
