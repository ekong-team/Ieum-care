"""대상 프로필 → 복지 추천 요청 변환과 복지 추천 노드 검증.

핵심: 변환 결과가 장현지 님 코드의 기존 검증(validate_request)을 그대로 통과해야 한다.
외부 호출은 하지 않는다 (offline 저장 자료 또는 가짜 함수).
"""

import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from ai.contracts import TargetProfile, CauseHypothesis
from ai.nodes.context import NodeContext
from ai.nodes.welfare import recommend_existing, to_welfare_payload, to_existing_resources
from ai.welfare_agent.live_agent import AgentError, SEARCH_CACHE
from ai.welfare_agent.recommender import validate_request

FIXTURES = Path(__file__).parent / "fixtures"


def profile_data():
    return json.loads((FIXTURES / "target_profile_example.json").read_text(encoding="utf-8"))


class WelfareBridgeTests(unittest.TestCase):
    def convert(self, data):
        payload, warnings = to_welfare_payload(TargetProfile.model_validate(data), "run-test")
        validate_request(payload)  # 기존 검증 통과가 핵심
        return payload, warnings

    def test_with_complete_risk(self):
        payload, warnings = self.convert(profile_data())
        risk = payload["risk_assessment"]
        self.assertEqual(payload["target"], {"region": "춘천시", "age_group": 20, "sex": "all", "purpose": "all"})
        self.assertEqual(risk["level"], 3)
        self.assertEqual([item["type"] for item in risk["signals"]], ["consumption_decline", "movement_decline"])
        self.assertIn("외식·카페", risk["signals"][0]["description"])
        self.assertTrue(risk["is_example"])
        self.assertEqual(warnings, [])

    def test_without_risk(self):
        data = profile_data()
        data["risk"] = None
        payload, _ = self.convert(data)
        self.assertNotIn("risk_assessment", payload)

    def test_held_risk(self):
        data = profile_data()
        data["risk"] = {"level": None, "status": "held"}
        payload, _ = self.convert(data)
        self.assertIsNone(payload["risk_assessment"]["level"])
        self.assertEqual(payload["risk_assessment"]["model_version"], "manual-input")

    def test_sex_is_preserved_in_new_contract(self):
        data = profile_data()
        data["target"]["sex"] = "female"
        payload, warnings = self.convert(data)
        self.assertEqual(payload["target"]["sex"], "female")
        self.assertEqual(payload["risk_assessment"]["sex"], "female")
        self.assertEqual(payload["risk_assessment"]["schema_version"], "risk-input-0.2")
        self.assertEqual(warnings, [])

    def test_structured_evidence_and_causes_are_preserved_without_conversion(self):
        profile = TargetProfile.model_validate(profile_data())
        causes = [CauseHypothesis(code="C3_overall_withdrawal", evidence_ids=["E1", "E2"],
                                  explanation="추가 확인이 필요한 예시 가설")]
        original = profile.model_dump(mode="json")
        payload, _ = to_welfare_payload(profile, "run", causes=causes)
        validate_request(payload)
        context = payload["analysis_context"]
        self.assertEqual(context["profile"], original)
        self.assertEqual(context["profile"]["evidence"][0]["value"], -0.083)
        self.assertEqual(context["profile"]["evidence"][0]["unit"], "ratio")
        self.assertEqual(context["causes"][0]["evidence_ids"], ["E1", "E2"])
        self.assertEqual(context["causes"][0]["basis"], "hypothesis")
        context["profile"]["evidence"][0]["value"] = 999
        self.assertEqual(profile.model_dump(mode="json"), original)

    def test_invalid_cause_references_and_held_causal_claims_are_rejected(self):
        profile = TargetProfile.model_validate(profile_data())
        with self.assertRaises(ValueError):
            to_welfare_payload(profile, "run", causes=[CauseHypothesis(code="C1_mobility", evidence_ids=["E99"])])
        data = profile_data()
        data["risk"] = {"level": None, "status": "held"}
        with self.assertRaises(ValueError):
            to_welfare_payload(TargetProfile.model_validate(data), "run", causes=[CauseHypothesis(code="C1_mobility")])

    def test_contradictory_context_is_rejected(self):
        payload, _ = self.convert(profile_data())
        for changes in ({"period": "2025-11"}, {"risk": None},
                        {"target": {"region": "강남구", "age_group": 20}},
                        {"target": {"region": "춘천시", "age_group": 20, "sex": "female"}},
                        {"is_example": False}, {"signals": []},
                        {"limitations": []}):
            modified = copy.deepcopy(payload)
            modified["analysis_context"]["profile"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_request(modified)

    def test_missing_risk_keeps_observations_and_only_unknown_cause(self):
        data = profile_data()
        data["risk"] = None
        payload, _ = to_welfare_payload(TargetProfile.model_validate(data), "run",
                                        causes=[CauseHypothesis(code="C0_unknown")])
        validate_request(payload)
        self.assertNotIn("risk_assessment", payload)
        self.assertEqual(len(payload["analysis_context"]["profile"]["evidence"]), 2)


class WelfareNodeTests(unittest.TestCase):
    def setUp(self):
        self.profile = TargetProfile.model_validate(profile_data())

    def test_offline_uses_stored_catalog(self):
        ctx = NodeContext(run_id="run-test", mode="offline")
        result = recommend_existing(ctx, self.profile)
        self.assertEqual(result.status, "available")
        self.assertGreater(len(result.resources), 0)
        self.assertEqual(sum(ctx.calls.values()), 0)  # 외부 호출 없음

    def test_live_failure_does_not_stop_pipeline(self):
        def failing_call(payload):
            raise AgentError("Gemini 한도 초과", 429)

        ctx = NodeContext(run_id="run-test", mode="live")
        result = recommend_existing(ctx, self.profile, live_call=failing_call)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("한도 초과", result.reason)

    def test_live_success_maps_resources(self):
        def fake_call(payload):
            return {"resources": [{"id": "r1", "name": "가짜 자원", "purpose": "connection", "format": "모임",
                                   "age_match": "overlap", "source": {"url": "https://www.chuncheon.go.kr/x"}}],
                    "warnings": ["가짜 응답"]}

        ctx = NodeContext(run_id="run-test", mode="live")
        result = recommend_existing(ctx, self.profile, live_call=fake_call)
        self.assertEqual(result.resources[0].id, "r1")
        self.assertEqual(sum(ctx.calls.values()), 0)  # 가짜 함수는 실제 외부 호출이 아니다

    def test_planning_receives_rich_resources_and_independent_snapshot(self):
        item = {"id": "r1", "name": "자원", "purpose": "connection", "age_match": "partial",
                "description": "교류 활동", "eligibility": "회원 조건 확인", "reason": "예시 신호와 비교",
                "check": "회비 확인", "application_method": "기관 문의", "schedule": "모집 확인 필요",
                "age_ranges": [{"min": 25, "max": 39}], "isolation_relevance": "direct",
                "relevance_reason": "교류 근거 있음, 효과는 미검증",
                "source": {"url": "https://www.chuncheon.go.kr/test", "reference_year": 2026,
                           "reference_year_kind": "publication", "reference_year_evidence": "2026년 소식지"}}
        response = {"resources": [item], "warnings": ["자격 확인"], "coverage": {"status": "candidates_found"},
                    "review": {"summary": "추가 확인"}, "has_example_context": True,
                    "search_new_calls": 2, "exclusion_counts": {"closed": 1}}
        result = to_existing_resources(response, ["관측 제한"])
        self.assertEqual(result.resources[0].eligibility, item["eligibility"])
        self.assertEqual(result.resources[0].reason, item["reason"])
        self.assertEqual(result.resources[0].source, item["source"])
        self.assertEqual(result.resources[0].source_url, item["source"]["url"])
        self.assertEqual(result.resources[0].age_ranges, item["age_ranges"])
        self.assertEqual(result.recommendation, response)
        self.assertTrue(result.has_example_context)
        self.assertEqual(result.warnings, ["관측 제한", "자격 확인"])
        response["resources"][0]["source"]["reference_year"] = 1999
        self.assertEqual(result.resources[0].source["reference_year"], 2026)
        self.assertEqual(result.recommendation["resources"][0]["source"]["reference_year"], 2026)

    def test_empty_success_and_unavailable_remain_distinct(self):
        ctx = NodeContext(run_id="test", mode="live")
        result = recommend_existing(ctx, self.profile, live_call=lambda payload: {
            "resources": [], "coverage": {"status": "no_grounded_candidates"}})
        self.assertEqual(result.status, "available")
        self.assertEqual(result.resources, [])
        self.assertEqual(result.coverage["status"], "no_grounded_candidates")
        self.assertTrue(result.has_example_context)
        self.assertEqual(result.recommendation["analysis_context"]["profile"]["evidence"][0]["value"], -0.083)

    def test_existing_linkage_and_preventive_planning_are_both_offered(self):
        result = recommend_existing(NodeContext("test", "offline"), self.profile)
        routing = result.response_routing
        routes = {route.route: route for route in routing.routes}
        self.assertEqual(routing.candidate_status, "candidates_found")
        self.assertEqual(set(routes), {"existing_resource_linkage", "preventive_planning", "further_review"})
        self.assertEqual(routes["existing_resource_linkage"].resource_ids, [r.id for r in result.resources])
        self.assertTrue(routes["preventive_planning"].checks)
        self.assertTrue(routing.notes)

    def test_no_candidates_allows_preventive_planning_without_claiming_absence(self):
        before = self.profile.model_dump(mode="json")
        result = recommend_existing(NodeContext("test", "live"), self.profile,
                                    live_call=lambda p: {"resources": [], "coverage": {"status": "no_grounded_candidates"}})
        routing = result.response_routing
        routes = {route.route: route for route in routing.routes}
        self.assertEqual(routing.candidate_status, "no_candidates_found")
        self.assertEqual(set(routes), {"preventive_planning", "further_review"})
        self.assertIn("이번 조회", routes["preventive_planning"].reason)
        self.assertIn("자원 부재를 뜻하지", routes["further_review"].reason)
        self.assertEqual(self.profile.model_dump(mode="json"), before)

    def test_search_failure_still_allows_planning_draft_with_different_reason(self):
        def fail(payload):
            raise AgentError("검색 한도", 429)
        result = recommend_existing(NodeContext("test", "live"), self.profile, live_call=fail)
        routing = result.response_routing
        routes = {route.route: route for route in routing.routes}
        self.assertEqual(routing.candidate_status, "unavailable")
        self.assertEqual(set(routes), {"preventive_planning", "further_review"})
        self.assertIn("완료되지 않았지만", routes["preventive_planning"].reason)
        self.assertIsNone(result.recommendation)
        self.assertTrue(result.has_example_context)

    def test_response_routes_do_not_depend_on_or_change_risk_level(self):
        def route_at(level):
            data = profile_data()
            data["risk"]["level"] = level
            profile = TargetProfile.model_validate(data)
            result = recommend_existing(NodeContext("test", "live"), profile,
                                        live_call=lambda p: {"resources": []})
            self.assertEqual(result.recommendation["analysis_context"]["profile"]["risk"]["level"], level)
            return result.response_routing.model_dump()
        self.assertEqual(route_at(1), route_at(5))


class WelfareCallAccountingTests(unittest.TestCase):
    def setUp(self):
        self.profile = TargetProfile.model_validate(profile_data())
        SEARCH_CACHE.clear()
        self.addCleanup(SEARCH_CACHE.clear)
        config = {"key": "fake-key", "search_key": "fake-search", "model": "gemini-3.5-flash-lite"}
        patcher = patch("ai.welfare_agent.live_agent.configuration", return_value=config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def response(self, data):
        return io.BytesIO(json.dumps(data).encode())

    def local(self, count=2):
        return {"results": [{"url": f"https://www.chuncheon.go.kr/service/{i}",
                             "content": "청년 지원대상과 신청방법 안내"} for i in range(count)], "usage": {"credits": 1}}

    def judgment(self):
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": json.dumps({"summary": "예시 검증", "questions": [], "resources": []})}]}}]}

    def test_failed_gemini_and_manual_cached_retry_count_real_attempts(self):
        first, second = NodeContext("one", "live"), NodeContext("two", "live")
        responses = [self.response(self.local()), HTTPError("https://test", 503, "busy", {}, None),
                     self.response(self.judgment())]
        with patch("ai.welfare_agent.live_agent.urlopen", side_effect=responses) as send:
            failure = recommend_existing(first, self.profile)
            result = recommend_existing(second, self.profile)
        self.assertEqual(failure.status, "unavailable")
        self.assertEqual(result.status, "available")
        self.assertEqual(dict(first.calls), {"tavily": 1, "gemini": 1})
        self.assertEqual(dict(second.calls), {"gemini": 1})
        self.assertEqual(send.call_count, 3)
        self.assertTrue(result.recommendation["search_cache_hit"])

    def test_two_searches_and_gemini_failure_are_counted(self):
        national = {"results": [{"url": "https://www.bokjiro.go.kr/service", "content": "서비스 안내"}]}
        ctx = NodeContext("run", "live")
        with patch("ai.welfare_agent.live_agent.urlopen", side_effect=[self.response(self.local(1)),
                   self.response(national), HTTPError("https://test", 429, "limit", {}, None)]):
            result = recommend_existing(ctx, self.profile)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(dict(ctx.calls), {"tavily": 2, "gemini": 1})

    def test_no_key_causes_no_external_attempt(self):
        ctx = NodeContext("run", "live")
        with patch("ai.welfare_agent.live_agent.configuration", return_value={"key": "", "search_key": "", "model": "gemini-3.5-flash-lite"}), \
                patch("ai.welfare_agent.live_agent.urlopen") as send:
            result = recommend_existing(ctx, self.profile)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(sum(ctx.calls.values()), 0)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
