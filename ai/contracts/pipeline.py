"""그래프 중간 결과, 판단 기록, 그래프 상태. (설계 문서 5.3, 5.6)"""

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import Field, model_validator

from ai.contracts.causes import CauseCode, CauseHypothesis
from ai.contracts.evaluation import PlanEvaluation
from ai.contracts.plan import ProgramPlan
from ai.contracts.profile import Strict, TargetProfile


class WelfareAnalysisContext(Strict):
    """복지 추천에 전달할 수치·출처·원인 가설. 검색어에는 포함하지 않는다."""

    schema_version: Literal["welfare-context-0.1"] = "welfare-context-0.1"
    profile: TargetProfile
    causes: list[CauseHypothesis] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_causes(self):
        evidence_ids = set(self.profile.evidence_by_id())
        codes = [cause.code for cause in self.causes]
        if len(codes) != len(set(codes)):
            raise ValueError("원인 가설 코드가 중복되었습니다.")
        for cause in self.causes:
            if not set(cause.evidence_ids) <= evidence_ids:
                raise ValueError("원인 가설이 프로필에 없는 근거를 참조합니다.")
            if (self.profile.risk is None or self.profile.risk.status != "complete") and cause.code != "C0_unknown":
                raise ValueError("위험도 미연결·보류·불완전 상태에서는 원인 미확정만 전달합니다.")
        return self


class ExistingResource(Strict):
    """복지 추천 Agent 결과에서 기획에 필요한 부분만 옮긴 것."""

    id: str
    name: str
    purpose: str
    format: str = ""
    age_match: str = "unknown"
    source_url: Optional[str] = None
    region: str = ""
    organization: str = ""
    description: str = ""
    eligibility: str = ""
    schedule: str = ""
    application_method: str = ""
    application_url: Optional[str] = None
    age_ranges: list[dict[str, Optional[int]]] = Field(default_factory=list)
    reason: str = ""
    check: str = ""
    match_reasons: list[str] = Field(default_factory=list)
    isolation_relevance: Optional[Literal["direct", "indirect", "uncertain"]] = None
    relevance_reason: str = ""
    eligibility_status: str = "needs_confirmation"
    availability_status: str = "needs_confirmation"
    source: dict[str, Any] = Field(default_factory=dict)


class ResponseRoute(Strict):
    """배타적인 분기가 아닌, 담당자가 함께 검토할 수 있는 대응 선택지."""

    route: Literal["existing_resource_linkage", "preventive_planning", "further_review"]
    title: str
    reason: str
    resource_ids: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class ResponseRouting(Strict):
    schema_version: Literal["response-routing-0.1"] = "response-routing-0.1"
    candidate_status: Literal["candidates_found", "no_candidates_found", "unavailable"]
    routes: list[ResponseRoute]
    notes: list[str] = Field(default_factory=list)


class ExistingResources(Strict):
    status: Literal["available", "unavailable"]
    reason: Optional[str] = Field(default=None, description="unavailable일 때 이유")
    resources: list[ExistingResource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] = Field(default_factory=dict)
    has_example_context: bool = False
    recommendation: Optional[dict[str, Any]] = Field(default=None, description="검색·검증 메타데이터를 포함한 추천 응답 스냅샷")
    response_routing: Optional[ResponseRouting] = None


class TrendReference(Strict):
    title: str
    url: str = Field(pattern=r"^https?://")
    year: Optional[int] = None
    grade: Literal["public", "research", "media", "other"]
    summary: str = ""


class GapItem(Strict):
    cause: CauseCode
    coverage: Literal["covered", "partial", "gap", "unknown"]
    reason: str
    related_resource_ids: list[str] = Field(default_factory=list)


class GroundingIssue(Strict):
    plan_id: str
    kind: Literal["unknown_evidence", "unknown_url", "forbidden_phrase", "duplicate_suspected", "target_mismatch"]
    detail: str
    action: Literal["excluded", "removed_item", "warned"]


class GroundingReport(Strict):
    kept_plan_ids: list[str] = Field(default_factory=list)
    excluded_plan_ids: list[str] = Field(default_factory=list)
    issues: list[GroundingIssue] = Field(default_factory=list)


class FinalReport(Strict):
    run_id: str
    status: Literal["completed", "failed"]
    summary: str
    recommended_plan_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TraceEvent(Strict):
    """노드 하나의 판단 기록. 화면 타임라인과 '재현 가능한 설명'의 근거가 된다."""

    run_id: str
    seq: int = Field(ge=0)
    node: str
    status: Literal["started", "done", "failed", "skipped"]
    decision: str = ""
    reasons: list[str] = Field(default_factory=list)
    inputs_summary: dict[str, Any] = Field(default_factory=dict)
    llm_called: bool = False
    external_calls: dict[str, int] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, ge=0)
    at: str


class PipelineState(TypedDict, total=False):
    """LangGraph가 노드 사이에 넘기는 상태.

    trace·errors·warnings는 병렬 노드(복지 추천·트렌드 검색)가 동시에 쓰므로
    operator.add 리듀서로 '덮어쓰기' 대신 '이어 붙이기'를 한다. 나머지 필드는 한 노드만 쓴다.
    """

    run_id: str
    mode: Literal["live", "offline"]
    profile: TargetProfile
    causes: list[CauseHypothesis]
    existing_resources: ExistingResources
    trend_references: list[TrendReference]
    gaps: list[GapItem]
    plans: list[ProgramPlan]
    plans_original: list[ProgramPlan]
    grounding_report: GroundingReport
    evaluations: list[PlanEvaluation]
    evaluations_original: list[PlanEvaluation]
    revision_count: int
    report: FinalReport
    failed: bool
    revision_settled: bool  # 재기획안이 모두 제외되어 원안 결과로 마무리할 때 True
    trace: Annotated[list[TraceEvent], operator.add]
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
