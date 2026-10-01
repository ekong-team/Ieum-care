import os
import glob

import numpy as np
import pandas as pd


# ============================================================
# 설정
# ============================================================

RAW_DIR = "data/raw"
PROCESSED_DIR = "data/processed"

OUTPUT_FILE = os.path.join(
    PROCESSED_DIR,
    "telecom_features.csv"
)

# 통신 데이터의 위치 식별 기준
# BLOCK_CD만 사용하지 않고 좌표까지 함께 사용
LOCATION_COLS = [
    "BLOCK_CD",
    "X_COORD",
    "Y_COORD"
]

# 위치 + 월
KEY_COLS = [
    "STD_YM",
    "BLOCK_CD",
    "X_COORD",
    "Y_COORD"
]


# ============================================================
# 1. 월별 CSV 파일 불러오기
# ============================================================

def load_files(pattern):
    """
    같은 종류의 월별 CSV 파일을 모두 읽어서 하나의 DataFrame으로 합친다.

    예)
    flow_age_pop_202507.csv
    flow_age_pop_202508.csv
    ...
    """

    files = sorted(glob.glob(pattern))

    if not files:
        raise FileNotFoundError(
            f"파일을 찾을 수 없습니다: {pattern}"
        )

    data_list = []

    for file in files:

        df = pd.read_csv(
            file,
            sep="|",
            low_memory=False
        )

        print(f"\n읽는 중: {file}")
        print(f"  원본 행 수: {len(df):,}")

        # 완전히 동일한 중복행 제거
        before = len(df)

        df = df.drop_duplicates()

        after = len(df)

        if before != after:
            print(
                f"  중복 제거: "
                f"{before - after:,}건"
            )

        data_list.append(df)

    result = pd.concat(
        data_list,
        ignore_index=True
    )

    return result


# ============================================================
# 2. 통신 데이터 3종 불러오기
# ============================================================

print("\n================================")
print("통신 데이터 불러오기")
print("================================")


# 연령 / 성별
telecom_age = load_files(
    os.path.join(
        RAW_DIR,
        "flow_age_pop_*.csv"
    )
)


# 시간대별
telecom_time = load_files(
    os.path.join(
        RAW_DIR,
        "flow_time_pop_*.csv"
    )
)


# 요일별
telecom_wkdy = load_files(
    os.path.join(
        RAW_DIR,
        "flow_wkdy_pop_*.csv"
    )
)


print("\n===== 통합 결과 =====")

print(
    "AGE :",
    telecom_age.shape
)

print(
    "TIME:",
    telecom_time.shape
)

print(
    "WKDY:",
    telecom_wkdy.shape
)


# ============================================================
# 3. 데이터 Key 중복 확인
# ============================================================

def check_key_duplicates(df, name):
    """
    STD_YM + BLOCK_CD + X_COORD + Y_COORD 기준으로
    중복 레코드가 있는지 확인한다.
    """

    duplicate_count = (
        df
        .duplicated(KEY_COLS)
        .sum()
    )

    print(
        f"{name} KEY 중복:",
        f"{duplicate_count:,}건"
    )

    # 완전히 동일한 중복행을 제거했는데도
    # 동일 KEY가 여러 개 존재하면 데이터 구조 확인 필요
    if duplicate_count > 0:

        print(
            f"⚠ {name}에 동일 위치/월 "
            f"KEY가 여러 개 존재합니다."
        )


print("\n===== KEY 중복 확인 =====")

check_key_duplicates(
    telecom_age,
    "AGE"
)

check_key_duplicates(
    telecom_time,
    "TIME"
)

check_key_duplicates(
    telecom_wkdy,
    "WKDY"
)


# ============================================================
# 4. AGE 데이터 Feature 생성
# ============================================================

print("\n================================")
print("AGE Feature 생성")
print("================================")


age_groups = [
    "10G",
    "20G",
    "30G",
    "40G",
    "50G",
    "60GU"
]


# ------------------------------------------------------------
# 4-1. 남성 + 여성 → 연령대 전체 유동인구
# ------------------------------------------------------------

