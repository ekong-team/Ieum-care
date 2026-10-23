"""④-B 기획 노드(ai/nodes/planner.py) 검증. 가짜 Gemini 응답만 쓰고 외부 호출은 하지 않는다.

확인하는 규칙:
- 응답 스키마는 이번 입력에 있는 근거 id·원인·사례 URL·자원 id만 허용한다.
- plan_id·대상·revision은 LLM이 아니라 코드가 정한다.
- 형식이 틀린 초안은 그것만 버리고 이유를 남긴다. 첫 기획에서 모두 틀리면 실패한다.
- 재기획은 요청한 id만 받고, 결과가 없으면 빈 목록으로 원안 유지 경로에 맡긴다.
- 버린 이유가 그래프 판단 기록과 최종 경고에 남는다.
"""

from dataclasses import replace
from functools import partial
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ai.contracts import ExistingResource, ExistingResources, GapItem, TargetProfile, TrendReference
from ai.graph.pipeline import Engines, PlanningInput, run_pipeline
from ai.nodes import causes, planner, stubs
from ai.nodes.context import NodeContext
from ai.welfare_agent.live_agent import AgentError

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = TargetProfile.model_validate(json.loads((FIXTURES / "target_profile_example.json").read_text(encoding="utf-8")))
RUN_ID = "run-plantest0001"
TREND = TrendReference(title="청년 식사 모임 사례", url="https://www.example.go.kr/case", year=2026, grade="public",
                       summary="주 1회 저녁 식사 모임")

DRAFT = {
    "title": "주말 한 끼 모임", "one_liner": "주 1회 6인 저녁 식사 모임", "format": "offline_group",
    "risk_causes_addressed": ["C3_overall_withdrawal"], "problem_statement": "소비와 이동이 함께 줄었다.",
    "novelty": {"gap_causes": ["C3_overall_withdrawal"], "differs_from_existing": "기존 자원 확인 불가"},
    "activities": [{"name": "저녁 식사", "description": "함께 요리", "frequency": "주 1회", "time_slot": "토 18~20시",
                    "format": "offline"}],
    "schedule": {"duration_weeks": 8, "sessions": 8}, "operation": {"lead_candidates": ["청년센터(확인 필요)"]},
    "recruitment": [], "budget_items": [{"item": "식비", "unit": "1인 1회", "quantity": 48, "unit_cost_krw": None,
                                         "basis": "단가 확인 필요"}],
    "kpis": [{"name": "재참여율", "definition": "2회 이상 참여 비율", "data_source": "운영 기록", "measurable_by_data": False}],
    "risks_and_mitigations": [], "assumptions": [], "data_evidence": ["E1"],
    "trend_references": [{"url": TREND.url, "how_applied": "식사 모임 방식을 주말로 옮김"}],
}
TOO_LONG = {**DRAFT, "title": "가" * 101}


# 저장 자료의 실제 연령 조건 형태를 본뜬 자원 (대상은 20대)
AGED_RESOURCES = ExistingResources(status="available", resources=[
    ExistingResource(id="youth", name="청년 마음 모임", purpose="connection", age_ranges=[{"min": 19, "max": 64}]),
    ExistingResource(id="senior", name="노인맞춤돌봄", purpose="daily", age_ranges=[{"min": 65, "max": None}]),
    # 65세 이상 + 연령 미명시 조건(중증장애인 등). age_overlap은 unknown을 돌려주지만 연계 대상은 아니다.
    ExistingResource(id="senior-or-disabled", name="우유 안부 확인", purpose="daily",
                     age_ranges=[{"min": 65, "max": None}, {"min": None, "max": None}]),
    ExistingResource(id="no-age", name="연령 정보 없는 자원", purpose="other"),
])
GAP = GapItem(cause="C3_overall_withdrawal", coverage="gap", reason="관계형 자원 없음")


