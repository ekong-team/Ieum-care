"""분석 반환값 → 1차 순위별 복지 요청. ZIP·외부 API·위험도 재판정 없이 연결한다."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.request import Request, urlopen

from ai.analysis_agent.agent import recommendation_request
from ai.analysis_agent.inputs import digest
from ai.analysis_agent.priority import priority_for


def prepare_analysis_inputs(bundle: dict) -> dict:
    if not isinstance(bundle, dict) or bundle.get('schema_version') != 'analysis-bundle-0.3':
        raise ValueError('지원하는 분석 결과 객체가 필요합니다.')
    if bundle.get('bundle_hash') != digest({k: v for k, v in bundle.items() if k != 'bundle_hash'}):
        raise ValueError('분석 결과 해시가 일치하지 않습니다.')
    priority = bundle['priority_review']
    # 순위를 새 정책으로 바꾸지 않고, 전달된 순위가 원래 분석과 같은지만 검사한다.
    expected = priority_for(bundle['cohorts'], priority['period'].replace('-', ''))
    if priority != expected:
        raise ValueError('1차 순위와 분석 집단이 일치하지 않습니다.')
    entries = []
    for item in priority['ranked_cohorts']:
        request = recommendation_request(bundle, item['analysis_id'])
        entries.append(dict(analysis_id=item['analysis_id'], rank=item['rank'], request=request,
                            quality_warnings=deepcopy(item['quality_warnings'])))
    return dict(schema_version='analysis-welfare-inputs-0.1', batch_id=bundle['bundle_hash'],
                period=priority['period'], priority=deepcopy(priority), entries=entries,
                notes=['완료 판정의 1차 순위를 유지합니다. 부분판정·보류는 별도 확인 대상입니다.',
                       '합산 비교 집단을 남녀 순위에 중복 추가하지 않습니다.'])


def latest_analysis_inputs(root: Path) -> dict:
    """분석 실행기가 공개한 고정 경로만 읽는다. 임의 경로나 ZIP은 받지 않는다."""
    root = root.resolve()
    latest = json.loads((root / 'latest.json').read_text(encoding='utf-8'))
    folder = (root / latest['directory']).resolve()
    if not folder.is_relative_to(root) or folder == root:
        raise ValueError('분석 결과 경로가 올바르지 않습니다.')
    status = json.loads((folder / 'run_status.json').read_text(encoding='utf-8'))
    bundle = json.loads((folder / 'analysis_bundle.json').read_text(encoding='utf-8'))
    if status.get('status') != 'passed' or status.get('bundle_hash') != bundle.get('bundle_hash') or latest.get('bundle_hash') != bundle.get('bundle_hash'):
        raise ValueError('완료된 최신 분석 결과가 아닙니다.')
    return prepare_analysis_inputs(bundle)


def publish_analysis_inputs(bundle: dict, *, port: int = 5175) -> dict:
    """별도 분석 프로세스에서 로컬 추천 서버로 전달한다. 검색·모델은 실행하지 않는다."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('로컬 서버 포트를 확인해주세요.')
    request = Request(f'http://127.0.0.1:{port}/api/welfare/analysis-inputs',
                      data=json.dumps(bundle, ensure_ascii=False, allow_nan=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=30) as response:
        return json.load(response)
