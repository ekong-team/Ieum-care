"""저장 배경을 연결한다. 관측 사실·가능한 설명·미확인을 서로 구분한다."""
from copy import deepcopy
from ai.analysis_agent.inputs import number, digest
from ai.analysis_agent.interpretation import profile_for, hypotheses_for, team_causes_for

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
