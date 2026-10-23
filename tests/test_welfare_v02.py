"""생산자 출력 → 추천 수신부 연결. 성별·보류·부분판정 보존, 외부 API는 가짜 함수로 대체."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from tests.test_analysis_agent import rows
from tests.test_welfare_live_agent import URL, message
from ai.analysis_agent.assessment import assess
from ai.analysis_agent.inputs import digest
from ai.analysis_agent.interpretation import profile_for
from ai.analysis_agent.agent import to_welfare_request
from ai.welfare_agent.recommender import validate_request, recommend, age_overlap
from ai.welfare_agent.live_agent import recommend_live, SEARCH_CACHE


def producer_requests(sex):
    data = rows(['202507', '202508', '202509'], [10000, 9000, 8000], [None, -.1, -.1], [None, -.1, -.1])
    for row in data:
        row['sex'] = sex
    for assessment in assess(data):
        profile = profile_for(assessment)
        yield to_welfare_request(dict(analysis_id=assessment['analysis_id'], assessment=assessment,
                                      profile=profile, profile_hash=digest(profile)))


class WelfareV02Tests(unittest.TestCase):
    def test_producer_output_is_accepted_for_all_sexes_and_statuses(self):
        for sex in ('all', 'male', 'female'):
            statuses = set()
            for request in producer_requests(sex):
                before = copy.deepcopy(request)
                result = recommend(request)
                statuses.add(result['risk_assessment']['status'])
                self.assertEqual(result['target']['sex'], sex)
                self.assertEqual(result['risk_assessment'], request['risk_assessment'])
                self.assertEqual(request, before)
                self.assertEqual(result['review']['confirmed_support_needs'], [])
            self.assertEqual(statuses, {'held', 'partial', 'complete'})

    def test_missing_mismatched_or_unknown_sex_and_mixed_versions_fail(self):
        request = list(producer_requests('female'))[-1]
        for where, key, value in [('target', 'sex', None), ('risk_assessment', 'sex', None),
                                  ('target', 'sex', 'male'), ('risk_assessment', 'sex', 'other'),
                                  ('risk_assessment', 'schema_version', 'risk-input-0.1')]:
            changed = copy.deepcopy(request)
            if value is None:
                changed[where].pop(key)
            else:
                changed[where][key] = value
            with self.subTest(where=where, key=key, value=value), self.assertRaises(ValueError):
                validate_request(changed)
        legacy = copy.deepcopy(request)
        legacy['risk_assessment'].pop('sex')
        legacy['risk_assessment']['schema_version'] = 'risk-input-0.1'
        with self.assertRaises(ValueError):
            validate_request(legacy)
        legacy['target'].pop('sex')
        validate_request(legacy)  # 이전 버전은 성별 미지정 합산으로만 수용한다.
        legacy['target']['sex'] = 'all'
        validate_request(legacy)  # 새 화면이 합산을 명시해도 이전 입력은 계속 지원한다.

    def test_ten_means_ten_to_nineteen_not_under_twenty(self):
        self.assertEqual(age_overlap(10, [{'min': 0, 'max': 9}]), 'none')
        self.assertEqual(age_overlap(10, [{'min': 10, 'max': 19}]), 'overlap')
        self.assertEqual(age_overlap(10, [{'min': 15, 'max': 19}]), 'partial')

    def test_sex_reaches_gemini_and_response_without_creating_needs(self):
        SEARCH_CACHE.clear()
        self.addCleanup(SEARCH_CACHE.clear)
        request = list(producer_requests('female'))[-1]
        config = {'key': 'fake-test', 'search_key': 'fake-search', 'model': 'gemini-3.5-flash-lite'}
        search = Mock(return_value={'results': [{'url': URL, 'title': '공식 안내', 'content': '대상 및 신청 안내'}]})
        call = Mock(return_value={'candidates': [message(json.dumps({'summary': '근거 확인 필요', 'questions': [], 'resources': []}))]})
        with patch('ai.welfare_agent.live_agent.configuration', return_value=config):
            result = recommend_live(request, call=call, search_call=search)
        context = json.loads(call.call_args.args[0]['contents'][0]['parts'][0]['text'])['context']
        self.assertEqual(context['target']['sex'], 'female')
        self.assertEqual(context['risk_assessment'], request['risk_assessment'])
        self.assertEqual(context['confirmed_support_needs'], [])
        self.assertEqual(result['target']['sex'], 'female')
        self.assertEqual(result['risk_assessment']['sex'], 'female')


if __name__ == '__main__':
    unittest.main()
