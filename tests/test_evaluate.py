"""평가 노드 규칙 축(ai/nodes/evaluate.py) 검증. 외부 호출 없음.

확인하는 규칙 (타깃 적합성 25점 = 원인 대응 10 + 시간대 10 + 형식 5):
- 시간대 문장에서 요일·시각을 읽고, 연령별로 피할 시간대(10대 평일 9~16시, 20~50대 평일 9~18시, 60대 이상 21시 이후)를 감점한다.
- 시각을 읽지 못하면 감점하지 않는다. 평일과 주말이 함께 적혀 있으면 평일만으로 보지 않는다.
- 개선 요청은 축 점수가 만점의 60% 미만일 때만 낸다.
"""

import json
from pathlib import Path
import unittest

from ai.contracts import (CauseHypothesis, ExistingResource, ExistingResources, GapItem, ProgramPlan, TargetProfile,
                          TrendReference)
from ai.graph.pipeline import PlanningInput
from ai.nodes import evaluate, feasibility
from ai.nodes.context import NodeContext
from ai.welfare_agent.live_agent import AgentError

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = TargetProfile.model_validate(json.loads((FIXTURES / "target_profile_example.json").read_text(encoding="utf-8")))
LIVE = json.loads((FIXTURES / "live_plans_20261023.json").read_text(encoding="utf-8"))["runs"]
BASE = LIVE["run3"][0]  # 춘천 20대, C3, 토·일 낮 활동, 오프라인 모임


def planning(*codes, age=20, gaps=(), existing=None):
    profile = PROFILE.model_copy(update={"target": PROFILE.target.model_copy(update={"age_group": age})})
    return PlanningInput(run_id="run-eval0001", profile=profile,
                         causes=[CauseHypothesis(code=c) for c in codes or ("C3_overall_withdrawal",)],
                         existing=existing or ExistingResources(status="unavailable"), trends=[], gaps=list(gaps))


def gap(code="C3_overall_withdrawal", coverage="gap"):
    return GapItem(cause=code, coverage=coverage, reason="테스트")


# 저장 자료의 춘천 자원 이름 그대로 (중복 판정용)
CATALOG = ExistingResources(status="available", resources=[
    ExistingResource(id="cc-loneliness-prevention", name="고독사 예방 사업", purpose="connection"),
    ExistingResource(id="cc-daily-care", name="일상돌봄서비스", purpose="daily")])
NO_LINK = {"lead_candidates": [], "linked_existing_resources": []}


def plan_with(*slots, **changes):
    data = {**BASE, **changes}
    if slots:
        data["activities"] = [{**BASE["activities"][0], "name": f"활동{i}", "time_slot": s} for i, s in enumerate(slots)]
    return ProgramPlan.model_validate(data)


class ReadSlotTests(unittest.TestCase):
    def test_days_and_hours(self):
        cases = {"목요일 오후 2시~3시": (True, 14), "토요일 오전 10시~12시": (False, 10),
                 "수요일 저녁 8시~9시": (True, 20), "평일 19~21시": (True, 19), "평일 저녁 또는 주말 오후 2시": (False, 14),
                 "매주 화요일 19:00": (True, 19), "상시": (None, None), "주 1회": (None, None)}
        for text, expected in cases.items():
            self.assertEqual(evaluate.read_slot(text), expected, text)

    def test_age_specific_busy_hours(self):
        self.assertEqual(evaluate.slot_problem("목요일 오후 2시", 20), "근로·학업 시간")
        self.assertEqual(evaluate.slot_problem("목요일 오후 5시", 10), None)       # 10대는 16시 이후 가능
        self.assertEqual(evaluate.slot_problem("목요일 오후 3시", 10), "수업 시간")
        self.assertEqual(evaluate.slot_problem("토요일 오후 2시", 30), None)       # 주말은 감점 안 함
        self.assertEqual(evaluate.slot_problem("목요일 오후 2시", 60), None)       # 60대 이상은 낮 시간 괜찮음
        self.assertEqual(evaluate.slot_problem("금요일 밤 9시", 60), "야간 이동 부담")
        self.assertEqual(evaluate.slot_problem("오후 2시", 20), None)              # 요일을 모르면 평일로 단정하지 않는다


