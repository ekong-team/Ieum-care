"""위험 단계만으로 1차 검토 순위를 정한다. 복지자원·모델 의견은 사용하지 않는다."""
from ai.analysis_agent.inputs import month_number
from ai.analysis_agent.policy import REGIONS, AGES, VERSION
from ai.analysis_agent.interpretation import profile_for
from ai.contracts.profile import TargetProfile

def priority_for(cohorts: list[dict], period: str, *, sexes=None) -> dict:
    """완료 판정만 정렬하고 부분판정·보류는 별도 목록으로 보존한다."""
    month_number(period)
    available = {c["assessment"].get("sex", "all") for c in cohorts}
    sexes = tuple(sexes) if sexes is not None else (("male", "female") if available & {"male", "female"} else ("all",))
    if not sexes or not set(sexes) <= {"all", "male", "female"} or "all" in sexes and len(sexes) > 1:
        raise ValueError("합산 집단과 남녀 집단을 같은 순위에 섞을 수 없습니다.")
    selected = [c for c in cohorts if c["assessment"]["month"] == period and c["assessment"].get("sex", "all") in sexes]
    if not selected:
        raise ValueError("comparison period missing")
    groups = {key: [] for key in ("ranked_cohorts", "partial_assessments", "held_cohorts")}
    targets = set()
    for cohort in selected:
        assessment = cohort["assessment"]
        profile = TargetProfile.model_validate(cohort["profile"]).model_dump()
        if profile != profile_for(assessment):
            raise ValueError("순위의 분석 수치·기준과 전달 입력이 일치하지 않습니다.")
        expected_target = dict(region=REGIONS[assessment["region"]][0],
                               age_group=AGES[assessment["age"]], sex=assessment.get("sex", "all"))
        expected_period = period[:4] + "-" + period[4:]
        if (profile["target"] != expected_target or profile["period"] != expected_period
                or profile["risk"] != dict(level=assessment["level"], status=assessment["status"], model_version=VERSION)
                or cohort["analysis_id"] != assessment["analysis_id"]):
            raise ValueError("순위 입력의 대상·기간·단계·분석 버전이 일치하지 않습니다.")
        target_key = tuple(expected_target.values())
        if target_key in targets:
            raise ValueError("duplicate priority target")
        targets.add(target_key)
        item = dict(analysis_id=cohort["analysis_id"], target=expected_target,
                    level=assessment["level"], assessment_status=assessment["status"],
                    reason=assessment["reason"], quality_warnings=assessment["quality_warnings"],
                    sensitivity=cohort["sensitivity"], human_confirmation_required=True)
        if assessment["status"] == "complete":
            groups["ranked_cohorts"].append(item)
        elif assessment["status"] == "partial":
            groups["partial_assessments"].append(item)
        elif assessment["status"] == "held":
            groups["held_cohorts"].append(item)
        else:
            raise ValueError("알 수 없는 판정 상태입니다.")

    levels = sorted({item["level"] for item in groups["ranked_cohorts"]}, reverse=True)
    rank_by_level = {level: index + 1 for index, level in enumerate(levels)}
    for item in groups["ranked_cohorts"]:
        item["rank"] = rank_by_level[item["level"]]
        item["tie_group"] = "level-" + str(item["level"])
    groups["ranked_cohorts"].sort(key=lambda item: (item["rank"], item["analysis_id"]))
    expected_targets = {(region[0], age, sex) for region in REGIONS.values() for age in AGES.values() for sex in sexes}
    return dict(
        period=period[:4] + "-" + period[4:], stage="data_review", status="provisional",
        policy_version="stage-only-dense-ties-v2", policy_status="proposed",
        policy="완료 판정의 단계 내림차순·동일 단계 공동 밀집순위. 별도 후보 제외 기준 없음.",
        scope=dict(sexes=list(sexes), observed_cohorts=len(targets), expected_cohorts=len(expected_targets),
                   coverage_complete=targets == expected_targets,
                   missing_targets=[dict(region=r, age_group=a, sex=s) for r,a,s in sorted(expected_targets-targets)]),
        limitations=[
            "활동 위축 검토 순위이며 고립 확률·확정 지원 자격이 아님",
            "부분판정·보류는 낮은 단계로 치환하지 않음",
            "민감도·품질 경고는 보존하되 순위 가중치에 사용하지 않음",
            "복지자원 추천 및 2차 필터링 제외",
        ],
        **groups,
    )
