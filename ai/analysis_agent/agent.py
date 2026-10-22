"""분석 결과의 공통 프로필과 복지추천 입력·실행 진입점."""
from ai.analysis_agent.inputs import digest
from ai.analysis_agent.interpretation import profile_for, team_causes_for
from ai.analysis_agent.model import validate_review
from ai.contracts import WelfareAnalysisContext
from ai.contracts.causes import CauseHypothesis
from ai.contracts.profile import Strict, Target, RiskInfo, TargetProfile
from ai.nodes.welfare import to_existing_resources
from ai.welfare_agent.recommender import recommend, validate_request
from copy import deepcopy
from datetime import date
from pydantic import Field, model_validator, field_validator
from typing import Literal


Sex = Literal["all","male","female"]
Purpose = Literal["all","connection","daily","wellbeing","economic","other"]

class WelfareTarget02(Target):
    sex: Sex = Field(...)
    purpose: Purpose = "all"

class SignalInput(Strict):
    type: Literal["activity_decline","consumption_decline","movement_decline"]
    description: str = Field(min_length=1,max_length=1000)

class WelfareRisk02(RiskInfo):
    schema_version: Literal["risk-input-0.2"]
    assessment_id: str = Field(min_length=1,max_length=200)
    region: Literal["춘천시","강남구"]
    age_group: Literal[10,20,30,40,50,60]
    sex: Sex
    period: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    signals: list[SignalInput] = Field(max_length=3)
    limitations: list[str] = Field(max_length=20)
    model_version: str = Field(min_length=1,max_length=200)
    is_example: bool = Field(strict=True)

    @field_validator("age_group", "level", mode="before")
    @classmethod
    def age_is_int(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("연령·단계 코드는 정수여야 합니다.")
        return value

    @field_validator("limitations")
    @classmethod
    def limitation_texts(cls, values):
        if any(not value.strip() or len(value)>1000 for value in values):
            raise ValueError("관측 제한 문장은 1~1000자여야 합니다.")
        return values

    @model_validator(mode="after")
    def signal_types_unique(self):
        if len({signal.type for signal in self.signals}) != len(self.signals):
            raise ValueError("위험 신호 유형이 중복입니다.")
        return self

    @field_validator("period")
    @classmethod
    def real_month(cls, value):
        date.fromisoformat(value + "-01")
        return value

class WelfareRequest02(Strict):
    target: WelfareTarget02
    risk_assessment: WelfareRisk02
    confirmed_support_needs: list[Literal["connection","daily","wellbeing","economic","other"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def identity_matches(self):
        target, risk = self.target,self.risk_assessment
        if (target.region,target.age_group,target.sex) != (risk.region,risk.age_group,risk.sex):
            raise ValueError("분석과 추천 대상의 지역·연령·성별이 다릅니다.")
        if len(self.confirmed_support_needs) != len(set(self.confirmed_support_needs)):
            raise ValueError("확인한 지원 필요가 중복입니다.")
        if type(risk.age_group) is not int:
            raise ValueError("연령 코드는 정수여야 합니다.")
        return self

def to_welfare_request(cohort: dict) -> dict:
    """사용자가 기준으로 확정한 risk-input-0.2 요청. 성별을 필수 필드로 보존한다."""
    profile = cohort["profile"]
    if profile != profile_for(cohort["assessment"]) or digest(profile) != cohort["profile_hash"]:
        raise ValueError("분석과 전달할 대상 정보가 다릅니다.")
    signals = []
    for code in profile["signals"]:
        related = [entry["description"] for entry in profile["evidence"] if entry["related_signal"] == code]
        signals.append(dict(type=code,description=" / ".join(related)[:1000] or code))
    payload = dict(target={**profile["target"],"purpose":"all"},risk_assessment=dict(
        schema_version="risk-input-0.2",assessment_id=cohort["analysis_id"],
        region=profile["target"]["region"],age_group=profile["target"]["age_group"],sex=profile["target"]["sex"],
        period=profile["period"],status=profile["risk"]["status"],level=profile["risk"]["level"],
        signals=signals,limitations=profile["limitations"],model_version=profile["risk"]["model_version"],
        is_example=profile["is_example"]),confirmed_support_needs=[])
    return WelfareRequest02.model_validate(payload).model_dump()



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





def recommendation_request(bundle: dict, analysis_id: str) -> dict:
    """분석 수치·성별·가설을 검증하고 현지 추천 입력을 만든다. 파일/API 호출 없음."""
    profile = target_profile(bundle, analysis_id)
    causes = make_cause_engine(bundle)(None, profile)
    cohort = next(item for item in bundle["cohorts"] if item["analysis_id"] == analysis_id)
    payload = to_welfare_request(cohort)
    payload["analysis_context"] = WelfareAnalysisContext(
        profile=profile, causes=causes,
    ).model_dump(mode="json")
    validate_request(payload)
    return payload


def recommend_from_analysis(bundle: dict, analysis_id: str, *,
                            mode: Literal["offline", "live"] = "offline") -> dict:
    """run_analysis() 반환값을 그대로 받는다. live일 때만 실제 외부 API를 사용한다."""
    if mode not in ("offline", "live"):
        raise ValueError("mode는 offline 또는 live여야 합니다.")
    payload = recommendation_request(bundle, analysis_id)
    if mode == "live":
        from ai.welfare_agent.live_agent import recommend_live
        result = recommend_live(payload)
    else:
        result = {**recommend(payload), "mode": "offline"}
        result["warnings"].insert(0, "저장된 자원 후보 조회입니다. 외부 검색·LLM을 실행하지 않았습니다.")
    result["response_routing"] = to_existing_resources(result, []).response_routing.model_dump(mode="json")
    return result
