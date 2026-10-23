"""2차 우선순위: 1차 위험 순위 + 집단별 기존 자원 대응 공백.

규칙으로만 정한다 (LLM 의견 없음). 원칙:
- 1차 순위(위험 단계)를 먼저 따르고, 같은 1차 순위 안에서만 공백이 큰 집단을 앞에 둔다.
- 후보 '수'를 공급량으로 쓰지 않는다. 연령이 확인된 직접 연결 자원이 '있나 없나'만 본다.
- 조회 실패·미조회는 자원이 없다고 보지 않고 순위 밖 보류 목록에 둔다.
"""

from typing import Literal, Optional

from pydantic import Field

from ai.contracts.profile import Strict, Target

SCHEMA_VERSION = "second-priority-0.1"
POLICY_VERSION = "first-rank-then-gap-tier-v1"

GapTier = Literal["G3_gap", "G2_partial", "G1_covered"]
TIER_ORDER = {"G3_gap": 0, "G2_partial": 1, "G1_covered": 2}  # 같은 1차 순위 안에서 앞에 올 순서
TIER_ROUTE = {
    "G3_gap": "preventive_planning",          # 신규 기획 우선
    "G2_partial": "linkage_and_planning",     # 기존 자원 연계 + 보완 기획
    "G1_covered": "existing_resource_linkage",  # 기존 자원 연계 우선
}
LOOKUP_DONE = ("candidates_found", "no_candidates_found")


class Candidate(Strict):
    """복지 추천 결과의 자원 하나에서 공백 판단에 필요한 값만."""

    id: str
    name: str = ""
    age_match: Literal["overlap", "partial", "unknown", "none"] = "unknown"
    purpose: Optional[str] = None  # offline 저장 자료의 지원 목적
    isolation_relevance: Optional[Literal["direct", "indirect", "uncertain"]] = None  # live AI 분류


class CohortLookup(Strict):
    """집단 하나의 1차 순위와 복지 조회 결과."""

    analysis_id: str
    target: Target
    first_rank: int = Field(ge=1)
    level: int = Field(ge=1, le=5)
    lookup_status: Literal["candidates_found", "no_candidates_found", "unavailable", "pending"]
    candidates: list[Candidate] = Field(default_factory=list)


class SecondPriorityItem(Strict):
    analysis_id: str
    target: Target
    first_rank: int
    level: int
    gap_tier: GapTier
    second_rank: int
    route: Literal["preventive_planning", "linkage_and_planning", "existing_resource_linkage"]
    direct_resource_ids: list[str] = Field(default_factory=list, description="연령이 확인된 직접 연결 자원")
    reasons: list[str]
    human_confirmation_required: Literal[True] = True


class HeldItem(Strict):
    analysis_id: str
    target: Target
    first_rank: int
    lookup_status: Literal["unavailable", "pending"]
    reason: str


class SecondPriority(Strict):
    schema_version: Literal["second-priority-0.1"] = SCHEMA_VERSION
    policy_version: str = POLICY_VERSION
    policy: str = "1차 순위 오름차순 → 같은 1차 순위 안에서 공백 등급(G3 > G2 > G1). 같은 순위·같은 등급은 공동 순위."
    ranked: list[SecondPriorityItem]
    held: list[HeldItem]
    limitations: list[str]


def is_direct(candidate: Candidate) -> bool:
    """관계 형성에 직접 쓸 수 있는 자원인지. live는 AI 연관성 분류, offline은 지원 목적으로 판단한다."""
    if candidate.isolation_relevance is not None:
        return candidate.isolation_relevance == "direct"
    return candidate.purpose == "connection"


def gap_tier(cohort: CohortLookup) -> tuple[Optional[GapTier], list[str], list[str]]:
    """집단 하나의 공백 등급. (등급, 연령 확인된 직접 자원 id, 이유). 조회가 끝나지 않았으면 등급은 None."""
    if cohort.lookup_status not in LOOKUP_DONE:
        return None, [], ["복지 조회가 끝나지 않아 자원 공백을 판단하지 않았습니다."]
    usable = [c for c in cohort.candidates if c.age_match != "none"]
    direct = [c for c in usable if is_direct(c) and c.age_match == "overlap"]
    if direct:
        return "G1_covered", [c.id for c in direct], [
            f"연령이 확인된 직접 연결 자원 {len(direct)}개: " + ", ".join(c.name or c.id for c in direct[:3]),
            "실제 운영·정원·참여 가능 여부는 기관 확인이 필요합니다."]
    if usable:
        return "G2_partial", [], [
            f"후보 {len(usable)}개가 있으나 연령이 확인된 직접 연결 자원은 없습니다.",
            "간접 지원이거나 연령 조건이 일부만 맞거나 미확인인 자원입니다."]
    return "G3_gap", [], ["조회는 성공했으나 연령이 맞는 후보가 없습니다.",
                          "등록·검색 범위에서 찾지 못했다는 뜻이며 지역에 자원이 없다는 확정은 아닙니다."]


def rank_second(cohorts: list[CohortLookup]) -> SecondPriority:
    """집단 목록 → 2차 순위. 1차 순위가 같은 집단끼리만 공백 등급으로 순서를 바꾼다."""
    ids = [c.analysis_id for c in cohorts]
    if len(ids) != len(set(ids)):
        raise ValueError("2차 순위 입력에 같은 집단이 중복되었습니다.")
    graded, held = [], []
    for cohort in cohorts:
        tier, direct_ids, reasons = gap_tier(cohort)
        if tier is None:
            held.append(HeldItem(analysis_id=cohort.analysis_id, target=cohort.target, first_rank=cohort.first_rank,
                                 lookup_status=cohort.lookup_status, reason=reasons[0]))
        else:
            graded.append((cohort, tier, direct_ids, reasons))

    graded.sort(key=lambda row: (row[0].first_rank, TIER_ORDER[row[1]], row[0].analysis_id))
    # (1차 순위, 공백 등급)이 같으면 공동 순위. 1차와 같은 밀집 순위 방식이다.
    keys = sorted({(c.first_rank, TIER_ORDER[t]) for c, t, _, _ in graded})
    rank_of = {key: index + 1 for index, key in enumerate(keys)}
    ranked = [SecondPriorityItem(analysis_id=c.analysis_id, target=c.target, first_rank=c.first_rank, level=c.level,
                                 gap_tier=t, second_rank=rank_of[(c.first_rank, TIER_ORDER[t])], route=TIER_ROUTE[t],
                                 direct_resource_ids=ids_, reasons=reasons)
              for c, t, ids_, reasons in graded]
    limitations = [
        "활동 위축 검토 순위와 등록·검색된 자원 후보로 정한 검토 순서이며 지원 자격·효과·실제 자원 부족을 확정하지 않습니다.",
        "후보 수는 공급량·정원이 아니므로 순위 계산에 쓰지 않았습니다.",
        "부분판정·보류 집단은 1차 순위에서 이미 제외되어 이 목록에도 없습니다.",
    ]
    if held:
        limitations.append(f"복지 조회가 끝나지 않은 {len(held)}개 집단은 순위 밖 보류 목록에 있습니다.")
    return SecondPriority(ranked=ranked, held=held, limitations=limitations)
