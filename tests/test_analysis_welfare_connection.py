"""계산부터 실제 저장 자원 추천까지 ZIP 없이 연결하고 성별·근거를 보존한다."""
import copy
import json
from http.client import HTTPConnection
from threading import Thread
import unittest
from unittest.mock import patch

from ai.analysis_agent.workflow import run_analysis
from ai.analysis_agent.agent import recommendation_request, recommend_from_analysis
from ai.welfare_agent.recommender import validate_request, age_overlap
from backend.server import create_server
from tests.test_analysis_sex import sex_rows


class AnalysisWelfareConnectionTests(unittest.TestCase):
    def setUp(self):
        data = sex_rows("female", [3100, 2700, 2400], [None, -.1, -.1], [None, -.1, -.1])
        data += sex_rows("male", [3100, 3200, 3300], [None, .01, .01], [None, .01, .01])
        self.bundle = run_analysis(data, {}, [], period="202509")

    def test_all_statuses_and_sexes_reach_real_offline_recommender(self):
        original = copy.deepcopy(self.bundle)
        for cohort in self.bundle["cohorts"]:
            with self.subTest(id=cohort["analysis_id"]):
                result = recommend_from_analysis(self.bundle, cohort["analysis_id"])
                self.assertEqual(result["target"]["sex"], cohort["profile"]["target"]["sex"])
                self.assertEqual(result["risk_assessment"]["status"], cohort["assessment"]["status"])
                self.assertEqual(result["risk_assessment"]["level"], cohort["assessment"]["level"])
                self.assertEqual(result["risk_assessment"]["assessment_id"], cohort["analysis_id"])
                self.assertEqual(result["analysis_context"]["profile"], cohort["profile"])
                self.assertIn("response_routing", result)
                self.assertEqual(result["mode"], "offline")
        self.assertEqual(self.bundle, original)

    def test_mismatch_and_missing_gender_rejected(self):
        request = recommendation_request(self.bundle, self.bundle["cohorts"][-1]["analysis_id"])
        for location in ("target", "risk_assessment"):
            bad = copy.deepcopy(request)
            bad[location]["sex"] = "all"
            with self.assertRaises(ValueError):
                validate_request(bad)
            bad = copy.deepcopy(request)
            bad[location].pop("sex")
            with self.assertRaises(ValueError):
                validate_request(bad)
        bad = copy.deepcopy(request)
        bad["analysis_context"]["profile"]["target"]["sex"] = "all"
        with self.assertRaises(ValueError):
            validate_request(bad)

    def test_invalid_target_and_tampered_evidence_fail_before_recommendation(self):
        with self.assertRaises(ValueError):
            recommendation_request(self.bundle, "missing")
        self.bundle["cohorts"][-1]["profile"]["evidence"][0]["value"] = 99
        with self.assertRaises(ValueError):
            recommendation_request(self.bundle, self.bundle["cohorts"][-1]["analysis_id"])

    def test_live_dispatch_preserves_payload_without_real_api(self):
        aid = self.bundle["cohorts"][-1]["analysis_id"]
        expected = recommend_from_analysis(self.bundle, aid)
        with patch("ai.welfare_agent.live_agent.recommend_live", return_value=expected) as live:
            recommend_from_analysis(self.bundle, aid, mode="live")
        request = live.call_args.args[0]
        self.assertEqual(request["target"]["sex"], "male")
        self.assertIn("analysis_context", request)
        with self.assertRaises(ValueError):
            recommend_from_analysis(self.bundle, aid, mode="unknown")

    def test_child_only_resource_is_not_teen_resource(self):
        self.assertEqual(age_overlap(10, [{"min": 0, "max": 9}]), "none")

    def test_http_offline_accepts_same_request(self):
        aid = self.bundle["cohorts"][-1]["analysis_id"]
        body = {**recommendation_request(self.bundle, aid), "mode": "offline"}
        server = create_server(0)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("POST", "/api/welfare/recommendations",
                               json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
            response = connection.getresponse()
            result = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(result["target"]["sex"], "male")
            self.assertEqual(result["analysis_context"], body["analysis_context"])
        finally:
            connection.close()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()
