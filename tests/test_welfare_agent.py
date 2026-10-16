"""공식 자원 후보의 필터·연령 구간·출처·운영 상태 및 HTTP 연결 검증."""

import copy
from http.client import HTTPConnection
import json
from pathlib import Path
from threading import Thread
import unittest
from unittest.mock import patch

from ai.welfare_agent.recommender import recommend, age_overlap, load_catalog, validate_request
from backend.server import create_server
from ai.welfare_agent.live_agent import AgentError


def risk_example():
    return {"schema_version": "risk-input-0.1", "assessment_id": "example-only",
            "region": "춘천시", "age_group": 60, "period": "2025-12", "status": "complete", "level": 3,
            "signals": [{"type": "movement_decline", "description": "연결 검증용 예시 이동 감소"}],
            "limitations": ["실제 결과가 아닌 예시"], "model_version": "example-v1", "is_example": True}


class WelfareAgentTests(unittest.TestCase):
    def setUp(self):
        self.payload = {"target": {"region": "춘천시", "age_group": 60, "purpose": "all"}, "risk_assessment": None}

    def test_region_and_provenance(self):
        result = recommend(self.payload)
        self.assertEqual(result["total"], 4)
        self.assertFalse(result["is_demo"])
        self.assertIsNone(result["risk_assessment"])
        self.assertTrue(result["warnings"])
        for item in result["resources"]:
            self.assertEqual(item["region"], "춘천시")
            self.assertEqual(item["source"]["type"], "official_local_government")
            self.assertTrue(item["source"]["url"].startswith("https://"))
            self.assertEqual(item["source"]["checked_at"], "2026-10-16")
            self.assertIsNone(item["application_url"])
            self.assertEqual(item["eligibility_status"], "needs_confirmation")
            self.assertEqual(len(item["match_reasons"]), 3)
        self.assertNotIn("score", result)

    def test_switch_region(self):
        self.payload["target"]["region"] = "강남구"
        self.assertTrue(all(item["region"] == "강남구" for item in recommend(self.payload)["resources"]))

    def test_age_and_purpose(self):
        self.payload["target"].update(region="강남구", age_group=20, purpose="wellbeing")
        result = recommend(self.payload)
        self.assertEqual([item["purpose"] for item in result["resources"]], ["wellbeing"])

    def test_empty_is_valid_result(self):
        self.payload["target"].update(region="강남구", age_group=20, purpose="connection")
        result = recommend(self.payload)
        self.assertEqual(result["resources"], [])
        self.assertEqual(result["total"], 0)
        self.assertTrue(result["warnings"])

    def test_reject_invalid_requests(self):
        invalid = [None, [], {}, {"target": []}, {"target": self.payload["target"], "unknown": 1},
                   {**self.payload, "risk_assessment": {"level": 3}}]
        for key, value in [("region", "전국"), ("age_group", True), ("age_group", 25),
                           ("age_group", "60"), ("purpose", "unknown"), ("purpose", [])]:
            payload = copy.deepcopy(self.payload)
            payload["target"][key] = value
            invalid.append(payload)
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                recommend(payload)

    def test_does_not_mutate_request(self):
        original = copy.deepcopy(self.payload)
        recommend(self.payload)
        self.assertEqual(original, self.payload)

    def test_age_boundaries_and_missing_ages(self):
        cases = [
            (60, [{"min": 65, "max": None}], "partial"),
            (60, [{"min": 19, "max": 64}], "partial"),
            (50, [{"min": 65, "max": None}], "none"),
            (10, [{"min": 19, "max": 64}], "partial"),
            (20, [{"min": 19, "max": 64}], "overlap"),
            (60, [{"min": 60, "max": None}], "overlap"),
            (20, [{"min": None, "max": None}], "unknown"),
            (20, [{"min": 20, "max": 24}, {"min": 26, "max": 29}], "partial"),
        ]
        for group, spans, expected in cases:
            with self.subTest(group=group, spans=spans):
                self.assertEqual(age_overlap(group, spans), expected)

    def test_senior_program_is_not_full_match_for_60_plus(self):
        items = {item["id"]: item for item in recommend(self.payload)["resources"]}
        self.assertEqual(items["cc-senior-care"]["age_match"], "partial")
        self.assertEqual(items["cc-daily-care"]["age_match"], "partial")

    def test_closed_and_expired_are_not_returned(self):
        items = load_catalog()
        for item in items:
            item["availability_status"] = "closed"
        with patch('ai.welfare_agent.recommender.load_catalog', return_value=items):
            self.assertEqual(recommend(self.payload)["total"], 0)
        for item in items:
            item["availability_status"] = "needs_confirmation"
            item["application_end"] = "2020-01-01"
        with patch('ai.welfare_agent.recommender.load_catalog', return_value=items):
            self.assertEqual(recommend(self.payload)["total"], 0)

    def test_unsafe_source_fails_catalog_validation(self):
        items = load_catalog()
        items[0]["source"]["url"] = "javascript:alert(1)"
        with patch('ai.welfare_agent.recommender.CATALOG_PATH') as path:
            path.read_text.return_value = json.dumps(items)
            with self.assertRaises(ValueError):
                load_catalog()

    def test_risk_context_is_preserved_with_example_label(self):
        self.payload["risk_assessment"] = risk_example()
        original = copy.deepcopy(self.payload)
        result = recommend(self.payload)
        self.assertEqual(result["risk_assessment"], original["risk_assessment"])
        self.assertTrue(result["has_example_context"])
        self.assertEqual(self.payload, original)
        self.assertEqual(result["review"]["status"], "needs_confirmation")

    def test_signal_hypothesis_does_not_filter_services(self):
        self.payload["risk_assessment"] = risk_example()
        result = recommend(self.payload)
        self.assertEqual(result["total"], 4)
        self.assertEqual([item["purpose"] for item in result["review"]["suggested_purposes"]], ["connection"])
        self.assertTrue(all(item["support_basis"] == "general_browse" for item in result["resources"]))

    def test_consumption_does_not_infer_daily_or_mental_need(self):
        self.payload["risk_assessment"] = risk_example()
        self.payload["risk_assessment"]["signals"] = [{"type": "consumption_decline", "description": "예시 소비 감소"}]
        review = recommend(self.payload)["review"]
        self.assertEqual(review["suggested_purposes"], [])
        self.assertEqual(review["confirmed_support_needs"], [])
        self.assertTrue(any("경제적 어려움" in question for question in review["questions"]))

    def test_higher_level_alone_does_not_change_services(self):
        self.payload["risk_assessment"] = risk_example()
        self.payload["risk_assessment"]["level"] = 1
        low = recommend(self.payload)
        self.payload["risk_assessment"]["level"] = 5
        high = recommend(self.payload)
        self.assertEqual(low["resources"], high["resources"])

    def test_held_and_partial_do_not_use_signal_hypotheses(self):
        for status, level in (("held", None), ("partial", 3)):
            with self.subTest(status=status):
                self.payload["risk_assessment"] = {**risk_example(), "status": status, "level": level}
                result = recommend(self.payload)
                self.assertEqual(result["review"]["status"], f"risk_{status}")
                self.assertEqual(result["review"]["suggested_purposes"], [])
                self.assertEqual(result["total"], 4)

    def test_confirmed_need_filters_without_eligibility_decision(self):
        self.payload["confirmed_support_needs"] = ["connection"]
        result = recommend(self.payload)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["review"]["status"], "ready_for_review")
        item = result["resources"][0]
        self.assertEqual(item["support_basis"], "staff_confirmed_need")
        self.assertEqual(item["eligibility_status"], "needs_confirmation")
        self.assertEqual(item["age_match"], "partial")

    def test_explicit_purpose_overrides_other_confirmed_need_with_notice(self):
        self.payload["target"]["purpose"] = "daily"
        self.payload["confirmed_support_needs"] = ["connection"]
        result = recommend(self.payload)
        self.assertEqual(result["total"], 3)
        self.assertTrue(all(item["support_basis"] == "staff_requested_purpose" for item in result["resources"]))
        self.assertTrue(any("다릅니다" in text for text in result["review"]["questions"]))
        self.assertEqual(result["review"]["status"], "needs_confirmation")

    def test_invalid_risk_contract(self):
        variants = [{"region": "강남구"}, {"age_group": 50}, {"age_group": True}, {"period": "2025-13"},
                    {"period": "0000-01"}, {"schema_version": "unknown"}, {"status": "held", "level": 3},
                    {"level": True}, {"level": 6}, {"level": None}, {"is_example": "true"},
                    {"limitations": "not-list"}, {"model_version": ""}, {"signals": [{"type": "diagnosis", "description": "bad"}]},
                    {"signals": [{"type": "movement_decline", "description": "a"}] * 2}]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                recommend({**self.payload, "risk_assessment": {**risk_example(), **changes}})

    def test_invalid_confirmed_needs(self):
        for needs in (None, "daily", ["daily", "daily"], ["unknown"], [{}]):
            with self.subTest(needs=needs), self.assertRaises(ValueError):
                recommend({**self.payload, "confirmed_support_needs": needs})