class TargetFitTests(unittest.TestCase):
    def score(self, plan, plan_input=None):
        result = evaluate.target_fit(plan, plan_input or planning())
        return result.score.score, [r.request for r in result.requests], result.score.reasons

    def test_full_score(self):
        points, requests, _ = self.score(plan_with("토요일 오후 2시", "수요일 저녁 8시", format="hybrid"))
        self.assertEqual((points, requests), (25, []))

    def test_each_part_deducts(self):
        # 원인 2개 중 1개만 대응(-5), 활동 2개 중 1개 평일 낮(-5), C3에 오프라인 모임(-5) → 10점
        points, requests, reasons = self.score(plan_with("목요일 오후 2시", "토요일 오후 2시"),
                                               planning("C3_overall_withdrawal", "C4_prolonged"))
        self.assertEqual(points, 10)
        self.assertTrue(any("위축 장기화" in r for r in requests))
        self.assertTrue(any("활동0" in r and "저녁·주말" in r for r in requests))
        self.assertTrue(any("온·오프라인 단계형" in r for r in requests))
        self.assertIn("빠짐: 위축 장기화", reasons[0])

    def test_no_request_at_or_above_sixty_percent(self):
        points, requests, _ = self.score(plan_with("목요일 오후 2시", "토요일 오후 2시"))  # 10 + 5 + 0 = 15 (=60%)
        self.assertEqual((points, requests), (15, []))

    def test_unreadable_slot_is_not_penalized_but_noted(self):
        points, _, reasons = self.score(plan_with("상시", "토요일 오후 2시", format="hybrid"))
        self.assertEqual(points, 25)
        self.assertIn("시각 확인 필요: 활동0", reasons[1])

    def test_real_live_outputs(self):
        # 2026-10-23 실제 결과 (C3 생활 전반 위축, 20대)
        # 01 오프라인 모임(형식 -5) = 20 / 02 단계형 = 25 / 03 평일 낮 활동 2개(시간대 -10) + 연계형(형식 -5) = 10
        scores = {p["plan_id"][-2:]: evaluate.target_fit(ProgramPlan.model_validate(p), planning()).score.score
                  for p in LIVE["run3"]}
        self.assertEqual(scores, {"01": 20, "02": 25, "03": 10})
        result = evaluate.target_fit(ProgramPlan.model_validate(LIVE["run3"][2]), planning())
        self.assertEqual(len(result.requests), 3)  # 60% 미만 → 활동 2개 시간 이동 + 형식 제안


