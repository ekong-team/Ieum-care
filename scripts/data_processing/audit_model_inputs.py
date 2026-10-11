"""위험도 설계 전 특징의 관측 단위·결측·중복 정보와 사용 목적을 정리한다.

기본 특징은 변경하지 않는다. 후보 목록은 검토용이며 점수·등급·라벨은 만들지 않는다.
"""
from pathlib import Path
from datetime import datetime, timezone
from itertools import combinations
import json

import numpy as np
import pandas as pd

from data_contract import MONTHS, AGES, REGIONS, require_keys, require_months
from industry_classification import RULES, ALL_GROUPS
from validate_processed import file_hash

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
KEYS = ["월", "지역", "연령대"]
CANDIDATES = ["통신_연령유동량_전월변화율", "카드1_전체_결제건수_전월변화율",
              "카드1_사회활동관련후보_건수전월변화율"]
REGIONAL = ["통신_전체관측위치수", "통신_지역전체유동량"]
REGIONAL += [f"통신_{kind}관측{suffix}" for kind in ["연령", "시간", "요일"] for suffix in ["위치수", "률"]]
REGIONAL += [f"통신_지역공통_{name}" for name in ["TIME_FLOW_TOTAL", "FLOW_DAWN", "FLOW_DAYTIME",
             "FLOW_EVENING", "WEEKDAY_AVG", "WEEKEND_AVG", "WEEK_AVG", "새벽비중", "주간비중", "저녁비중", "주말평일비"]]
AGE_SCOPE = "월×지역×연령"
REGION_SCOPE = "월×지역"


def feature_rule(column):
    """뜻을 알 수 없는 신규 열은 조용히 입력 후보로 넣지 않고 중단한다."""
    if column in KEYS:
        return "식별키", AGE_SCOPE, "결합·보고·시간 순서에 사용. 수치 위험 신호가 아님"
    if column in CANDIDATES:
        return "입력검토후보", AGE_SCOPE, "활동량 변화의 탐색 지표. 고립 원인·정답이나 가중치는 미확정"
    if column in REGIONAL:
        reason = "지역 공통값. 연령별 관측값이나 독립 표본으로 해석하지 않음"
        if "관측" in column:
            reason += "; 관측 위치의 품질 맥락이며 인구 대표성·위험 점수가 아님"
        return "맥락", REGION_SCOPE, reason
    if column in ["통신_전월공통위치수", "통신_전월공통위치비율"]:
        return "맥락", AGE_SCOPE, "전월 공통 위치 비교의 품질 맥락. 첫 달 위치수 0은 활동 0이 아님"
    if column in ["통신_연령유동량", "통신_연령비중"]:
        return "맥락", AGE_SCOPE, "인구 규모·구성·관측 범위 영향. 거주민/고유 방문자 수가 아님"
    if column == "카드2_결제건수_전월변화율":
        return "점수입력제외", AGE_SCOPE, "카드1 건수 변화와 중복 반영 방지. 출처별 교차확인용으로 보존"
    if column in ["카드2_결제금액", "카드2_결제건수", "카드2_결제금액_전월변화율", "카드2_건당결제금액"]:
        return "맥락", AGE_SCOPE, "카드1과 더하지 않는 별도 출처. 거주민만의 소비나 추가 독립 증거로 단정하지 않음"
    if column.startswith("카드1_사회활동관련후보_") and column.endswith(
            ("결제건수", "건수비중", "비중전월차이")):
        return "맥락", AGE_SCOPE, "후보 합계·소비 구성 설명. 비중 변화는 분모 영향을 받으며 건수 변화와 중복 가능"
    if column in ["카드1_전체_결제금액", "카드1_전체_결제건수", "카드1_전체_결제금액_전월변화율", "카드1_전체_건당결제금액"]:
        return "맥락", AGE_SCOPE, "규모·지출 맥락. 소득·가격·결제수단 영향이 있어 고립의 직접 근거로 쓰지 않음"
    for group in ALL_GROUPS:
        if column not in [f"카드1_{group}_{metric}" for metric in ["결제금액", "결제건수", "결제건수_비중"]]:
            continue
        if group == "미분류":
            return "점수입력제외", AGE_SCOPE, "현재 상수 0. 신규 업종 모니터링을 위해 원본 특징에는 유지"
        if group == "해석보류":
            return "맥락", AGE_SCOPE, "해석 불확실성 맥락. 후보 분자 제외·전체 분모 유지. 높다고 위험을 높이지 않음"
        if RULES[group][0] == "위험지표_제외후보":
            return "점수입력제외", AGE_SCOPE, RULES[group][2]
        return "맥락", AGE_SCOPE, RULES[group][2] + "; 초기 후보 합계와 별도 가중 합산하지 않음"
    raise ValueError(f"사용 목적이 정의되지 않은 특징: {column}")


def correlation_review(df, registry):
    """같은 의미의 관측 단위끼리만 비교. 지역 공통값은 12개 조합으로 축소한다."""
    rows = []
    for scope in [AGE_SCOPE, REGION_SCOPE]:
        columns = registry.loc[(registry["관측단위"] == scope) & registry["숫자열"], "특징"].tolist()
        table = df if scope == AGE_SCOPE else df.drop_duplicates(["월", "지역"])
        for left, right in combinations(columns, 2):
            pair = table[[left, right]].dropna()
            if len(pair) < 3 or pair[left].nunique() < 2 or pair[right].nunique() < 2:
                continue
            r = pair[left].corr(pair[right])
            if abs(r) >= 0.95:
                rows.append({"특징1": left, "특징2": right, "관측단위": scope,
                             "비교행수": len(pair), "피어슨상관": r,
                             "참고": "탐색 경고만 표시. 상관은 독립성·인과성·자동 제거 기준이 아님"})
    return pd.DataFrame(rows, columns=["특징1", "특징2", "관측단위", "비교행수", "피어슨상관", "참고"])


