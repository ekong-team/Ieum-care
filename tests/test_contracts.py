"""입출력 형식(ai/contracts) 검증. 잘못된 입력을 조용히 고쳐 쓰지 않고 거부하는지 확인한다.

시나리오 번호는 설계 문서의 1단계 표(T01~)를 따른다.
"""

import copy
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from ai.contracts import AxisScore, ProgramPlan, RevisionRequest, TargetProfile, summarize

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TargetProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = load("target_profile_example.json")

    def assertRejected(self, data):
        with self.assertRaises(ValidationError):
            TargetProfile.model_validate(data)

    def test_t01_valid_example_passes(self):
        profile = TargetProfile.model_validate(self.profile)
        self.assertEqual(profile.target.region, "춘천시")
        self.assertEqual(set(profile.evidence_by_id()), {"E1", "E2"})

    def test_t02_unsupported_region_rejected(self):
        self.profile["target"]["region"] = "서울시"
        self.assertRejected(self.profile)

    def test_t03_unknown_signal_rejected(self):
        self.profile["signals"] = ["loneliness"]
        self.assertRejected(self.profile)

    def test_t04_evidence_value_must_be_number(self):
        self.profile["evidence"][0]["value"] = "-8%"
        self.assertRejected(self.profile)
        self.profile["evidence"][0]["value"] = "-0.08"  # 숫자처럼 보이는 문자열도 바꾸지 않는다
        self.assertRejected(self.profile)

    def test_t05_duplicate_evidence_id_rejected(self):
        self.profile["evidence"][1]["id"] = "E1"
        self.assertRejected(self.profile)

    def test_t09_risk_status_and_level_must_match(self):
        held = copy.deepcopy(self.profile)
        held["risk"] = {"level": 3, "status": "held"}
        self.assertRejected(held)
        complete = copy.deepcopy(self.profile)
        complete["risk"] = {"level": None, "status": "complete"}
        self.assertRejected(complete)
        partial = copy.deepcopy(self.profile)
        partial["risk"] = {"level": None, "status": "partial"}
        TargetProfile.model_validate(partial)  # 부분 판정은 단계 없이도 허용

    def test_age_group_must_be_exact_int(self):
        self.profile["target"]["age_group"] = 20.0  # 실수를 정수로 바꿔 받지 않는다
        self.assertRejected(self.profile)

    def test_unknown_field_rejected(self):
        self.profile["target"]["income"] = "low"
        self.assertRejected(self.profile)

    def test_without_risk_is_allowed(self):
        self.profile["risk"] = None
        self.profile["signals"] = []
        TargetProfile.model_validate(self.profile)


class ProgramPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = load("program_plan_example.json")

    def test_t08_example_plan_passes(self):
        plan = ProgramPlan.model_validate(self.plan)
        self.assertEqual(plan.plan_id, "P-EXAMPLE-01")

    def test_t06_plan_without_kpi_rejected(self):
        self.plan["kpis"] = []
        with self.assertRaises(ValidationError):
            ProgramPlan.model_validate(self.plan)

    def test_t07_unknown_unit_cost_allowed(self):
        plan = ProgramPlan.model_validate(self.plan)
        self.assertIsNone(plan.budget_items[0].unit_cost_krw)

    def test_plan_without_cause_rejected(self):
        self.plan["risk_causes_addressed"] = []
        with self.assertRaises(ValidationError):
            ProgramPlan.model_validate(self.plan)

    def test_unknown_cause_code_rejected(self):
        self.plan["risk_causes_addressed"] = ["C9_unknown"]
        with self.assertRaises(ValidationError):
            ProgramPlan.model_validate(self.plan)


class EvaluationTests(unittest.TestCase):
    def axes(self, feasibility_available=True):
        scores = {"target_fit": 20, "novelty": 15, "grounding": 10, "budget": 10, "measurability": 5}
        axes = [AxisScore(axis=name, score=value, method="rule") for name, value in scores.items()]
        if feasibility_available:
            axes.append(AxisScore(axis="feasibility", score=12, method="llm"))
        else:
            axes.append(AxisScore(axis="feasibility", score=0, method="llm", available=False, reasons=["LLM 호출 실패"]))
        return axes

    def test_total_is_sum_when_all_axes_available(self):
        result = summarize("P-1", self.axes(), [])
        self.assertEqual(result.total, 72.0)
        self.assertTrue(result.passed)
        self.assertTrue(result.llm_axis_available)

    def test_llm_axis_failure_rescales_rule_axes_to_100(self):
        result = summarize("P-1", self.axes(feasibility_available=False), [])
        self.assertAlmostEqual(result.total, 60 / 85 * 100, places=2)
        self.assertFalse(result.llm_axis_available)

    def test_score_above_axis_max_rejected(self):
        with self.assertRaises(ValidationError):
            AxisScore(axis="measurability", score=11, method="rule")

    def test_llm_axis_cannot_be_rule(self):
        with self.assertRaises(ValidationError):
            AxisScore(axis="feasibility", score=10, method="rule")

    def test_rule_axis_cannot_be_skipped(self):
        # 평가를 생략할 수 있는 축은 LLM 축뿐이다. 규칙 축을 빼서 점수를 부풀리지 못하게 한다.
        with self.assertRaises(ValidationError):
            AxisScore(axis="budget", score=0, method="rule", available=False)

    def test_hand_written_total_rejected(self):
        result = summarize("P-1", self.axes(), [RevisionRequest(axis="budget", request="단가 근거 보완")])
        data = result.model_dump()
        data["total"] = 95
        with self.assertRaises(ValidationError):
            type(result).model_validate(data)


if __name__ == "__main__":
    unittest.main()