class NoveltyTests(unittest.TestCase):
    """신규성 20점 = 공백 대응 12 + 중복 없음 8 (중복 의심 1건당 -4)."""

    def score(self, plan, plan_input):
        result = evaluate.novelty(plan, plan_input)
        return result.score.score, [r.request for r in result.requests], result.score.reasons

    def test_addressing_open_gap_is_full(self):
        for coverage in ("gap", "partial"):
            points, requests, _ = self.score(plan_with(), planning(gaps=[gap(coverage=coverage)]))
            self.assertEqual((points, requests), (20, []), coverage)

    def test_ignoring_open_gap_scores_zero_and_requests(self):
        plan_input = planning("C3_overall_withdrawal", "C4_prolonged",
                              gaps=[gap(), gap("C4_prolonged")])
        plan = plan_with(risk_causes_addressed=["C3_overall_withdrawal"],
                         novelty={"gap_causes": [], "differs_from_existing": "x"})
        points, _, _ = self.score(plan, plan_input)
        self.assertEqual(points, 20)  # 공백 하나라도 다루면 만점 (설계 결정 C)
        plan_input = planning("C3_overall_withdrawal", "C4_prolonged", gaps=[gap("C4_prolonged")])
        points, requests, reasons = self.score(plan, plan_input)
        self.assertEqual(points, 8)
        self.assertIn("위축 장기화", requests[0])
        self.assertIn("다루지 않음", reasons[0])

    def test_no_gap_prefers_linkage(self):
        covered = planning(gaps=[gap(coverage="covered")])
        self.assertEqual(self.score(plan_with(operation=NO_LINK, format="hybrid"), covered)[0], 12)  # 4 + 8
        linked = {"lead_candidates": [], "linked_existing_resources": ["cc-daily-care"]}
        self.assertEqual(self.score(plan_with(operation=linked, format="hybrid"), covered)[0], 16)  # 8 + 8

    def test_unknown_gap_gets_half_without_request(self):
        points, requests, reasons = self.score(plan_with(), planning(gaps=[gap(coverage="unknown")]))
        self.assertEqual((points, requests), (14, []))  # 6 + 8, 기획안 탓이 아니므로 요청 없음
        self.assertIn("공백 미확인", reasons[0])

    def test_duplicate_names_deduct(self):
        plan = plan_with(title="춘천 고독사 예방 모임", operation=NO_LINK)
        points, requests, reasons = self.score(plan, planning(gaps=[gap(coverage="unknown")], existing=CATALOG))
        self.assertEqual(points, 10)  # 6 + (8 - 4)
        self.assertIn("중복 의심 1건", reasons[1])
        self.assertEqual(len(requests), 1)  # 10점은 60%(12점) 미만 → 중복 해소 요청
        self.assertIn("고독사 예방 사업", requests[0])

    def test_real_live_outputs_with_offline_catalog(self):
        # 2026-10-23 실제 결과 + 실제 공백 분석(저장 자료: C3 covered). 01·02는 일상돌봄·고독사 예방과 연계, 03은 연계형
        from ai.nodes import gaps, welfare
        from ai.nodes.context import NodeContext
        existing = welfare.recommend_existing(NodeContext(run_id="r", mode="offline"), PROFILE)
        plan_input = planning(existing=existing)
        plan_input.gaps = gaps.analyze_gaps(None, plan_input)
        scores = {p["plan_id"][-2:]: evaluate.novelty(ProgramPlan.model_validate(p), plan_input).score.score
                  for p in LIVE["run3"]}
        self.assertEqual(scores, {"01": 16, "02": 16, "03": 16})  # 공백 없음 + 연계 포함(8) + 중복 없음(8)


class GroundingAxisTests(unittest.TestCase):
    """근거성 15점 = 원인별 근거 연결 9 + 참고 사례 6 (검색이 없었으면 근거 연결만으로 15점 환산)."""

    def run_axis(self, plan, *, causes, trends=()):
        plan_input = planning()
        plan_input.causes, plan_input.trends = causes, list(trends)
        result = evaluate.grounding(plan, plan_input)
        return result.score.score, [r.request for r in result.requests], result.score.reasons

    C3 = CauseHypothesis(code="C3_overall_withdrawal", evidence_ids=["E1", "E2"])
    C4 = CauseHypothesis(code="C4_prolonged", evidence_ids=["E3"])
    PUBLIC = TrendReference(title="공공 사례", url="https://www.seoul.go.kr/a", grade="public")
    MEDIA = TrendReference(title="언론 사례", url="https://www.yna.co.kr/a", grade="media")

    def ref(self, trend):
        return {"title": trend.title, "url": trend.url, "year": None, "grade": trend.grade, "how_applied": "적용"}

    def test_no_search_rescales_evidence_link_to_full(self):
        points, requests, reasons = self.run_axis(plan_with(data_evidence=["E1"]), causes=[self.C3])
        self.assertEqual((points, requests), (15, []))
        self.assertIn("환산", reasons[1])

    def test_unlinked_cause_deducts_and_requests(self):
        plan = plan_with(data_evidence=["E1"], risk_causes_addressed=["C3_overall_withdrawal", "C4_prolonged"])
        points, requests, _ = self.run_axis(plan, causes=[self.C3, self.C4])
        self.assertEqual(points, 7.5)  # 1/2 연결 → 15 × 0.5
        self.assertIn("위축 장기화의 근거(E3)", requests[0])

    def test_cause_without_evidence_is_not_counted(self):
        points, _, reasons = self.run_axis(plan_with(data_evidence=[], risk_causes_addressed=["C0_unknown"]),
                                           causes=[CauseHypothesis(code="C0_unknown")])
        self.assertEqual(points, 15)
        self.assertEqual(reasons[0], "근거가 필요한 원인 가설 없음")

    def test_reference_quality_when_search_ran(self):
        trends = [self.PUBLIC, self.MEDIA]
        both = plan_with(data_evidence=["E1"], trend_references=[self.ref(self.PUBLIC), self.ref(self.MEDIA)])
        self.assertEqual(self.run_axis(both, causes=[self.C3], trends=trends)[0], 13.5)  # 9 + 3 + 3 × 1/2
        public = plan_with(data_evidence=["E1"], trend_references=[self.ref(self.PUBLIC)])
        self.assertEqual(self.run_axis(public, causes=[self.C3], trends=trends)[0], 15)

    def test_no_reference_when_search_ran_requests_citation(self):
        points, requests, _ = self.run_axis(plan_with(data_evidence=[], trend_references=[]),
                                            causes=[self.C3], trends=[self.PUBLIC])
        self.assertEqual(points, 0)
        self.assertEqual(len(requests), 2)  # 근거 연결 + 사례 인용 (등급은 요청하지 않음)

    def test_real_live_outputs(self):
        # 2026-10-23 실제 결과: 사례 검색 없이 실행, 3개 모두 C3 근거(E1·E2)를 인용 → 15점
        from ai.nodes import causes
        rule_causes = causes.analyze_causes(None, PROFILE)
        for data in LIVE["run3"]:
            self.assertEqual(self.run_axis(ProgramPlan.model_validate(data), causes=rule_causes)[0], 15, data["plan_id"])


