"""통신 3종의 월별 특징 생성. 어느 작업 폴더에서 실행해도 동일한 경로를 사용한다.

한 행 = 월 × 소지역코드 × X좌표 × Y좌표. 원본의 완전 중복만 제거한다.
AGE/TIME/WEEKDAY 관측 위치 차이는 outer 결합으로 보존하며 0으로 채우지 않는다.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from data_contract import AGES, MONTHS, require_columns, require_keys, require_numbers

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data" / "raw"
OUTPUT_FILE = REPO / "data" / "processed" / "telecom_features.csv"
LOCATION_COLS = ["BLOCK_CD", "X_COORD", "Y_COORD"]
KEY_COLS = ["STD_YM"] + LOCATION_COLS


def load_files(kind, metrics):
    """6개월 파일을 검증해 결합. 누락·추가 월이나 중복 키가 있으면 중단."""
    files = sorted(RAW_DIR.glob(f"flow_{kind}_pop_*.csv"))
    expected = {f"flow_{kind}_pop_{month}.csv" for month in MONTHS}
    if {file.name for file in files} != expected:
        raise ValueError(f"{kind}: 제공 기간 6개월의 원본 파일 구성이 다릅니다.")
    tables = []
    for file in files:
        df = pd.read_csv(file, sep="|", dtype={"STD_YM": str, "BLOCK_CD": str})
        require_columns(df, KEY_COLS + metrics, file.name)
        before = len(df)
        df = df.drop_duplicates().copy()
        require_keys(df, KEY_COLS, file.name)
        if not df["STD_YM"].eq(file.stem[-6:]).all():
            raise ValueError(f"{file.name}: 파일명과 기준년월이 일치하지 않습니다.")
        require_numbers(df, ["X_COORD", "Y_COORD"] + metrics, file.name)
        print(f"{file.name}: {before:,}행 → {len(df):,}행 (완전 중복 {before-len(df):,}행 제거)")
        tables.append(df[KEY_COLS + metrics])
    return pd.concat(tables, ignore_index=True)


def ratio(numerator, denominator):
    return numerator / denominator.where(denominator > 0)


def normalized_entropy(df, columns):
    """합계 0이면 분포가 없으므로 NaN. log(0) 경고 없이 0~1 엔트로피 계산."""
    values = df[columns].to_numpy(dtype=float)
    total = values.sum(axis=1)
    probabilities = np.divide(values, total[:, None], out=np.zeros_like(values), where=total[:, None] > 0)
    log_values = np.zeros_like(probabilities)
    np.log(probabilities, out=log_values, where=probabilities > 0)
    entropy = -(probabilities * log_values).sum(axis=1) / np.log(len(columns))
    entropy[total == 0] = np.nan
    return entropy


def main():
    age_cols = [f"{sex}_FLOW_POP_CNT_{age}" for sex in ["MAN", "WMAN"] for age in AGES]
    time_cols = [f"TMST_{hour:02d}" for hour in range(24)]
    weekday_cols = [f"FLOW_POP_CNT_{day}" for day in ["MON", "TUS", "WED", "THU", "FRI"]]
    weekend_cols = ["FLOW_POP_CNT_SAT", "FLOW_POP_CNT_SUN"]
    week_cols = weekday_cols + weekend_cols
    age = load_files("age", age_cols).sort_values(LOCATION_COLS + ["STD_YM"]).reset_index(drop=True)
    time = load_files("time", time_cols)
    week = load_files("wkdy", week_cols)

    # 성별을 합쳐 연령별 유동량 생성. 금액이나 고유 방문자 수가 아니다.
    for code in AGES:
        age[f"FLOW_POP_{code}"] = age[f"MAN_FLOW_POP_CNT_{code}"] + age[f"WMAN_FLOW_POP_CNT_{code}"]
    population_cols = [f"FLOW_POP_{code}" for code in AGES]
    age["FLOW_POP_TOTAL"] = age[population_cols].sum(axis=1)
    month_number = pd.to_datetime(age["STD_YM"], format="%Y%m").dt.to_period("M").astype("int64")
    adjacent = month_number.groupby([age[col] for col in LOCATION_COLS]).diff().eq(1)
    age_features = KEY_COLS.copy()
    for code in AGES:
        current = age[f"FLOW_POP_{code}"]
        previous = current.groupby([age[col] for col in LOCATION_COLS]).shift(1)
        age[f"FLOW_POP_RATIO_{code}"] = ratio(current, age["FLOW_POP_TOTAL"])
        age[f"FLOW_POP_DIFF_{code}"] = (current - previous).where(adjacent)
        # 기존 통신 컬럼은 백분율 유지: -10 = 10% 감소. risk_features는 -0.1.
        age[f"FLOW_POP_PCT_{code}"] = ((ratio(current, previous) - 1) * 100).where(adjacent)
        age_features += [f"FLOW_POP_{code}", f"FLOW_POP_RATIO_{code}", f"FLOW_POP_DIFF_{code}", f"FLOW_POP_PCT_{code}"]
    age_features.append("FLOW_POP_TOTAL")

    time["TIME_FLOW_TOTAL"] = time[time_cols].sum(axis=1)
    for label, hours in [("DAWN", range(6)), ("DAYTIME", range(6, 18)), ("EVENING", range(18, 24))]:
        time[f"FLOW_{label}"] = time[[f"TMST_{hour:02d}" for hour in hours]].sum(axis=1)
        time[f"{label}_RATIO"] = ratio(time[f"FLOW_{label}"], time["TIME_FLOW_TOTAL"])
    time["TIME_ENTROPY"] = normalized_entropy(time, time_cols)
    time_features = KEY_COLS + ["TIME_FLOW_TOTAL", "FLOW_DAWN", "FLOW_DAYTIME", "FLOW_EVENING",
                                "DAWN_RATIO", "DAYTIME_RATIO", "EVENING_RATIO", "TIME_ENTROPY"]

    week["WEEKDAY_AVG"] = week[weekday_cols].mean(axis=1)
    week["WEEKEND_AVG"] = week[weekend_cols].mean(axis=1)
    week["WEEK_AVG"] = week[week_cols].mean(axis=1)
    week["WEEKEND_WEEKDAY_RATIO"] = ratio(week["WEEKEND_AVG"], week["WEEKDAY_AVG"])
    week["WEEK_ENTROPY"] = normalized_entropy(week, week_cols)
    week_features = KEY_COLS + ["WEEKDAY_AVG", "WEEKEND_AVG", "WEEK_AVG", "WEEKEND_WEEKDAY_RATIO", "WEEK_ENTROPY"]

    result = age[age_features].merge(time[time_features], on=KEY_COLS, how="outer", validate="one_to_one").merge(
        week[week_features], on=KEY_COLS, how="outer", validate="one_to_one")
    result = result.sort_values(LOCATION_COLS + ["STD_YM"]).reset_index(drop=True)
    require_keys(result, KEY_COLS, "최종 통신 특징")
    if np.isinf(result.select_dtypes(include="number").to_numpy()).any():
        raise ValueError("최종 통신 특징에 무한대가 있습니다.")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUTPUT_FILE} / {result.shape}")


if __name__ == "__main__":
    main()
