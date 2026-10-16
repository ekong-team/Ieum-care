"""공식 자원 후보의 필터·연령 구간·출처·운영 상태 및 HTTP 연결 검증."""

import copy
from http.client import HTTPConnection
import json
from threading import Thread
import unittest
from unittest.mock import patch

from ai.welfare_agent.recommender import recommend, age_overlap, load_catalog
from backend.server import create_server


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
