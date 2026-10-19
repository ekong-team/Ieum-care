"""Offline end-to-end demonstration. Real analysis, synthetic program, fixture generator."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai.evaluation.revision_v2 import load_context
from ai.evaluation.revision_runtime import RevisionRuntime


class DemoGenerator:
    identity = 'offline-fixture-v2'
    kind = 'fixture'

    def __call__(self, system, payload):
        values = dict(title='[가상 시연] 지역 활동 참여 기회 확대안',
                      objective='관측된 집단 활동 감소를 참고해 참여 기회를 제안하고, 개인 자격과 고립 여부는 별도 확인한다.',
                      activities=[dict(activity_id='demo-activity', name='[제안] 소규모 교류 활동',
                                       description='담당자가 참여 의사와 자격을 확인한 뒤 운영 가능성을 검토하는 제안. 추가 비용은 별도 확인한다.')],
                      performance_measures=[dict(metric_id='demo-participation', name='참여 지속 기록',
                          definition='참여 의사가 확인된 등록자의 회차별 참여를 기록하는 계획', denominator='해당 프로그램 등록자',
                          measurement_timing='각 회차 종료 후', data_collection_method='담당자 출석 기록', responsible_party=None,
                          target_value=None, target_basis='unset', source_ref=None)])
        changes, used = [], set()
        for issue in payload['evaluation']['issues']:
            field = issue['field']
            if issue['category'] == 'editable' and field in values and field not in used:
                changes.append(dict(field=field, value=values[field], issue_id=issue['issue_id'], reason='시연용 고정 예시로 누락 계획 항목 보완'))
                used.add(field)
        return dict(proposal=dict(changes=changes, questions=['실제 자격·일정·인원·활동 비용과 운영 가능성을 담당자가 확인해야 합니다.']),
                    provenance=dict(kind='fixture', provider=None, model=None, response_id=None, usage=None,
                                    note='Prewritten deterministic fixture; no actual LLM'))


def demo_plan():
    return dict(schema_version='integration-v1', plan_id='synthetic-study-plan-v2', version=1, status='draft',
                origin='user_input', mode='new', base_resource_id=None, analysis_id='202512_32010_30G',
                title=None, objective=None,
                target=dict(region_code='32010', age_code='30G', planned_participants=None, eligibility_text=None,
                            residency_confirmation='unknown'),
                activities=[], schedule=dict(start_date=None, end_date=None, sessions=None, venue=None),
                performance_measures=[], budget_items=[], assumptions=[], source_refs=[],
                missing_fields=['title', 'objective', 'target.planned_participants', 'target.eligibility_text',
                                'activities', 'schedule', 'performance_measures', 'budget_items'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/revision_demo_20261018')
    parser.add_argument('--run-id', default='offline-demo-v2')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    plan, context = demo_plan(), load_context('202512_32010_30G')
    runtime = RevisionRuntime(args.output / 'runs.sqlite3')
    try:
        state = runtime.run(args.run_id, plan, context, DemoGenerator())
        events = runtime.events(args.run_id)
    finally:
        runtime.close()
    for name, value in [('input_plan.json', plan), ('input_context.json', context), ('result.json', state), ('events.json', events)]:
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(status=state['status'], attempts=state['attempt_count'],
                          generator_calls=state['generator_call_count'], real_model_calls=state['model_call_count'],
                          original_version=plan['version'], candidate_version=state['current_plan']['version'],
                          changes=len(state['history']), remaining_issues=[i['issue_id'] for i in state['evaluation']['issues']],
                          note='Real aggregate analysis + synthetic plan + fixture; not a live agent quality test.'), ensure_ascii=False))


if __name__ == '__main__':
    main()
