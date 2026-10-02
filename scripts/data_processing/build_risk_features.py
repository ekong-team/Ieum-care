"""통신·카드 특징 결합. 실행: python scripts/data_processing/build_risk_features.py

한 행 = 월 × 가맹점/유동인구 지역 × 연령대.
위험도 학습용 특징을 만들며, 정답 라벨이나 5단계 위험도를 임의로 생성하지 않는다.
통신·카드는 동일 개인을 추적한 자료가 아니며 거주민만의 활동도 아니다.
첫 달의 전월 변화, 분모 0, 관측 없음은 NaN으로 보존한다.
모델의 결측 대체·스케일링은 이후 학습 데이터에만 fit해야 한다.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from industry_classification import RULES


# 1. 경로와 결합 기준
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
KEYS = ["월", "지역", "연령대"]
LOCATION = ["BLOCK_CD", "X_COORD", "Y_COORD"]
AGES = {"10G": "10대", "20G": "20대", "30G": "30대",
        "40G": "40대", "50G": "50대", "60GU": "60대이상"}

# 소지역코드 앞 5자리의 통계청 지역코드 사용. 행안부 코드와 다름.
# 강남구: https://sgis.kostat.go.kr/developer/upload/doc/SGIS_OpenAPI_정의서.pdf
# 춘천시: https://mlib1.kostat.go.kr/search/detail/CATTOT000000042001
# 원본의 좌표 기반 소지역과 이 코드가 일치하는지는 별도 공간 검증 대상이다.
# 주변 지역 코드를 강남/춘천으로 강제 변환하지 않는다.
REGIONS = {"11230": "서울 강남구", "32010": "강원 춘천시"}
TIME_COLS = ["TIME_FLOW_TOTAL", "FLOW_DAWN", "FLOW_DAYTIME", "FLOW_EVENING"]
WEEK_COLS = ["WEEKDAY_AVG", "WEEKEND_AVG", "WEEK_AVG"]


def safe_ratio(numerator, denominator):
    """분모가 0이거나 결측이면 비율을 계산하지 않는다."""
    return numerator / denominator.where(denominator > 0)


def check_unique(df, keys, name):
    if df[keys].isna().any().any() or df.duplicated(keys).any():
        raise ValueError(f"{name}: 결합 키에 결측 또는 중복이 있습니다.")


def check_numeric(df, columns, name):
    for col in columns:
        df[col] = pd.to_numeric(df[col], errors="raise")
    values = df[columns].to_numpy(dtype=float)
    if np.isinf(values).any() or (values < 0).any():
        raise ValueError(f"{name}: 음수 또는 무한대가 있습니다.")


def load_inputs():
    telecom = pd.read_csv(PROCESSED_DIR / "telecom_features.csv",
                          dtype={"STD_YM": str, "BLOCK_CD": str})
    card = pd.read_csv(PROCESSED_DIR / "card_features.csv",
                       dtype={key: str for key in KEYS})
    telecom = telecom.rename(columns={"STD_YM": "월"})
    age_cols = [f"FLOW_POP_{code}" for code in AGES]
    required = ["월"] + LOCATION + age_cols + ["FLOW_POP_TOTAL"] + TIME_COLS + WEEK_COLS
    missing = set(required) - set(telecom.columns)
    card_required = KEYS + ["카드1_전체_결제금액", "카드1_전체_결제건수",
                            "카드2_결제금액", "카드2_결제건수"]
    missing_card = set(card_required) - set(card.columns)
    if missing or missing_card:
        raise ValueError(f"필수 컬럼 누락: 통신 {missing}, 카드 {missing_card}")
    check_unique(telecom, ["월"] + LOCATION, "통신")
    check_unique(card, KEYS, "카드")
    for df in [telecom, card]:
        if not df["월"].str.fullmatch(r"\d{6}").all():
            raise ValueError("월은 YYYYMM 형식이어야 합니다.")
        pd.to_datetime(df["월"], format="%Y%m", errors="raise")
    if not card["연령대"].isin(AGES.values()).all():
        raise ValueError("카드에 지원하지 않는 연령대가 있습니다.")
    if not card["지역"].isin(REGIONS.values()).all():
        raise ValueError("카드 지역명과 REGIONS 설정을 확인하세요.")
    check_numeric(telecom, LOCATION[1:] + age_cols + ["FLOW_POP_TOTAL"]
                  + TIME_COLS + WEEK_COLS, "통신")
    check_numeric(card, [col for col in card if col not in KEYS], "카드")

    telecom["지역"] = telecom["BLOCK_CD"].str[:5].map(REGIONS)
    outside = telecom["지역"].isna()
    print("대상 밖 코드 제외(월별 행 수):",
          telecom.loc[outside, "BLOCK_CD"].str[:5].value_counts().to_dict())
    return telecom.loc[~outside].copy(), card


def summarize_telecom(telecom):
    """지역 합계와 관측률 생성. 기존 위치별 비율·증감률을 단순 합산하지 않음."""
    region_keys = ["월", "지역"]
    age_cols = [f"FLOW_POP_{code}" for code in AGES]
    # AGE/TIME/WEEKDAY의 관측 위치가 다르므로 각 자료별로 완전한 행을 선택.
    age_valid = telecom[age_cols + ["FLOW_POP_TOTAL"]].notna().all(axis=1)
    time_valid = telecom[TIME_COLS].notna().all(axis=1)
    week_valid = telecom[WEEK_COLS].notna().all(axis=1)
    total = telecom.groupby(region_keys).size().rename("통신_전체관측위치수")
    result = total.to_frame()
    for label, cols, valid in [("연령", age_cols + ["FLOW_POP_TOTAL"], age_valid),
                               ("시간", TIME_COLS, time_valid),
                               ("요일", WEEK_COLS, week_valid)]:
        grouped = telecom.loc[valid].groupby(region_keys)
        result = result.join(grouped[cols].sum(min_count=1))
        count_col = f"통신_{label}관측위치수"
        result[count_col] = grouped.size().reindex(result.index, fill_value=0)
        result[f"통신_{label}관측률"] = result[count_col] / total

    # 분자·분모를 같은 관측 위치에서 합산한 뒤 지역 비율을 재계산.
    for label, col in [("새벽", "FLOW_DAWN"), ("주간", "FLOW_DAYTIME"),
                       ("저녁", "FLOW_EVENING")]:
        result[f"통신_지역공통_{label}비중"] = safe_ratio(result[col], result["TIME_FLOW_TOTAL"])
    result["통신_지역공통_주말평일비"] = safe_ratio(result["WEEKEND_AVG"], result["WEEKDAY_AVG"])
    result = result.rename(columns={
        "FLOW_POP_TOTAL": "통신_지역전체유동량",
        **{col: f"통신_지역공통_{col}" for col in TIME_COLS + WEEK_COLS},
    }).reset_index()

    # 연령별 열을 행으로 펼침. 시간/요일 특징은 연령별 정보가 없어 반복됨.
    tables = []
    for code, age in AGES.items():
        part = result.drop(columns=age_cols).copy()
        part["연령대"] = age
        part["통신_연령유동량"] = result[f"FLOW_POP_{code}"]
        part["통신_연령비중"] = safe_ratio(part["통신_연령유동량"], part["통신_지역전체유동량"])
        tables.append(part)
    return pd.concat(tables, ignore_index=True)


def common_location_changes(telecom):
    """관측 위치 변화가 유동량 변화처럼 보이지 않도록 전월 공통 위치만 비교."""
    rows = []
    for region, region_df in telecom.groupby("지역"):
        by_month = {month: df for month, df in region_df.groupby("월")}
        for month, current in by_month.items():
            previous_month = str(pd.Period(month, freq="M") - 1).replace("-", "")
            previous = by_month.get(previous_month)
            paired = None if previous is None else current.merge(
                previous, on=LOCATION, suffixes=("_현재", "_전월"), validate="one_to_one")
            for code, age in AGES.items():
                row = {"월": month, "지역": region, "연령대": age,
                       "통신_전월공통위치수": 0, "통신_전월공통위치비율": np.nan,
                       "통신_연령유동량_전월변화율": np.nan}
                col = f"FLOW_POP_{code}"
                if paired is not None:
                    valid = paired[[f"{col}_현재", f"{col}_전월"]].notna().all(axis=1)
                    common = paired.loc[valid]
                    row["통신_전월공통위치수"] = len(common)
                    count = current[col].notna().sum()
                    if count > 0:
                        row["통신_전월공통위치비율"] = len(common) / count
                    before = common[f"{col}_전월"].sum(min_count=1)
                    if before > 0:
                        row["통신_연령유동량_전월변화율"] = common[f"{col}_현재"].sum() / before - 1
                rows.append(row)
    return pd.DataFrame(rows)


def add_card_features(card):
    card = card.sort_values(["지역", "연령대", "월"]).copy()
    group = card.groupby(["지역", "연령대"])
    # 카드1·2는 겹칠 수 있어 출처별로 유지. 변화율은 0.1 = 10% 증가.
    month_number = pd.to_datetime(card["월"], format="%Y%m").dt.to_period("M").astype("int64")
    adjacent = month_number.groupby([card["지역"], card["연령대"]]).diff().eq(1)
    for col in ["카드1_전체_결제금액", "카드1_전체_결제건수", "카드2_결제금액", "카드2_결제건수"]:
        before = group[col].shift(1)
        card[f"{col}_전월변화율"] = (safe_ratio(card[col], before) - 1).where(adjacent)
    for source in ["카드1_전체", "카드2"]:
        card[f"{source}_건당결제금액"] = safe_ratio(card[f"{source}_결제금액"], card[f"{source}_결제건수"])
    for col in list(card.columns):
        if col.startswith("카드1_") and "전체" not in col and col.endswith("_결제건수"):
            card[f"{col}_비중"] = safe_ratio(card[col], card["카드1_전체_결제건수"])
    # 후보 업종 합계는 실제 대인 교류가 아니라 해당 업종에서의 관측 결제다.
    # 해석보류/미분류를 포함한 전체 건수를 분모로 유지하며 비중을 부풀리지 않음.
    candidate_cols = [f"카드1_{name}_결제건수" for name, rule in RULES.items()
                      if rule[0] == "사회활동관련_후보"]
    card["카드1_사회활동관련후보_결제건수"] = card[candidate_cols].sum(axis=1, min_count=len(candidate_cols))
    candidate = card["카드1_사회활동관련후보_결제건수"]
    card["카드1_사회활동관련후보_건수비중"] = safe_ratio(candidate, card["카드1_전체_결제건수"])
    group_keys = [card["지역"], card["연령대"]]
    previous = candidate.groupby(group_keys).shift(1)
    card["카드1_사회활동관련후보_건수전월변화율"] = (safe_ratio(candidate, previous) - 1).where(adjacent)
    # 비중 변화는 상대 변화율이 아닌 차이: -0.01 = 1%p 하락.
    card["카드1_사회활동관련후보_비중전월차이"] = card["카드1_사회활동관련후보_건수비중"].groupby(group_keys).diff().where(adjacent)
    return card


def main():
    telecom, card = load_inputs()
    telecom_summary = summarize_telecom(telecom).merge(
        common_location_changes(telecom), on=KEYS, validate="one_to_one")
    # outer 결합 후 검사: 한쪽에 없는 월·지역·연령을 조용히 버리지 않는다.
    result = add_card_features(card).merge(
        telecom_summary, on=KEYS, how="outer", validate="one_to_one", indicator=True)
    if not result["_merge"].eq("both").all():
        raise ValueError("통신·카드 키 불일치:\n" + result.loc[result["_merge"] != "both", KEYS + ["_merge"]].to_string(index=False))
    result = result.drop(columns="_merge").sort_values(KEYS).reset_index(drop=True)
    check_unique(result, KEYS, "최종 결과")
    if np.isinf(result.select_dtypes(include="number").to_numpy()).any():
        raise ValueError("최종 특징에 무한대가 있습니다.")
    # 정답 라벨, 위험 점수, 결측 대체는 후속 모델 설계 단계에서 결정.
    path = PROCESSED_DIR / "risk_features.csv"
    result.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {path} / {len(result)}행 × {len(result.columns)}열")
    print("한 행 = 월 × 지역 × 연령대 / 시간·요일 특징은 지역 공통")
    print("결측치가 있는 컬럼:", result.isna().sum().loc[lambda s: s > 0].to_dict())
    print("주의: 유동량 합계는 고유 방문자 수가 아니며, 관측률·공통위치비율도 함께 확인하세요.")


if __name__ == "__main__":
    main()
