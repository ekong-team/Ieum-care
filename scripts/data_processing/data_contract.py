"""공모전 제공 데이터의 공통 입력 계약. 다른 기간을 쓰면 이 설정부터 변경한다."""

import hashlib

import numpy as np
import pandas as pd

MONTHS = [f"2025{month:02d}" for month in range(7, 13)]
REGIONS = {"11230": "서울 강남구", "32010": "강원 춘천시"}
AGES = {"10G": "10대", "20G": "20대", "30G": "30대",
        "40G": "40대", "50G": "50대", "60GU": "60대이상"}


def file_hash(path):
    """큰 원본도 메모리에 전부 올리지 않고 변경 여부를 기록한다."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_ratio(numerator, denominator):
    """분모가 0이거나 결측이면 계산 불가를 유지한다."""
    return numerator / denominator.where(denominator > 0)


def require_columns(df, columns, name):
    missing = set(columns) - set(df.columns)
    if missing:
        raise ValueError(f"{name}: 필수 컬럼 누락 {sorted(missing)}")


def require_keys(df, keys, name, unique=True):
    if df[keys].isna().any().any() or df[keys].astype(str).apply(lambda s: s.str.strip().eq("")).any().any():
        raise ValueError(f"{name}: 결합 키가 비어 있습니다.")
    if unique and df.duplicated(keys).any():
        raise ValueError(f"{name}: 서로 다른 기록에 동일한 키가 있습니다.")


def require_months(values, name):
    if set(values.dropna().astype(str)) != set(MONTHS):
        raise ValueError(f"{name}: 제공 기간 {MONTHS}과 실제 월이 다릅니다.")


def require_numbers(df, columns, name, integer=False):
    for col in columns:
        df[col] = pd.to_numeric(df[col], errors="raise")
    values = df[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError(f"{name}: 숫자에 결측·음수·무한대가 있습니다.")
    if integer and not np.equal(values, np.floor(values)).all():
        raise ValueError(f"{name}: 금액·건수에 정수가 아닌 값이 있습니다.")


def validate_card_raw(df, name):
    required = ["TA_YMD", "MCT_SGG_CD", "MCT_RY_CD", "SEX_CCD", "AGE_CCD", "TS_AT", "USE_CNT"]
    require_columns(df, required, name)
    # 카드2 거주지의 결측은 허용하지만, 날짜·지역·업종·성연령은 필요하다.
    require_keys(df, required[:5], name, unique=False)
    if not df["TA_YMD"].str.fullmatch(r"\d{8}").all():
        raise ValueError(f"{name}: 일자는 YYYYMMDD여야 합니다.")
    pd.to_datetime(df["TA_YMD"], format="%Y%m%d", errors="raise")
    require_months(df["TA_YMD"].str[:6], name)
    if not df["MCT_SGG_CD"].isin(REGIONS.values()).all():
        raise ValueError(f"{name}: 대상 지역 밖의 가맹점이 있습니다.")
    age = df["AGE_CCD"].str.replace(" ", "", regex=False)
    allowed = ["10대", "20대", "30대", "40대", "50대", "60대", "70대", "80대", "90대", "60대이상", "법인"]
    if not age.isin(allowed).all():
        raise ValueError(f"{name}: 해석하지 않은 연령대가 있습니다.")
    require_numbers(df, ["TS_AT", "USE_CNT"], name, integer=True)
