"""대상 프로필: 데이터 계층(또는 담당자 입력)이 AI 로직에 넘기는 유일한 입력 형식.

데이터 재분석 결과가 어떤 모양으로 나오든, 어댑터가 이 형식으로만 바꿔 주면
원인 분석·기획·평가·화면은 수정 없이 동작한다. (설계 문서 5.1)
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "target-profile-0.2"

# 복지 추천 Agent(recommender.validate_request)와 같은 허용값을 쓴다.
Region = Literal["춘천시", "강남구"]
AgeGroup = Literal[10, 20, 30, 40, 50, 60]  # 60 = 60대 이상
Sex = Literal["male", "female", "all"]
Signal = Literal["activity_decline", "consumption_decline", "movement_decline"]

SIGNAL_LABELS = {
    "activity_decline": "소비·이동 동시 감소",
    "consumption_decline": "소비 감소",
    "movement_decline": "이동 감소",
}


class Strict(BaseModel):
    """모든 계약 모델의 공통 설정. 정의되지 않은 필드는 조용히 버리지 않고 거부한다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Target(Strict):
    region: Region
    age_group: AgeGroup
    sex: Sex = "all"

    @field_validator("age_group", mode="before")
    @classmethod
    def age_group_must_be_int(cls, value):
        # 10.0·True 같은 값을 정수로 바꿔 받지 않는다 (복지 추천 검증과 같은 기준).
        if type(value) is not int:
            raise ValueError("age_group은 정수(10, 20, … 60)여야 합니다.")
        return value


class Evidence(Strict):
    """기획안이 인용할 수 있는 근거 수치 하나. 특정 데이터 열 이름에 묶이지 않는다."""

    id: str = Field(pattern=r"^E\d{1,3}$", description="프로필 안에서 유일한 근거 번호 (E1, E2 …)")
    name: str = Field(min_length=1, max_length=100)
    # strict=True: "-8%" 같은 문자열을 숫자로 바꾸지 않고 거부한다. NaN·무한대도 거부한다.
    value: float = Field(strict=True, allow_inf_nan=False)
    unit: Literal["ratio", "percent", "count", "krw", "other"]
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    description: str = Field(min_length=1, max_length=500)
    source: Literal["telecom", "card", "public", "manual", "other"]
    related_signal: Optional[Signal] = Field(default=None, description="이 근거가 뒷받침하는 신호 (복지 추천 변환에 사용)")


class RiskInfo(Strict):
    """위험 단계 결과. 판정 상태와 단계의 조합 규칙은 복지 추천의 validate_risk와 같다."""

    level: Optional[int] = Field(default=None, ge=1, le=5)
    status: Literal["complete", "partial", "held"]
    model_version: Optional[str] = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def level_matches_status(self):
        if self.status == "complete" and self.level is None:
            raise ValueError("판정 완료(complete)에는 위험 단계(1~5)가 필요합니다.")
        if self.status == "held" and self.level is not None:
            raise ValueError("판단 보류(held)에는 위험 단계를 넣지 않습니다(null).")
        return self


class TargetProfile(Strict):
    schema_version: Literal["target-profile-0.2"] = SCHEMA_VERSION
    source: Literal["manual", "data"]
    target: Target
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="분석 기준 월 YYYY-MM")
    risk: Optional[RiskInfo] = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    signals: list[Signal] = Field(default_factory=list, max_length=3)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    is_example: bool = False

    @model_validator(mode="after")
    def unique_ids_and_signals(self):
        ids = [item.id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("근거 id가 중복되었습니다.")
        if len(self.signals) != len(set(self.signals)):
            raise ValueError("신호가 중복되었습니다.")
        if any(not text or len(text) > 1000 for text in self.limitations):
            raise ValueError("관측 제한은 1~1000자 문자열이어야 합니다.")
        return self

    def evidence_by_id(self) -> dict[str, Evidence]:
        return {item.id: item for item in self.evidence}
