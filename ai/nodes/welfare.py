"""④-A 기존 복지자원 추천 노드. 장현지 님의 복지 추천 Agent를 수정하지 않고 감싸서 쓴다.

1. 대상 프로필 → 복지 추천 요청(risk-input-0.1 포함)으로 변환 (설계 문서 5.1 변환표)
2. live면 recommend_live(), offline이면 저장 자료 recommend() 호출
3. 실패하거나 지원하지 않는 지역이어도 그래프를 멈추지 않고 unavailable로 돌려준다 (설계 문서 4.1)
"""

import hashlib
import json

from ai.contracts import SIGNAL_LABELS, ExistingResource, ExistingResources, TargetProfile
from ai.nodes.context import NodeContext
from ai.welfare_agent.live_agent import AgentError, recommend_live
from ai.welfare_agent.recommender import recommend, validate_request


def to_welfare_payload(profile: TargetProfile, run_id: str) -> tuple[dict, list[str]]:
    """대상 프로필을 복지 추천 Agent의 요청 형식으로 바꾼다. (요청, 경고 목록)을 돌려준다."""
    warnings = []
    target = profile.target
    if target.sex != "all":
        warnings.append("복지 추천은 성별 구분 없이 조회합니다. 성별 조건은 담당자가 확인하세요.")
    payload = {"target": {"region": target.region, "age_group": target.age_group, "purpose": "all"},
               "confirmed_support_needs": []}
    if profile.risk is None:
        return payload, warnings

    digest = hashlib.sha256(profile.model_dump_json().encode("utf-8")).hexdigest()[:8]
    signals = []
    for code in profile.signals:
        related = [item.description for item in profile.evidence if item.related_signal == code]
        description = " / ".join(related) if related else f"{SIGNAL_LABELS[code]} 신호"
        signals.append({"type": code, "description": description[:1000]})
    payload["risk_assessment"] = {
        "schema_version": "risk-input-0.1",
        "assessment_id": f"{run_id}-{digest}"[:200],
        "region": target.region,
        "age_group": target.age_group,
        "period": profile.period,
        "status": profile.risk.status,
        "level": profile.risk.level,
        "signals": signals,
        "limitations": [text[:1000] for text in profile.limitations],
        "model_version": profile.risk.model_version or "manual-input",
        "is_example": profile.is_example,
    }
    return payload, warnings


def to_existing_resources(result: dict, warnings: list[str]) -> ExistingResources:
    """복지 추천 응답에서 기획·공백 분석에 필요한 필드만 옮긴다."""
    resources = []
    for item in result.get("resources", []):
        source = item.get("source") or {}
        resources.append(ExistingResource(
            id=str(item.get("id", "")), name=str(item.get("name", "")), purpose=str(item.get("purpose", "")),
            format=str(item.get("format", "")), age_match=str(item.get("age_match", "unknown")),
            source_url=source.get("url")))
    return ExistingResources(status="available", resources=resources,
                             warnings=warnings + [str(text) for text in result.get("warnings", [])][:10])


def recommend_existing(ctx: NodeContext, profile: TargetProfile, *, live_call=None, offline_call=None) -> ExistingResources:
    """노드 본체. live_call·offline_call은 테스트에서 가짜 함수로 바꿔 끼우기 위한 자리다."""
    live_call = live_call or recommend_live
    offline_call = offline_call or recommend
    try:
        payload, warnings = to_welfare_payload(profile, ctx.run_id)
        validate_request(payload)  # 기존 검증을 그대로 통과하는지 먼저 확인
        if ctx.mode == "live":
            ctx.count("tavily")
            ctx.count("gemini")
            result = live_call(payload)
        else:
            result = offline_call(payload)
            warnings.append("저장된 자료 조회(offline)입니다. 외부 검색·LLM을 실행하지 않았습니다.")
        return to_existing_resources(result, warnings)
    except AgentError as error:
        return ExistingResources(status="unavailable", reason=f"복지 추천 실행 실패: {error}")
    except ValueError as error:
        return ExistingResources(status="unavailable", reason=f"복지 추천이 지원하지 않는 입력: {error}")


def payload_preview(profile: TargetProfile, run_id: str = "preview") -> str:
    """디버깅용: 변환 결과를 사람이 읽기 좋은 JSON으로 보여 준다."""
    payload, warnings = to_welfare_payload(profile, run_id)
    return json.dumps({"payload": payload, "warnings": warnings}, ensure_ascii=False, indent=2)