class BudgetTests(unittest.TestCase):
    """예산 15점 = 항목 구성 5 + 회차 연동 5 + 단가 확정 5. 단가 미확정은 요청하지 않는다."""

    def run_axis(self, items, sessions=6):
        plan = plan_with(budget_items=items, schedule={"duration_weeks": 4, "sessions": sessions})
        result = evaluate.budget(plan, planning())
        return result.score.score, [r.request for r in result.requests], result.score.reasons

    @staticmethod
    def item(name, unit, quantity, cost=None):
        return {"item": name, "unit": unit, "quantity": quantity, "unit_cost_krw": cost,
                "basis": "기준 단가" if cost else "단가 확인 필요"}

    def test_all_priced_and_consistent_is_full_with_total(self):
        points, requests, reasons = self.run_axis([self.item("대관", "시간", 12.0, 20000),
                                                   self.item("간식", "1인 1회", 36.0, 5000)])
        self.assertEqual((points, requests), (15, []))
        self.assertIn("총액 420,000원", reasons[3])

    def test_unpriced_items_lose_points_without_request(self):
        points, requests, reasons = self.run_axis([self.item("대관", "시간", 12.0), self.item("재료", "식", 20.0)])
        self.assertEqual((points, requests), (10, []))  # 5 + 5 + 0, 66% → 요청 없음
        self.assertIn("단가 확인 필요", reasons[2])

    def test_short_session_quantity_requests_fix(self):
        points, requests, _ = self.run_axis([self.item("대관", "시간", 4.0)], sessions=6)
        self.assertEqual(points, 2.5)  # 항목 1개(2.5) + 회차 부족(0) + 단가 없음(0)
        self.assertEqual(len(requests), 2)
        self.assertIn("'대관' 수량 4(시간)이 운영 6회보다 적습니다", requests[1])

    def test_items_without_session_unit_are_not_judged(self):
        points, _, reasons = self.run_axis([self.item("홍보물", "부", 100.0), self.item("재료", "식", 20.0)])
        self.assertEqual(points, 10)
        self.assertEqual(reasons[1], "회차 단위 항목 없음")

    def test_real_live_outputs(self):
        # 2026-10-23 실제 결과: 모두 항목 2개·단가 미확정, 회차 연동 항목은 운영 회차 이상 → 10점, 요청 없음
        for data in LIVE["run3"]:
            result = evaluate.budget(ProgramPlan.model_validate(data), planning())
            self.assertEqual((result.score.score, result.requests), (10, []), data["plan_id"])