def planning_input(*, trends=(TREND,), existing=None, gaps=(GAP,), revision_targets=()):
    ctx = NodeContext(run_id=RUN_ID, mode="offline")
    return PlanningInput(run_id=RUN_ID, profile=PROFILE, causes=causes.analyze_causes(ctx, PROFILE),
                         existing=existing or ExistingResources(status="unavailable", reason="테스트"),
                         trends=list(trends), gaps=list(gaps), revision_targets=list(revision_targets))


def fake_gemini(drafts=None, text=None):
    """요청을 기록하고 정해진 응답을 돌려주는 가짜 Gemini 호출."""
    body = text if text is not None else json.dumps({"plans": drafts}, ensure_ascii=False)
    def call(request, settings):
        call.requests.append(request)
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": body}]}}]}
    call.requests = []
    return call


def revision_input():
    """첫 번째 가짜 기획안 하나만 기준 미달로 돌아온 재기획 입력."""
    base = planning_input()
    ctx = NodeContext(run_id=RUN_ID, mode="offline")
    plans = stubs.generate_plans(ctx, base)
    evaluations = stubs.evaluate_plans(ctx, plans, base)
    return planning_input(revision_targets=[(plans[0], evaluations[0])]), plans[0].plan_id


def plan_fields(schema):
    return schema["properties"]["plans"]["items"]["properties"]


class DraftSchemaTests(unittest.TestCase):
    def test_choices_are_limited_to_this_input(self):
        fields = plan_fields(planner.draft_schema(planning_input()))
        self.assertEqual(fields["data_evidence"]["items"]["enum"], [e.id for e in PROFILE.evidence])
        self.assertEqual(fields["risk_causes_addressed"]["items"]["enum"], ["C3_overall_withdrawal"])
        self.assertEqual(fields["trend_references"]["items"]["properties"]["url"]["enum"], [TREND.url])
        for fixed in ("plan_id", "target", "source", "revision", "status"):
            self.assertNotIn(fixed, fields)  # 코드가 정하는 값은 LLM에게 묻지 않는다

    def test_empty_lists_drop_the_field(self):
        fields = plan_fields(planner.draft_schema(planning_input(trends=())))
        self.assertNotIn("trend_references", fields)  # 빈 enum은 Gemini가 받지 않는다
        self.assertNotIn("linked_existing_resources", fields["operation"]["properties"])

    def test_only_confirmed_gaps_count_as_novelty(self):
        unknown = GapItem(cause="C3_overall_withdrawal", coverage="unknown", reason="확인 안 됨")
        novelty = plan_fields(planner.draft_schema(planning_input(gaps=(unknown,))))["novelty"]["properties"]
        self.assertNotIn("gap_causes", novelty)  # 확인 안 된 공백은 신규성 근거로 고를 수 없다
        partial = unknown.model_copy(update={"coverage": "partial"})
        novelty = plan_fields(planner.draft_schema(planning_input(gaps=(partial, partial))))["novelty"]["properties"]
        self.assertEqual(novelty["gap_causes"]["items"]["enum"], ["C3_overall_withdrawal"])

    def test_prompt_limits_data_kpis_to_group_level(self):
        text = planner.instructions(planning_input())
        self.assertIn("집단 전체의 월별 변화", text)
        self.assertIn("추적하는 지표는 쓰지 마라", text)

    def test_only_age_matching_resources_are_linkable(self):
        fields = plan_fields(planner.draft_schema(planning_input(existing=AGED_RESOURCES)))
        self.assertEqual(fields["operation"]["properties"]["linked_existing_resources"]["items"]["enum"],
                         ["youth", "no-age"])
        items = planner.build_context(planning_input(existing=AGED_RESOURCES))["existing_resources"]["items"]
        self.assertEqual({i["id"]: i["linkable"] for i in items},
                         {"youth": True, "senior": False, "senior-or-disabled": False, "no-age": True})
        self.assertEqual(items[0]["age_ranges"], [{"min": 19, "max": 64}])  # LLM도 연령 근거를 본다

    def test_prompt_wording_rules(self):
        text = planner.instructions(planning_input())
        self.assertIn("퍼센트로 바꿔 써라", text)
        self.assertIn("원인 코드(C1_mobility 등)는 쓰지 마라", text)
        self.assertIn("섞이면 hybrid", text)
        self.assertNotIn("-0.083", text)  # 예시 프로필 값이 프롬프트 예시로 새지 않게

    def test_existing_resource_ids_become_choices(self):
        existing = ExistingResources(status="available", resources=[ExistingResource(id="R1", name="청년 모임", purpose="connection")])
        fields = plan_fields(planner.draft_schema(planning_input(existing=existing)))
        self.assertEqual(fields["operation"]["properties"]["linked_existing_resources"]["items"]["enum"], ["R1"])

    def test_revision_asks_for_original_plan_id(self):
        planning, plan_id = revision_input()
        self.assertEqual(plan_fields(planner.draft_schema(planning))["plan_id"]["enum"], [plan_id])
        self.assertIn("재기획", planner.instructions(planning))
        self.assertEqual(planner.build_context(planning)["revision_targets"][0]["plan_id"], plan_id)

    def test_request_keeps_internal_fields_out(self):
        request = planner.build_request(planning_input())
        context = json.loads(request["contents"][0]["parts"][0]["text"])
        self.assertNotIn("related_signal", context["evidence"][0])
        self.assertEqual(request["generationConfig"]["responseSchema"]["type"], "OBJECT")


