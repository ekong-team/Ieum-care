"""유료 API 호출 없이 검색→LLM 판단→출처 대조를 가짜 API 응답으로 검증한다."""

import copy
import io
import json
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError, URLError

from ai.welfare_agent.live_agent import recommend_live, AgentError, official_url, response_call, tavily_search, search_evidence, config_status, SEARCH_CACHE, SEARCH_CACHE_LIMIT

URL = 'https://www.chuncheon.go.kr/service-test'


def message(text):
    return {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}


def example_decision():
    return {"summary": "가짜 검색 응답을 이용한 연결 검증입니다.", "questions": ["현재 운영 여부를 확인하세요."], "resources": [{
        "name": "테스트용 자원", "organization": "테스트 기관", "region": "춘천시", "purpose": "connection",
        "description": "가상 검색 결과", "eligibility": "정확한 조건 확인 필요", "age_ranges": [{"min": 65, "max": None}],
        "format": "문의 후 이용", "schedule": "미확인", "application_method": "공식 기관 문의",
        "source_url": URL, "source_title": "가상 검색 출처", "reason": "입력 분석과의 관련성을 검토하는 예시",
        "check": "본인 의사·자격·운영 여부 확인", "availability_status": "needs_confirmation",
        "isolation_relevance": "direct", "relevance_reason": "교류 활동이 있는 가상 자료에 근거한 분류입니다.",
        "reference_year": None, "reference_year_kind": "unknown", "reference_year_evidence": None,
    }]}


