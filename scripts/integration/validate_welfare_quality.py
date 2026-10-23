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
    parser.add_argument('--case', choices=CASES, default='CC30F')
    parser.add_argument('--allow-external', action='store_true', help='선택한 한 사례의 실제 추천을 실행')
    parser.add_argument('--attempt', type=int, default=1, help='같은 시도는 재호출하지 않음. 새 번호는 명시적인 별도 실행')
    args = parser.parse_args()
    inputs = latest_analysis_inputs(ROOT / 'data/processed/analysis_current')
    folder, manifest = run_case(prepare_case(inputs, args.case), ROOT / 'data/processed/welfare_quality',
                               allow_external=args.allow_external, attempt=args.attempt)
    print(json.dumps(dict(folder=str(folder), status=manifest['status'], candidates=manifest['candidate_count'],
                          external_calls=manifest['external_calls']), ensure_ascii=False))


if __name__ == '__main__':
    main()
