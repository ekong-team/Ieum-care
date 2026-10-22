"""수치 근거·원인 가설·인구와 달력 배경을 정리한다."""
from ai.analysis_agent.inputs import VERSION, REGIONS, AGES, LIMITATIONS, DEFAULT_BASIS, DECLINE_THRESHOLD, SEVERE_THRESHOLD, number, digest
from ai.contracts.causes import CauseHypothesis
from ai.contracts.profile import TargetProfile
from copy import deepcopy


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



FEATURE_KEYS = (
    "과거3개월대비변화율", "지역전체_소비전월변화율", "소비_지역전체대비차이",
    "후보업종_비교가능수", "후보업종_감소수_3퍼센트", "업종민감도주의",
)

def background_for(record: dict, raw: dict | None) -> dict:
    """배경 일부만 있어도 전체가 확인된 것처럼 표시하지 않는다."""
    keys = ("resident_population", "prior_resident_population", "population_mom_change", "calendar_context")
    values = {key: deepcopy(raw[key]) for key in keys if raw and raw.get(key) is not None}
    for key in ("resident_population", "prior_resident_population"):
        value = number(values.get(key), minimum=0)
        if value is not None and value != value.to_integral_value():
            raise ValueError("주민등록 인구는 정수여야 합니다.")
        if value is not None:
            values[key] = int(value)
    change = number(values.get("population_mom_change"), minimum=-1)
    if change is not None:
        values["population_mom_change"] = float(change)
    current, previous = values.get("resident_population"), values.get("prior_resident_population")
    if change is not None and current is not None and previous is not None and previous > 0:
        if abs(float(change) - (current / previous - 1)) > 1e-9:
            raise ValueError("인구 변화율과 인구 수가 일치하지 않습니다.")
    calendar = values.get("calendar_context")
    if calendar is not None:
        from calendar import monthrange
        if calendar.get("month") != record["month"] or calendar.get("days") != monthrange(int(record["month"][:4]), int(record["month"][4:]))[1]:
            raise ValueError("달력 배경의 기준월·일수가 다릅니다.")
    missing = [key for key in keys if key not in values]
    return dict(status="unavailable" if not values else "partial" if missing else "available",
                usage="background_only", values=values, missing_fields=missing,
                limitations=["주민 인구를 위험 인원·유동량의 모집단으로 사용하지 않음", "단계 재가중·인과 확정에 사용하지 않음"])

def describe_cohort(record: dict, raw: dict | None, sensitivity: list[dict]) -> dict:
    """원래 분석과 배경의 집단·변화율이 맞을 때만 특성을 함께 제공한다."""
    source = {}
    if raw is not None:
        source = raw["analysis_evidence"]
        actual_key = (source["월"], source["지역"], source["연령대"], source.get("성별", "all"))
        if actual_key != (record["month"], record["region"], record["age"], record.get("sex", "all")):
            raise ValueError("context identity mismatch")
        for old_key, new_key in (
            ("소비_일평균건수_전월변화율", "card_change"),
            ("통신_연령유동량_전월변화율", "movement_change"),
        ):
            old_value, new_value = number(source.get(old_key)), record[new_key]
            if ((old_value is None) != (new_value is None)
                    or old_value is not None and abs(float(old_value) - new_value) > 1e-9):
                raise ValueError("stale context evidence")
    background = background_for(record, raw)
    trait_values = {key: source.get(key) for key in FEATURE_KEYS} if raw else {}
    missing_traits = [key for key in FEATURE_KEYS if trait_values.get(key) is None]
    characteristics = dict(
        source_role="context_packet",
        availability="unavailable" if len(missing_traits) == len(FEATURE_KEYS) else "partial" if missing_traits else "available",
        values=trait_values, missing_fields=missing_traits,
        comparison_sex=record.get("sex", "all"),
        interpretation="동일 집단의 반복 관측·지역 구성 비교이며 독립 표본이나 인과 효과가 아님",
    )
    notes = []
    population_change = background["values"].get("population_mom_change")
    if population_change is not None and record["conditions"]["joint_decline"] is True:
        notes.append("인구 감소가 동반됨; 활동 감소의 원인이라는 뜻은 아님" if population_change < 0
                     else "인구가 감소하지 않은 상태에서 활동 지표는 감소; 인구 감소만으로 단순 설명 불가")
    region_change = characteristics["values"].get("지역전체_소비전월변화율")
    if region_change is not None and record["card_change"] is not None:
        notes.append("같은 성별 범위의 지역 전체 소비도 감소하여 지역 공통 변화와 집단 특성을 함께 확인해야 함" if region_change <= -.03
                     else "지역 전체와 해당 연령 집단의 소비 변화 차이를 확인해야 함")
    profile = profile_for(record)
    return dict(
        analysis_id=record["analysis_id"], assessment=record, analysis_hash=digest(record),
        profile=profile, profile_hash=digest(profile), sensitivity=sensitivity,
        team_causes=team_causes_for(record),
        characteristics=characteristics, background_context=background, context_hash=digest(background),
        interpretation=dict(
            observed=record["reason"], hypotheses=hypotheses_for(record),
            causal_status="not_established", contextual_observations=notes,
            possible_influence_factors=[
                dict(factor="인구 구성 변화", status="background_only" if population_change is not None else "unavailable",
                     role="대안 설명 검토; 인과관계 미검증"),
                dict(factor="달 길이·휴일·계절", status="partially_observed",
                     role="일평균은 달 길이만 반영; 장기 계절성 미확인"),
                dict(factor="업종·방문객·관측 범위 변화", status="needs_confirmation",
                     role="구성 변화와 실제 활동 변화 구분 필요"),
            ],
            wording_method="evidence_bound_templates",
        ),
        evidence_provenance={
            evidence["id"]: dict(
                source_role="features", formula={
                    "E1": "(현재 건수/현재 달력일수)/(전월 건수/전월 달력일수)-1",
                    "E2": "기존 특징의 인접 월 공통 위치 연령 유동량 변화율",
                    "E3": "인접한 전월 비교 중 소비·유동량이 함께 3% 이상 감소한 연속 횟수",
                }[evidence["id"]],
            ) for evidence in profile["evidence"]
        },
    )
