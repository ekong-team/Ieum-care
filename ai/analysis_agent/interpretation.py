"""정욱의 공통 입력과 근거에 한정한 원인 가설을 만든다."""
from ai.contracts.profile import TargetProfile
from ai.contracts.causes import CauseHypothesis
from ai.analysis_agent.policy import VERSION, REGIONS, AGES, LIMITATIONS, DEFAULT_BASIS, DECLINE_THRESHOLD, SEVERE_THRESHOLD

def profile_for(record):
    """기본 일평균 판정만 팀에 전달한다. 민감도 결과를 기본 판정으로 바꾸지 않는다."""
    expected_policy = dict(basis=DEFAULT_BASIS, decline_ratio=float(DECLINE_THRESHOLD), severe_ratio=float(SEVERE_THRESHOLD))
    if record.get("policy") != expected_policy:
        raise ValueError("민감도 시나리오를 기본 판정 입력으로 전달할 수 없습니다.")
    evidence = []
    period = record["month"][:4] + "-" + record["month"][4:]
    for key, eid, name, source, signal in [
        ("card_change", "E1", "카드1 개인 결제건수 일평균 전월 변화율", "card", "consumption_decline"),
        ("movement_change", "E2", "공통 관측 위치 연령 유동량 전월 변화율", "telecom", "movement_decline")]:
        if record[key] is not None:
            evidence.append(dict(id=eid, name=name, value=float(record[key]), unit="ratio", period=period,
                description=f"{period} {name}: {record[key] * 100:+.2f}%. 표시값은 반올림이며 판정은 원래 값 사용. 활동지역 집계로 개인 고립·욕구를 확정하지 않음",
                source=source, related_signal=signal))
    if record["status"] != "held":
        evidence.append(dict(id="E3", name="관측 가능한 동시 감소 연속 전월 비교 횟수",
            value=float(record["consecutive_joint_comparisons"]), unit="count", period=period,
            description=f"관측 가능한 동시 감소 전월 비교 {record['consecutive_joint_comparisons']}회. 전월 비교 두 번에는 원자료 세 달이 필요; 만성 고립 기간이 아님", source="other",
            related_signal="activity_decline" if record["conditions"]["joint_decline"] is True else None))
    flags = record["conditions"]
    signals = []
    if flags["consumption_decline"] is True: signals.append("consumption_decline")
    if flags["movement_decline"] is True: signals.append("movement_decline")
    if flags["joint_decline"] is True: signals.append("activity_decline")
    value = dict(schema_version="target-profile-0.2", source="data",
        target=dict(region=REGIONS[record["region"]][0], age_group=AGES[record["age"]], sex=record.get("sex", "all")),
        period=period, risk=dict(level=record["level"], status=record["status"], model_version=VERSION),
        evidence=evidence, signals=signals,
        limitations=LIMITATIONS + ["성별 범위: " + record.get("sex", "all"), record["reason"]] + record["quality_warnings"], is_example=False)
    return TargetProfile.model_validate(value).model_dump()

def hypotheses_for(record):
    refs = {e["id"] for e in profile_for(record)["evidence"]}
    flags, result = record["conditions"], []
    def add(code, label, evidence, question):
        result.append(dict(code=code, basis="hypothesis", label=label, evidence_ids=evidence,
            questions=[question], interpretation="관측 신호의 해석 가설이며 실제 고립 원인·개인 욕구는 미확정"))
    if record["status"] != "complete":
        add("C0_unknown", "원인 미확정", [], "누락 자료·지속성 이력을 확인할 수 있나요?")
    else:
        if flags["joint_decline"] is True:
            add("C3_overall_withdrawal", "소비·관측 유동량의 동반 위축", ["E1", "E2"], "방문객·업종 구성·관측 범위 변화가 동반됐나요?")
        else:
            if flags["movement_decline"] is True:
                add("C1_mobility", "관측 유동량 위축", ["E2"], "관측 범위나 지역 방문 패턴 변화가 있었나요?")
            if flags["consumption_decline"] is True:
                # 팀의 코드명을 유지하지만 전체 카드 소비를 실제 관계 활동으로 단정하지 않는다.
                add("C2_social_consumption", "지역 소비 활동 위축", ["E1"], "업종 구성·소비 장소·온라인 소비로의 변화가 있었나요?")
        if flags["persistent"] is True:
            add("C4_prolonged", "동시 감소 신호 지속", ["E1", "E2", "E3"], "지속 감소가 지역 행사·계절·관측 변화와 겹치나요?")
        if not result:
            add("C0_unknown", "현재 기준의 원인 가설 없음", [], "추가 확인이 필요한 집단 특성이 있나요?")
    if not all(set(h["evidence_ids"]) <= refs for h in result):
        raise ValueError("가설이 없는 근거를 참조합니다.")
    return result

def team_causes_for(record: dict) -> list[dict]:
    """팀 CauseHypothesis 형식으로 변환한다. 추가 필드는 공통 계약에 끼워 넣지 않는다."""
    return [CauseHypothesis.model_validate(dict(
        code=hypothesis["code"], basis="hypothesis", evidence_ids=hypothesis["evidence_ids"],
        explanation=hypothesis["label"] + ": " + hypothesis["interpretation"],
        questions=hypothesis["questions"],
    )).model_dump() for hypothesis in hypotheses_for(record)]