class WelfareScenarioTests(unittest.TestCase):
    """팀 검토용 기대 결과를 고정해 규칙 변경 시 동작의 변화를 확인한다."""

    def test_review_scenarios(self):
        path = Path(__file__).with_name("fixtures") / "welfare_review_cases.json"
        suite = json.loads(path.read_text(encoding="utf-8"))
        ids = [case["id"] for case in suite["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        results = {}
        for case in suite["cases"]:
            with self.subTest(case=case["id"], title=case["title"]):
                payload, expected = case["request"], case["expected"]
                original = copy.deepcopy(payload)
                if expected["invalid_request"]:
                    # 목록 파일 오류를 입력 거절 성공으로 잘못 집계하지 않는다.
                    with self.assertRaises(ValueError):
                        validate_request(payload)
                    continue
                result = recommend(payload)
                results[case["id"]] = result
                self.assertEqual(payload, original)
                self.assertEqual(result["catalog_version"], suite["catalog_version"])
                self.assertEqual(result["review"]["rules_version"], suite["rules_version"])
                actual_ids = [item["id"] for item in result["resources"]]
                self.assertCountEqual(actual_ids, expected["resource_ids"])
                self.assertEqual(result["total"], len(expected["resource_ids"]))
                self.assertEqual(len(actual_ids), len(set(actual_ids)))
                self.assertEqual(result["review"]["status"], expected["review_status"])
                self.assertEqual(result["coverage"]["status"], expected["coverage_status"])
                if not actual_ids:
                    self.assertIn("서비스 부재나 지원 불필요를 뜻하지", result["coverage"]["message"])
                self.assertEqual(result["review"]["confirmed_support_needs"], payload["confirmed_support_needs"])
                self.assertEqual(result["risk_assessment"], payload["risk_assessment"])
                self.assertEqual(result["has_example_context"], payload["risk_assessment"] is not None)
                self.assertCountEqual([item["purpose"] for item in result["review"]["suggested_purposes"]], expected["suggested_purposes"])
                self.assertTrue(result["warnings"])
                self.assertNotIn("score", result)
                for text in expected.get("question_contains", []):
                    self.assertTrue(any(text in question for question in result["review"]["questions"]))
                for item in result["resources"]:
                    self.assertEqual(item["eligibility_status"], "needs_confirmation")
                    self.assertEqual(item["availability_status"], "needs_confirmation")
                    self.assertEqual(item["source"]["type"], "official_local_government")
                    self.assertTrue(item["source"]["url"].startswith("https://"))
                    if item["id"] in expected.get("age_matches", {}):
                        self.assertEqual(item["age_match"], expected["age_matches"][item["id"]])
        # 같은 조건에서 단계만 바뀐 두 사례의 자원·자격·근거가 같아야 한다.
        self.assertEqual(results["S10"]["resources"], results["S11"]["resources"])


class WelfareApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, body=None, content_type="application/json"):
        # 고정 목록 회귀 검사는 offline을 명시한다. 실제 유료 API는 호출하지 않는다.
        if method == "POST" and content_type == "application/json" and body:
            try:
                payload = json.loads(body)
                if isinstance(payload, dict):
                    payload.setdefault("mode", "offline")
                    body = json.dumps(payload)
            except ValueError:
                pass
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers={"Content-Type": content_type})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_http_success(self):
        body = json.dumps({"target": {"region": "강남구", "age_group": 60, "purpose": "all"}})
        status, content = self.request("POST", "/api/welfare/recommendations", body)
        result = json.loads(content)
        self.assertEqual(status, 200)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["target"]["region"], "강남구")
        self.assertEqual(result["mode"], "offline")
        self.assertEqual(result["schema_version"], "welfare-0.4")

    def test_http_live_failure_is_not_disguised_as_offline_success(self):
        payload = {"mode": "live", "target": {"region": "춘천시", "age_group": 60, "purpose": "all"}}
        with patch('backend.server.recommend_live', side_effect=AgentError('테스트용 키 미설정', 503)):
            status, content = self.request("POST", "/api/welfare/recommendations", json.dumps(payload))
        self.assertEqual(status, 503)
        self.assertIn("error", json.loads(content))
        self.assertNotIn("resources", json.loads(content))

    def test_status_does_not_return_api_key(self):
        status, content = self.request("GET", "/api/welfare/status")
        result = json.loads(content)
        self.assertEqual(status, 200)
        self.assertEqual(set(result), {"configured", "gemini_configured", "tavily_configured", "model", "provider", "search_provider"})

    def test_http_risk_and_confirmed_needs(self):
        payload = {"target": {"region": "춘천시", "age_group": 60, "purpose": "all"},
                   "risk_assessment": risk_example(), "confirmed_support_needs": ["connection"]}
        status, content = self.request("POST", "/api/welfare/recommendations", json.dumps(payload))
        result = json.loads(content)
        self.assertEqual(status, 200)
        self.assertEqual(result["total"], 1)
        self.assertTrue(result["has_example_context"])
        self.assertEqual(result["review"]["confirmed_support_needs"], ["connection"])
        payload["risk_assessment"]["region"] = "강남구"
        self.assertEqual(self.request("POST", "/api/welfare/recommendations", json.dumps(payload))[0], 400)

    def test_http_invalid_json_and_values(self):
        for body in ('{', 'null', '{}', '[]', 'true'):
            with self.subTest(body=body):
                status, content = self.request("POST", "/api/welfare/recommendations", body)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(content))

    def test_http_media_path_and_size(self):
        self.assertEqual(self.request("POST", "/api/welfare/recommendations", '{}', "text/plain")[0], 415)
        self.assertEqual(self.request("POST", "/api/unknown", '{}')[0], 404)
        self.assertEqual(self.request("POST", "/api/welfare/recommendations", 'x' * 16385)[0], 413)

    def test_static_root_does_not_expose_project_files(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"app.js", body)
        for path in ("/requirements.txt", "/../requirements.txt", "/ai/welfare_agent/welfare_resources.json"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)


if __name__ == "__main__":
    unittest.main()
