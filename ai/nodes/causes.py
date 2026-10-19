"""③ 원인 분석 노드의 규칙 부분: 신호 → 원인 가설.

⚠️ 임시 규칙이다. 데이터 재분석 결과가 나오면 장현지 님과 함께 확정한다 (설계 문서 5.2, 13장).
LLM 해석 문장(explanation)은 10/21에 추가한다. 지금은 규칙 결과만 낸다.
"""

from ai.contracts import CauseHypothesis, TargetProfile
from ai.nodes.context import NodeContext

RULES_VERSION = "cause-rules-provisional-0.1"


def _evidence_for(profile: TargetProfile, *signals: str) -> list[str]:
    return [item.id for item in profile.evidence if item.related_signal in signals]


def analyze_causes(ctx: NodeContext, profile: TargetProfile) -> list[CauseHypothesis]:
    risk = profile.risk
    # 위험도가 없거나 보류·부분 판정이면 원인 가설을 만들지 않는다 (복지 추천 build_review와 같은 원칙).
    if risk is None or risk.status != "complete" or not profile.signals:
        return [CauseHypothesis(code="C0_unknown", questions=["위험 판정이 없거나 확정되지 않았습니다. 관측 제한과 실제 상황을 먼저 확인하세요."])]

    signals = set(profile.signals)
    causes = []
    both = "activity_decline" in signals or {"consumption_decline", "movement_decline"} <= signals
    if both:
        causes.append(CauseHypothesis(
            code="C3_overall_withdrawal",
            evidence_ids=_evidence_for(profile, "activity_decline", "consumption_decline", "movement_decline"),
            questions=["소비와 이동이 함께 줄어든 이유(계절·이사·건강 등)를 확인했나요?"]))
    elif "movement_decline" in signals:
        causes.append(CauseHypothesis(code="C1_mobility", evidence_ids=_evidence_for(profile, "movement_decline"),
                                      questions=["이동 감소가 접근성·건강 제약 때문인지 확인했나요?"]))
    elif "consumption_decline" in signals:
        causes.append(CauseHypothesis(code="C2_social_consumption", evidence_ids=_evidence_for(profile, "consumption_decline"),
                                      questions=["소비 감소만으로 경제적 어려움을 확정하지 않습니다. 관계형 활동 감소인지 확인하세요."]))
    if risk.level is not None and risk.level >= 4:
        causes.append(CauseHypothesis(code="C4_prolonged", evidence_ids=[item.id for item in profile.evidence],
                                      questions=["감소가 연속으로 유지된 기간과 기존 지원 이력을 확인했나요?"]))
    return causes or [CauseHypothesis(code="C0_unknown")]