for age in age_groups:

    telecom_age[
        f"FLOW_POP_{age}"
    ] = (

        telecom_age[
            f"MAN_FLOW_POP_CNT_{age}"
        ]

        +

        telecom_age[
            f"WMAN_FLOW_POP_CNT_{age}"
        ]
    )


# ------------------------------------------------------------
# 4-2. 전체 연령 유동인구
# ------------------------------------------------------------

age_population_cols = [
    f"FLOW_POP_{age}"
    for age in age_groups
]


telecom_age[
    "FLOW_POP_TOTAL"
] = (

    telecom_age[
        age_population_cols
    ]

    .sum(axis=1)
)


# ------------------------------------------------------------
# 4-3. 연령별 비중
#
# 예:
# FLOW_POP_RATIO_20G = 0.23
# → 해당 블록 유동인구 중 20대가 약 23%
# ------------------------------------------------------------

for age in age_groups:

    telecom_age[
        f"FLOW_POP_RATIO_{age}"
    ] = (

        telecom_age[
            f"FLOW_POP_{age}"
        ]

        /

        telecom_age[
            "FLOW_POP_TOTAL"
        ].replace(0, np.nan)
    )


# ------------------------------------------------------------
# 4-4. 월 순서 정렬
# ------------------------------------------------------------

telecom_age = (
    telecom_age
    .sort_values(
        LOCATION_COLS
        +
        ["STD_YM"]
    )
    .reset_index(drop=True)
)


# ------------------------------------------------------------
# 4-5. 전월 대비 절대 변화량
#
# 첫 달은 이전 달이 없으므로 NaN → 정상
# ------------------------------------------------------------

for age in age_groups:

    telecom_age[
        f"FLOW_POP_DIFF_{age}"
    ] = (

        telecom_age

        .groupby(
            LOCATION_COLS
        )[
            f"FLOW_POP_{age}"
        ]

        .diff()
    )


# ------------------------------------------------------------
# 4-6. 전월 대비 변화율
#
# 전월이 0이면 % 변화율을 정의할 수 없기 때문에 NaN 처리
# ------------------------------------------------------------

for age in age_groups:

    previous = (

        telecom_age

        .groupby(
            LOCATION_COLS
        )[
            f"FLOW_POP_{age}"
        ]

        .shift(1)
    )

    current = telecom_age[
        f"FLOW_POP_{age}"
    ]

    telecom_age[
        f"FLOW_POP_PCT_{age}"
    ] = np.where(

        previous > 0,

        (
            (current - previous)
            /
            previous
        )
        * 100,

        np.nan
    )


# ============================================================
# 5. TIME 데이터 Feature 생성
# ============================================================

print("\n================================")
print("TIME Feature 생성")
print("================================")


# 24시간 컬럼
time_cols = [
    f"TMST_{hour:02d}"
    for hour in range(24)
]


# ------------------------------------------------------------
# 5-1. 전체 시간대 유동인구
# ------------------------------------------------------------

telecom_time[
    "TIME_FLOW_TOTAL"
] = (

    telecom_time[
        time_cols
    ]

    .sum(axis=1)
)


# ------------------------------------------------------------
# 5-2. 시간대를 생활패턴 기준으로 분리
#
# 새벽 : 00 ~ 05
# 주간 : 06 ~ 17
# 저녁 : 18 ~ 23
# ------------------------------------------------------------

dawn_cols = [
    f"TMST_{hour:02d}"
    for hour in range(0, 6)
]

daytime_cols = [
    f"TMST_{hour:02d}"
    for hour in range(6, 18)
]

evening_cols = [
    f"TMST_{hour:02d}"
    for hour in range(18, 24)
]


telecom_time[
    "FLOW_DAWN"
] = (

    telecom_time[
        dawn_cols
    ]

    .sum(axis=1)
)


telecom_time[
    "FLOW_DAYTIME"
] = (

    telecom_time[
        daytime_cols
    ]

    .sum(axis=1)
)


telecom_time[
    "FLOW_EVENING"
] = (

    telecom_time[
        evening_cols
    ]

    .sum(axis=1)
)


