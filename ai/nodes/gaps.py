"""공백 분석 노드 (설계 문서 부록 A P3): 원인 가설마다 기존 자원으로 대응되고 있는지 규칙으로 판정한다.

LLM을 쓰지 않는다. 같은 입력에 같은 결과가 나오고, offline에서도 진짜 결과가 나온다.
결과는 기획 생성의 신규성 근거 선택지(planner.open_gaps)와 평가의 신규성 축 입력이 된다.

    covered  대응 자원이 있고 대상 연령이 확인됨
    partial  대응 자원이 있지만 연령이 일부만 맞거나 미확인
    gap      대응 자원이 없음 (등록·검색 범위에서 찾지 못했다는 뜻이며 지역에 없다는 확정은 아님)
    unknown  기존 자원 조회 실패
"""

from ai.contracts import CAUSE_LABELS, ExistingResource, ExistingResources, GapItem
from ai.nodes.context import NodeContext

# 직접 연결 자원 외에 원인별로 대응 자원으로 인정하는 지원 목적.
# C1 외출·이동 위축은 찾아가는 일상 지원도, C4 위축 장기화는 정서·심리 지원도 대응으로 본다.
EXTRA_SUPPORT = {
    "C1_mobility": {"daily"},
    "C4_prolonged": {"wellbeing"},
}


def is_direct(resource: ExistingResource) -> bool:
    """관계 형성에 직접 쓸 수 있는 자원인지. live는 AI 연관성 분류, offline은 지원 목적으로 판단한다.

    2차 우선순위(ai/orchestrator/second_priority.py)와 같은 기준이다. 두 브랜치가 병합되면 하나로 합친다.
    """
    if resource.isolation_relevance is not None:
        return resource.isolation_relevance == "direct"
    return resource.purpose == "connection"


def addresses(resource: ExistingResource, cause: str) -> bool:
    """이 자원이 이 원인에 대응하는지. 대상 연령이 전혀 맞지 않는 자원은 대응으로 보지 않는다."""
    if resource.age_match == "none":
        return False
    return is_direct(resource) or resource.purpose in EXTRA_SUPPORT.get(cause, set())


def gap_for(cause: str, existing: ExistingResources) -> GapItem:
    """원인 하나의 공백 판정."""
    label = CAUSE_LABELS[cause]
    if existing.status != "available":
        return GapItem(cause=cause, coverage="unknown",
                       reason=f"{label}: 기존 자원을 확인하지 못해 공백을 판단하지 않았습니다. ({existing.reason or '사유 미상'})")
    matched = [r for r in existing.resources if addresses(r, cause)]
    confirmed = [r for r in matched if r.age_match == "overlap"]
    if confirmed:
        names = ", ".join(r.name for r in confirmed[:3])
        return GapItem(cause=cause, coverage="covered", related_resource_ids=[r.id for r in confirmed],
                       reason=f"{label}: 대상 연령이 확인된 대응 자원이 있습니다 ({names}). 실제 운영·정원은 기관 확인이 필요합니다.")
    if matched:
        names = ", ".join(r.name for r in matched[:3])
        return GapItem(cause=cause, coverage="partial", related_resource_ids=[r.id for r in matched],
                       reason=f"{label}: 대응 자원이 있으나 대상 연령이 일부만 맞거나 확인되지 않았습니다 ({names}).")
    return GapItem(cause=cause, coverage="gap",
                   reason=f"{label}: 조회된 기존 자원 중 대응 자원이 없습니다. 등록·검색 범위의 결과이며 지역에 없다는 확정은 아닙니다.")


def analyze_gaps(ctx: NodeContext, planning) -> list[GapItem]:
    """그래프 gap_analysis 노드의 계산 함수 (Engines.analyze_gaps 자리). 외부 호출 없음."""
    return [gap_for(cause.code, planning.existing) for cause in planning.causes]
