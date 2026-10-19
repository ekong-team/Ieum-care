"""대상 프로필 → 복지 추천 요청 변환과 복지 추천 노드 검증.

핵심: 변환 결과가 장현지 님 코드의 기존 검증(validate_request)을 그대로 통과해야 한다.
외부 호출은 하지 않는다 (offline 저장 자료 또는 가짜 함수).
"""

import copy
import json
from pathlib import Path
import unittest

from ai.contracts import TargetProfile
from ai.nodes.context import NodeContext
from ai.nodes.welfare import recommend_existing, to_welfare_payload
from ai.welfare_agent.live_agent import AgentError
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
        self.assertEqual(payload["target"], {"region": "춘천시", "age_group": 20, "purpose": "all"})
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

    def test_sex_is_dropped_with_warning(self):
        data = profile_data()
        data["target"]["sex"] = "female"
        payload, warnings = self.convert(data)
        self.assertNotIn("sex", payload["target"])
        self.assertTrue(any("성별" in text for text in warnings))


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
        self.assertEqual(ctx.calls["gemini"], 1)


if __name__ == "__main__":
    unittest.main()
