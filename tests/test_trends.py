"""참고 사례 검색 노드(ai/nodes/trends.py) 검증. 가짜 Tavily 응답만 쓰고 외부 호출은 하지 않는다.

확인하는 규칙:
- 검색어에는 연령 표현·원인 키워드만 들어가고 지역명·근거 수치는 들어가지 않는다. 최대 2회.
- 안전한 https URL·내용이 있는 결과만 남기고, 도메인으로 출처 등급을 정한다. 연도는 API 날짜만 쓴다.
- offline은 빈 목록. 첫 검색 실패는 노드 실패, 두 번째 실패는 첫 결과를 살리고 경고만 남긴다.
"""

from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ai.contracts import CauseHypothesis, ExistingResources, TargetProfile
from ai.graph.pipeline import Engines, PlanningInput, run_pipeline
from ai.nodes import trends
from ai.nodes.context import NodeContext
from ai.welfare_agent.live_agent import AgentError

PROFILE = TargetProfile.model_validate(json.loads(
    (Path(__file__).parent / "fixtures" / "target_profile_example.json").read_text(encoding="utf-8")))  # 춘천 20대


def planning(*codes):
    causes = [CauseHypothesis(code=code) for code in codes or ("C3_overall_withdrawal",)]
    return PlanningInput(run_id="run-trend0001", profile=PROFILE, causes=causes,
                         existing=ExistingResources(status="unavailable"), trends=[], gaps=[])


def result(url, content="청년 대상 소모임 사업 사례", **extra):
    return {"url": url, "title": "사례 제목", "content": content, **extra}


def fake_tavily(*responses):
    """요청을 기록하고 차례로 응답한다. 응답이 예외면 그 예외를 낸다."""
    def call(payload, settings):
        call.payloads.append(payload)
        response = responses[len(call.payloads) - 1]
        if isinstance(response, Exception):
            raise response
        return response
    call.payloads = []
    return call


LIVE = NodeContext(run_id="run-trend0001", mode="live")


class SearchPlanTests(unittest.TestCase):
    def test_queries_use_age_and_first_cause_only(self):
        plan = trends.search_plan(planning("C3_overall_withdrawal", "C4_prolonged"))
        self.assertEqual([stage for stage, _, _ in plan], ["domestic", "overseas"])
        domestic, overseas = plan[0][1]["query"], plan[1][1]["query"]
        self.assertIn("청년", domestic)
        self.assertIn("일상 활동 위축", domestic)       # 첫 번째 원인
        self.assertNotIn("은둔", domestic)              # 두 번째 원인은 검색하지 않는다
        self.assertIn("young adults", overseas)
        for query in (domestic, overseas):
            self.assertNotIn("춘천", query)             # 지역명 제외: 다른 곳 사례를 찾는다
            self.assertNotIn("0.083", query)            # 근거 수치 제외
        self.assertEqual(plan[0][1]["time_range"], "year")
        self.assertNotIn("time_range", plan[1][1])
        self.assertFalse(plan[0][1]["include_answer"])

    def test_every_cause_and_age_has_keywords(self):
        for code in trends.CAUSE_KO:
            self.assertIn(code, trends.CAUSE_EN)
        self.assertEqual(set(trends.AGE_KO), {10, 20, 30, 40, 50, 60})


class ParsingTests(unittest.TestCase):
    def test_grade_by_domain(self):
        cases = {"https://www.seoul.go.kr/a": "public", "https://www.cdc.gov/a": "public",
                 "https://www.kihasa.re.kr/a": "research", "https://www.snu.ac.kr/a": "research",
                 "https://www.yna.co.kr/a": "media", "https://news.example.com/a": "media",
                 "https://blog.example.com/a": "other", "https://evilgo.kr/a": "other"}
        for url, expected in cases.items():
            self.assertEqual(trends.grade(url), expected, url)

    def test_unsafe_or_empty_results_are_dropped(self):
        response = {"results": [
            result("http://www.seoul.go.kr/plain"), result("https://user:pw@www.seoul.go.kr/a"),
            result("https://www.seoul.go.kr:8443/a"), result("https://www.seoul.go.kr/empty", content="  "),
            result("https://www.seoul.go.kr/ok#section"), result("https://www.seoul.go.kr/ok"),  # 조각만 다른 중복
        ]}
        refs = trends.to_references(response, limit=5)
        self.assertEqual([r.url for r in refs], ["https://www.seoul.go.kr/ok"])

    def test_year_only_from_api_date_and_summary_trimmed(self):
        response = {"results": [result("https://a.go.kr/1", content="2019년 사업 " * 200, published_date="2026-03-01"),
                                 result("https://a.go.kr/2", content="2023년 시작한 사업")]}
        first, second = trends.to_references(response, limit=5)
        self.assertEqual((first.year, second.year), (2026, None))  # 본문의 연도는 추측하지 않는다
        self.assertLessEqual(len(first.summary), trends.SUMMARY_CHARS)

    def test_limit_per_stage(self):
        response = {"results": [result(f"https://a.go.kr/{i}") for i in range(8)]}
        self.assertEqual(len(trends.to_references(response, limit=3)), 3)


class SearchTrendsTests(unittest.TestCase):
    def test_offline_returns_empty_without_calling(self):
        call = fake_tavily()
        self.assertEqual(trends.search_trends(NodeContext(run_id="r", mode="offline"), planning(), call=call), [])
        self.assertEqual(call.payloads, [])

    def test_two_searches_merged_without_duplicates(self):
        call = fake_tavily({"results": [result("https://a.go.kr/1"), result("https://a.go.kr/2")]},
                           {"results": [result("https://a.go.kr/2"), result("https://www.oecd.org/x")]})
        refs = trends.search_trends(LIVE, planning(), call=call)
        self.assertEqual(len(call.payloads), 2)
        self.assertEqual([r.url for r in refs], ["https://a.go.kr/1", "https://a.go.kr/2", "https://www.oecd.org/x"])

    def test_first_failure_raises_and_stops(self):
        call = fake_tavily(AgentError("한도 초과", 429), {"results": []})
        with self.assertRaises(AgentError):
            trends.search_trends(LIVE, planning(), call=call)
        self.assertEqual(len(call.payloads), 1)  # 한도에 걸린 뒤 다시 두드리지 않는다

    def test_second_failure_keeps_first_results(self):
        ctx = NodeContext(run_id="r", mode="live")
        call = fake_tavily({"results": [result("https://a.go.kr/1")]}, AgentError("한도 초과", 429))
        refs = trends.search_trends(ctx, planning(), call=call)
        self.assertEqual([r.url for r in refs], ["https://a.go.kr/1"])
        self.assertTrue(any("overseas" in w for w in ctx.warnings))

    def test_missing_key_stops_before_calling(self):
        with patch.object(trends, "configuration", return_value={"key": "", "model": "", "search_key": ""}):
            with self.assertRaises(AgentError):
                trends.search_trends(NodeContext(run_id="r", mode="live"), planning())


class GraphConnectionTests(unittest.TestCase):
    def test_default_engine_and_offline_has_no_fake_urls(self):
        self.assertIs(Engines().search_trends, trends.search_trends)
        state = run_pipeline(PROFILE, mode="offline", engines=replace(Engines()), run_id="run-trend0002")
        self.assertEqual(state["trend_references"], [])  # example.org 가짜 사례가 사라졌다


if __name__ == "__main__":
    unittest.main()
