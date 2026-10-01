from pathlib import Path

import pandas as pd


# 1. 폴더 설정
# 이 파일 위치: Ieum-care/ai/risk_model/01_eda_card.py
repo_dir = Path(__file__).resolve().parents[2]

# 원본 데이터는 Ieum-care 바깥의 기존 폴더에 있음
data_dir = (
    repo_dir.parent
    / "2026빅콘테스트_신한카드_데이터_레이아웃"
)

# 결과 CSV는 Git 업로드에서 제외되는 폴더에 저장
output_dir = repo_dir / "data" / "processed"
output_dir.mkdir(parents=True, exist_ok=True)


# 2. 공통 연령 구간과 업종 그룹 정의
age_mapping = {
    "60대": "60대이상",
    "70대": "60대이상",
    "80대": "60대이상",
    "90대": "60대이상"
}

# 초기 분류이며, 목록에 없는 업종은 미분류로 보존
industry_groups = {
    "외식·카페": [
        "한식", "중식", "일식", "양식",
        "기타요식", "패스트푸드", "커피전문점", "제과점"
    ],
    "문화·오락": [
        "영화/공연", "노래방", "게임방/오락실"
    ],
    "운동": [
        "헬스장", "스포츠시설", "실내/실외골프장"
    ]
}


# 3. 카드 데이터1 읽기
card1 = pd.read_csv(
    data_dir / "신한카드_빅콘테스트2026_데이터1.txt",
    sep="\t",
    encoding="cp949",
    dtype=str
)


# 4. 법인 표시 일치 확인 후 개인 기록 선택
sex_corp = card1["SEX_CCD"] == "법인"
age_corp = card1["AGE_CCD"] == "법인"

if (sex_corp != age_corp).any():
    raise ValueError("카드1의 성별·연령 법인 표시가 일치하지 않습니다.")

card1_personal = card1[~sex_corp].copy()


# 5. 카드1 정제
card1_personal["월"] = card1_personal["TA_YMD"].str[:6]

card1_personal["연령대"] = (
    card1_personal["AGE_CCD"]
    .str.replace(" ", "", regex=False)
    .replace(age_mapping)
)

for col in ["TS_AT", "USE_CNT"]:
    card1_personal[col] = pd.to_numeric(
        card1_personal[col],
        errors="raise"
    )


# 6. 카드1: 월 × 가맹점 지역 × 연령별 전체 소비
card_monthly = (
    card1_personal
    .groupby(
        ["월", "MCT_SGG_CD", "연령대"],
        as_index=False,
        dropna=False
    )[["TS_AT", "USE_CNT"]]
    .sum()
    .rename(columns={
        "MCT_SGG_CD": "지역",
        "TS_AT": "카드_결제금액",
        "USE_CNT": "카드_결제건수"
    })
)


# 7. 카드1: 월 × 가맹점 지역 × 연령 × 원래 업종
card_by_industry = (
    card1_personal
    .groupby(
        ["월", "MCT_SGG_CD", "연령대", "MCT_RY_CD"],
        as_index=False,
        dropna=False
    )[["TS_AT", "USE_CNT"]]
    .sum()
    .rename(columns={
        "MCT_SGG_CD": "지역",
        "MCT_RY_CD": "업종",
        "TS_AT": "카드_결제금액",
        "USE_CNT": "카드_결제건수"
    })
)


# 8. 카드1 업종 그룹 지정
card_by_industry["업종그룹"] = "미분류"

for group_name, industries in industry_groups.items():
    card_by_industry.loc[
        card_by_industry["업종"].isin(industries),
        "업종그룹"
    ] = group_name


# 9. 카드1: 월 × 가맹점 지역 × 연령 × 업종그룹
card_by_group = (
    card_by_industry
    .groupby(
        ["월", "지역", "연령대", "업종그룹"],
        as_index=False,
        dropna=False
    )[["카드_결제금액", "카드_결제건수"]]
    .sum()
)


# 10. 카드1 집계 전후 합계 확인
for source_col, result_col in [
    ("TS_AT", "카드_결제금액"),
    ("USE_CNT", "카드_결제건수")
]:
    original_total = card1_personal[source_col].sum()

    for table in [card_monthly, card_by_industry, card_by_group]:
        if table[result_col].sum() != original_total:
            raise ValueError(
                f"카드1 {result_col}의 집계 전후 합계가 다릅니다."
            )


# 11. 카드 데이터2 읽기
card2 = pd.read_csv(
    data_dir / "신한카드_빅콘테스트2026_데이터2.txt",
    sep="\t",
    encoding="cp949",
    dtype=str
)


# 12. 카드2 정제
# 데이터2는 정의서상 법인 결제가 제외된 자료
card2_clean = card2.copy()

card2_clean["월"] = card2_clean["TA_YMD"].str[:6]

card2_clean["연령대"] = (
    card2_clean["AGE_CCD"]
    .str.replace(" ", "", regex=False)
    .replace(age_mapping)
)

for col in ["TS_AT", "USE_CNT"]:
    card2_clean[col] = pd.to_numeric(
        card2_clean[col],
        errors="raise"
    )


# 13. 카드2: 월 × 가맹점 지역 × 고객 거주지 × 연령
# 고객 거주지의 '정보없음'과 결측값도 포함
card2_monthly = (
    card2_clean
    .groupby(
        ["월", "MCT_SGG_CD", "CLN_SGG_CD", "연령대"],
        as_index=False,
        dropna=False
    )[["TS_AT", "USE_CNT"]]
    .sum()
    .rename(columns={
        "MCT_SGG_CD": "가맹점지역",
        "CLN_SGG_CD": "고객거주지",
        "TS_AT": "카드2_결제금액",
        "USE_CNT": "카드2_결제건수"
    })
)


# 14. 카드2 집계 전후 합계 확인
for source_col, result_col in [
    ("TS_AT", "카드2_결제금액"),
    ("USE_CNT", "카드2_결제건수")
]:
    if card2_clean[source_col].sum() != card2_monthly[result_col].sum():
        raise ValueError(
            f"카드2 {result_col}의 집계 전후 합계가 다릅니다."
        )


# 15. 결과 저장
outputs = {
    "card1_monthly_region_age.csv": card_monthly,
    "card1_monthly_region_age_industry.csv": card_by_industry,
    "card1_monthly_region_age_group.csv": card_by_group,
    "card2_monthly_region_residence_age.csv": card2_monthly
}

for filename, table in outputs.items():
    table.to_csv(
        output_dir / filename,
        index=False,
        encoding="utf-8-sig"
    )


# 16. 실행 결과 요약
print("카드1 원본:", card1.shape)
print("카드1 개인 기록:", card1_personal.shape)
print("카드2 원본:", card2.shape)
print("카드1·2 각각 집계 전후 금액·건수 합계 일치")

for filename, table in outputs.items():
    print(f"저장 완료: {filename} / {table.shape}")

print("결과 저장 폴더:", output_dir)