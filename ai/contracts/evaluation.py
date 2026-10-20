"""기획안 평가 결과와 점수 합산 규칙. (설계 문서 5.5)

점수의 85%는 규칙으로, 15%만 LLM으로 매긴다. 같은 모델이 만들고 채점하면 점수가 후해지기 때문이다.
LLM 축이 실패하면 남은 규칙 축만으로 100점 만점으로 환산한다.
"""

from typing import Literal

from pydantic import Field, model_validator

from ai.contracts.profile import Strict

Axis = Literal["target_fit", "novelty", "grounding", "budget", "measurability", "feasibility"]

# 축별 만점 (합계 100). 팀 합의 전 초안.
AXIS_MAX = {
    "target_fit": 25,
    "novelty": 20,
    "grounding": 15,
    "budget": 15,
    "measurability": 10,
    "feasibility": 15,  # LLM 축
}
AXIS_LABELS = {
    "target_fit": "타깃 적합성",
    "novelty": "신규성",
    "grounding": "근거성",
    "budget": "예산",
    "measurability": "측정 가능성",
    "feasibility": "실현 가능성",
}
LLM_AXES = {"feasibility"}
PASS_SCORE = 60.0


class AxisScore(Strict):
    axis: Axis
    score: float = Field(ge=0, strict=True, allow_inf_nan=False)
    method: Literal["rule", "llm"]
    available: bool = True
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def within_max(self):
        if self.score > AXIS_MAX[self.axis]:
            raise ValueError(f"{AXIS_LABELS[self.axis]} 점수는 {AXIS_MAX[self.axis]}점을 넘을 수 없습니다.")
        expected = "llm" if self.axis in LLM_AXES else "rule"
        if self.method != expected:
            raise ValueError(f"{AXIS_LABELS[self.axis]}은(는) {expected} 방식 축입니다.")
        if not self.available and self.axis not in LLM_AXES:
            raise ValueError("규칙 축은 항상 평가해야 합니다. 평가를 생략할 수 있는 축은 LLM 축뿐입니다.")
        if not self.available and self.score != 0:
            raise ValueError("평가하지 못한 축(available=false)의 점수는 0이어야 합니다.")
        return self


class RevisionRequest(Strict):
    axis: Axis
    request: str = Field(min_length=1, max_length=500)


class PlanEvaluation(Strict):
    plan_id: str
    axes: list[AxisScore] = Field(min_length=len(AXIS_MAX), max_length=len(AXIS_MAX))
    total: float = Field(ge=0, le=100)
    passed: bool
    llm_axis_available: bool
    revision_requests: list[RevisionRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        if {item.axis for item in self.axes} != set(AXIS_MAX):
            raise ValueError("6개 평가 축이 정확히 한 번씩 있어야 합니다.")
        total, llm_ok = total_score(self.axes)
        if abs(total - self.total) > 0.01 or llm_ok != self.llm_axis_available or self.passed != (total >= PASS_SCORE):
            raise ValueError("총점·통과 여부가 축별 점수와 맞지 않습니다. summarize()로 만드세요.")
        return self


def total_score(axes: list[AxisScore]) -> tuple[float, bool]:
    """평가한 축의 점수 합 ÷ 평가한 축의 만점 합 × 100. LLM 축이 빠지면 85점 만점이 100점으로 환산된다."""
    available = [item for item in axes if item.available]
    max_sum = sum(AXIS_MAX[item.axis] for item in available)
    total = round(sum(item.score for item in available) / max_sum * 100, 2) if max_sum else 0.0
    llm_ok = all(item.available for item in axes if item.axis in LLM_AXES)
    return total, llm_ok


def summarize(plan_id: str, axes: list[AxisScore], revision_requests: list[RevisionRequest]) -> PlanEvaluation:
    """축별 점수로 총점과 통과 여부를 계산해 평가 결과를 만든다. 총점을 손으로 넣지 않게 한다."""
    total, llm_ok = total_score(axes)
    return PlanEvaluation(plan_id=plan_id, axes=axes, total=total, passed=total >= PASS_SCORE,
                          llm_axis_available=llm_ok, revision_requests=revision_requests)
