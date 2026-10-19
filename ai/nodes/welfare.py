"""④-A 기존 복지자원 추천 노드. 기존 복지 추천 Agent를 공통 프로필·기획 입력에 연결한다.

1. 대상 프로필·원인 가설 → 기존 위험도 요청 + 선택적 분석 맥락으로 변환
2. live면 recommend_live(), offline이면 저장 자료 recommend() 호출
3. 실패하거나 지원하지 않는 지역이어도 그래프를 멈추지 않고 unavailable로 돌려준다 (설계 문서 4.1)
"""

from copy import deepcopy
import hashlib
import json

from ai.contracts import (SIGNAL_LABELS, ExistingResource, ExistingResources, TargetProfile, CauseHypothesis,
                          WelfareAnalysisContext, ResponseRoute, ResponseRouting)
from ai.nodes.context import NodeContext
from ai.welfare_agent.live_agent import AgentError, recommend_live
from ai.welfare_agent.recommender import recommend, validate_request


def to_welfare_payload(profile: TargetProfile, run_id: str, *, causes: list[CauseHypothesis] | None = None) -> tuple[dict, list[str]]:
    """대상 프로필을 복지 추천 Agent의 요청 형식으로 바꾼다. (요청, 경고 목록)을 돌려준다."""
    warnings = []
    target = profile.target
    if target.sex != "all":
        warnings.append("외부 검색은 성별 구분 없이 조회합니다. 성별은 분석 맥락으로만 전달하며 실제 자격 조건은 담당자가 확인하세요.")
    payload = {"target": {"region": target.region, "age_group": target.age_group, "purpose": "all"},
               "confirmed_support_needs": []}
    try:
        context = WelfareAnalysisContext(profile=profile, causes=causes or [])
    except ValueError:
        raise ValueError("복지 추천에 전달할 원인 가설의 상태·근거 참조가 올바르지 않습니다.") from None
    payload["analysis_context"] = context.model_dump(mode="json")
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


def attach_response_routes(existing: ExistingResources) -> ExistingResources:
    """추천 결과로 대응 선택지만 만든다. 위험도·우선순위·실제 자원 공백은 판정하지 않는다."""
    found = existing.status == "available" and bool(existing.resources)
    candidate_status = ("unavailable" if existing.status == "unavailable" else
                        "candidates_found" if found else "no_candidates_found")
    ids = [resource.id for resource in existing.resources] if found else []
    routes = []
    if found:
        routes.append(ResponseRoute(
            route="existing_resource_linkage", title="기존 자원 연계 검토", resource_ids=ids,
            reason="이번 조회에서 검토할 기존 자원 후보를 확보했습니다.",
            checks=["개인 신청 자격·참여 의사·현재 운영·모집 여부를 기관과 확인하세요."]))
    planning_reason = (
        "기존 후보와 함께 예방·관계 형성 또는 기존 서비스를 보완하는 새 프로그램을 검토할 수 있습니다."
        if found else "이번 조회에서 적절한 후보를 확보하지 못해 예방·관계 형성 프로그램 기획을 검토할 수 있습니다."
        if candidate_status == "no_candidates_found" else
        "기존 자원 확인이 완료되지 않았지만, 예방·관계 형성을 위한 기획 초안을 검토할 수 있습니다.")
    routes.append(ResponseRoute(
        route="preventive_planning", title="예방·신규 프로그램 기획 검토", resource_ids=ids,
        reason=planning_reason,
        checks=["기존 자원과의 중복·보완 관계와 참여 수요를 확인하세요.",
                "근거 확인 전에는 확정된 자원 부족이나 예방 효과로 제시하지 마세요."]))
    review_reason = ("후보의 자격·최신성·지역 제공 여부를 확인해야 합니다." if found else
                     "추천 0개가 실제 지역의 자원 부재를 뜻하지 않으므로 검색 범위와 제외 사유를 확인해야 합니다."
                     if candidate_status == "no_candidates_found" else
                     "검색·추천 실행이 완료되지 않아 기존 자원의 유무와 제공 조건은 아직 판단할 수 없습니다.")
    routes.append(ResponseRoute(
        route="further_review", title="추가 확인", reason=review_reason,
        checks=["검색 실패·근거 부족·조건 불일치와 실제 자원 부족을 구분하세요."]))
    routing = ResponseRouting(candidate_status=candidate_status, routes=routes,
                              notes=["대응 경로는 함께 검토할 수 있으며 자동 연계·기획 실행을 뜻하지 않습니다.",
                                     "추천 건수로 위험 단계를 높이거나 낮추지 않습니다. 지원 긴급성은 별도로 판단합니다."])
    return existing.model_copy(update={"response_routing": routing})


def to_existing_resources(result: dict, warnings: list[str]) -> ExistingResources:
    """복지 추천 응답에서 기획·공백 분석에 필요한 필드만 옮긴다."""
    resources = []
    for item in result.get("resources", []):
        source = item.get("source") or {}
        # 기획에서 바로 쓰는 항목은 공통 모델로, 전체 응답은 스냅샷으로 함께 보존한다.
        fields = {key: deepcopy(value) for key, value in item.items() if key in ExistingResource.model_fields}
        fields.update(id=str(item.get("id", "")), name=str(item.get("name", "")),
                      purpose=str(item.get("purpose", "")), source_url=source.get("url"))
        resources.append(ExistingResource.model_validate(fields))
    return attach_response_routes(ExistingResources(status="available", resources=resources,
                             warnings=warnings + [str(text) for text in result.get("warnings", [])],
                             coverage=deepcopy(result.get("coverage", {})), review=deepcopy(result.get("review", {})),
                             has_example_context=result.get("has_example_context", False),
                             recommendation=deepcopy(result)))


def recommend_existing(ctx: NodeContext, profile: TargetProfile, *, live_call=None, offline_call=None) -> ExistingResources:
    """노드 본체. live_call·offline_call은 테스트에서 가짜 함수로 바꿔 끼우기 위한 자리다."""
    offline_call = offline_call or recommend
    warnings = []
    try:
        payload, warnings = to_welfare_payload(profile, ctx.run_id, causes=ctx.cause_hypotheses)
        validate_request(payload)  # 기존 검증을 그대로 통과하는지 먼저 확인
        if ctx.mode == "live":
            # 실제 HTTP 요청 직전 콜백으로 세므로 캐시·조기 실패·HTTP 오류도 구분된다.
            result = (recommend_live(payload, on_external_call=ctx.count) if live_call is None
                      else live_call(payload))
        else:
            result = offline_call(payload)
            warnings.append("저장된 자료 조회(offline)입니다. 외부 검색·LLM을 실행하지 않았습니다.")
        result = {**result, "analysis_context": deepcopy(payload["analysis_context"]),
                  "has_example_context": bool(profile.is_example or result.get("has_example_context"))}
        return to_existing_resources(result, warnings)
    except AgentError as error:
        return attach_response_routes(ExistingResources(status="unavailable", reason=f"복지 추천 실행 실패: {error}", has_example_context=profile.is_example, warnings=warnings))
    except ValueError as error:
        return attach_response_routes(ExistingResources(status="unavailable", reason=f"복지 추천이 지원하지 않는 입력: {error}", has_example_context=profile.is_example, warnings=warnings))


def payload_preview(profile: TargetProfile, run_id: str = "preview") -> str:
    """디버깅용: 변환 결과를 사람이 읽기 좋은 JSON으로 보여 준다."""
    payload, warnings = to_welfare_payload(profile, run_id)
    return json.dumps({"payload": payload, "warnings": warnings}, ensure_ascii=False, indent=2)
