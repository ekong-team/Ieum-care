"""아직 구현 전인 노드의 가짜 구현. 그래프가 처음부터 끝까지 도는지 확인하는 용도다.

- 외부 호출을 하지 않고, 같은 입력에는 항상 같은 결과를 낸다.
- 결과에는 '[가짜]' 표시를 붙여 실제 결과로 오해하지 않게 한다.
- 실제 구현으로 바꿀 일정: 트렌드 검색·공백 분석·기획 생성·근거 검증 10/20, 평가 10/21.
"""

from ai.contracts import (AxisScore, BudgetItem, ExistingResources, GapItem, GroundingReport, KPI, Activity, Novelty,
                          Operation, PlanEvaluation, ProgramPlan, RevisionRequest, Schedule, TrendReference, summarize)
from ai.nodes.context import NodeContext

STUB = "[가짜]"


def search_trends(ctx: NodeContext, planning) -> list[TrendReference]:
    return [TrendReference(title=f"{STUB} 국내 사례", url="https://example.org/stub-domestic", grade="other",
                           summary="가짜 검색 결과"),
            TrendReference(title=f"{STUB} 해외 사례", url="https://example.org/stub-overseas", grade="other",
                           summary="가짜 검색 결과")]


def analyze_gaps(ctx: NodeContext, planning) -> list[GapItem]:
    existing: ExistingResources = planning.existing
    if existing.status != "available":
        return [GapItem(cause=c.code, coverage="unknown", reason=f"{STUB} 기존 자원 확인 불가") for c in planning.causes]
    relational = [r.id for r in existing.resources if r.purpose == "connection"]
    return [GapItem(cause=c.code, coverage="partial" if relational else "gap",
                    reason=f"{STUB} 관계 형성 목적 자원 {len(relational)}개", related_resource_ids=relational)
            for c in planning.causes]


def _plan(planning, number: int, revision: int = 0, plan_id: str | None = None) -> ProgramPlan:
    profile = planning.profile
    causes = [c.code for c in planning.causes]
    title = f"{STUB} {profile.target.region} {profile.target.age_group}대 기획안 {number}" + (" (수정)" if revision else "")
    return ProgramPlan(
        plan_id=plan_id or f"P-{planning.run_id[-8:]}-{number:02d}", source="generated", revision=revision,
        title=title, one_liner=f"{STUB} 그래프 연결 확인용", format="offline_group", target=profile.target,
        risk_causes_addressed=causes, problem_statement=f"{STUB} 문제 정의",
        data_evidence=[item.id for item in profile.evidence][:2],
        novelty=Novelty(gap_causes=[g.cause for g in planning.gaps if g.coverage == "gap"],
                        differs_from_existing=f"{STUB} 차별점"),
        activities=[Activity(name=f"{STUB} 활동", description="가짜 활동", frequency="주 1회", time_slot="평일 저녁", format="offline")],
        schedule=Schedule(duration_weeks=8, sessions=8), operation=Operation(),
        budget_items=[BudgetItem(item="운영비", unit="1회", quantity=8, unit_cost_krw=100000 if revision else None,
                                 basis="가짜 단가")],
        kpis=[KPI(name="재참여율", definition="2회 이상 참여 비율", data_source="운영 기록", measurable_by_data=False)])


def generate_plans(ctx: NodeContext, planning) -> list[ProgramPlan]:
    if planning.revision_targets:
        return [_plan(planning, 0, revision=1, plan_id=plan.plan_id) for plan, _ in planning.revision_targets]
    return [_plan(planning, 1), _plan(planning, 2)]


def check_grounding(ctx: NodeContext, plans: list[ProgramPlan], planning) -> tuple[list[ProgramPlan], GroundingReport]:
    """(통과한 기획안, 검증 리포트). 실제 구현은 통과한 기획안에서 문제 항목만 지운 수정본을 돌려줄 수 있다."""
    return plans, GroundingReport(kept_plan_ids=[p.plan_id for p in plans])


def evaluate_plans(ctx: NodeContext, plans: list[ProgramPlan], planning) -> list[PlanEvaluation]:
    """원안 1번은 통과(72점), 원안 2번은 미달(54점), 수정안은 통과(66점)하도록 고정해 재기획 루프를 확인한다."""
    results = []
    for index, plan in enumerate(plans):
        if plan.revision:
            values = (18, 14, 10, 10, 4, 10)
        elif index == 0:
            values = (20, 15, 10, 10, 5, 12)
        else:
            values = (14, 10, 8, 8, 4, 10)
        names = ("target_fit", "novelty", "grounding", "budget", "measurability", "feasibility")
        axes = [AxisScore(axis=name, score=value, method="llm" if name == "feasibility" else "rule",
                          reasons=[f"{STUB} 고정 점수"]) for name, value in zip(names, values)]
        requests = [] if sum(values) >= 60 else [RevisionRequest(axis="budget", request=f"{STUB} 단가 근거를 보완하세요")]
        results.append(summarize(plan.plan_id, axes, requests))
    return results
