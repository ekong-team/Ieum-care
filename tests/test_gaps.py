"""공백 분석 노드(ai/nodes/gaps.py) 검증. 외부 호출 없음.

확인하는 규칙:
- 원인별 대응 자원: 직접 연결 자원 + C1은 일상 지원, C4는 정서 지원도 인정한다.
- 연령이 확인되면 covered, 일부만 맞거나 미확인이면 partial, 대응 자원이 없으면 gap, 조회 실패면 unknown.
- 실제 저장 자료(offline)로 돌린 결과가 기획 생성의 신규성 근거로 이어진다.
"""

from dataclasses import replace
import json
from pathlib import Path
import unittest

from ai.contracts import CAUSE_LABELS, CauseHypothesis, ExistingResource, ExistingResources, TargetProfile
from ai.graph.pipeline import Engines, PlanningInput, run_pipeline
from ai.nodes import gaps, planner, welfare
from ai.nodes.context import NodeContext

PROFILE = TargetProfile.model_validate(json.loads(
    (Path(__file__).parent / "fixtures" / "target_profile_example.json").read_text(encoding="utf-8")))  # 춘천 20대


def resource(rid, purpose, age="overlap", relevance=None):
    return ExistingResource(id=rid, name=f"자원 {rid}", purpose=purpose, age_match=age, isolation_relevance=relevance)


def available(*resources):
    return ExistingResources(status="available", resources=list(resources))


def coverage(cause, existing):
    item = gaps.gap_for(cause, existing)
    return item.coverage, item.related_resource_ids


class GapForTests(unittest.TestCase):
    def test_confirmed_direct_resource_covers(self):
        self.assertEqual(coverage("C3_overall_withdrawal", available(resource("A", "connection"))), ("covered", ["A"]))

    def test_unconfirmed_age_is_partial(self):
        for age in ("partial", "unknown"):
            self.assertEqual(coverage("C3_overall_withdrawal", available(resource("A", "connection", age))),
                             ("partial", ["A"]), age)

    def test_age_mismatch_or_unrelated_purpose_is_gap(self):
        existing = available(resource("A", "connection", "none"), resource("B", "economic"))
        self.assertEqual(coverage("C3_overall_withdrawal", existing), ("gap", []))
        self.assertEqual(coverage("C3_overall_withdrawal", available()), ("gap", []))  # 조회 성공·후보 0개

    def test_cause_specific_support_counts(self):
        daily, wellbeing = available(resource("D", "daily")), available(resource("W", "wellbeing"))
        self.assertEqual(coverage("C1_mobility", daily)[0], "covered")       # 찾아가는 일상 지원
        self.assertEqual(coverage("C3_overall_withdrawal", daily)[0], "gap")  # 다른 원인에는 대응 아님
        self.assertEqual(coverage("C4_prolonged", wellbeing)[0], "covered")   # 정서·심리 지원

    def test_live_relevance_label_wins_over_purpose(self):
        indirect = available(resource("A", "connection", relevance="indirect"))
        self.assertEqual(coverage("C2_social_consumption", indirect)[0], "gap")
        direct = available(resource("B", "other", relevance="direct"))
        self.assertEqual(coverage("C2_social_consumption", direct)[0], "covered")

    def test_failed_lookup_is_unknown_with_reason(self):
        item = gaps.gap_for("C3_overall_withdrawal", ExistingResources(status="unavailable", reason="검색 한도 초과"))
        self.assertEqual(item.coverage, "unknown")
        self.assertIn("검색 한도 초과", item.reason)

    def test_reason_uses_readable_label(self):
        item = gaps.gap_for("C2_social_consumption", available())
        self.assertTrue(item.reason.startswith(CAUSE_LABELS["C2_social_consumption"]))
        self.assertEqual(CAUSE_LABELS["C2_social_consumption"], "지역 소비 활동 위축")  # 분석 Agent와 같은 의미


class RealCatalogTests(unittest.TestCase):
    """저장 자료(offline) 춘천 20대 = 일상돌봄(일상)·고독사 예방(연결, 19~64세)·우유배달 안부확인(일상, 연령 미확인)."""

    def setUp(self):
        self.existing = welfare.recommend_existing(NodeContext(run_id="run-gaps0001", mode="offline"), PROFILE)

    def test_catalog_gaps_per_cause(self):
        self.assertEqual(coverage("C3_overall_withdrawal", self.existing), ("covered", ["cc-loneliness-prevention"]))
        self.assertEqual(coverage("C1_mobility", self.existing)[0], "covered")  # 일상돌봄도 대응으로 인정
        self.assertEqual(coverage("C4_prolonged", self.existing), ("covered", ["cc-loneliness-prevention"]))

    def test_gaps_reach_planner_novelty_choices(self):
        causes = [CauseHypothesis(code="C3_overall_withdrawal"), CauseHypothesis(code="C1_mobility")]
        planning = PlanningInput(run_id="run-gaps0001", profile=PROFILE, causes=causes,
                                 existing=available(resource("D", "daily", "partial")), trends=[], gaps=[])
        planning.gaps = gaps.analyze_gaps(None, planning)
        self.assertEqual([(g.cause, g.coverage) for g in planning.gaps],
                         [("C3_overall_withdrawal", "gap"), ("C1_mobility", "partial")])
        self.assertEqual(planner.open_gaps(planning), ["C3_overall_withdrawal", "C1_mobility"])


class GraphConnectionTests(unittest.TestCase):
    def test_default_engine_and_offline_run(self):
        self.assertIs(Engines().analyze_gaps, gaps.analyze_gaps)
        state = run_pipeline(PROFILE, mode="offline", engines=replace(Engines()), run_id="run-gaps0002")
        event = next(e for e in state["trace"] if e.node == "gap_analysis" and e.status == "done")
        self.assertEqual(event.decision, "C3_overall_withdrawal=covered")
        self.assertNotIn("[가짜]", " ".join(event.reasons))


if __name__ == "__main__":
    unittest.main()
