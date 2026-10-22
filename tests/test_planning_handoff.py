"""기획 전달함 검증·저장·HTTP 흐름. 외부 API와 가짜 기획 생성은 호출하지 않는다."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from ai.welfare_agent.planning_handoff import PlanningInbox, validate_planning_request
from ai.welfare_agent.recommender import recommend
from backend.server import create_server


def planning_fixture():
    target = {'region': '춘천시', 'age_group': 60, 'sex': 'female', 'purpose': 'all'}
    result = {**recommend({'target': target, 'confirmed_support_needs': []}),
              'schema_version': 'welfare-0.4', 'mode': 'offline'}
    assert result['resources']
    return {'schema_version': 'planning-request-0.1', 'request_id': str(uuid4()),
            'created_at': datetime.now(timezone.utc).isoformat(), 'planning_type': 'existing_resource_based',
            'target': target, 'officer_prompt': '소규모 관계 형성 활동을 검토해주세요.',
            'confirmed_support_needs': [], 'risk_assessment': None, 'analysis_context': None,
            'has_example_context': False, 'selected_resources': result['resources'][:1],
            'welfare_lookup': {'mode': 'offline', 'status': 'completed', 'candidate_status': 'candidates_found',
                              'total_candidates': len(result['resources']), 'error': None,
                              'response_routing': None, 'recommendation_snapshot': result}, 'notes': []}


class PlanningHandoffTests(unittest.TestCase):
    def test_actual_analysis_context_and_sex_are_preserved(self):
        from tests.test_welfare_analysis_input import bundle_fixture
        from ai.welfare_agent.analysis_input import prepare_analysis_inputs
        source = prepare_analysis_inputs(bundle_fixture())['entries'][0]['request']
        result = {**recommend(source), 'schema_version': 'welfare-0.4', 'mode': 'offline'}
        request = planning_fixture()
        for key in ('target', 'risk_assessment', 'analysis_context', 'confirmed_support_needs'):
            request[key] = deepcopy(source[key])
        request.update(planning_type='preventive_new', selected_resources=[], has_example_context=result['has_example_context'])
        request['welfare_lookup'].update(recommendation_snapshot=result, total_candidates=len(result['resources']),
            candidate_status='candidates_found' if result['resources'] else 'no_candidates_found')
        saved = validate_planning_request(request)
        self.assertEqual(saved['analysis_context'], source['analysis_context'])
        self.assertEqual(saved['risk_assessment'], source['risk_assessment'])
        self.assertEqual(saved['target']['sex'], 'female')
        request['analysis_context']['profile']['target']['sex'] = 'male'
        with self.assertRaises(ValueError):
            validate_planning_request(request)

    def test_original_prompt_target_source_preserved_and_copy_returned(self):
        request = planning_fixture()
        result = validate_planning_request(request)
        self.assertEqual(result, request)
        result['selected_resources'][0]['name'] = 'changed'
        self.assertNotEqual(result, request)

    def test_selected_resource_identity_and_snapshot_context_must_match(self):
        for change in ('target', 'resource', 'total', 'example'):
            with self.subTest(change=change):
                request = deepcopy(planning_fixture())
                if change == 'target':
                    request['target'] = {**request['target'], 'sex': 'male'}
                elif change == 'resource':
                    request['selected_resources'] = [{**request['selected_resources'][0], 'name': 'changed'}]
                elif change == 'total':
                    request['welfare_lookup']['total_candidates'] = 0
                else:
                    request['has_example_context'] = True
                with self.assertRaises(ValueError):
                    validate_planning_request(request)

    def test_successful_zero_and_failed_lookup_remain_distinct_preventive_requests(self):
        request = planning_fixture()
        request['planning_type'] = 'preventive_new'
        request['selected_resources'] = []
        lookup = request['welfare_lookup']
        lookup.update(total_candidates=0, candidate_status='no_candidates_found')
        lookup['recommendation_snapshot']['resources'] = []
        self.assertEqual(validate_planning_request(request)['welfare_lookup']['total_candidates'], 0)
        lookup.update(status='unavailable', total_candidates=None, candidate_status='unavailable', error='HTTP 503', recommendation_snapshot=None)
        self.assertIsNone(validate_planning_request(request)['welfare_lookup']['total_candidates'])
        request['planning_type'] = 'existing_resource_based'
        with self.assertRaises(ValueError):
            validate_planning_request(request)

    def test_prompt_uuid_and_duplicate_selections_rejected(self):
        for change in ('prompt', 'uuid', 'duplicate'):
            request = planning_fixture()
            if change == 'prompt':
                request['officer_prompt'] = 'x' * 2001
            elif change == 'uuid':
                request['request_id'] = '../outside'
            else:
                request['selected_resources'] *= 2
            with self.assertRaises(ValueError):
                validate_planning_request(request)

    def test_disk_restart_idempotency_and_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            request = planning_fixture()
            inbox = PlanningInbox(temporary)
            saved = inbox.save(request)
            self.assertEqual(inbox.save(request), saved)
            restored = PlanningInbox(temporary).list_requests()
            self.assertEqual(restored, [saved])
            self.assertFalse(saved['agent_connected'])
            self.assertEqual(saved['status'], 'awaiting_planning_agent')
            request['officer_prompt'] = 'different'
            with self.assertRaises(ValueError):
                inbox.save(request)
            (Path(temporary) / f'{uuid4()}.json').write_text('{bad', encoding='utf-8')
            self.assertEqual(len(inbox.list_requests()), 1)

    def test_local_http_post_and_get_and_invalid_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = create_server(0, planning_root=temporary)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}/api/planning/requests'
            try:
                request = planning_fixture()
                def post(data):
                    return urlopen(Request(url, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'}), timeout=5)
                with post(request) as response:
                    self.assertEqual(json.load(response)['request'], request)
                with urlopen(url, timeout=5) as response:
                    self.assertEqual(json.load(response)['requests'][0]['request'], request)
                with self.assertRaises(HTTPError) as caught:
                    post({'request_id': '../bad'})
                self.assertEqual(caught.exception.code, 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
