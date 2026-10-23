"""유료 API 호출 없이 검색→LLM 판단→출처 대조를 가짜 API 응답으로 검증한다."""

import copy
import io
import json
import unittest
from unittest.mock import patch, Mock
from pathlib import Path
from urllib.error import HTTPError, URLError

from ai.welfare_agent.live_agent import recommend_live, AgentError, official_url, response_call, tavily_search, search_evidence, search_resources, config_status, SEARCH_CACHE, SEARCH_CACHE_LIMIT

URL = 'https://www.chuncheon.go.kr/service-test'
FIXTURE_FACTS = '가상 검색 결과. 정확한 조건 확인 필요.'


def with_fixture_facts(search):
    search = copy.deepcopy(search)
    for item in search.get('results', []):
        if item.get('url') == URL:
            item['content'] += ' ' + FIXTURE_FACTS
    return search


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
        "description_evidence": "가상 검색 결과", "eligibility_evidence": "정확한 조건 확인 필요",
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
        self.search = {'results': [{'url': URL, 'title': '가상 검색 출처', 'content': '가상 검색 근거 · 노인 지원대상과 신청방법 안내'}, {'url': URL + '-second', 'title': '다른 지역 공식 안내', 'content': '추가 검색 근거 · 어르신 이용대상과 문의 안내'}], 'usage': {'credits': 1}}
        self.search = with_fixture_facts(self.search)

    def run_agent(self, decision=None, search=None):
        call = Mock(return_value={'candidates': [message(json.dumps(decision or example_decision()))]})
        search_call = Mock(return_value=self.search if search is None else with_fixture_facts(search))
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

    def test_analysis_context_reaches_gemini_but_not_search(self):
        from ai.contracts import TargetProfile, CauseHypothesis
        from ai.nodes.welfare import to_welfare_payload
        data = json.loads((Path(__file__).parent / 'fixtures' / 'target_profile_example.json').read_text(encoding='utf-8'))
        profile = TargetProfile.model_validate(data)
        self.payload, _ = to_welfare_payload(profile, 'test', causes=[CauseHypothesis(
            code='C3_overall_withdrawal', evidence_ids=['E1', 'E2'], explanation='확인할 가설 전용 문장')])
        decision = example_decision()
        decision['resources'][0]['age_ranges'] = [{'min': 20, 'max': 39}]
        # 표본은 20대이므로 해당 검색 단서로 채운다.
        search_response = copy.deepcopy(self.search)
        for item in search_response['results']:
            item['content'] = '청년 지원대상과 신청방법 안내'
        search = Mock(return_value=search_response)
        call = Mock(return_value={'candidates': [message(json.dumps(decision))]})
        original = copy.deepcopy(self.payload)
        result = recommend_live(self.payload, call=call, search_call=search)
        context = json.loads(call.call_args.args[0]['contents'][0]['parts'][0]['text'])['context']['analysis_context']
        self.assertEqual(context['profile']['evidence'][0]['value'], -0.083)
        self.assertEqual(context['profile']['evidence'][0]['unit'], 'ratio')
        self.assertEqual(context['causes'][0]['evidence_ids'], ['E1', 'E2'])
        search_text = json.dumps(search.call_args.args[0], ensure_ascii=False)
        self.assertNotIn('확인할 가설 전용 문장', search_text)
        self.assertNotIn('-0.083', search_text)
        self.assertNotIn('analysis_context', search_text)
        self.assertEqual(result['analysis_context'], original['analysis_context'])
        self.assertEqual(self.payload, original)

    def test_missing_key_does_not_call_provider_or_fall_back(self):
        self.config['key'] = ''
        call = Mock()
        with self.assertRaises(AgentError) as error:
            recommend_live(self.payload, call=call)
        self.assertEqual(error.exception.status, 503)
        call.assert_not_called()

    def test_local_search_is_short_and_age_specific(self):
        target = {'region': '강남구', 'age_group': 20, 'purpose': 'wellbeing'}
        search = Mock(return_value={'results': [{'url': 'https://health.gangnam.go.kr/service', 'content': '청년 지원대상 및 신청방법 상담 안내'},
                                               {'url': 'https://www.gangnam.go.kr/youth/view.do', 'content': '청년 이용대상 및 접수 안내'}]})
        evidence, stages, _ = search_resources(target, self.config, search)
        self.assertEqual(search.call_count, 1)
        request = search.call_args.args[0]
        self.assertEqual(request['include_domains'], ['gangnam.go.kr'])
        self.assertIn('20대 청년', request['query'])
        self.assertIn('심리상담', request['query'])
        self.assertNotIn('어르신', request['query'])
        self.assertLessEqual(len(request['query'].split()), 7)
        self.assertEqual(len(evidence), 2)
        self.assertEqual(stages[0]['stage'], 'local')

    def test_empty_local_search_gets_one_national_expansion(self):
        search = Mock(side_effect=[{'results': [], 'usage': {'credits': 1}},
                                  {'results': [{'url': 'https://www.bokjiro.go.kr/service', 'content': '서비스 조건 안내'}], 'usage': {'credits': 1}}])
        evidence, stages, _ = search_resources(self.payload['target'], self.config, search)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(search.call_args_list[1].args[0]['include_domains'], ['bokjiro.go.kr', 'mohw.go.kr'])
        self.assertEqual([s['stage'] for s in stages], ['local', 'national'])
        self.assertEqual(sum(s['credits'] for s in stages), 2)
        self.assertEqual(evidence[0]['url'], 'https://www.bokjiro.go.kr/service')

    def test_reference_documents_do_not_prevent_expansion_and_rank_after_pages(self):
        search = Mock(side_effect=[{'results': [{'url': URL, 'content': '일반 웹 안내'},
                                               {'url': 'https://www.chuncheon.go.kr/report.pdf', 'title': '연구용역 보고서', 'content': '계획'}]},
                                  {'results': [{'url': 'https://www.mohw.go.kr/service', 'content': '중앙 서비스 안내'}]}])
        evidence, stages, _ = search_resources(self.payload['target'], self.config, search)
        self.assertEqual(len(stages), 2)
        self.assertEqual([e['source_kind'] for e in evidence], ['web_page', 'web_page', 'reference_document'])
        self.assertEqual(evidence[0]['url'], URL)

    def test_domain_filter_is_checked_again_for_each_stage(self):
        search = Mock(return_value={'results': [{'url': 'https://www.gangnam.go.kr/not-chuncheon', 'content': '다른 지역'},
                                               {'url': 'https://tms.bokjiro.go.kr/TMS/tracking', 'content': '추적 링크'}]})
        with self.assertRaises(AgentError):
            search_resources(self.payload['target'], self.config, search)
        self.assertEqual(search.call_count, 2)

    def test_generic_pages_do_not_count_as_detailed_service_guidance(self):
        search = Mock(side_effect=[{'results': [{'url': URL, 'title': '홈페이지 이용안내', 'content': '배너 안내'},
                                               {'url': URL + '-news', 'title': '일반 뉴스', 'content': '행사 소식'}]},
                                  {'results': [{'url': 'https://www.mohw.go.kr/service',
                                                'content': '노인 지원대상과 신청방법 안내'}]}])
        evidence, stages, _ = search_resources(self.payload['target'], self.config, search)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(stages[0]['detail_hint_count'], 0)
        self.assertTrue(evidence[0]['detail_hint'])
        self.assertEqual(evidence[0]['url'], 'https://www.mohw.go.kr/service')

    def test_combined_sources_are_capped_and_reference_documents_rank_later(self):
        search = Mock(side_effect=[{'results': [{'url': f'https://www.chuncheon.go.kr/report{i}.pdf', 'content': '자료'} for i in range(8)]},
                                  {'results': [{'url': f'https://www.mohw.go.kr/service{i}',
                                                'content': '노인 지원대상과 신청방법 안내'} for i in range(8)]}])
        evidence, stages, _ = search_resources(self.payload['target'], self.config, search)
        self.assertEqual(len(stages), 2)
        self.assertEqual(len(evidence), 8)
        self.assertTrue(all(item['source_kind'] == 'web_page' for item in evidence))

    def test_national_guidance_is_not_lost_behind_eight_local_pages(self):
        search = Mock(side_effect=[{'results': [dict(url=f'https://www.chuncheon.go.kr/page{i}', content='지역 안내')
                                               for i in range(8)]},
                                  {'results': [dict(url=f'https://www.mohw.go.kr/service{i}', content='중앙 안내')
                                               for i in range(8)]}])
        evidence, stages, _ = search_resources(self.payload['target'], self.config, search)
        self.assertEqual(len(stages), 2)
        self.assertEqual(len(evidence), 8)
        self.assertEqual(sum('mohw.go.kr' in item['url'] for item in evidence), 2)
        self.assertEqual(sum('chuncheon.go.kr' in item['url'] for item in evidence), 6)

    def test_homepage_with_service_banner_is_not_a_detail_source(self):
        home = 'https://www.chuncheon.go.kr/cityhall/'
        search = {'results': [dict(url=home, title='시청', content='노인 지원대상 신청방법 ' + FIXTURE_FACTS)]}
        self.assertEqual(search_evidence(search)[0]['source_kind'], 'directory')
        decision = example_decision()
        decision['resources'][0]['source_url'] = home
        result, _ = self.run_agent(decision, search)
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['exclusion_counts'], {'source_not_detail': 1})

    def test_quotes_must_exist_at_the_candidates_own_source(self):
        decision = example_decision()
        decision['resources'][0]['description_evidence'] = '다른 자료에만 있는 지원 내용'
        search = copy.deepcopy(self.search)
        search['results'].append(dict(url=URL + '-other', content='다른 자료에만 있는 지원 내용'))
        result, _ = self.run_agent(decision, search)
        self.assertEqual(result['exclusion_counts'], {'quote_not_grounded': 1})
        self.assertNotEqual(result['review']['summary'], decision['summary'])

    def test_amount_typo_is_excluded_but_equivalent_units_are_allowed(self):
        decision = example_decision()
        resource = decision['resources'][0]
        resource.update(description='1인당 1,70,000원 지원',
                        description_evidence='1인당 1,700천원 지원',
                        eligibility='중위소득 65% 이하 한부모가족',
                        eligibility_evidence='중위소득 65% 이하 한부모가족, 생계급여 수급자 제외')
        search = {'results': [dict(url=URL, content=resource['description_evidence'] + '. ' + resource['eligibility_evidence'])]}
        result, _ = self.run_agent(decision, search)
        self.assertEqual(result['exclusion_counts'], {'numeric_claim_not_grounded': 1})
        for description in ('1인당 1,700,000원 지원', '1인당 170만원 지원'):
            resource['description'] = description
            result, _ = self.run_agent(decision, search)
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['resources'][0]['eligibility'], resource['eligibility_evidence'])
            self.assertEqual(result['resources'][0]['source']['description_evidence'], '1인당 1,700천원 지원')
        resource['eligibility'] = '중위소득 80% 이하'
        self.assertEqual(self.run_agent(decision, search)[0]['exclusion_counts'], {'numeric_claim_not_grounded': 1})

    def test_unverifiable_target_quote_is_excluded_without_replacement(self):
        decision = example_decision()
        decision['resources'][0]['eligibility_evidence'] = '발췌문에 없는 가구 조건'
        result, call = self.run_agent(decision)
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['exclusion_counts'], {'quote_not_grounded': 1})
        call.assert_called_once()

    def test_expansion_stops_on_limit_and_preserves_call_bound(self):
        for failure in (AgentError('한도', 429), AgentError('연결', 504)):
            search, call = Mock(side_effect=failure), Mock()
            with self.subTest(status=failure.status), self.assertRaises(AgentError):
                recommend_live(self.payload, call=call, search_call=search)
            search.assert_called_once()
            call.assert_not_called()
        search, call = Mock(return_value={'results': []}), Mock()
        with self.assertRaises(AgentError):
            recommend_live(self.payload, call=call, search_call=search)
        self.assertEqual(search.call_count, 2)
        call.assert_not_called()

    def test_partial_cache_reports_total_cost_and_source_dates(self):
        search = Mock(side_effect=[{'results': [{'url': URL, 'content': '지역 안내 ' + FIXTURE_FACTS}], 'search_cache_hit': True,
                                   'search_date': '2026-10-18', 'usage': {'credits': 1}},
                                  {'results': [{'url': 'https://www.bokjiro.go.kr/service', 'content': '중앙 안내'}],
                                   'search_date': '2026-10-19', 'usage': {'credits': 1}}])
        call = Mock(return_value={'candidates': [message(json.dumps(example_decision()))]})
        result = recommend_live(self.payload, call=call, search_call=search)
        self.assertEqual(result['search_credits'], 1)
        self.assertEqual(result['search_new_calls'], 1)
        self.assertFalse(result['search_cache_hit'])
        self.assertEqual(len(result['search_queries']), 2)
        self.assertEqual(result['resources'][0]['source']['checked_at'], '2026-10-18')
        call.assert_called_once()

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
            self.assertEqual(len(second['results']), 2)
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