# ------------------------------------------------------------
# 5-3. 시간대별 활동 비중
# ------------------------------------------------------------

total_time_safe = (

    telecom_time[
        "TIME_FLOW_TOTAL"
    ]

    .replace(
        0,
        np.nan
    )
)


telecom_time[
    "DAWN_RATIO"
] = (

    telecom_time[
        "FLOW_DAWN"
    ]

    /
    total_time_safe
)


telecom_time[
    "DAYTIME_RATIO"
] = (

    telecom_time[
        "FLOW_DAYTIME"
    ]

    /
    total_time_safe
)


telecom_time[
    "EVENING_RATIO"
] = (

    telecom_time[
        "FLOW_EVENING"
    ]

    /
    total_time_safe
)


# ------------------------------------------------------------
# 5-4. 시간대 활동 다양성 (Entropy)
#
# 특정 시간에만 몰리면 낮음
# 여러 시간에 골고루 활동하면 높음
#
# 0 ~ 1 사이 값으로 정규화
# ------------------------------------------------------------

time_values = (
    telecom_time[
        time_cols
    ]
    .to_numpy(dtype=float)
)


time_sum = (
    time_values
    .sum(axis=1)
)


time_prob = np.divide(

    time_values,

    time_sum[:, None],

    out=np.zeros_like(
        time_values,
        dtype=float
    ),

    where=(
        time_sum[:, None] != 0
    )
)


time_entropy = -np.sum(

    np.where(
        time_prob > 0,
        time_prob
        *
        np.log(time_prob),
        0
    ),

    axis=1
)


# 최대 entropy = log(24)
telecom_time[
    "TIME_ENTROPY"
] = (

    time_entropy
    /
    np.log(24)
)


# ============================================================
# 6. WEEKDAY 데이터 Feature 생성
# ============================================================

print("\n================================")
print("WEEKDAY Feature 생성")
print("================================")


weekday_cols = [
    "FLOW_POP_CNT_MON",
    "FLOW_POP_CNT_TUS",
    "FLOW_POP_CNT_WED",
    "FLOW_POP_CNT_THU",
    "FLOW_POP_CNT_FRI"
]


weekend_cols = [
    "FLOW_POP_CNT_SAT",
    "FLOW_POP_CNT_SUN"
]


all_week_cols = (
    weekday_cols
    +
    weekend_cols
)


# ------------------------------------------------------------
# 6-1. 평일 평균 활동량
# ------------------------------------------------------------

telecom_wkdy[
    "WEEKDAY_AVG"
] = (

    telecom_wkdy[
        weekday_cols
    ]

    .mean(axis=1)
)


# ------------------------------------------------------------
# 6-2. 주말 평균 활동량
# ------------------------------------------------------------

telecom_wkdy[
    "WEEKEND_AVG"
] = (

    telecom_wkdy[
        weekend_cols
    ]

    .mean(axis=1)
)


# ------------------------------------------------------------
# 6-3. 전체 요일 평균
# ------------------------------------------------------------

telecom_wkdy[
    "WEEK_AVG"
] = (

    telecom_wkdy[
        all_week_cols
    ]

    .mean(axis=1)
)


# ------------------------------------------------------------
# 6-4. 주말 / 평일 활동비율
#
# 1보다 작음 → 평일보다 주말 활동이 적음
# 1보다 큼 → 평일보다 주말 활동이 많음
# ------------------------------------------------------------

telecom_wkdy[
    "WEEKEND_WEEKDAY_RATIO"
] = (

    telecom_wkdy[
        "WEEKEND_AVG"
    ]

    /

    telecom_wkdy[
        "WEEKDAY_AVG"
    ].replace(
        0,
        np.nan
    )
)


# ------------------------------------------------------------
# 6-5. 요일별 활동 다양성
#
# 특정 요일에만 활동이 몰리는지 확인
# 0 ~ 1 사이 값
# ------------------------------------------------------------

week_values = (

    telecom_wkdy[
        all_week_cols
    ]

    .to_numpy(dtype=float)
)


