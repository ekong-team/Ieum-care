"""실제 분석 입력의 추천 품질을 한 사례씩 검토한다. 기본 실행은 외부 호출이 없다."""
import argparse
from collections import Counter
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai.welfare_agent.analysis_input import latest_analysis_inputs
from ai.welfare_agent.live_agent import AgentError, recommend_live
from ai.nodes.welfare import to_existing_resources

CASES = {
    'CC30F': ('춘천시', 30, 'female', '이전 추천의 추가 자격·상세 출처 확인'),
    'CC60M': ('춘천시', 60, 'male', '60대와 만 65세 이상 조건 구분'),
    'GN20F': ('강남구', 20, 'female', '지역·청년 지원 조건 확인'),
    'GN10M': ('강남구', 10, 'male', '성인 사업 혼입·10~19세 연령 확인'),
}
CRITERIA = {
    'official_detail': '공식 상세 출처인가',
    'region_age': '지역·연령 조건이 맞는가',
    'additional_eligibility': '추가 자격을 충족한다고 단정하지 않는가',
    'current_operation': '연도·종료·모집 여부를 정확히 구분하는가',
    'grounded_relevance': '추천 이유가 원문에 있고 고립 예방 효과를 과장하지 않는가',
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def prepare_case(inputs, case_id):
    region, age, sex, focus = CASES[case_id]
    entries = [entry for entry in inputs['entries'] if
               (entry['request']['target']['region'], entry['request']['target']['age_group'],
                entry['request']['target']['sex']) == (region, age, sex)]
    if len(entries) != 1:
        raise ValueError('완료 판정의 해당 집단 입력이 정확히 한 건 있어야 합니다.')
    entry = entries[0]
    request = deepcopy(entry['request'])
    # 모두 같은 탐색 조건으로 비교한다. 원래 위험도·원인 맥락은 변경하지 않는다.
    request['target']['purpose'] = 'all'
    return dict(schema_version='welfare-quality-case-0.1', case_id=case_id,
                batch_id=inputs['batch_id'], period=inputs['period'], analysis_id=entry['analysis_id'],
                first_rank=entry['rank'], focus=focus, request=request)


def prepare_analysis_case(inputs, analysis_id):
    """최신 완료 집단을 ID로 선택한다. 집단 이름이나 위험 단계를 고정하지 않는다."""
    matches = [entry for entry in inputs['entries'] if entry['analysis_id'] == analysis_id]
    if len(matches) != 1:
        raise ValueError('최신 완료 판정 목록에 해당 분석 ID가 정확히 한 건 있어야 합니다.')
    entry = matches[0]
    request = deepcopy(entry['request'])
    request['target']['purpose'] = 'all'
    # 외부 입력 ID를 파일 경로로 직접 사용하지 않는다.
    case_id = 'AUTO-' + hashlib.sha256(analysis_id.encode()).hexdigest()[:16]
    return dict(schema_version='welfare-quality-case-0.1', case_id=case_id,
                batch_id=inputs['batch_id'], period=inputs['period'], analysis_id=analysis_id,
                first_rank=entry['rank'], focus='최신 분석 결과 기반 품질 검토', request=request)


def coverage_values(entry):
    target = entry['request']['target']
    risk = entry['request'].get('risk_assessment') or {}
    return {('region', target['region']), ('age_group', target['age_group']),
            ('sex', target['sex']), ('risk_level', risk.get('level'))}


def prepare_latest_plan(inputs):
    """공동 1순위 전원 + 아직 없는 조건을 가장 많이 보충하는 집단을 선택한다.

    전체 성능을 추정하는 통계 표본이 아니라 조건 누락을 줄이는 점검 목록이다.
    """
    entries = sorted(inputs['entries'], key=lambda entry: (entry['rank'], entry['analysis_id']))
    ids = [entry['analysis_id'] for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError('분석 ID가 중복되어 검증 대상을 선택할 수 없습니다.')
    selected, covered = [], set()
    remaining = []
    for entry in entries:
        if entry['rank'] == 1:
            selected.append((entry, ['joint_first_priority']))
            covered |= coverage_values(entry)
        else:
            remaining.append(entry)
    while remaining:
        # 동점은 원래 순위, 분석 ID 순서로 결정하여 실행마다 표본이 바뀌지 않게 한다.
        entry = max(remaining, key=lambda item: len(coverage_values(item) - covered))
        added = coverage_values(entry) - covered
        if not added:
            break
        selected.append((entry, [f'coverage:{key}={value}' for key, value in sorted(added)]))
        covered |= added
        remaining.remove(entry)
    rows = []
    for entry, reasons in selected:
        snapshot = prepare_analysis_case(inputs, entry['analysis_id'])
        rows.append(dict(analysis_id=entry['analysis_id'], case_id=snapshot['case_id'],
                         first_rank=entry['rank'], target=deepcopy(snapshot['request']['target']),
                         risk_level=(snapshot['request'].get('risk_assessment') or {}).get('level'),
                         reasons=reasons))
    priority = inputs.get('priority', {})
    return dict(schema_version='welfare-quality-plan-0.1', batch_id=inputs['batch_id'],
                period=inputs['period'], policy='all-rank-1-then-greedy-condition-coverage-v1',
                eligible_count=len(entries), selected=rows,
                not_selected=[dict(analysis_id=entry['analysis_id'], first_rank=entry['rank'],
                                   reason='선택된 사례에 지역·연령·성별·단계 조건이 이미 포함됨')
                              for entry in remaining],
                partial_count=len(priority.get('partial_assessments', [])),
                held_count=len(priority.get('held_cohorts', [])),
                notes=['부분판정·보류는 추천 검증 대상에 넣지 않음',
                       '관측된 조건만 점검하며 전체 조합·통계적 대표성을 보장하지 않음',
                       '계획 생성은 외부 API를 호출하지 않음. 실제 추천은 ID별 명시 실행'])


def save_latest_plan(inputs, output_root):
    plan = prepare_latest_plan(inputs)
    folder = Path(output_root) / 'plans' / inputs['batch_id']
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / 'plan.json', plan)
    # JSON을 열지 않아도 팀원이 선정 집단과 이유를 표로 확인할 수 있게 한다.
    with (folder / 'plan.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            'analysis_id', 'region', 'age_group', 'sex', 'risk_level', 'first_rank', 'reasons'])
        writer.writeheader()
        for row in plan['selected']:
            reasons = ['공동 1순위 전체 포함' if reason == 'joint_first_priority' else reason
                       for reason in row['reasons']]
            writer.writerow(dict(analysis_id=row['analysis_id'],
                **{key: row['target'][key] for key in ('region', 'age_group', 'sex')},
                risk_level=row['risk_level'], first_rank=row['first_rank'], reasons=' / '.join(reasons)))
    for row in plan['selected']:
        run_case(prepare_analysis_case(inputs, row['analysis_id']), output_root)
    return folder, plan


def write_review(folder, snapshot, result=None):
    candidates = (result or {}).get('resources', [])
    fields = ['case_id', 'resource_id', 'resource_name', 'criterion', 'check',
              'verdict', 'source_url', 'evidence', 'note']
    with (folder / 'review.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in candidates:
            for criterion, label in CRITERIA.items():
                writer.writerow(dict(case_id=snapshot['case_id'], resource_id=item['id'],
                    resource_name=item['name'], criterion=criterion, check=label, verdict='pending',
                    source_url=item.get('source', {}).get('url', ''), evidence='', note=''))
        if not candidates:
            writer.writerow(dict(case_id=snapshot['case_id'], resource_id='', resource_name='',
                criterion='lookup_coverage', check='실패·미실행·정상 0개를 구분하고 검색 누락을 확인',
                verdict='pending', source_url='', evidence='', note='실제 지역 자원 부재를 뜻하지 않음'))


def run_case(snapshot, output_root, *, allow_external=False, attempt=1, agent=None):
    if type(attempt) is not int or not 1 <= attempt <= 100:
        raise ValueError('attempt는 1~100 정수여야 합니다.')
    folder = Path(output_root) / snapshot['case_id'] / snapshot['batch_id'][:16] / f'attempt-{attempt:02}'
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    manifest_path = folder / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['input_hash'] != fingerprint:
            raise ValueError('같은 경로의 입력이 다릅니다. 새 시도 번호를 사용해주세요.')
        # 완료·오류·중단 흔적은 자동 재실행하지 않아 중복 API 호출을 막는다.
        if manifest['status'] != 'prepared' or not allow_external:
            return folder, manifest
    else:
        write_json(folder / 'request.json', snapshot)
        manifest = dict(schema_version='welfare-quality-run-0.1', input_hash=fingerprint,
            status='prepared', case_id=snapshot['case_id'], analysis_id=snapshot['analysis_id'],
            batch_id=snapshot['batch_id'], external_calls={}, candidate_count=None,
            created_at=datetime.now(timezone.utc).isoformat(), quality_status='pending_manual_review')
        write_json(manifest_path, manifest)
        write_review(folder, snapshot)
    if not allow_external:
        return folder, manifest
    manifest['status'] = 'running'
    write_json(manifest_path, manifest)
    calls = Counter()
    try:
        result = (agent or recommend_live)(deepcopy(snapshot['request']), on_external_call=lambda provider: calls.update([provider]))
        result['response_routing'] = to_existing_resources(result, []).response_routing.model_dump(mode='json')
        write_json(folder / 'result.json', result)
        write_review(folder, snapshot, result)
        manifest.update(status='completed', candidate_count=len(result['resources']),
                        exclusion_counts=result.get('exclusion_counts', {}),
                        search_new_calls=result.get('search_new_calls'), search_credits=result.get('search_credits'))
    except AgentError as error:
        # 기존 Agent의 정리된 오류 설명만 저장하고 제공자 원문이나 키는 기록하지 않는다.
        manifest.update(status='failed', http_status=error.status, error=str(error))
    except Exception:
        manifest.update(status='failed', error='추천 실행 또는 결과 보관 실패 · 자동 재시도하지 않음')
    finally:
        manifest.update(external_calls=dict(calls), finished_at=datetime.now(timezone.utc).isoformat())
        write_json(manifest_path, manifest)
    return folder, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--case', choices=CASES, help='고정 사례를 회귀 비교용으로 준비·실행')
    selection.add_argument('--analysis-id', help='최신 완료 판정의 한 집단만 준비·실행')
    selection.add_argument('--latest-plan', action='store_true', help='최신 분석 기반 검증 계획 준비 (기본값)')
    parser.add_argument('--allow-external', action='store_true', help='선택한 한 사례의 실제 추천을 실행')
    parser.add_argument('--attempt', type=int, default=1, help='같은 시도는 재호출하지 않음. 새 번호는 명시적인 별도 실행')
    args = parser.parse_args()
    if args.allow_external and not (args.case or args.analysis_id):
        parser.error('외부 추천은 --case 또는 --analysis-id로 한 집단을 지정해야 합니다.')
    inputs = latest_analysis_inputs(ROOT / 'data/processed/analysis_current')
    output_root = ROOT / 'data/processed/welfare_quality'
    if not (args.case or args.analysis_id):
        folder, plan = save_latest_plan(inputs, output_root)
        print(json.dumps(dict(folder=str(folder), batch_id=plan['batch_id'],
                              eligible=plan['eligible_count'], selected=plan['selected'],
                              external_calls={}), ensure_ascii=False))
        return
    snapshot = (prepare_case(inputs, args.case) if args.case else
                prepare_analysis_case(inputs, args.analysis_id))
    folder, manifest = run_case(snapshot, output_root,
                               allow_external=args.allow_external, attempt=args.attempt)
    print(json.dumps(dict(folder=str(folder), status=manifest['status'], candidates=manifest['candidate_count'],
                          external_calls=manifest['external_calls']), ensure_ascii=False))


if __name__ == '__main__':
    main()
