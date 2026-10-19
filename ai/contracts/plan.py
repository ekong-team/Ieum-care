"""신규 프로그램 기획안. 기획 Agent의 출력이자 평가 Agent의 입력이다. (설계 문서 5.4)

담당자가 직접 쓴 기획안도 같은 모델로 받는다(source="manual").
여기서는 '형식'만 검사한다. 인용 수치·URL이 실제 근거와 맞는지는 근거 검증 노드가 따로 확인한다.
"""

from typing import Literal, Optional

from pydantic import Field

from ai.contracts.causes import CauseCode
from ai.contracts.profile import Strict, Target

PLAN_SCHEMA_VERSION = "program-plan-0.2"
MAX_REVISIONS = 1  # 재기획은 최대 1회 (설계 문서 4.1). 그래프 분기와 revision 필드가 같은 값을 쓴다.


class Activity(Strict):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    frequency: str = Field(min_length=1, max_length=50, description="예: 주 1회")
    time_slot: str = Field(min_length=1, max_length=50, description="예: 평일 19~21시")
    format: Literal["offline", "online", "hybrid"]


class Schedule(Strict):
    duration_weeks: int = Field(ge=1, le=52)
    sessions: int = Field(ge=1, le=200)


class Operation(Strict):
    lead_candidates: list[str] = Field(default_factory=list, description="운영 주체 후보. 확인 전이면 '(확인 필요)' 표시")
    linked_existing_resources: list[str] = Field(default_factory=list, description="연계할 기존 자원 id")


class BudgetItem(Strict):
    item: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=50, description="예: 1인 1회")
    quantity: float = Field(gt=0, strict=True, allow_inf_nan=False)
    # 단가를 모르면 숫자를 지어내지 말고 null로 둔다. 평가 단계에서 단가 미확정으로 다룬다.
    unit_cost_krw: Optional[int] = Field(default=None, ge=0)
    basis: str = Field(min_length=1, max_length=300, description="단가 근거 또는 '단가 확인 필요'")


class KPI(Strict):
    name: str = Field(min_length=1, max_length=100)
    definition: str = Field(min_length=1, max_length=300)
    data_source: str = Field(min_length=1, max_length=100, description="예: 운영 기록, 카드 데이터")
    measurable_by_data: bool = Field(description="제공 데이터(통신·카드 등)로 측정 가능한 지표인지")


class TrendRef(Strict):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(pattern=r"^https?://", max_length=500)
    year: Optional[int] = Field(default=None, ge=2000, le=2100)
    grade: Literal["public", "research", "media", "other"]
    how_applied: str = Field(min_length=1, max_length=500, description="이 사례를 우리 대상에 어떻게 바꿔 적용했는지")


class Novelty(Strict):
    gap_causes: list[CauseCode] = Field(default_factory=list, description="이 기획이 채우는 공백 원인")
    differs_from_existing: str = Field(min_length=1, max_length=500)


class RiskMitigation(Strict):
    risk: str = Field(min_length=1, max_length=300)
    mitigation: str = Field(min_length=1, max_length=300)


class ProgramPlan(Strict):
    schema_version: Literal["program-plan-0.2"] = PLAN_SCHEMA_VERSION
    plan_id: str = Field(pattern=r"^P-[A-Za-z0-9-]{1,40}$")
    source: Literal["generated", "manual"]
    revision: int = Field(default=0, ge=0, le=MAX_REVISIONS, description="0=원안, 1=재기획안")
    title: str = Field(min_length=1, max_length=100)
    one_liner: str = Field(min_length=1, max_length=200)
    format: Literal["offline_group", "online", "hybrid", "outreach", "linked"]
    target: Target
    risk_causes_addressed: list[CauseCode] = Field(min_length=1)
    problem_statement: str = Field(min_length=1, max_length=1500)
    data_evidence: list[str] = Field(default_factory=list, description="TargetProfile.evidence의 id 목록")
    novelty: Novelty
    activities: list[Activity] = Field(min_length=1, max_length=10)
    schedule: Schedule
    operation: Operation
    recruitment: list[str] = Field(default_factory=list, max_length=10)
    budget_items: list[BudgetItem] = Field(min_length=1, max_length=20)
    kpis: list[KPI] = Field(min_length=1, max_length=10)
    trend_references: list[TrendRef] = Field(default_factory=list, max_length=10)
    risks_and_mitigations: list[RiskMitigation] = Field(default_factory=list, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    status: Literal["draft_needs_review"] = "draft_needs_review"
