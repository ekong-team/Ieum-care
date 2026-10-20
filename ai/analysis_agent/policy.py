"""팀과 합의할 분석 기준·집단 범위. 검증된 임상 기준이 아니다."""
from decimal import Decimal

VERSION = "activity-review-v2.2-sex-aware"
SEXES = ("all", "male", "female")
DEFAULT_BASIS = "daily"
DECLINE_THRESHOLD = Decimal("0.03")
SEVERE_THRESHOLD = Decimal("0.05")
SENSITIVITY_SCENARIOS = (
    ("monthly_3pct", {"basis": "monthly"}),
    ("daily_2pct", {"decline": "0.02"}),
    ("daily_4pct", {"decline": "0.04"}),
)
REGIONS = {"강원 춘천시": ("춘천시", "32010"), "서울 강남구": ("강남구", "11230")}
AGES = {"10대": 10, "20대": 20, "30대": 30, "40대": 40, "50대": 50, "60대이상": 60}

def age_code(age):
    """60세 이상은 원본과 기존 준비본의 60GU 코드를 유지한다."""
    value = AGES[age]
    return "60GU" if value == 60 else str(value) + "G"
KEYS = ("월", "지역", "연령대")
MOVEMENT = "통신_연령유동량_전월변화율"
CARD = "카드1_전체_결제건수"
FILTERED = "일평균_결제건수_전월변화율_골프레저제외"
LIMITATIONS = [
    "risk.level은 사회적 고립 확정 등급이 아닌 활동 위축 검토 단계",
    "월×활동지역×연령×원본 성별 구분의 집계이며 개인 고립 진단·확률이 아님",
    "통신·카드의 동일 개인 결합이 아니며 활동지역을 주민 거주지로 확정할 수 없음",
    "통신은 연령별 유동량, 소비는 카드1 개인 결제건수이며 비용·사람 수가 아님",
    "3%·5%·지속 두 번은 설계 가정으로 정답 자료를 이용해 검증한 기준이 아님",
    "일평균은 달 길이만 조정하며 휴일·계절성·인과관계를 보정하지 않음",
    "원본 성별 코드의 집계이며 실제 개인의 지원 자격·욕구를 확인한 것이 아님",
]
