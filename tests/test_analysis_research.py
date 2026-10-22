"""질문별 검색, 부적합 자료 차단, 근거 인용과 설명 보고서 검증."""
import json
import unittest
from copy import deepcopy
from ai.analysis_agent.model import GeminiTavilyProvider, ExternalCallError
from ai.analysis_agent.research import source_scope, search_plan, FocusedSelection, check_findings, explain_bundle, validate_research_receipt
from ai.analysis_agent.workflow import run_analysis
from ai.contracts.profile import TargetProfile
from tests.test_analysis_gemini import CONFIG, dataset, model_response

TEXT = "춘천시 2025년 9월 주민등록 인구 현황은 해당 월 집계 통계표에서 확인할 수 있습니다."


class FocusedResearchTests(unittest.TestCase):
    def baseline(self):
        return run_analysis(dataset(),{},[],period="202509")

    def profile(self):
        return TargetProfile.model_validate(self.baseline()["cohorts"][-1]["profile"])

    def source(self):
        source=dict(id="S1",question_id="population",title="2025년 9월 춘천시 인구 현황",
                    snippet=TEXT,url="https://www.chuncheon.go.kr/statistics/123")
        source["scope_check"]=source_scope(source,self.profile(),"population")
        return source

    def selection(self, **changes):
        finding=dict(question_id="population",source_id="S1",quote=TEXT,
                     relevance="같은 지역과 기준월의 인구 자료 후보이며, 활동 감소 원인을 확정하지는 못합니다.")
        finding.update(changes)
        return FocusedSelection(observation_ids=["E1"],source_ids=["S1"],findings=[finding])

    def test_three_distinct_questions_and_retrospective_publication_cutoff(self):
        plans=search_plan(self.profile())
        self.assertEqual([p["question_id"] for p in plans],["population","economy","calendar"])
        self.assertEqual(len({p["payload"]["query"] for p in plans}),3)
        self.assertTrue(all(p["payload"]["end_date"]>"2025-09-30" for p in plans))
        self.assertTrue(all(p["payload"]["max_results"]==3 for p in plans))

    def test_homepage_with_matching_words_is_discovery_only(self):
        source=self.source(); source["url"]="https://www.chuncheon.go.kr/"
        scope=source_scope(source,self.profile(),"population")
        self.assertEqual(scope["status"],"discovery_only")
        self.assertFalse(scope["detail_page"])
        source["url"]="https://www.chuncheon.go.kr/index.do"
        self.assertEqual(source_scope(source,self.profile(),"population")["status"],"discovery_only")

    def test_other_period_and_region_are_not_reference_candidates(self):
        source=self.source(); source.update(title="",snippet="강남구 2024년 9월 인구 현황")
        scope=source_scope(source,self.profile(),"population")
        self.assertFalse(scope["period_text_match"])
        self.assertFalse(scope["region_text_match"])
        self.assertEqual(scope["status"],"discovery_only")

    def test_bulletin_listing_with_matching_period_is_not_a_data_table(self):
        source=self.source()
        source["snippet"] += " 총 152건의 게시물이 있습니다. 번호 제목 작성자 작성일 첨부 조회수"
        scope=source_scope(source,self.profile(),"population")
        self.assertTrue(scope["listing_page"])
        self.assertEqual(scope["status"],"discovery_only")

    def test_national_holiday_can_be_applicable_without_region_text(self):
        source=dict(url="https://astro.kasi.re.kr/calendar/2025",title="2025년 9월 공휴일",snippet="전국 공휴일 월력요항")
        self.assertEqual(source_scope(source,self.profile(),"calendar")["status"],"reference_candidate")

    def test_verbatim_quote_accepted_only_as_reference_candidate(self):
        accepted,rejected=check_findings(self.selection(),[self.source()])
        self.assertEqual(len(accepted),1)
        self.assertEqual(rejected,[])
        self.assertEqual(accepted[0]["status"],"quoted_reference_candidate")

    def test_invented_quote_rejected(self):
        accepted,rejected=check_findings(self.selection(quote="춘천시 인구가 급감하여 해당 집단의 사회적 고립이 증가하였습니다."),[self.source()])
        self.assertEqual(accepted,[])
        self.assertEqual(rejected[0]["reason"],"quote_not_in_excerpt")

    def test_homepage_cannot_be_promoted_by_model(self):
        source=self.source(); source["url"]="https://chuncheon.go.kr"
        source["scope_check"]=source_scope(source,self.profile(),"population")
        accepted,rejected=check_findings(self.selection(),[source])
        self.assertEqual(accepted,[])
        self.assertEqual(rejected[0]["reason"],"insufficient_source_scope")

    def test_wrong_question_and_unselected_source_rejected(self):
        accepted,rejected=check_findings(self.selection(question_id="economy"),[self.source()])
        self.assertEqual(rejected[0]["reason"],"question_source_mismatch")
        selection=self.selection(); selection.source_ids=[]
        accepted,rejected=check_findings(selection,[self.source()])
        self.assertEqual(rejected[0]["reason"],"unknown_or_unselected_source")

    def test_max_three_searches_and_one_model_with_new_report(self):
        calls=[]
        def transport(url,headers,body):
            calls.append((url,body))
            if "tavily" in url:
                if len(calls)==1:
                    return dict(results=[dict(url=self.source()["url"],title=self.source()["title"],content=TEXT,published_date="2025-10-01")],usage=dict(credits=1))
                return dict(results=[],usage=dict(credits=1))
            proposal=self.selection().model_dump()
            return model_response(proposal)
        before=self.baseline()
        provider=GeminiTavilyProvider(config=CONFIG,transport=transport,research_mode="focused")
        after=run_analysis(dataset(),{},[],period="202509",provider=provider,
                           model_analysis_id=before["cohorts"][-1]["analysis_id"])
        self.assertEqual(len(calls),4)
        self.assertEqual(after["execution"]["search_attempts"],3)
        self.assertEqual(after["execution"]["gemini_attempts"],1)
        self.assertEqual(before["priority_review"],after["priority_review"])
        for a,b in zip(before["cohorts"],after["cohorts"]): self.assertEqual(a["profile"],b["profile"])
        receipt=after["execution"]["model_receipts"][0]
        self.assertEqual(len(receipt["research_findings"]),1)
        self.assertTrue(receipt["sources"][0]["publication_after_target_period"])
        validate_research_receipt(receipt,self.profile())
        tampered=deepcopy(receipt)
        tampered["research_findings"][0]["quote"]="원문에 없는 문장을 만들어 통계적 인과관계가 확인되었다고 주장합니다."
        with self.assertRaises(ValueError): validate_research_receipt(tampered,self.profile())
        report=explain_bundle(after)
        self.assertIn(TEXT,report)
        self.assertIn("구체적인 보완 근거를 확보하지 못했습니다",report)
        self.assertIn("모델의 관련성 해석(별도 사실 검증 전)",report)
        self.assertEqual(after["execution"]["confirmed_llm_responses"],0)

    def test_independent_search_failures_counted_without_retry(self):
        calls=[]
        def transport(url,headers,body):
            calls.append(url)
            if "tavily" in url: raise ExternalCallError("http_503")
            return model_response(dict(observation_ids=[],hypothesis_codes=[],question_codes=[],source_ids=[],findings=[]))
        baseline=self.baseline()
        after=run_analysis(dataset(),{},[],period="202509",
            provider=GeminiTavilyProvider(config=CONFIG,transport=transport,research_mode="focused"),
            model_analysis_id=baseline["cohorts"][-1]["analysis_id"])
        self.assertEqual(len(calls),4)
        receipt=after["execution"]["model_receipts"][0]
        self.assertEqual(receipt["search_status"],"failed")
        self.assertEqual(len(receipt["research_findings"]),0)
        self.assertEqual([q["status"] for q in receipt["search_questions"]],["failed"]*3)

    def test_quota_error_stops_remaining_search_questions(self):
        calls=[]
        def transport(url,headers,body):
            calls.append(url)
            if "tavily" in url: raise ExternalCallError("http_429")
            return model_response(dict(observation_ids=[],hypothesis_codes=[],question_codes=[],source_ids=[],findings=[]))
        baseline=self.baseline()
        after=run_analysis(dataset(),{},[],period="202509",
            provider=GeminiTavilyProvider(config=CONFIG,transport=transport,research_mode="focused"),
            model_analysis_id=baseline["cohorts"][-1]["analysis_id"])
        self.assertEqual(len(calls),2)
        receipt=after["execution"]["model_receipts"][0]
        self.assertEqual(receipt["search_attempts"],1)
        self.assertEqual([q["status"] for q in receipt["search_questions"]],
                         ["failed","not_run_auth_or_quota_limit","not_run_auth_or_quota_limit"])

    def test_offline_report_does_not_claim_external_findings(self):
        report=explain_bundle(self.baseline())
        self.assertIn("외부 검색·Gemini 검토를 수행하지 않았습니다",report)

    def test_old_live_record_gets_plain_language_explanation_without_new_call(self):
        baseline=self.baseline()
        cohort=baseline["cohorts"][-1]
        baseline["execution"]["model_receipts"]=[dict(analysis_id=cohort["analysis_id"],provider="gemini",
            search_query="기존 검색",sources=[dict(title="일반 인구 홈페이지",url="https://jumin.mois.go.kr")])]
        report=explain_bundle(baseline)
        self.assertIn("일반 인구 홈페이지",report)
        self.assertIn("구체적인 보완 근거를 확보하지 못했습니다",report)

    def test_cli_rejects_partial_input_paths_before_reading_files(self):
        import sys,io
        from contextlib import redirect_stderr
        from unittest.mock import patch
        from scripts.integration.run_analysis_agent import main
        with patch.object(sys,"argv",["run_analysis_agent.py","--features","missing.csv"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error: main()
        self.assertEqual(error.exception.code,2)

    def test_cli_rejects_focused_search_in_offline_mode(self):
        import sys,io
        from contextlib import redirect_stderr
        from unittest.mock import patch
        from scripts.integration.run_analysis_agent import main
        with patch.object(sys,"argv",["run_analysis_agent.py","--research-mode","focused"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error: main()
        self.assertEqual(error.exception.code,2)


if __name__=="__main__": unittest.main()