class AssembleTests(unittest.TestCase):
    def test_code_owned_values_win(self):
        sneaky = {**DRAFT, "target": {"region": "강남구", "age_group": 60, "sex": "all"}, "revision": 1}
        plan = planner.to_plan(sneaky, planning_input(), "P-x-01", revision=0)
        self.assertEqual(plan.target, PROFILE.target)
        self.assertEqual((plan.plan_id, plan.revision, plan.source), ("P-x-01", 0, "generated"))

    def test_trend_metadata_comes_from_search(self):
        plan = planner.to_plan(DRAFT, planning_input(), "P-x-01", revision=0)
        ref = plan.trend_references[0]
        self.assertEqual((ref.title, ref.grade, ref.year), (TREND.title, "public", 2026))

    def test_unknown_url_rejects_the_draft(self):
        draft = {**DRAFT, "trend_references": [{"url": "https://fake.example/x", "how_applied": "x"}]}
        with self.assertRaises(planner.PlanningError):
            planner.to_plan(draft, planning_input(), "P-x-01", revision=0)

    def test_unconfirmed_gap_claim_rejects_the_draft(self):
        unknown = GapItem(cause="C3_overall_withdrawal", coverage="unknown", reason="확인 안 됨")
        with self.assertRaises(planner.PlanningError):
            planner.to_plan(DRAFT, planning_input(gaps=(unknown,)), "P-x-01", revision=0)
        draft = {**DRAFT, "novelty": {"differs_from_existing": "공백 확인 필요"}}
        self.assertEqual(planner.to_plan(draft, planning_input(gaps=(unknown,)), "P-x-01", revision=0).novelty.gap_causes, [])

    def test_linking_age_mismatched_resource_rejects_the_draft(self):
        planning = planning_input(existing=AGED_RESOURCES)
        for rid in ("senior-or-disabled", "unknown-id"):
            draft = {**DRAFT, "operation": {"lead_candidates": [], "linked_existing_resources": [rid]}}
            with self.assertRaises(planner.PlanningError):
                planner.to_plan(draft, planning, "P-x-01", revision=0)
        ok = {**DRAFT, "operation": {"lead_candidates": [], "linked_existing_resources": ["youth"]}}
        self.assertEqual(planner.to_plan(ok, planning, "P-x-01", revision=0).operation.linked_existing_resources, ["youth"])

    def test_invalid_draft_is_dropped_with_reason(self):
        plans, notes = planner.assemble([DRAFT, TOO_LONG, DRAFT], planning_input())
        self.assertEqual([p.plan_id for p in plans], ["P-test0001-01", "P-test0001-03"])
        self.assertTrue(any("P-test0001-02" in n and "title" in n for n in notes))

    def test_extra_drafts_are_trimmed(self):
        plans, notes = planner.assemble([DRAFT] * 4, planning_input())
        self.assertEqual(len(plans), planner.PLAN_COUNT[1])
        self.assertTrue(notes)

    def test_revision_keeps_only_requested_ids(self):
        planning, plan_id = revision_input()
        drafts = [{**DRAFT, "plan_id": plan_id}, {**DRAFT, "plan_id": plan_id}, {**DRAFT, "plan_id": "P-ghost"}]
        plans, notes = planner.assemble(drafts, planning)
        self.assertEqual([(p.plan_id, p.revision) for p in plans], [(plan_id, 1)])
        self.assertEqual(len(notes), 2)  # 중복 1건 + 요청하지 않은 id 1건


