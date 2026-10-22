"""추천 화면의 기획 요청을 검증·보관한다. 기획 생성/외부 API는 실행하지 않는다."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from uuid import UUID

from ai.contracts import ResponseRouting
from ai.welfare_agent.recommender import validate_request


def validate_planning_request(payload):
    required = {'schema_version', 'request_id', 'created_at', 'planning_type', 'target',
                'officer_prompt', 'confirmed_support_needs', 'risk_assessment', 'analysis_context',
                'has_example_context', 'selected_resources', 'welfare_lookup', 'notes'}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError('기획 요청의 필수 항목을 확인해주세요.')
    if payload['schema_version'] != 'planning-request-0.1':
        raise ValueError('지원하지 않는 기획 요청 버전입니다.')
    if str(UUID(payload['request_id'])) != payload['request_id']:
        raise ValueError('기획 요청 ID를 확인해주세요.')
    created = datetime.fromisoformat(payload['created_at'].replace('Z', '+00:00'))
    if created.tzinfo is None:
        raise ValueError('기획 요청 시각에 시간대가 필요합니다.')
    if payload['planning_type'] not in ('existing_resource_based', 'preventive_new'):
        raise ValueError('기획 방식을 확인해주세요.')
    if not isinstance(payload['officer_prompt'], str) or len(payload['officer_prompt']) > 2000:
        raise ValueError('담당자 요청은 2,000자 이내여야 합니다.')
    if not isinstance(payload['notes'], list) or any(not isinstance(note, str) for note in payload['notes']):
        raise ValueError('기획 요청 참고 사항을 확인해주세요.')
    request = {key: payload[key] for key in ('target', 'risk_assessment', 'confirmed_support_needs')}
    if payload['analysis_context'] is not None:
        request['analysis_context'] = payload['analysis_context']
    validate_request(request)  # 대상·성별·위험 단계·근거 맥락의 기존 계약을 재사용한다.
    expected_example = bool((payload['risk_assessment'] or {}).get('is_example')
                            or (payload['analysis_context'] or {}).get('profile', {}).get('is_example'))
    if type(payload['has_example_context']) is not bool or payload['has_example_context'] != expected_example:
        raise ValueError('예시 분석 여부가 원래 입력과 다릅니다.')
    lookup = payload['welfare_lookup']
    fields = {'mode', 'status', 'candidate_status', 'total_candidates', 'error', 'response_routing', 'recommendation_snapshot'}
    if not isinstance(lookup, dict) or set(lookup) != fields or lookup['mode'] not in ('live', 'offline'):
        raise ValueError('복지 조회 상태를 확인해주세요.')
    if lookup['response_routing'] is not None:
        routing = ResponseRouting.model_validate(lookup['response_routing'])
        if routing.candidate_status != lookup['candidate_status']:
            raise ValueError('대응 경로와 조회 상태가 다릅니다.')
    selected = payload['selected_resources']
    if not isinstance(selected, list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in selected):
        raise ValueError('선택 자원 목록을 확인해주세요.')
    ids = [item['id'] for item in selected]
    if len(ids) != len(set(ids)):
        raise ValueError('선택 자원이 중복되었습니다.')
    snapshot = lookup['recommendation_snapshot']
    if lookup['status'] == 'completed':
        if not isinstance(snapshot, dict) or snapshot.get('schema_version') != 'welfare-0.4' or snapshot.get('mode') != lookup['mode'] or snapshot.get('is_demo') is not False:
            raise ValueError('완료된 추천 응답이 필요합니다.')
        if snapshot.get('target') != payload['target'] or snapshot.get('risk_assessment') != payload['risk_assessment'] or snapshot.get('analysis_context') != payload['analysis_context']:
            raise ValueError('추천 응답과 기획 대상·분석 맥락이 다릅니다.')
        if not isinstance(snapshot.get('review'), dict) or snapshot['review'].get('confirmed_support_needs') != payload['confirmed_support_needs']:
            raise ValueError('담당자가 확인한 지원 필요가 추천 입력과 다릅니다.')
        candidates = snapshot.get('resources')
        if not isinstance(candidates, list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] for item in candidates):
            raise ValueError('추천 후보 목록을 확인해주세요.')
        if len({item['id'] for item in candidates}) != len(candidates):
            raise ValueError('추천 후보 ID가 중복되었습니다.')
        status = 'candidates_found' if candidates else 'no_candidates_found'
        if type(lookup['total_candidates']) is not int or lookup['total_candidates'] != len(candidates) or lookup['candidate_status'] != status or lookup['error'] is not None:
            raise ValueError('후보 수와 조회 상태가 다릅니다.')
        if any(item not in candidates for item in selected):
            raise ValueError('선택 자원이 원래 추천 후보와 다릅니다.')
    elif lookup['status'] == 'unavailable':
        if snapshot is not None or lookup['total_candidates'] is not None or lookup['candidate_status'] != 'unavailable' or selected or not isinstance(lookup['error'], str) or not lookup['error']:
            raise ValueError('조회 실패를 후보 0개나 선택 자원으로 바꿀 수 없습니다.')
    else:
        raise ValueError('지원하지 않는 조회 상태입니다.')
    if payload['planning_type'] == 'existing_resource_based' and (not selected or lookup['status'] != 'completed'):
        raise ValueError('기존 자원 활용 기획에는 조회한 선택 자원이 필요합니다.')
    return deepcopy(payload)


class PlanningInbox:
    """로컬 개발용 전달함. 같은 ID의 동일 요청은 중복 저장하지 않는다."""
    def __init__(self, root):
        self.root = Path(root)
        self.lock = Lock()

    def save(self, payload):
        request = validate_planning_request(payload)
        envelope = {'schema_version': 'planning-inbox-0.1', 'status': 'awaiting_planning_agent',
                    'agent_connected': False, 'received_at': datetime.now(timezone.utc).isoformat(), 'request': request}
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / f"{request['request_id']}.json"
            if path.exists():
                previous = json.loads(path.read_text(encoding='utf-8'))
                if previous['request'] != request:
                    raise ValueError('같은 요청 ID에 다른 내용이 있습니다. 요청을 새로 준비해주세요.')
                return previous
            # 임시 파일을 같은 폴더에 작성한 후 교체하여 중간 기록을 목록에 노출하지 않는다.
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(path)
        return envelope

    def list_requests(self):
        results = []
        with self.lock:
            for path in self.root.glob('*.json'):
                try:
                    if str(UUID(path.stem)) != path.stem:
                        continue
                    envelope = json.loads(path.read_text(encoding='utf-8'))
                    validate_planning_request(envelope['request'])
                    if envelope.get('schema_version') != 'planning-inbox-0.1' or envelope['request']['request_id'] != path.stem or envelope.get('status') != 'awaiting_planning_agent' or envelope.get('agent_connected') is not False:
                        continue
                    if not isinstance(envelope.get('received_at'), str) or datetime.fromisoformat(envelope['received_at']).tzinfo is None:
                        continue
                    results.append(envelope)
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue
        return sorted(results, key=lambda item: item['received_at'], reverse=True)