class LiveAgentTests(unittest.TestCase):
    def setUp(self):
        SEARCH_CACHE.clear()
        self.addCleanup(SEARCH_CACHE.clear)
        self.payload = {"target": {"region": "춘천시", "age_group": 60, "purpose": "all"}, "risk_assessment": None}
        self.config = {"key": "fake-test-key", "model": "gemini-3.5-flash-lite", "search_key": "fake-search-key"}
        self.config_patch = patch('ai.welfare_agent.live_agent.configuration', return_value=self.config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.search = {'results': [{'url': URL, 'title': '가상 검색 출처', 'content': '가상 검색 근거'}], 'usage': {'credits': 1}}

    def run_agent(self, decision=None, search=None):
        call = Mock(return_value={'candidates': [message(json.dumps(decision or example_decision()))]})
        search_call = Mock(return_value=self.search if search is None else search)
        result = recommend_live(self.payload, call=call, search_call=search_call)
        return result, call

    def test_search_and_llm_judgment_do_not_use_fixed_catalog(self):
        search_call = Mock(return_value=self.search)
        call = Mock(return_value={'candidates': [message(json.dumps(example_decision()))]})
        with patch('ai.welfare_agent.recommender.load_catalog', side_effect=AssertionError('고정 목록 사용 금지')):
            result = recommend_live(self.payload, call=call, search_call=search_call)
        self.assertEqual(call.call_count, 1)
        search_call.assert_called_once()
        query = search_call.call_args.args[0]
        self.assertEqual(query['search_depth'], 'basic')
        self.assertFalse(query['auto_parameters'])
        self.assertFalse(query['include_answer'])
        self.assertIn('chuncheon.go.kr', query['include_domains'])
        self.assertNotIn('gangnam.go.kr', query['include_domains'])
        self.assertNotIn('tools', call.call_args.args[0])
        self.assertEqual(result['provider'], 'gemini')
        self.assertEqual(result['search_provider'], 'tavily')
        self.assertEqual(result['search_credits'], 1)
        self.assertEqual(call.call_args.args[0]['generationConfig']['responseMimeType'], 'application/json')
        self.assertEqual(call.call_args.args[0]['generationConfig']['responseSchema']['type'], 'OBJECT')
        self.assertIn('가상 검색 근거', call.call_args.args[0]['contents'][0]['parts'][0]['text'])
        self.assertEqual(result['mode'], 'live')
        self.assertIsNone(result['catalog_version'])
        self.assertEqual(result['resources'][0]['source']['url'], URL)
        self.assertEqual(result['resources'][0]['age_match'], 'partial')
        self.assertEqual(result['resources'][0]['support_basis'], 'llm_analysis_match')
        self.assertEqual(result['review']['summary'], example_decision()['summary'])

    def test_missing_key_does_not_call_provider_or_fall_back(self):
        self.config['key'] = ''
        call = Mock()
        with self.assertRaises(AgentError) as error:
            recommend_live(self.payload, call=call)
        self.assertEqual(error.exception.status, 503)
        call.assert_not_called()

    def test_economic_support_is_distinct_from_isolation_relevance(self):
        decision = example_decision()
        decision['resources'][0].update(purpose='economic', isolation_relevance='indirect',
                                        relevance_reason='생활비 지원 후보이며 교류 활동은 근거에 없습니다.')
        self.payload['target']['purpose'] = 'economic'
        result, call = self.run_agent(decision)
        self.assertEqual(result['resources'][0]['purpose'], 'economic')
        self.assertEqual(result['resources'][0]['isolation_relevance'], 'indirect')
        self.assertEqual(result['purposes']['economic'], '경제·생활 안정')
        self.assertIn('economic', call.call_args.args[0]['generationConfig']['responseSchema']['properties']['resources']['items']['properties']['purpose']['enum'])
        self.payload['target']['purpose'] = 'connection'
        self.assertEqual(self.run_agent(decision)[0]['total'], 0)

    def test_missing_risk_note_and_reader_friendly_text(self):
        decision = example_decision()
        decision['summary'] = 'risk_assessment가 null이면 지역과 연령만 참고합니다.'
        decision['resources'][0]['reason'] = 'null인 분석 결과는 사용하지 않습니다.'
        result, _ = self.run_agent(decision)
        self.assertIn('위험도 분석 결과가 연결되지 않아', result['review']['input_note'])
        self.assertNotIn('null', result['review']['summary'])
        self.assertNotIn('risk_assessment', result['review']['summary'])
        self.assertNotIn('null', result['resources'][0]['reason'])

    def test_reference_year_requires_matching_quote_from_same_source(self):
        decision = example_decision()
        decision['resources'][0].update(reference_year=2025, reference_year_kind='applicable', reference_year_evidence='2025년 기준 지원 안내')
        search = {'results': [{'url': URL, 'title': '2025년 기준 지원 안내', 'content': '대상자 안내'}]}
        result, _ = self.run_agent(decision, search)
        source = result['resources'][0]['source']
        self.assertEqual(source['reference_year'], 2025)
        self.assertEqual(source['reference_year_status'], 'past_year')
        self.assertEqual(source['reference_year_evidence'], '2025년 기준 지원 안내')
        self.assertNotEqual(source['checked_at'], '2025')
        for changes in ({'reference_year_evidence': '실제 검색 내용에 없는 2025년 안내'},
                        {'reference_year': 2026}, {'reference_year': None},
                        {'reference_year': True}, {'reference_year_evidence': None}):
            with self.subTest(changes=changes):
                modified = copy.deepcopy(decision)
                modified['resources'][0].update(changes)
                source = self.run_agent(modified, search)[0]['resources'][0]['source']
                self.assertIsNone(source['reference_year'])
                self.assertIsNone(source['reference_year_evidence'])
                self.assertEqual(source['reference_year_status'], 'unknown')

    def test_other_sources_year_cannot_be_assigned_to_resource(self):
        decision = example_decision()
        decision['resources'][0].update(reference_year=2025, reference_year_kind='applicable', reference_year_evidence='2025년 기준 지원 안내')
        search = {'results': [{'url': URL, 'content': '연도 미명시 자료'},
                              {'url': 'https://www.chuncheon.go.kr/another', 'content': '2025년 기준 지원 안내'}]}
        self.assertIsNone(self.run_agent(decision, search)[0]['resources'][0]['source']['reference_year'])

    def test_publication_year_is_preserved_separately_from_applicability(self):
        decision = example_decision()
        decision['resources'][0].update(reference_year=2026, reference_year_kind='publication',
                                        reference_year_evidence='2026년 5월 소식지')
        search = {'results': [{'url': URL, 'title': '2026년 5월 소식지', 'content': '교류 활동 안내'}]}
        source = self.run_agent(decision, search)[0]['resources'][0]['source']
        self.assertEqual(source['reference_year'], 2026)
        self.assertEqual(source['reference_year_kind'], 'publication')
        decision['resources'][0]['reference_year_kind'] = 'unknown'
        self.assertIsNone(self.run_agent(decision, search)[0]['resources'][0]['source']['reference_year'])

    def test_exclusion_counts_explain_filtered_candidates_without_repeating_claims(self):
        decision = example_decision()
        original = copy.deepcopy(decision['resources'][0])
        decision['resources'] = [{**original, 'region': '강남구'},
                                 {**original, 'age_ranges': [{'min': 20, 'max': 39}]},
                                 {**original, 'availability_status': 'closed'},
                                 {**original, 'source_url': 'https://www.chuncheon.go.kr/not-in-search'}]
        result, _ = self.run_agent(decision)
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['exclusion_counts'], {'region_mismatch': 1, 'age_mismatch': 1,
                                                     'closed': 1, 'source_not_grounded': 1})
        self.assertEqual(sum(result['exclusion_counts'].values()), result['excluded_count'])

    def test_ungrounded_or_unofficial_sources_are_excluded(self):
        for url in ('https://www.chuncheon.go.kr/not-in-search', 'https://example.com/fake', 'javascript:alert(1)'):
            with self.subTest(url=url):
                decision = example_decision()
                decision['resources'][0]['source_url'] = url
                result, _ = self.run_agent(decision)
                self.assertEqual(result['resources'], [])
                self.assertEqual(result['excluded_count'], 1)
                self.assertNotEqual(result['review']['summary'], decision['summary'])

    def test_closed_other_region_and_age_mismatch_are_excluded(self):
        for changes in ({'availability_status': 'closed'}, {'region': '강남구'}, {'age_ranges': [{'min': 20, 'max': 39}]}):
            with self.subTest(changes=changes):
                decision = example_decision()
                decision['resources'][0].update(changes)
                self.assertEqual(self.run_agent(decision)[0]['total'], 0)

    def test_missing_search_key_does_not_consume_gemini_or_search(self):
        self.config['search_key'] = ''
        call, search_call = Mock(), Mock()
        with self.assertRaises(AgentError):
            recommend_live(self.payload, call=call, search_call=search_call)
        call.assert_not_called()
        search_call.assert_not_called()

    def test_no_official_evidence_does_not_call_gemini(self):
        for search in ({'results': []}, {'results': [{'url': 'https://evil.com', 'content': 'fake'}]},
                       {'results': [{'url': URL, 'content': ''}]}, {'candidates': []}):
            call, search_call = Mock(), Mock(return_value=search)
            with self.subTest(search=search), self.assertRaises(AgentError):
                recommend_live(self.payload, call=call, search_call=search_call)
            call.assert_not_called()

    def test_invalid_judgment_is_rejected(self):
        decision = example_decision()
        decision['resources'][0]['age_ranges'] = [{'min': 80, 'max': 65}]
        with self.assertRaises(AgentError):
            self.run_agent(decision)

    def test_held_context_and_limitations_are_preserved(self):
        self.payload['risk_assessment'] = {'schema_version': 'risk-input-0.1', 'assessment_id': 'test', 'region': '춘천시',
            'age_group': 60, 'period': '2025-12', 'status': 'held', 'level': None, 'signals': [],
            'limitations': ['검증용 보류 사유'], 'model_version': 'example', 'is_example': True}
        original = copy.deepcopy(self.payload)
        result, call = self.run_agent()
        self.assertEqual(self.payload, original)
        self.assertEqual(result['risk_assessment'], original['risk_assessment'])
        self.assertEqual(result['review']['status'], 'risk_held')
        self.assertTrue(result['has_example_context'])
        self.assertIn('검증용 보류 사유', call.call_args.args[0]['contents'][0]['parts'][0]['text'])

    def test_api_transport_and_incomplete_response(self):
        response = json.dumps({'candidates': [message('test')]}).encode()
        with patch('ai.welfare_agent.live_agent.urlopen', return_value=io.BytesIO(response)) as send:
            response_call({'contents': []}, self.config)
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent')
        self.assertEqual(request.get_header('X-goog-api-key'), 'fake-test-key')
        self.assertNotIn('fake-test-key', request.full_url)
        with patch('ai.welfare_agent.live_agent.urlopen', return_value=io.BytesIO(b'{"candidates":[{"finishReason":"MAX_TOKENS"}]}')):
            with self.assertRaises(AgentError):
                response_call({'contents': []}, self.config)

    def test_quota_error_stops_without_retry(self):
        with patch('ai.welfare_agent.live_agent.urlopen', side_effect=HTTPError('https://test', 429, 'quota', {}, None)) as send:
            with self.assertRaises(AgentError) as error:
                response_call({'contents': []}, self.config)
        self.assertEqual(error.exception.status, 429)
        self.assertEqual(send.call_count, 1)

    def test_retired_model_is_reported_without_exposing_provider_message(self):
        body = json.dumps({'error': {'message': 'no longer available to new users fake-test-key'}}).encode()
        with patch('ai.welfare_agent.live_agent.urlopen', side_effect=HTTPError('https://test', 404, 'missing', {}, io.BytesIO(body))) as send:
            with self.assertRaises(AgentError) as error:
                response_call({'contents': []}, self.config)
        self.assertEqual(error.exception.status, 503)
        self.assertIn('신규 사용자', str(error.exception))
        self.assertIn('404', str(error.exception))
        self.assertNotIn('fake-test-key', str(error.exception))
        self.assertEqual(send.call_count, 1)

    def test_invalid_key_is_distinguished_from_model_error(self):
        body = json.dumps({'error': {'message': 'API key not valid. fake-test-key'}}).encode()
        with patch('ai.welfare_agent.live_agent.urlopen', side_effect=HTTPError('https://test', 400, 'invalid', {}, io.BytesIO(body))):
            with self.assertRaises(AgentError) as error:
                response_call({'contents': []}, self.config)
        self.assertIn('키가 유효하지', str(error.exception))
        self.assertNotIn('fake-test-key', str(error.exception))

    def test_provider_unavailable_is_reported_without_retry(self):
        with patch('ai.welfare_agent.live_agent.urlopen', side_effect=HTTPError('https://test', 503, 'unavailable', {}, None)) as send:
            with self.assertRaises(AgentError) as error:
                response_call({'contents': []}, self.config)
        self.assertEqual(error.exception.status, 503)
        self.assertIn('Gemini 서버', str(error.exception))
        self.assertIn('503', str(error.exception))
        self.assertEqual(error.exception.retry_after_seconds, 30)
        self.assertEqual(send.call_count, 1)

    def test_non_free_search_model_is_rejected_without_call(self):
        self.config['model'] = 'gemini-3.8-flash'
        call = Mock()
        with self.assertRaises(AgentError):
            recommend_live(self.payload, call=call)
        call.assert_not_called()

    def test_tavily_transport_separates_credentials_and_stops_on_limit(self):
        with patch('ai.welfare_agent.live_agent.urlopen', return_value=io.BytesIO(json.dumps(self.search).encode())) as send:
            tavily_search({'query': '춘천시'}, self.config)
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.tavily.com/search')
        self.assertEqual(request.get_header('Authorization'), 'Bearer fake-search-key')
        self.assertIsNone(request.get_header('X-goog-api-key'))
        self.assertNotIn('fake-search-key', request.data.decode())
        for code in (402, 429, 432, 433):
            SEARCH_CACHE.clear()
            with self.subTest(code=code), patch('ai.welfare_agent.live_agent.urlopen', side_effect=HTTPError('https://test', code, 'limit', {}, None)) as send:
                with self.assertRaises(AgentError) as error:
                    tavily_search({'query': '춘천시'}, self.config)
                self.assertEqual(error.exception.status, 429)
                self.assertEqual(send.call_count, 1)

    def test_search_is_reused_after_manual_gemini_retry(self):
        with patch('ai.welfare_agent.live_agent.urlopen', return_value=io.BytesIO(json.dumps(self.search).encode())) as send:
            failed_call = Mock(side_effect=AgentError('Gemini 일시 중단', 503, 30))
            with self.assertRaises(AgentError):
                recommend_live(self.payload, call=failed_call)
            failed_call.assert_called_once()
            call = Mock(return_value={'candidates': [message(json.dumps(example_decision()))]})
            result = recommend_live(self.payload, call=call)
        self.assertEqual(send.call_count, 1)
        self.assertTrue(result['search_cache_hit'])
        self.assertEqual(result['search_credits'], 0)
        self.assertEqual(result['resources'][0]['source']['checked_at'], result['searched_at'])
        call.assert_called_once()

    def test_search_cache_expires_and_returns_independent_data(self):
        with patch('ai.welfare_agent.live_agent.monotonic', return_value=100) as clock, patch('ai.welfare_agent.live_agent.urlopen', side_effect=lambda *a, **k: io.BytesIO(json.dumps(self.search).encode())) as send:
            first = tavily_search({'query': '검색'}, self.config)
            first['results'].clear()
            clock.return_value = 200
            second = tavily_search({'query': '검색'}, self.config)
            self.assertEqual(len(second['results']), 1)
            self.assertTrue(second['search_cache_hit'])
            clock.return_value = 401
            third = tavily_search({'query': '검색'}, self.config)
        self.assertFalse(third['search_cache_hit'])
        self.assertEqual(send.call_count, 2)

    def test_search_cache_separates_queries_credentials_and_caps_entries(self):
        with patch('ai.welfare_agent.live_agent.urlopen', side_effect=lambda *a, **k: io.BytesIO(json.dumps(self.search).encode())) as send:
            tavily_search({'query': '검색'}, self.config)
            tavily_search({'query': '다른 검색'}, self.config)
            config = {**self.config, 'search_key': 'another-fake-key'}
            tavily_search({'query': '검색'}, config)
            self.assertEqual(send.call_count, 3)
            for index in range(SEARCH_CACHE_LIMIT + 1):
                tavily_search({'query': str(index)}, config)
        self.assertLessEqual(len(SEARCH_CACHE), SEARCH_CACHE_LIMIT)
        self.assertNotIn('fake-search-key', repr(list(SEARCH_CACHE)))

    def test_search_error_does_not_call_gemini(self):
        call = Mock()
        with self.assertRaises(AgentError):
            recommend_live(self.payload, call=call, search_call=Mock(side_effect=AgentError('검색 한도', 429)))
        call.assert_not_called()

    def test_status_reports_both_credentials_without_secrets(self):
        status = config_status()
        self.assertTrue(status['configured'])
        self.config['search_key'] = ''
        self.assertFalse(config_status()['configured'])
        self.assertNotIn('fake-test-key', json.dumps(status))
        self.assertNotIn('fake-search-key', json.dumps(status))

    def test_evidence_filters_duplicates_and_caps_text(self):
        evidence = search_evidence({'results': [{'url': URL, 'content': 'a' * 7000},
                                               {'url': URL, 'content': 'duplicate'},
                                               {'url': 'https://evil.com', 'content': 'fake'}]})
        self.assertEqual(len(evidence), 1)
        self.assertEqual(len(evidence[0]['content']), 6000)

    def test_official_domain_matching_is_not_a_substring_check(self):
        for url in ('https://chuncheon.go.kr.evil.com/a', 'https://evilchuncheon.go.kr/a', 'https://user@chuncheon.go.kr/a',
                    'https://tms.bokjiro.go.kr/TMS/tracking?URL=https://example.com'):
            self.assertIsNone(official_url(url))
        self.assertIsNotNone(official_url('https://www.chuncheon.go.kr/a'))


if __name__ == '__main__':
    unittest.main()