class MeasurabilityTests(unittest.TestCase):
    """측정 가능성 10점 = 집단 단위 데이터 KPI 5 + 과정 KPI 5."""

    @staticmethod
    def kpi(name, definition, by_data):
        return {"name": name, "definition": definition, "data_source": "카드 데이터" if by_data else "운영 기록",
                "measurable_by_data": by_data}

    def run_axis(self, *kpis):
        result = evaluate.measurability(plan_with(kpis=list(kpis)), planning())
        return result.score.score, [r.request for r in result.requests], result.score.reasons

    GROUP = ("소비 건수 변화", "대상 지역·연령 집단의 월별 소비 건수 변화", True)
    PROCESS = ("재참여율", "2회 이상 참여한 비율", False)

    def test_both_kinds_full(self):
        self.assertEqual(self.run_axis(self.kpi(*self.GROUP), self.kpi(*self.PROCESS))[:2], (10, []))

    def test_missing_kind_deducts_and_requests(self):
        points, requests, _ = self.run_axis(self.kpi(*self.PROCESS))
        self.assertEqual(points, 5)
        self.assertIn("집단 단위 지표", requests[0])
        points, requests, _ = self.run_axis(self.kpi(*self.GROUP))
        self.assertEqual(points, 5)
        self.assertIn("과정 지표", requests[0])

    def test_individual_tracking_is_not_a_data_kpi(self):
        tracking = self.kpi("이동량 변화", "참여자 대상 위치 데이터를 통한 이동량 변화 측정", True)
        points, requests, reasons = self.run_axis(tracking, self.kpi(*self.PROCESS))
        self.assertEqual(points, 5)
        self.assertIn("집계 데이터로 측정할 수 없음", reasons[2])
        self.assertIn("'이동량 변화' 지표를", requests[0])

    def test_real_live_outputs_improved_after_prompt_fix(self):
        # 첫 호출(run1)은 데이터 KPI가 참여자 개인 추적이라 0점. 프롬프트 수정 뒤(run2·run3)는 모두 만점.
        scores = {run: [evaluate.measurability(ProgramPlan.model_validate(p), planning()).score.score for p in plans]
                  for run, plans in LIVE.items()}
        self.assertEqual(scores, {"run1": [0, 0, 5], "run2": [10, 10, 10], "run3": [10, 10, 10]})


def fake_gemini(reviews=None, text=None, error=None):
    """요청을 기록하고 정해진 평가 응답을 돌려주는 가짜 Gemini."""
    body = text if text is not None else json.dumps({"reviews": reviews}, ensure_ascii=False)
    def call(request, settings):
        call.requests.append(request)
        if error:
            raise error
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": body}]}}]}
    call.requests = []
    return call


def review(plan_id, score, reason="운영 주체와 장소가 구체적임", request=""):
    return {"plan_id": plan_id, "score": score, "reason": reason, "request": request}


RUN3 = [ProgramPlan.model_validate(p) for p in LIVE["run3"]]
IDS = [p.plan_id for p in RUN3]


class FeasibilityTests(unittest.TestCase):
    def live(self):
        return NodeContext(run_id="run-eval0001", mode="live")

    def test_request_sends_only_operational_fields(self):
        request = feasibility.build_request(RUN3, planning())
        context = json.loads(request["contents"][0]["parts"][0]["text"])
        self.assertEqual(set(context["plans"][0]) - {"plan_id"},
                         {"title", "one_liner", "format", "activities", "schedule", "operation", "recruitment",
                          "budget_items", "risks_and_mitigations", "assumptions"})
        self.assertNotIn("problem_statement", context["plans"][0])  # 근거 수치는 보내지 않는다
        self.assertEqual(request["generationConfig"]["temperature"], 0)
        enum = request["generationConfig"]["responseSchema"]["properties"]["reviews"]["items"]["properties"]["plan_id"]["enum"]
        self.assertEqual(enum, IDS)

    def test_offline_does_not_call(self):
        call = fake_gemini([])
        self.assertEqual(feasibility.review_feasibility(NodeContext(run_id="r", mode="offline"), RUN3, planning(), call=call), {})
        self.assertEqual(call.requests, [])

    def test_scores_and_request_only_below_sixty_percent(self):
        call = fake_gemini([review(IDS[0], 12, request="이미 충분"), review(IDS[1], 5, request="운영 주체를 정하세요")])
        result = feasibility.review_feasibility(self.live(), RUN3, planning(), call=call)
        self.assertEqual(len(call.requests), 1)  # 기획안 전체를 한 번에
        self.assertEqual((result[IDS[0]][0].score, result[IDS[0]][1]), (12, []))
        self.assertEqual([r.request for r in result[IDS[1]][1]], ["운영 주체를 정하세요"])
        self.assertNotIn(IDS[2], result)  # 응답에 없는 기획안은 '평가 못 함'

    def test_invalid_items_are_skipped_individually(self):
        ctx = self.live()
        call = fake_gemini([review(IDS[0], 16), review(IDS[1], 10, reason=" "), {**review(IDS[2], 9), "score": "9"},
                            review("P-ghost", 10)])
        self.assertEqual(feasibility.review_feasibility(ctx, RUN3, planning(), call=call), {})
        self.assertEqual(len(ctx.warnings), 4)

    def test_call_or_parse_failure_returns_empty_with_warning(self):
        for call in (fake_gemini(error=AgentError("한도 초과", 429)), fake_gemini(text="not json")):
            ctx = self.live()
            self.assertEqual(feasibility.review_feasibility(ctx, RUN3, planning(), call=call), {})
            self.assertTrue(ctx.warnings)


