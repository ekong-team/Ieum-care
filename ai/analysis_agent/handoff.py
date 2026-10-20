"""분석 결과를 정욱의 공통 계약과 원인 분석 함수에 연결하는 작은 어댑터."""
from copy import deepcopy
from ai.contracts.profile import TargetProfile
from ai.contracts.causes import CauseHypothesis
from ai.analysis_agent.inputs import digest
from ai.analysis_agent.interpretation import profile_for, team_causes_for
from ai.analysis_agent.reviewer import validate_review

def target_profile(bundle: dict, analysis_id: str) -> TargetProfile:
    """선택한 집단의 검증된 입력을 반환한다. 파일·API는 호출하지 않는다."""
    matches = [cohort for cohort in bundle["cohorts"] if cohort["analysis_id"] == analysis_id]
    if len(matches) != 1:
        raise ValueError("분석 대상이 없거나 중복입니다.")
    return TargetProfile.model_validate(matches[0]["profile"])

def make_cause_engine(bundle: dict):
    """정욱 Engines.analyze_causes(ctx, profile)에 주입할 함수를 만든다."""
    indexed = {}
    for cohort in bundle["cohorts"]:
        profile = TargetProfile.model_validate(cohort["profile"]).model_dump()
        key = digest(profile)
        if key != cohort["profile_hash"] or key in indexed:
            raise ValueError("분석 입력 해시가 다르거나 중복입니다.")
        if profile != profile_for(cohort["assessment"]) or cohort["team_causes"] != team_causes_for(cohort["assessment"]):
            raise ValueError("팀 전달 내용이 분석 근거와 다릅니다.")
        review = validate_review(cohort)
        causes = deepcopy(cohort["team_causes"])
        if review["status"] in ("executed", "fixture_only"):
            selected = review["selected_hypothesis_codes"]
            causes.sort(key=lambda cause: selected.index(cause["code"]) if cause["code"] in selected else len(selected))
            if causes:
                causes[0]["questions"] = list(dict.fromkeys(causes[0]["questions"] + review["questions"]))
        indexed[key] = causes

    def analyze_causes(context, profile: TargetProfile) -> list[CauseHypothesis]:
        # context는 정욱 노드의 공통 인자다. 추가 조회 없이 같은 분석 스냅샷만 쓴다.
        key = digest(profile.model_dump())
        if key not in indexed:
            raise ValueError("원인 가설과 대상 분석이 일치하지 않습니다.")
        return [CauseHypothesis.model_validate(deepcopy(value)) for value in indexed[key]]
    return analyze_causes