class GeneratePlansTests(unittest.TestCase):
    def live(self):
        return NodeContext(run_id=RUN_ID, mode="live")

    def test_offline_uses_stub_without_calling(self):
        call = fake_gemini([DRAFT])
        plans = planner.generate_plans(NodeContext(run_id=RUN_ID, mode="offline"), planning_input(), call=call)
        self.assertEqual(call.requests, [])
        self.assertTrue(all(p.title.startswith(stubs.STUB) for p in plans))

    def test_live_calls_once_and_reports_dropped(self):
        ctx, call = self.live(), fake_gemini([DRAFT, TOO_LONG])
        plans = planner.generate_plans(ctx, planning_input(), call=call)
        self.assertEqual(len(call.requests), 1)
        self.assertEqual(len(plans), 1)
        self.assertEqual(len(ctx.warnings), 2)  # 버린 1개 + 목표 개수 미달

    def test_all_invalid_first_plan_fails(self):
        with self.assertRaises(planner.PlanningError):
            planner.generate_plans(self.live(), planning_input(), call=fake_gemini([TOO_LONG]))

    def test_unreadable_response_fails(self):
        with self.assertRaises(planner.PlanningError):
            planner.generate_plans(self.live(), planning_input(), call=fake_gemini(text="not json"))

    def test_failed_revision_returns_empty(self):
        planning, plan_id = revision_input()
        plans = planner.generate_plans(self.live(), planning, call=fake_gemini([{**TOO_LONG, "plan_id": plan_id}]))
        self.assertEqual(plans, [])  # 그래프가 원안을 유지한다

    def test_missing_key_stops_before_calling(self):
        with patch.object(planner, "configuration", return_value={"key": "", "model": "gemini-3.5-flash-lite", "search_key": ""}):
            with self.assertRaises(AgentError):
                planner.generate_plans(self.live(), planning_input())


class GraphConnectionTests(unittest.TestCase):
    def test_default_engine_is_planner(self):
        self.assertIs(Engines().generate_plans, planner.generate_plans)

    def test_dropped_reason_reaches_trace_and_warnings(self):
        offline = lambda fn: lambda ctx, *args: fn(replace(ctx, mode="offline"), *args)  # noqa: E731
        engines = replace(Engines(), recommend_existing=offline(Engines().recommend_existing),
                          search_trends=lambda ctx, planning: [],
                          generate_plans=partial(planner.generate_plans,
                                                 call=fake_gemini([{**DRAFT, "trend_references": []}, TOO_LONG])))
        state = run_pipeline(PROFILE, mode="live", engines=engines, run_id=RUN_ID)
        event = next(e for e in state["trace"] if e.node == "plan_generate" and e.status == "done")
        self.assertTrue(any("형식 오류로 제외" in r for r in event.reasons))
        self.assertTrue(any("형식 오류로 제외" in w for w in state["warnings"]))
        self.assertEqual(state["report"].status, "completed")


if __name__ == "__main__":
    unittest.main()