def main():
    source = PROCESSED / "risk_features.csv"
    df = pd.read_csv(source, dtype={key: str for key in KEYS})
    require_keys(df, KEYS, "모델 입력 검토")
    require_months(df["월"], "모델 입력 검토")
    expected = set(pd.MultiIndex.from_product([MONTHS, REGIONS.values(), AGES.values()]).tolist())
    if set(map(tuple, df[KEYS].to_numpy())) != expected:
        raise ValueError("월×지역×연령 조합이 불완전합니다.")
    rows = []
    missing_rows = []
    for column in df:
        role, scope, reason = feature_rule(column)
        numeric = pd.api.types.is_numeric_dtype(df[column])
        missing = df[column].isna()
        first_month_only = bool(missing.any() and missing.equals(df["월"].eq(MONTHS[0])))
        if numeric and np.isinf(df[column].to_numpy()).any():
            raise ValueError(f"무한대: {column}")
        if numeric and missing.any() and not first_month_only:
            raise ValueError(f"예상 밖 결측: {column}")
        repeated = scope == REGION_SCOPE
        if repeated and df.groupby(["월", "지역"])[column].nunique(dropna=False).gt(1).any():
            raise ValueError(f"지역 공통 특징이 연령별로 다릅니다: {column}")
        rows.append({"특징": column, "사용목적": role, "관측단위": scope, "근거": reason,
            "숫자열": numeric, "행수": len(df), "결측수": int(missing.sum()),
            "결측사유": "첫 달 전월 비교 불가" if first_month_only else "없음",
            "고유값수": df[column].nunique(), "현재상수": df[column].nunique(dropna=False) <= 1,
            "최소": df[column].min() if numeric else np.nan,
            "최대": df[column].max() if numeric else np.nan,
            "관측단위조합수": df[["월", "지역"] if repeated else KEYS].drop_duplicates().shape[0]})
        for month, group in df.groupby("월"):
            if group[column].isna().any():
                missing_rows.append({"특징": column, "월": month, "결측수": int(group[column].isna().sum())})
    registry = pd.DataFrame(rows)
    registry.to_csv(PROCESSED / "model_feature_review.csv", index=False, encoding="utf-8-sig")
    df[["월", "지역"] + REGIONAL].drop_duplicates(["월", "지역"]).to_csv(
        PROCESSED / "model_region_context_review.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(missing_rows).to_csv(PROCESSED / "model_feature_missingness.csv", index=False, encoding="utf-8-sig")
    correlations = correlation_review(df, registry)
    correlations.to_csv(PROCESSED / "model_feature_correlations.csv", index=False, encoding="utf-8-sig")
    quality_cols = ["통신_연령관측률", "통신_시간관측률", "통신_요일관측률",
                    "통신_전월공통위치수", "통신_전월공통위치비율", "카드1_해석보류_결제건수_비중"]
    review = df[KEYS + CANDIDATES + quality_cols].copy()
    review["전월변화계산가능"] = review[CANDIDATES].notna().all(axis=1)
    review.to_csv(PROCESSED / "model_input_review.csv", index=False, encoding="utf-8-sig")
    summary = {
        "status": "input_review_complete_model_design_pending", "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "shape": list(df.shape), "role_counts": registry["사용목적"].value_counts().to_dict(),
        "candidate_features": CANDIDATES, "change_comparable_rows": int(review["전월변화계산가능"].sum()),
        "first_month_policy": "7월 전월 변화는 결측 유지. 0=변화 없음으로 대체하지 않음",
        "region_context_combinations": int(df[["월", "지역"]].drop_duplicates().shape[0]),
        "regional_context_feature_count": len(REGIONAL),
        "missing_feature_count": int(registry["결측수"].gt(0).sum()),
        "high_correlation_pair_count": len(correlations),
        "correlation_flag_threshold": 0.95,
        "constant_features": registry.loc[registry["현재상수"], "특징"].tolist(),
        "coverage_ranges": {col: {"min": float(df[col].min()), "max": float(df[col].max())}
                            for col in quality_cols if col.endswith("률") or col.endswith("비율")},
        "card_count_change_correlation": float(df["카드1_전체_결제건수_전월변화율"].corr(df["카드2_결제건수_전월변화율"])),
        "warnings": ["72행은 집계 조합 수이며 72명의 독립 개인/정답 표본이 아님",
                     "6개월 자료로 연간 계절성이나 충분한 미래 성능을 검증했다고 할 수 없음",
                     "고립 라벨 없음. 3개 입력 후보도 가중치·방향·정확도가 검증된 것은 아님",
                     "카드 후보 변화와 전체 변화는 같은 출처이므로 독립 증거로 중복 반영하지 않음"],
        "sha256": {path.relative_to(REPO).as_posix(): file_hash(path)
                   for path in [source, Path(__file__), Path(__file__).with_name("data_contract.py"),
                                Path(__file__).with_name("industry_classification.py")]},
    }
    (PROCESSED / "model_input_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
