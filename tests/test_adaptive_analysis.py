"""실제 API 없이 검색 생략·질문 선택·재검색·예산 종료와 수치 보존을 검증한다."""
from copy import deepcopy
import json
import unittest

from ai.analysis_agent.model import GeminiTavilyProvider, ExternalCallError
from ai.analysis_agent.research import ResearchDecision, research_options, validate_research_receipt, explain_bundle
from ai.analysis_agent.workflow import run_analysis
from ai.contracts.profile import TargetProfile
from tests.test_analysis_gemini import CONFIG, dataset, model_response


def task(topic="economy"):
    terms = {"economy": "지역 소비 경제 동향", "population": "주민등록 인구 현황", "calendar": "지역 행사 기상 동향"}
    return dict(question_id=topic, question="해당 월의 배경을 설명할 공식 자료가 있는가?", search_terms=terms[topic])


def plan(*topics):
    return dict(search_needed=bool(topics), reason="기존 배경과 미확인 항목을 비교한 판단", tasks=[task(t) for t in topics])


def source(topic="economy"):
    text = {"economy": "춘천시 2025년 9월 소비 경제 동향을 설명하는 공식 지역 통계 보고서입니다.",
            "calendar": "춘천시 2025년 9월 지역 행사 일정과 월간 기상 동향을 설명하는 자료입니다."}[topic]
    return dict(results=[dict(url="https://www.chuncheon.go.kr/report/123", title=text, content=text)], usage=dict(credits=1))