class EvaluatePlansTests(unittest.TestCase):
    def test_offline_rescales_rule_axes_to_100(self):
        # 실제 결과 run3. 이 입력은 복지 조회가 없어 신규성이 '공백 미확인'(6+8=14)이다.
        # 규칙 85점 중 69·74·59 (타깃 20·25·10 + 신규성 14 + 근거성 15 + 예산 10 + 측정 10) → 100점 환산
        results = evaluate.evaluate_plans(NodeContext(run_id="r", mode="offline"), RUN3, planning())
        self.assertEqual([(r.total, r.passed, r.llm_axis_available) for r in results],
                         [(81.18, True, False), (87.06, True, False), (69.41, True, False)])

    def test_llm_axis_adds_to_rule_axes(self):
        call = fake_gemini([review(IDS[0], 12), review(IDS[1], 14), review(IDS[2], 5, request="평일 낮 운영 인력 확인")])
        results = evaluate.evaluate_plans(NodeContext(run_id="r", mode="live"), RUN3, planning(), llm_call=call)
        self.assertEqual([r.total for r in results], [81, 88, 64])  # 69+12, 74+14, 59+5
        third = results[2]
        self.assertTrue(third.llm_axis_available)
        self.assertEqual({r.axis for r in third.revision_requests}, {"target_fit", "feasibility"})

    def test_completion_scenarios_from_design_doc(self):
        # 설계 문서 10장 완료 기준: gap 미대응·KPI 없음 → 감점과 개선 요청 (예산 상한은 입력이 없어 제외)
        plan = plan_with("목요일 오후 2시", kpis=[{"name": "참여율", "definition": "참여 비율", "data_source": "운영 기록",
                                                   "measurable_by_data": False}],
                         risk_causes_addressed=["C3_overall_withdrawal"], operation=NO_LINK)
        plan_input = planning("C3_overall_withdrawal", "C4_prolonged", gaps=[gap("C4_prolonged")])
        result = evaluate.evaluate_plans(NodeContext(run_id="r", mode="offline"), [plan], plan_input)[0]
        axes = {r.axis for r in result.revision_requests}
        self.assertTrue({"novelty", "measurability", "target_fit"} <= axes)
        self.assertFalse(result.passed)

    def test_default_engine_and_offline_graph(self):
        from dataclasses import replace
        from ai.graph.pipeline import Engines, run_pipeline
        self.assertIs(Engines().evaluate_plans, evaluate.evaluate_plans)
        state = run_pipeline(PROFILE, mode="offline", engines=replace(Engines()), run_id="run-eval0002")
        event = next(e for e in state["trace"] if e.node == "evaluate" and e.status == "done")
        self.assertTrue(all(not e.llm_axis_available for e in state["evaluations"]))
        self.assertEqual(state["report"].status, "completed")
        self.assertTrue(event.decision)


if __name__ == "__main__":
    unittest.main()
