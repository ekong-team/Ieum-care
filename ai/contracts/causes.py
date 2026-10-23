"""원인 코드와 원인 분석 결과. 원인 코드는 기획 쪽 개념으로 고정한다. (설계 문서 5.2)

신호·근거를 원인 코드로 바꾸는 규칙은 데이터 재분석 뒤 어댑터와 함께 확정한다.
모든 원인은 가설(hypothesis)이며, 집계 신호를 개인의 상태로 단정하지 않는다.
"""

from typing import Literal, Optional

from pydantic import Field

from ai.contracts.profile import Strict

CauseCode = Literal[
    "C0_unknown",
    "C1_mobility",
    "C2_social_consumption",
    "C3_overall_withdrawal",
    "C4_prolonged",
    "C5_weekend_gap",
]

CAUSE_LABELS = {
    "C0_unknown": "원인 미확정",
    "C1_mobility": "외출·이동 위축",
    # 분석 Agent는 전체 카드 소비 감소로 이 코드를 낸다. 관계 활동 감소로 단정하지 않도록 이름을 맞춘다 (2026-10-23).
    "C2_social_consumption": "지역 소비 활동 위축",
    "C3_overall_withdrawal": "생활 전반 위축",
    "C4_prolonged": "위축 장기화",
    "C5_weekend_gap": "주말 공백",
}


class CauseHypothesis(Strict):
    code: CauseCode
    basis: Literal["hypothesis"] = "hypothesis"
    evidence_ids: list[str] = Field(default_factory=list, description="TargetProfile.evidence의 id")
    explanation: Optional[str] = Field(default=None, max_length=1000, description="LLM 해석 문장. 실패하면 비워 둔다")
    questions: list[str] = Field(default_factory=list, description="담당자가 확인할 질문")
