"""팀 합의 규칙으로 지역×연령의 활동 감소 신호를 5단계로 분류한다.

실행: python ai/risk_model/classify_risk.py
민감도 검증: python ai/risk_model/classify_risk.py --sensitivity
월별 전이·관측 범위 점검: python ai/risk_model/classify_risk.py --review
원본·정제 특징은 유지하며 data/processed/risk_model/에 결과와 재현 기록을 저장한다.
개인의 고립 여부·확률을 예측하는 학습 모델이 아니다.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import sys

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "data_processing"))
from data_contract import (AGES, MONTHS, REGIONS, file_hash, require_columns,
                           require_keys, require_numbers, safe_ratio, validate_card_raw)

PROCESSED = REPO / "data" / "processed"
OUTPUT = PROCESSED / "risk_model"
KEYS = ["월", "지역", "연령대"]
VERSION = "activity-decline-v1"
DECLINE = 0.03
SEVERE = 0.05
EXCLUDED_INDUSTRIES = ["실내/실외골프장", "종합레저타운/놀이동산"]
TOTAL = "카드1_전체_결제건수"
MOVEMENT = "통신_연령유동량_전월변화율"
FILTERED = "업종제외_결제건수"


def summarize_card_exclusions(raw):
    """개인 거래만 집계하고 두 원본 업종 항목만 제외한다."""
    require_columns(raw, ["TA_YMD", "MCT_SGG_CD", "MCT_RY_CD", "SEX_CCD", "AGE_CCD", "USE_CNT"], "카드1")
    sex_corp = raw["SEX_CCD"].eq("법인")
    age_corp = raw["AGE_CCD"].eq("법인")
    if not sex_corp.eq(age_corp).all():
        raise ValueError("카드1 성별·연령의 법인 표시가 다릅니다.")
    personal = raw.loc[~sex_corp].copy()
    require_numbers(personal, ["USE_CNT"], "개인 결제건수", integer=True)
    personal["월"] = personal["TA_YMD"].str[:6]
    personal["지역"] = personal["MCT_SGG_CD"]
    personal["연령대"] = personal["AGE_CCD"].str.replace(" ", "", regex=False).replace(
        {f"{age}대": "60대이상" for age in [60, 70, 80, 90]})
    for industry, column in zip(EXCLUDED_INDUSTRIES, ["골프_결제건수", "레저타운놀이동산_결제건수"]):
        personal[column] = personal["USE_CNT"].where(personal["MCT_RY_CD"].eq(industry), 0)
    result = personal.groupby(KEYS, as_index=False)[
        ["USE_CNT", "골프_결제건수", "레저타운놀이동산_결제건수"]].sum().rename(columns={"USE_CNT": "원본_전체결제건수"})
    result[FILTERED] = result["원본_전체결제건수"] - result["골프_결제건수"] - result["레저타운놀이동산_결제건수"]
    if not result["원본_전체결제건수"].sum() == personal["USE_CNT"].sum():
        raise ValueError("개인 거래 집계 전후 전체 건수가 다릅니다.")
    return result


def tri_and(*values):
    """알 수 없는 조건을 거짓으로 바꾸지 않는다. 하나라도 거짓이면 전체는 거짓."""
    if any(not bool(value) for value in values if not pd.isna(value)):
        return False
    return pd.NA if any(pd.isna(value) for value in values) else True


def decline_flag(value, threshold):
    return pd.NA if pd.isna(value) else bool(value <= -threshold)


def classify_risk(features, decline_threshold=DECLINE, severe_threshold=SEVERE, *, consumption_basis="monthly"):
    """완료/부분판정/보류를 구분한다. 부분판정 단계는 확인된 하한이다."""
    if not 0 < decline_threshold <= severe_threshold < 1:
        raise ValueError("임계값은 0 < 감소 기준 <= 큰 감소 기준 < 1이어야 합니다.")
    if consumption_basis not in {"monthly", "daily"}:
        raise ValueError("소비 집계 기준은 monthly 또는 daily여야 합니다.")
    require_columns(features, KEYS + [TOTAL, MOVEMENT, FILTERED], "위험도 입력")
    data = features.copy()
    require_keys(data, KEYS, "위험도 입력")
    require_numbers(data, [TOTAL, FILTERED], "위험도 건수", integer=True)
    if data[FILTERED].gt(data[TOTAL]).any():
        raise ValueError("업종 제외 건수가 전체 건수보다 큽니다.")
    data[MOVEMENT] = pd.to_numeric(data[MOVEMENT], errors="raise")
    if np.isinf(data[MOVEMENT].to_numpy()).any() or data[MOVEMENT].lt(-1).any():
        raise ValueError("이동 변화율에 무한대 또는 -100% 미만 값이 있습니다.")
    if not data["월"].astype(str).str.fullmatch(r"\d{6}").all():
        raise ValueError("월은 YYYYMM 형식이어야 합니다.")
    data["월"] = data["월"].astype(str)
    month = pd.to_datetime(data["월"], format="%Y%m", errors="raise")
    data["_month_number"] = month.dt.to_period("M").astype("int64")
    data = data.sort_values(["지역", "연령대", "월"]).reset_index(drop=True)
    groups = data.groupby(["지역", "연령대"], sort=False)
    adjacent = groups["_month_number"].diff().eq(1)
    days = pd.to_datetime(data["월"], format="%Y%m").dt.days_in_month
    for count_column, change_column in [(TOTAL, "소비변화율"), (FILTERED, "업종제외소비변화율")]:
        # 원래 정수 건수는 보존한다. 일평균은 진단 시 소비와 업종 제외 소비에만 적용한다.
        values = data[count_column] if consumption_basis == "monthly" else data[count_column] / days
        previous = values.groupby([data["지역"], data["연령대"]]).shift(1)
        data[change_column] = (safe_ratio(values, previous) - 1).where(adjacent)
    data["이동변화율"] = data[MOVEMENT].where(adjacent)
    flags = pd.DataFrame(index=data.index)
    flags["소비감소"] = data["소비변화율"].map(lambda v: decline_flag(v, decline_threshold)).astype("boolean")
    flags["이동감소"] = data["이동변화율"].map(lambda v: decline_flag(v, decline_threshold)).astype("boolean")
    flags["동시감소"] = flags["소비감소"] & flags["이동감소"]
    previous_joint = flags["동시감소"].groupby([data["지역"], data["연령대"]]).shift(1).where(adjacent)
    previous_filtered = data["업종제외소비변화율"].groupby([data["지역"], data["연령대"]]).shift(1).where(adjacent)
    for column in ["소비변화율", "이동변화율", "업종제외소비변화율"]:
        data[f"전월{column}"] = data[column].groupby([data["지역"], data["연령대"]]).shift(1).where(adjacent)
    flags["전월동시감소"] = previous_joint.astype("boolean")
    outcomes = []
    for i, row in data.iterrows():
        c, m, filtered = row["소비변화율"], row["이동변화율"], row["업종제외소비변화율"]
        joint = flags.loc[i, "동시감소"]
        persistent = tri_and(joint, previous_joint.loc[i])
        severe = tri_and(decline_flag(c, severe_threshold), decline_flag(m, severe_threshold))
        filtered_persistent = tri_and(decline_flag(filtered, decline_threshold),
                                     decline_flag(previous_filtered.loc[i], decline_threshold))
        fifth = tri_and(persistent, severe, filtered_persistent)
        history = "확인가능" if pd.notna(previous_joint.loc[i]) else "이력부족"
        if pd.isna(c) or pd.isna(m):
            level, status, reason = pd.NA, "판단보류", "현재 두 지표의 전월 비교 불가: 이전 달 누락·분모 0·필수 값 결측 확인"
        elif not pd.isna(fifth) and fifth:
            level, status, reason = 5, "판정완료", "연속 동시 감소 + 현재 두 지표 큰 감소 + 업종 제외 소비도 연속 감소"
        elif not pd.isna(persistent) and persistent:
            level = 4
            status = "부분판정" if pd.isna(fifth) else "판정완료"
            reason = "연속 두 번 동시 감소; " + ("5단계 업종 점검 계산 불가로 상위 단계 보류" if pd.isna(fifth) else "5단계 추가 조건 불충족")
        elif not pd.isna(joint) and joint:
            level = 3
            status = "부분판정" if pd.isna(persistent) else "판정완료"
            reason = "현재 두 지표 동시 감소; " + ("지속성 이력 부족으로 상위 단계 보류" if pd.isna(persistent) else "연속 동시 감소 조건 불충족")
        elif bool(flags.loc[i, "소비감소"]) or bool(flags.loc[i, "이동감소"]):
            level, status, reason = 2, "판정완료", "소비·이동 중 정확히 한 지표에서 기준 이상 감소"
        else:
            level, status, reason = 1, "판정완료", "현재 두 지표 모두 기준 이상 감소하지 않음. 고립 없음/안전 확정은 아님"
        outcomes.append({"위험단계": level, "판정상태": status, "지속성상태": history,
                         "연속동시감소": persistent, "현재큰동시감소": severe,
                         "업종제외연속감소": filtered_persistent, "5단계조건": fifth, "판단근거": reason})
    result = pd.concat([data.drop(columns="_month_number"), flags, pd.DataFrame(outcomes)], axis=1)
    result["위험단계"] = result["위험단계"].astype("Int64")
    for col in ["연속동시감소", "현재큰동시감소", "업종제외연속감소", "5단계조건"]:
        result[col] = result[col].astype("boolean")
    return result.sort_values(KEYS).reset_index(drop=True)


def load_inputs():
    """정제 때 기록한 입력 해시와 원본 재집계 합계를 먼저 대조한다."""
    feature_path = PROCESSED / "risk_features.csv"
    raw_path = REPO / "data" / "raw" / "신한카드_빅콘테스트2026_데이터1.txt"
    manifest_path = PROCESSED / "preprocessing_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "passed":
        raise ValueError("최종 정제 검증이 통과한 입력이 필요합니다.")
    paths = [feature_path, raw_path, REPO / "scripts" / "data_processing" / "data_contract.py",
             REPO / "scripts" / "data_processing" / "build_risk_features.py"]
    for path in paths:
        key = path.relative_to(REPO).as_posix()
        if manifest["sha256"].get(key) != file_hash(path):
            raise ValueError(f"정제 입력 또는 코드 변경: {key}. 정제·검증부터 다시 실행하세요.")
    features = pd.read_csv(feature_path, dtype={key: str for key in KEYS})
    require_keys(features, KEYS, "결합 특징")
    expected = set(pd.MultiIndex.from_product([MONTHS, REGIONS.values(), AGES.values()]).tolist())
    if set(map(tuple, features[KEYS].to_numpy())) != expected:
        raise ValueError("월×지역×연령 72개 조합이 불완전합니다.")
    raw = pd.read_csv(raw_path, sep="\t", encoding="cp949", dtype=str)
    validate_card_raw(raw, "업종 제외 점검용 카드1")
    counts = summarize_card_exclusions(raw)
    result = features.merge(counts, on=KEYS, how="outer", validate="one_to_one", indicator=True)
    if not result["_merge"].eq("both").all() or not result[TOTAL].eq(result["원본_전체결제건수"]).all():
        raise ValueError("원본 개인 결제건수 재집계와 risk_features의 키/합계가 다릅니다.")
    context = ["통신_연령관측률", "통신_전월공통위치수", "통신_전월공통위치비율",
               "카드1_해석보류_결제건수_비중"]
    selected = KEYS + [TOTAL, MOVEMENT, FILTERED, "골프_결제건수", "레저타운놀이동산_결제건수"] + context
    return result[selected].copy(), paths + [manifest_path]


def run():
    inputs, sources = load_inputs()
    result = classify_risk(inputs)
    # 기본 소비 변화율이 기존 정제 결과와 같은지 별도로 확인한다.
    existing = pd.read_csv(PROCESSED / "risk_features.csv", dtype={key: str for key in KEYS}).set_index(KEYS).sort_index()
    pd.testing.assert_series_equal(result.set_index(KEYS).sort_index()["소비변화율"],
        existing["카드1_전체_결제건수_전월변화율"], check_names=False, check_dtype=False)
    output_path = OUTPUT / "risk_levels.csv"
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    summary = {
        "status": "passed", "rule_version": VERSION, "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "unit": "월×가맹점/유동인구 지역×연령", "rows": len(result),
        "consumption": "카드1 전체 개인 결제건수의 전월 변화율",
        "movement": "인접 두 달 공통 위치의 연령별 통신 유동량 전월 변화율",
        "decline_threshold": DECLINE, "severe_threshold": SEVERE,
        "excluded_industries": EXCLUDED_INDUSTRIES,
        "status_counts": result["판정상태"].value_counts().to_dict(),
        "level_counts_including_partial": {str(k): int(v) for k, v in result["위험단계"].value_counts().sort_index().items()},
        "completed_level_counts": {str(k): int(v) for k, v in result.loc[result["판정상태"].eq("판정완료"), "위험단계"].value_counts().sort_index().items()},
        "by_month": result.groupby(["월", "판정상태", "위험단계"], dropna=False).size().reset_index(name="조합수").astype(object).where(lambda s: s.notna(), None).to_dict("records"),
        "limitations": ["팀 규칙의 활동 감소 단계이며 개인 고립 확률/정답이 아님",
            "부분판정 단계는 현재 확인된 하한. 상위 단계 가능성은 미확인",
            "1단계는 기준 이상 감소 신호 없음이며 안전 확정이 아님",
            "레저타운/놀이동산 합성 업종 전체 제외. 놀이동산만 따로 구분 불가",
            "3%·5% 및 연속성은 팀 기준. 계절성·월 길이·관측 변화·대표성 영향 검증 필요"],
        "versions": {"python": sys.version.split()[0], "pandas": pd.__version__, "numpy": np.__version__},
        "sha256": {p.relative_to(REPO).as_posix(): file_hash(p) for p in sources +
                   [Path(__file__), REPO / "docs" / "risk_model_design.md", output_path]},
    }
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["rule_version", "rows", "status_counts", "level_counts_including_partial"]}, ensure_ascii=False, indent=2))


def compare_scenarios(baseline, alternative):
    """보류끼리의 NA는 단계 변경으로 세지 않고, 판정 상태 변화는 별도 기록한다."""
    left = baseline.set_index(KEYS).sort_index()
    right = alternative.set_index(KEYS).sort_index()
    pd.testing.assert_index_equal(left.index, right.index)
    comparable = left["위험단계"].notna() & right["위험단계"].notna()
    complete = comparable & left["판정상태"].eq("판정완료") & right["판정상태"].eq("판정완료")
    delta = right["위험단계"] - left["위험단계"]
    return pd.DataFrame({"기준단계": left["위험단계"], "비교단계": right["위험단계"],
        "기준판정상태": left["판정상태"], "비교판정상태": right["판정상태"],
        "양쪽단계있음": comparable, "양쪽판정완료": complete,
        "단계변경": (comparable & delta.ne(0)).fillna(False),
        "단계차이": delta, "상태변경": left["판정상태"].ne(right["판정상태"])}).reset_index()


def analyze_sensitivity(inputs):
    """임계값 3×3과 월합계/일평균 2종을 독립적으로 비교한다. 기본값은 변경하지 않는다."""
    cases = {}
    for basis in ["monthly", "daily"]:
        for decline in [0.02, DECLINE, 0.04]:
            for severe in [0.04, SEVERE, 0.06]:
                cases[(basis, decline, severe)] = classify_risk(
                    inputs, decline, severe, consumption_basis=basis)
    baseline = cases[("monthly", DECLINE, SEVERE)]
    rows, detail_tables = [], []
    for (basis, decline, severe), result in cases.items():
        case_id = f"{basis}_d{round(decline*100):02d}_s{round(severe*100):02d}"
        comparison = compare_scenarios(baseline, result)
        same_basis = compare_scenarios(cases[(basis, DECLINE, SEVERE)], result)
        known = int(comparison["양쪽단계있음"].sum())
        complete = comparison["양쪽판정완료"]
        row = {"시나리오": case_id, "소비기준": basis, "감소기준": decline, "큰감소기준": severe,
            "단계비교가능수": known, "월합계3_5대비단계변경수": int(comparison["단계변경"].sum()),
            "양쪽판정완료수": int(complete.sum()),
            "판정완료끼리단계변경수": int((complete & comparison["단계변경"]).sum()),
            "상승수": int(comparison["단계차이"].gt(0).sum()), "하락수": int(comparison["단계차이"].lt(0).sum()),
            "판정상태변경수": int(comparison["상태변경"].sum()),
            "같은소비기준3_5대비단계변경수": int(same_basis["단계변경"].sum()),
            "판정완료수": int(result["판정상태"].eq("판정완료").sum()),
            "부분판정수": int(result["판정상태"].eq("부분판정").sum()),
            "판단보류수": int(result["판정상태"].eq("판단보류").sum())}
        for level in range(1, 6):
            row[f"{level}단계수_부분포함"] = int(result["위험단계"].eq(level).sum())
        rows.append(row)
        detail = comparison.merge(result[KEYS + ["소비변화율", "업종제외소비변화율", "이동변화율",
            "전월소비변화율", "전월업종제외소비변화율", "전월이동변화율"]], on=KEYS, validate="one_to_one")
        detail["시나리오"], detail["소비기준"] = case_id, basis
        detail["감소기준"], detail["큰감소기준"] = decline, severe
        dates = pd.to_datetime(detail["월"], format="%Y%m")
        detail["현재월일수"] = dates.dt.days_in_month
        detail["전월일수"] = (dates.dt.to_period("M") - 1).dt.days_in_month
        detail_tables.append(detail)
    return pd.DataFrame(rows), pd.concat(detail_tables, ignore_index=True), baseline


def load_verified_baseline():
    """분석 기능들이 기본 판정의 입력·값·결측을 같은 방식으로 대조한다."""
    inputs, sources = load_inputs()
    baseline_path = OUTPUT / "risk_levels.csv"
    baseline_record = OUTPUT / "summary.json"
    saved = json.loads(baseline_record.read_text(encoding="utf-8"))
    if (saved.get("status") != "passed" or saved.get("rule_version") != VERSION
            or saved.get("decline_threshold") != DECLINE or saved.get("severe_threshold") != SEVERE):
        raise ValueError("기본 판정을 먼저 정상 실행해야 합니다.")
    # 실행 코드는 확장될 수 있지만, 기존 입력/설계와 기본 CSV가 바뀌었다면 재확인한다.
    for path in sources + [baseline_path, REPO / "docs" / "risk_model_design.md"]:
        if saved["sha256"].get(path.relative_to(REPO).as_posix()) != file_hash(path):
            raise ValueError(f"기본 판정 기록이 오래됐습니다: {path.name}. 기본 판정부터 다시 실행하세요.")
    baseline = classify_risk(inputs)
    # CSV의 빈 조건값을 NaN/False로 바꾸지 않고 미확인(boolean NA)으로 복원한다.
    types = {**{key: str for key in KEYS}, "위험단계": "Int64"}
    types.update({column: "boolean" for column in baseline.select_dtypes(include="boolean")})
    stored = pd.read_csv(baseline_path, dtype=types)
    pd.testing.assert_frame_equal(baseline, stored, check_dtype=False)
    return inputs, sources + [baseline_path, baseline_record, REPO / "docs" / "risk_model_design.md"], baseline, file_hash(baseline_path)


def run_sensitivity():
    inputs, sources, baseline, saved_hash = load_verified_baseline()
    comparisons, details, recalculated = analyze_sensitivity(inputs)
    pd.testing.assert_frame_equal(baseline, recalculated)
    baseline_path = OUTPUT / "risk_levels.csv"
    folder = OUTPUT / "sensitivity"
    case_path, detail_path = folder / "scenarios.csv", folder / "details.csv"
    comparisons.to_csv(case_path, index=False, encoding="utf-8-sig")
    details.to_csv(detail_path, index=False, encoding="utf-8-sig")
    calendar_case = details.loc[details["시나리오"].eq("daily_d03_s05")]
    monthly = calendar_case.groupby("월").agg(
        단계비교가능수=("양쪽단계있음", "sum"), 단계변경수=("단계변경", "sum"),
        판정상태변경수=("상태변경", "sum")).reset_index()
    if file_hash(baseline_path) != saved_hash:
        raise ValueError("민감도 분석 중 기본 판정 CSV가 변경됐습니다.")
    summary = {"status": "passed", "analysis_version": "activity-sensitivity-v1",
        "run_at_utc": datetime.now(timezone.utc).isoformat(), "baseline_rule_version": VERSION,
        "scenario_count": len(comparisons), "input_rows": len(inputs),
        "threshold_grid": {"decline": [.02, .03, .04], "severe": [.04, .05, .06]},
        "default_rule_unchanged": {"consumption_basis": "monthly", "decline": DECLINE, "severe": SEVERE},
        "calendar_case": comparisons.loc[comparisons["시나리오"].eq("daily_d03_s05")].to_dict("records")[0],
        "calendar_by_month": monthly.to_dict("records"),
        "limitations": ["일평균은 달력 일수로 나눈 소비. 영업일·공휴일·계절성 보정은 아님",
            "기본 소비와 업종 제외 소비를 모두 일평균화하며 이동 변화율은 유지",
            "임계값 격자는 ±1%p 영향 점검용. 최적값·정답·정확도 검증이 아님",
            "부분판정은 하한. 전체 비교와 양쪽 판정완료 비교를 구분",
            "시나리오 반복 행은 추가 독립 표본이 아님. 7월 보류를 단계 변경으로 세지 않음"],
        "sha256": {p.relative_to(REPO).as_posix(): file_hash(p) for p in
                   sources + [Path(__file__), case_path, detail_path]}}
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(comparisons[["시나리오", "월합계3_5대비단계변경수", "같은소비기준3_5대비단계변경수"]].to_string(index=False))
    print("일수 점검:", json.dumps(summary["calendar_case"], ensure_ascii=False))


REGION_QUALITY = ["통신_전체관측위치수", "통신_연령관측위치수", "통신_연령관측률",
                  "통신_시간관측위치수", "통신_시간관측률", "통신_요일관측위치수", "통신_요일관측률"]


def review_temporal_quality(baseline, features):
    """연속 월의 완료 판정끼리 전이를 집계하고 관측 범위 변화는 설명용으로 남긴다."""
    feature_columns = REGION_QUALITY + ["통신_연령유동량", "통신_전월공통위치비율",
                                        "카드1_해석보류_결제건수_비중"]
    require_columns(features, KEYS + feature_columns, "관측 범위 검토")
    require_keys(features, KEYS, "관측 범위 검토")
    require_keys(baseline, KEYS, "기본 판정 검토")
    overlap = [col for col in feature_columns if col in baseline]
    for col in overlap:
        pd.testing.assert_series_equal(baseline.set_index(KEYS).sort_index()[col],
            features.set_index(KEYS).sort_index()[col], check_dtype=False)
    extra = [col for col in feature_columns if col not in baseline]
    data = baseline.merge(features[KEYS + extra], on=KEYS, how="outer", validate="one_to_one", indicator=True)
    if not data["_merge"].eq("both").all():
        raise ValueError("판정 결과와 관측 범위 특징의 키가 다릅니다.")
    data = data.drop(columns="_merge").sort_values(["지역", "연령대", "월"]).reset_index(drop=True)
    if data.groupby(["월", "지역"])[REGION_QUALITY].nunique(dropna=False).gt(1).any().any():
        raise ValueError("지역 공통 관측 품질 값이 연령별로 다릅니다.")
    groups = data.groupby(["지역", "연령대"])
    month = pd.to_datetime(data["월"], format="%Y%m").dt.to_period("M").astype("int64")
    adjacent = month.groupby([data["지역"], data["연령대"]]).diff().eq(1)
    previous_columns = ["위험단계", "판정상태", "통신_연령유동량", "통신_연령관측위치수",
                        "통신_연령관측률", "통신_전월공통위치비율", "카드1_해석보류_결제건수_비중"]
    for col in previous_columns:
        data[f"전월_{col}"] = groups[col].shift(1).where(adjacent)
    data["전월연속자료있음"] = adjacent
    data["양쪽단계있음"] = adjacent & data["위험단계"].notna() & data["전월_위험단계"].notna()
    data["완료끼리비교"] = data["양쪽단계있음"] & data["판정상태"].eq("판정완료") & data["전월_판정상태"].eq("판정완료")
    data["단계차이"] = (data["위험단계"] - data["전월_위험단계"]).where(data["양쪽단계있음"])
    labels = []
    for _, row in data.iterrows():
        if not row["전월연속자료있음"]:
            label = "전월자료없음"
        elif row["완료끼리비교"]:
            label = "상승" if row["단계차이"] > 0 else "하락" if row["단계차이"] < 0 else "유지"
        else:
            label = "부분판정포함" if row["양쪽단계있음"] else "보류포함"
        labels.append(label)
    data["전이구분"] = labels
    for current, previous, name in [
        ("통신_연령관측률", "전월_통신_연령관측률", "연령관측률전월차이"),
        ("통신_전월공통위치비율", "전월_통신_전월공통위치비율", "공통위치비율전월차이"),
        ("카드1_해석보류_결제건수_비중", "전월_카드1_해석보류_결제건수_비중", "해석보류비중전월차이")]:
        data[name] = data[current] - data[previous]
    data["연령관측위치수변화율"] = (safe_ratio(data["통신_연령관측위치수"], data["전월_통신_연령관측위치수"]) - 1).where(adjacent)
    data["유동량단순변화율"] = (safe_ratio(data["통신_연령유동량"], data["전월_통신_연령유동량"]) - 1).where(adjacent)
    data["관측범위감소동반"] = data[["연령관측률전월차이", "공통위치비율전월차이", "연령관측위치수변화율"]].lt(-1e-12).any(axis=1)
    comparable_flow = data["유동량단순변화율"].notna() & data["이동변화율"].notna()
    data["단순공통3퍼센트판정다름"] = comparable_flow & (
        data["유동량단순변화율"].le(-DECLINE) != data["이동변화율"].le(-DECLINE))
    # 단순 합계 비교는 진단용 반사실 비교이며, 기본 공통 위치 기준을 대체하지 않는다.
    naive_input = data[KEYS + [TOTAL, FILTERED, MOVEMENT]].copy()
    naive_input[MOVEMENT] = data["유동량단순변화율"]
    naive = classify_risk(naive_input)
    difference = compare_scenarios(baseline, naive).rename(columns={
        "비교단계": "단순유동기준단계", "비교판정상태": "단순유동기준상태", "단계변경": "단순유동기준단계변경"})
    data = data.merge(difference[KEYS + ["단순유동기준단계", "단순유동기준상태", "단순유동기준단계변경"]], on=KEYS, validate="one_to_one")
    region = data[["월", "지역"] + REGION_QUALITY].drop_duplicates(["월", "지역"]).sort_values(["지역", "월"]).reset_index(drop=True)
    region_month = pd.to_datetime(region["월"], format="%Y%m").dt.to_period("M").astype("int64")
    region_adjacent = region_month.groupby(region["지역"]).diff().eq(1)
    for kind in ["연령", "시간", "요일"]:
        col = f"통신_{kind}관측률"
        region[f"{kind}관측률전월차이"] = region.groupby("지역")[col].diff().where(region_adjacent)
    return data.sort_values(KEYS).reset_index(drop=True), region.sort_values(["월", "지역"]).reset_index(drop=True)


def run_review():
    _, sources, baseline, saved_hash = load_verified_baseline()
    feature_path = PROCESSED / "risk_features.csv"
    features = pd.read_csv(feature_path, dtype={key: str for key in KEYS})
    transitions, region = review_temporal_quality(baseline, features)
    folder = OUTPUT / "review"
    transitions_path, region_path = folder / "transitions.csv", folder / "region_quality.csv"
    transitions.to_csv(transitions_path, index=False, encoding="utf-8-sig")
    region.to_csv(region_path, index=False, encoding="utf-8-sig")
    complete = transitions.loc[transitions["완료끼리비교"]]
    matrix = complete.groupby(["전월_위험단계", "위험단계"]).size().reset_index(name="조합수")
    monthly = [{"월": month, "연속월쌍수": int(group["전월연속자료있음"].sum()),
        "완료끼리비교수": int(group["완료끼리비교"].sum()),
        "상승수": int(group["전이구분"].eq("상승").sum()), "하락수": int(group["전이구분"].eq("하락").sum()),
        "유지수": int(group["전이구분"].eq("유지").sum())} for month, group in transitions.groupby("월")]
    summary = {"status": "passed", "review_version": "activity-review-v1", "baseline_rule_version": VERSION,
        "run_at_utc": datetime.now(timezone.utc).isoformat(), "cohort_rows": len(transitions),
        "region_month_rows": len(region), "adjacent_pairs": int(transitions["전월연속자료있음"].sum()),
        "numeric_level_pairs_including_partial": int(transitions["양쪽단계있음"].sum()),
        "completed_pairs": len(complete), "transition_counts": transitions["전이구분"].value_counts().to_dict(),
        "rises_with_observation_range_decrease": int((transitions["전이구분"].eq("상승") & transitions["관측범위감소동반"]).sum()),
        "observation_range_by_transition": complete.groupby(["전이구분", "관측범위감소동반"]).size().reset_index(name="조합수").to_dict("records"),
        "naive_common_flow_threshold_disagreements": int(transitions["단순공통3퍼센트판정다름"].sum()),
        "naive_flow_level_changes": int(transitions["단순유동기준단계변경"].sum()),
        "completed_transition_matrix": matrix.to_dict("records"), "by_month": monthly,
        "limitations": ["완료 판정끼리의 연속 월 비교만 상승·하락·유지로 집계",
            "부분판정의 단계는 하한. 보류에서 숫자가 생긴 것을 상승으로 세지 않음",
            "관측률은 합쳐진 위치 중 자료 존재 비율. 인구 대표성·정확도·위험 점수가 아님",
            "관측범위감소동반은 세 관측 지표 중 하나가 전월 하락했다는 뜻. 오차 1e-12만 제외하며 품질 합격 기준은 아님",
            "지역 공통값은 연령에 반복되므로 지역 품질 표는 월×지역 12개 조합만 기록",
            "단순 유동 합계 기준 비교는 위치 구성 영향을 살피는 진단이며 새 판정 기준이 아님",
            "월×지역×연령의 반복 비교이며 독립적인 개인 표본 수가 아님",
            "관측 변화와 단계 변화의 동반은 인과관계나 실제 고립의 증거가 아님"],
        "sha256": {p.relative_to(REPO).as_posix(): file_hash(p) for p in
                   sources + [Path(__file__), transitions_path, region_path]}}
    if file_hash(OUTPUT / "risk_levels.csv") != saved_hash:
        raise ValueError("전이 검토 중 기본 CSV가 변경됐습니다.")
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["completed_pairs", "transition_counts",
        "rises_with_observation_range_decrease", "naive_common_flow_threshold_disagreements", "naive_flow_level_changes"]}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="5단계 분류·민감도 검증·월별 전이/관측 범위 검토")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sensitivity", action="store_true", help="기본 판정은 유지하고 18개 비교 시나리오만 실행")
    mode.add_argument("--review", action="store_true", help="기본 판정은 유지하고 월별 전이·관측 범위만 검토")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    folder = OUTPUT / "sensitivity" if args.sensitivity else OUTPUT / "review" if args.review else OUTPUT
    folder.mkdir(parents=True, exist_ok=True)
    record = folder / "summary.json"
    record.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    try:
        action = run_sensitivity if args.sensitivity else run_review if args.review else run
        action()
    except Exception as error:
        record.write_text(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
