"""Audit current implementation boundaries. Does not call a model or mutate inputs."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = ROOT / 'ai/evaluation/revision_agent.py'
    spec = importlib.util.spec_from_file_location('revision_audit', source)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    plan = dict(plan_id='audit-plan', analysis_id='audit-analysis', version=2,
                status='draft', title='초안', objective=None, activities=[], budget_items=[],
                target={'age_code': '30G'}, missing_fields=['objective'])
    evaluation = dict(plan_id=plan['plan_id'], analysis_id=plan['analysis_id'],
                      evaluation_id='audit-evaluation', evaluated_plan_version=1,
                      criteria_results=[dict(criterion_id='target_fit', status='needs_revision')])
    def proposal(field, value):
        return dict(changes=[dict(field=field, value=value, criterion_id='target_fit', reason='감사 전용 예시')], questions=[])
    baseline = json.dumps(plan, sort_keys=True, ensure_ascii=False)
    findings = []
    stale = revision.revise(plan, evaluation, proposal=proposal('objective', '참여 기회 확대 제안'))
    assert stale['requires_reevaluation']
    findings.append(dict(id='stale_evaluation', observed='version1 evaluation applied to version2 plan',
                         status='reproduced_gap', required='check evaluated version and plan/context hashes'))
    claim = revision.revise(plan, evaluation, proposal=proposal('objective', '30대 전원이 지원 자격을 충족한다고 확정한다.'))
    assert claim['changes']
    findings.append(dict(id='semantic_claim', observed='unsupported eligibility claim accepted inside allowed objective field',
                         status='reproduced_gap', required='claim/source/eligibility semantic evaluation'))
    blocked = revision.revise(plan, evaluation, proposal=proposal('budget_items', [{'unit_price_krw': 1}]))
    assert not blocked['changes'] and blocked['rejected_changes']
    findings.append(dict(id='protected_budget', status='verified_boundary', observed='budget replacement rejected'))
    callbacks = []
    def fake_generator(system, payload):
        callbacks.append(payload)
        return proposal('objective', '참여 기회 확대 제안')
    generated = revision.revise(plan, evaluation, generate=fake_generator)
    assert generated['model_executed'] and len(callbacks) == 1
    assert set(callbacks[0]) == {'program_plan', 'evaluation'}
    findings.append(dict(id='model_provenance', status='reproduced_gap', observed='ordinary Python callable sets model_executed=true',
                         required='provider response evidence distinct from generator invocation'))
    findings.append(dict(id='missing_context', status='verified_boundary', observed='generator payload has plan/evaluation only; no analysis/background object'))
    no_op = revision.revise(plan, evaluation, proposal=dict(changes=[], questions=['추가 정보가 필요합니다.']), iteration=0)
    assert no_op['iteration'] == 0
    findings.append(dict(id='attempt_accounting', status='reproduced_gap', observed='no-change questions do not consume current revision iteration',
                         required='orchestrator counts every model attempt separately from accepted plan versions'))
    for topic, field in [('measurement', 'performance_measures'), ('schedule', 'schedule')]:
        rejected = revision.revise(plan, evaluation, proposal=proposal(field, []))
        assert not rejected['changes']
        findings.append(dict(id=f'limited_scope_{topic}', status='verified_boundary', observed=f'{field} not editable in v1'))
    assert json.dumps(plan, sort_keys=True, ensure_ascii=False) == baseline
    packet = json.loads((ROOT / 'data/processed/submission_data_review_20261015/analysis_with_population_calendar.json').read_text(encoding='utf-8'))
    original = json.loads((ROOT / 'data/processed/agent_activity_evidence.json').read_text(encoding='utf-8'))
    assert [r['analysis_evidence'] for r in packet['records']] == original['records']
    assert len(packet['records']) == len({r['analysis_id'] for r in packet['records']}) == 72
    assert all('calendar_context' in r and 'resident_population' in r for r in packet['records'])
    assert all('weather_context' not in r and 'economic_context' not in r for r in packet['records'])
    report = dict(audit_date='2026-10-18', method='local deterministic probes with synthetic plan; no real LLM',
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), findings=findings,
                  original_records_unchanged=72, input_unchanged=True,
                  limitations=['These probes demonstrate current gaps, not successful implementation of the proposed v2.',
                               'No domain expert review, provider integration, quality benchmark or live service was tested.'])
    out = ROOT / 'data/processed/agent_design_review_20261018'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