week_sum = (
    week_values
    .sum(axis=1)
)


week_prob = np.divide(

    week_values,

    week_sum[:, None],

    out=np.zeros_like(
        week_values,
        dtype=float
    ),

    where=(
        week_sum[:, None] != 0
    )
)


week_entropy = -np.sum(

    np.where(
        week_prob > 0,
        week_prob
        *
        np.log(week_prob),
        0
    ),

    axis=1
)


# 최대 entropy = log(7)
telecom_wkdy[
    "WEEK_ENTROPY"
] = (

    week_entropy
    /
    np.log(7)
)


# ============================================================
# 7. 최종 Feature에 필요한 컬럼만 선택
# ============================================================


# AGE
age_feature_cols = KEY_COLS.copy()

for age in age_groups:

    age_feature_cols += [
        f"FLOW_POP_{age}",
        f"FLOW_POP_RATIO_{age}",
        f"FLOW_POP_DIFF_{age}",
        f"FLOW_POP_PCT_{age}"
    ]


age_feature_cols += [
    "FLOW_POP_TOTAL"
]


age_features = telecom_age[
    age_feature_cols
].copy()


# TIME
time_feature_cols = KEY_COLS + [

    "TIME_FLOW_TOTAL",

    "FLOW_DAWN",
    "FLOW_DAYTIME",
    "FLOW_EVENING",

    "DAWN_RATIO",
    "DAYTIME_RATIO",
    "EVENING_RATIO",

    "TIME_ENTROPY"
]


time_features = telecom_time[
    time_feature_cols
].copy()


# WEEKDAY
weekday_feature_cols = KEY_COLS + [

    "WEEKDAY_AVG",
    "WEEKEND_AVG",
    "WEEK_AVG",

    "WEEKEND_WEEKDAY_RATIO",

    "WEEK_ENTROPY"
]


weekday_features = telecom_wkdy[
    weekday_feature_cols
].copy()


# ============================================================
# 8. AGE + TIME + WEEKDAY 병합
# ============================================================

print("\n================================")
print("3종 Feature 병합")
print("================================")


telecom_features = (

    age_features

    .merge(
        time_features,
        on=KEY_COLS,
        how="outer"
    )

    .merge(
        weekday_features,
        on=KEY_COLS,
        how="outer"
    )
)


# 월 / 위치 순으로 정렬
telecom_features = (

    telecom_features

    .sort_values(
        LOCATION_COLS
        +
        ["STD_YM"]
    )

    .reset_index(
        drop=True
    )
)


# ============================================================
# 9. 최종 데이터 검증
# ============================================================

print("\n===== 최종 데이터 =====")

print(
    "shape:",
    telecom_features.shape
)


print("\n포함 월:")

print(
    sorted(
        telecom_features[
            "STD_YM"
        ]
        .dropna()
        .unique()
    )
)


print("\n컬럼 수:")

print(
    len(
        telecom_features.columns
    )
)


print("\n결측치가 많은 주요 컬럼:")

check_cols = [

    "FLOW_POP_20G",
    "FLOW_POP_PCT_20G",

    "DAYTIME_RATIO",

    "WEEKEND_WEEKDAY_RATIO",

    "TIME_ENTROPY",

    "WEEK_ENTROPY"
]


for col in check_cols:

    missing = (
        telecom_features[
            col
        ]
        .isna()
        .sum()
    )

    print(
        f"{col}: "
        f"{missing:,}건"
    )


# ============================================================
# 10. processed 폴더 생성
# ============================================================

os.makedirs(
    PROCESSED_DIR,
    exist_ok=True
)


# ============================================================
# 11. telecom_features.csv 저장
# ============================================================

telecom_features.to_csv(

    OUTPUT_FILE,

    index=False,

    encoding="utf-8-sig"
)


print("\n================================")

print(
    "저장 완료:",
    OUTPUT_FILE
)

print(
    "최종 행 수:",
    f"{len(telecom_features):,}"
)

print(
    "최종 컬럼 수:",
    len(telecom_features.columns)
)

print("================================")