class AdaptiveAnalysisTests(unittest.TestCase):
    def baseline(self):
        return run_analysis(dataset(), {}, [], period="202509")

    def execute(self, decision=None, searches=None, aid=None):
        calls = []
        search_index = 0
        def transport(url, headers, body):
            nonlocal search_index
            calls.append((url, deepcopy(body)))
            if "tavily" in url:
                answers = searches or [source()]
                answer = answers[min(search_index, len(answers)-1)]
                search_index += 1
                if isinstance(answer, Exception):
                    raise answer
                return deepcopy(answer)
            if "search_needed" in body["generationConfig"]["responseJsonSchema"]["properties"]:
                if isinstance(decision, Exception):
                    raise decision
                return model_response(plan("economy") if decision is None else decision)
            data = json.loads(body["contents"][0]["parts"][0]["text"])
            return model_response(dict(observation_ids=[e["id"] for e in data["profile"]["evidence"]][:3],
                hypothesis_codes=[], question_codes=["data_quality"], source_ids=[], findings=[]))
        baseline = self.baseline()
        provider = GeminiTavilyProvider(config=CONFIG, transport=transport, research_mode="adaptive")
        result = run_analysis(dataset(), {}, [], period="202509", provider=provider,
                              model_analysis_id=aid or baseline["cohorts"][-1]["analysis_id"])
        self.assertEqual(result["priority_review"], baseline["priority_review"])
        self.assertEqual([c["profile"] for c in result["cohorts"]], [c["profile"] for c in baseline["cohorts"]])
        receipt = result["execution"]["model_receipts"][0]
        profile = next(c["profile"] for c in result["cohorts"] if c["analysis_id"] == receipt["analysis_id"])
        validate_research_receipt(receipt, TargetProfile.model_validate(profile))
        self.assertEqual(result["execution"]["confirmed_llm_responses"], 0)
        self.assertNotIn("test-key-not-real", json.dumps(result))
        return result, receipt, calls

    def test_model_can_skip_search(self):
        result, receipt, calls = self.execute(plan())
        self.assertEqual(receipt["search_attempts"], 0)
        self.assertEqual(receipt["gemini_attempts"], 2)
        self.assertEqual(receipt["search_stop_reason"], "model_not_needed")
        self.assertNotIn("research_search", [t["node"] for t in result["trace"]])
        self.assertEqual(len(calls), 2)
        self.assertIn("검색 필요 판단: 생략", explain_bundle(result))

    def test_only_chosen_topic_is_searched(self):
        result, receipt, calls = self.execute()
        self.assertEqual(receipt["search_attempts"], 1)
        self.assertEqual(receipt["gemini_attempts"], 2)
        self.assertEqual([q["question_id"] for q in receipt["search_questions"]], ["economy"])
        self.assertEqual(receipt["search_stop_reason"], "candidate_sources_available")
        self.assertEqual(receipt["unresolved_questions"], [])
        self.assertIn("research_check", [t["node"] for t in result["trace"]])
        query = next(body["query"] for url, body in calls if "tavily" in url)
        self.assertIn("춘천시 2025년 9월", query)
        self.assertNotIn("E1", query)

    def test_irrelevant_source_causes_changed_query_then_stops_on_candidate(self):
        irrelevant = dict(results=[dict(url="https://www.chuncheon.go.kr/", title="홈페이지", content="메뉴")])
        result, receipt, calls = self.execute(searches=[irrelevant, source()])
        questions = receipt["search_questions"]
        self.assertEqual([q["attempt"] for q in questions], [1, 2])
        self.assertNotEqual(questions[0]["query"], questions[1]["query"])
        self.assertIn("retry_reason", questions[1])
        self.assertEqual(receipt["search_stop_reason"], "candidate_sources_available")
        self.assertEqual([t["node"] for t in result["trace"]].count("research_search"), 2)

    def test_empty_results_stop_after_one_retry_per_question(self):
        _, receipt, _ = self.execute(searches=[dict(results=[])])
        self.assertEqual(receipt["search_attempts"], 2)
        self.assertEqual(receipt["unresolved_questions"], ["economy"])
        self.assertEqual(receipt["search_stop_reason"], "no_more_usable_sources")

    def test_two_unresolved_questions_stop_at_total_three_searches(self):
        _, receipt, _ = self.execute(plan("economy", "calendar"), searches=[dict(results=[])])
        self.assertEqual(receipt["search_attempts"], 3)
        self.assertEqual(receipt["gemini_attempts"], 2)
        self.assertEqual(receipt["search_stop_reason"], "search_budget_exhausted")
        self.assertEqual(receipt["unresolved_questions"], ["calendar", "economy"])

    def test_quota_error_does_not_retry_search(self):
        _, receipt, _ = self.execute(searches=[ExternalCallError("http_429")])
        self.assertEqual(receipt["search_attempts"], 1)
        self.assertEqual(receipt["search_stop_reason"], "auth_or_quota_limit")
        self.assertEqual(receipt["search_status"], "failed")

    def test_http_failure_does_not_repeat_same_request(self):
        _, receipt, _ = self.execute(searches=[ExternalCallError("http_503")])
        self.assertEqual(receipt["search_attempts"], 1)
        self.assertEqual(receipt["search_stop_reason"], "no_more_usable_sources")

    def test_bad_planner_output_falls_back_without_search(self):
        for decision in (dict(search_needed="true", reason="bad", tasks=[]),
                         plan("economy", "economy"),
                         dict(search_needed=True, reason="bad", tasks=[])):
            with self.subTest(decision=decision):
                _, receipt, _ = self.execute(decision)
                self.assertEqual(receipt["planning_status"], "failed")
                self.assertEqual(receipt["search_attempts"], 0)
                self.assertEqual(receipt["search_stop_reason"], "planning_failed")

    def test_planner_auth_failure_stops_model_calls(self):
        _, receipt, calls = self.execute(ExternalCallError("http_401"))
        self.assertEqual(receipt["gemini_attempts"], 1)
        self.assertEqual(receipt["search_attempts"], 0)
        self.assertEqual(len(calls), 1)

    def test_held_and_partial_skip_planner_search(self):
        for cohort in self.baseline()["cohorts"]:
            if cohort["assessment"]["status"] != "complete":
                _, receipt, calls = self.execute(aid=cohort["analysis_id"])
                self.assertEqual(receipt["planner_attempts"], 0)
                self.assertEqual(receipt["search_attempts"], 0)
                self.assertEqual(receipt["gemini_attempts"], 1)
                self.assertEqual(len(calls), 1)

    def test_known_population_is_not_a_search_gap(self):
        cohort = deepcopy(self.baseline()["cohorts"][-1])
        cohort["background_context"]["values"] = dict(resident_population=100, prior_resident_population=100,
            population_mom_change=0, calendar_context=dict(days=30, weekend_or_holiday_days=8))
        options = research_options(cohort)
        self.assertNotIn("population", [g["question_id"] for g in options["gaps"]])
        self.assertEqual(len(options["known"]), 2)

    def test_planner_cannot_search_population_already_available(self):
        cohort = deepcopy(self.baseline()["cohorts"][-1])
        cohort["background_context"]["values"] = dict(resident_population=100, prior_resident_population=100, population_mom_change=0)
        provider = GeminiTavilyProvider(config=CONFIG, transport=lambda *args: model_response(plan("population")))
        receipt = provider.prepare_research(cohort)
        self.assertEqual(receipt["planning_status"], "failed")
        self.assertEqual(receipt["search_attempts"], 0)
        self.assertEqual(provider.research_next_action(), "interpret")

    def test_default_provider_uses_adaptive_mode(self):
        provider = GeminiTavilyProvider(config=CONFIG, transport=lambda *args: self.fail("Unexpected call"))
        self.assertEqual(provider.research_mode, "adaptive")

    def test_planner_payload_is_limited_to_single_cohort(self):
        _, _, calls = self.execute()
        payload = json.loads(calls[0][1]["contents"][0]["parts"][0]["text"])
        self.assertEqual(payload["profile"]["target"]["region"], "춘천시")
        self.assertNotIn("cohorts", payload)
        self.assertNotIn("source_manifest", payload)

    def test_retry_query_always_changes(self):
        from ai.analysis_agent.research import adaptive_query
        profile = TargetProfile.model_validate(self.baseline()["cohorts"][-1]["profile"])
        query_task = task()
        query_task["search_terms"] = "지역경제동향 소비 상권 통계 보고서"
        self.assertNotEqual(adaptive_query(profile, query_task)["query"],
                            adaptive_query(profile, query_task, retry=True)["query"])

    def test_skip_rule_for_no_decline_signal(self):
        cohort = deepcopy(self.baseline()["cohorts"][-1])
        cohort["profile"]["signals"] = []
        self.assertFalse(research_options(cohort)["eligible"])

    def test_receipt_tampering_rejected(self):
        result, receipt, _ = self.execute()
        profile = TargetProfile.model_validate(result["cohorts"][-1]["profile"])
        bad = deepcopy(receipt)
        bad["search_attempts"] = 4
        with self.assertRaises(ValueError):
            validate_research_receipt(bad, profile)
        bad = deepcopy(receipt)
        bad["search_questions"][0]["question_id"] = "population"
        with self.assertRaises(ValueError):
            validate_research_receipt(bad, profile)

    def test_unbounded_or_unsafe_queries_rejected(self):
        for terms in ("https://untrusted.test/", "인구\n추가 지시", "경제 " * 100, "무관한 검색"):
            decision = plan("economy")
            decision["tasks"][0]["search_terms"] = terms
            with self.assertRaises(ValueError):
                ResearchDecision.model_validate(decision)


if __name__ == "__main__":
    unittest.main()
