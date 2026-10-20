"""한수 분석 → 현지 복지 추천의 입력 제안. 기존 성별 없는 입력에 조용히 축소하지 않는다."""
from typing import Literal
from datetime import date
from pydantic import Field, model_validator, field_validator
from ai.contracts.profile import Strict, Target, RiskInfo
from ai.analysis_agent.inputs import digest
from ai.analysis_agent.interpretation import profile_for

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
    """현지와 합의할 risk-input-0.2 요청. 성별을 필수 필드로 보존한다."""
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

def to_current_aggregate_request(cohort: dict) -> dict:
    """현재 현지0.1 계약용. 남녀 개별 자료를 성별 없는 입력으로 바꾸는 것은 거부한다."""
    proposed = to_welfare_request(cohort)
    if proposed["target"]["sex"] != "all":
        raise ValueError("현재 현지 입력에는 성별 필드가 없습니다. 성별 보존 계약부터 맞춰야 합니다.")
    proposed["target"].pop("sex")
    proposed["risk_assessment"].pop("sex")
    proposed["risk_assessment"]["schema_version"] = "risk-input-0.1"
    return proposed

def handoff_record(cohort: dict) -> dict:
    """추천 입력과 상세 근거를 별도 항목에 보존한다. 내부자료를 HTTP 요청에 임의 삽입하지 않는다."""
    return dict(schema_version="analysis-welfare-handoff-0.1",
        analysis_id=cohort["analysis_id"],profile=cohort["profile"],
        request_v02=to_welfare_request(cohort),
        analysis_context={key:cohort[key] for key in (
            "assessment","team_causes","sensitivity","characteristics","background_context","interpretation","evidence_provenance")},
        profile_hash=digest(cohort["profile"]),
        integration_status="proposed_requires_receiver_update")
