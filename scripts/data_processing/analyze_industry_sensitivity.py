"""해석보류 업종 처리에 따른 카드 후보 특징 민감도. 위험 등급은 계산하지 않는다.

기존 card_features/risk_features는 유지하고 비교 결과만 data/processed에 저장한다.
신규 분류의 정확도를 검증하는 분석이 아니라 처리 가정의 영향을 확인하는 분석이다.
"""
from pathlib import Path
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd

from data_contract import MONTHS, require_keys, require_months, require_numbers
from industry_classification import ALL_GROUPS, RULES, VERSION
from build_risk_features import safe_ratio
from validate_processed import file_hash

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
KEYS = ["월", "지역", "연령대"]
SCENARIOS = {
    "현재기준": "외식·카페+문화·오락+운동 / 전체 건수. 기본 특징 유지",
    "보류제외분모": "후보 건수 / (전체-해석보류-미분류). 분모 축소 영향만 비교",
    "보류전체후보포함": "(후보+해석보류+미분류) / 전체. 극단 가정이며 채택하지 않음",
    "외식제외후보": "문화·오락+운동 / 전체. 후보 업종 선택 민감도 비교",
}


def make_scenarios(card):
    card = card.sort_values(["지역", "연령대", "월"]).reset_index(drop=True)
    total = card["카드1_전체_결제건수"]
    held = card["카드1_해석보류_결제건수"] + card["카드1_미분류_결제건수"]
    candidate_groups = [group for group, rule in RULES.items() if rule[0] == "사회활동관련_후보"]
    candidate = card[[f"카드1_{group}_결제건수" for group in candidate_groups]].sum(axis=1)
    versions = {
        "현재기준": (candidate, total),
        "보류제외분모": (candidate, total - held),
        "보류전체후보포함": (candidate + held, total),
        "외식제외후보": (candidate - card["카드1_외식·카페_결제건수"], total),
    }
    result = []
    for name, (count, denominator) in versions.items():
        table = card[KEYS].copy()
        table["비교안"] = name
        table["후보건수"] = count
        table["분모건수"] = denominator
        table["후보비중"] = safe_ratio(count, denominator)
        table["해석보류비중"] = safe_ratio(card["카드1_해석보류_결제건수"], total)
        table["미분류비중"] = safe_ratio(card["카드1_미분류_결제건수"], total)
        group = table.groupby(["지역", "연령대"])
        month = pd.to_datetime(table["월"], format="%Y%m").dt.to_period("M").astype("int64")
        adjacent = month.groupby([table["지역"], table["연령대"]]).diff().eq(1)
        table["건수전월변화율"] = (safe_ratio(count, group["후보건수"].shift(1)) - 1).where(adjacent)
        table["비중전월차이"] = group["후보비중"].diff().where(adjacent)
        result.append(table)
    return pd.concat(result, ignore_index=True)


def direction_flips(left, right):
    """아주 작은 부동소수점 차이는 방향 전환으로 세지 않는다."""
    comparable = left.notna() & right.notna()
    flips = ((left > 1e-12) & (right < -1e-12)) | ((left < -1e-12) & (right > 1e-12))
    return int((comparable & flips).sum()), int(comparable.sum())


def main():
    card_path = PROCESSED / "card_features.csv"
    risk_path = PROCESSED / "risk_features.csv"
    review_path = PROCESSED / "industry_classification_review.csv"
    card = pd.read_csv(card_path, dtype={key: str for key in KEYS})
    risk = pd.read_csv(risk_path, dtype={key: str for key in KEYS})
    review = pd.read_csv(review_path)
    require_keys(card, KEYS, "카드 특징")
    require_keys(risk, KEYS, "결합 특징")
    require_months(card["월"], "카드 특징")
    pd.testing.assert_frame_equal(card.sort_values(KEYS).reset_index(drop=True),
                                  risk[card.columns].sort_values(KEYS).reset_index(drop=True), check_dtype=False)
    groups = [f"카드1_{group}_결제건수" for group in ALL_GROUPS]
    require_numbers(card, groups + ["카드1_전체_결제건수"], "카드 건수", integer=True)
    if not card[groups].sum(axis=1).eq(card["카드1_전체_결제건수"]).all():
        raise ValueError("업종그룹별 건수 합계가 전체와 다릅니다.")
    if set(review["분류버전"]) != {VERSION}:
        raise ValueError("업종 검토표 분류 버전이 다릅니다. 카드 특징을 다시 생성하세요.")
    for metric in ["결제금액", "결제건수"]:
        if review[f"카드_{metric}"].sum() != card[f"카드1_전체_{metric}"].sum():
            raise ValueError(f"업종 검토표와 카드 특징의 {metric} 합계가 다릅니다.")

    scenarios = make_scenarios(card)
    base = scenarios.loc[scenarios["비교안"].eq("현재기준")].set_index(KEYS).sort_index()
    expected = risk.set_index(KEYS).sort_index()
    for scenario_col, risk_col in [
        ("후보건수", "카드1_사회활동관련후보_결제건수"),
        ("후보비중", "카드1_사회활동관련후보_건수비중"),
        ("건수전월변화율", "카드1_사회활동관련후보_건수전월변화율"),
        ("비중전월차이", "카드1_사회활동관련후보_비중전월차이")]:
        pd.testing.assert_series_equal(base[scenario_col], expected[risk_col], check_names=False, check_dtype=False)
    comparisons = []
    for name in SCENARIOS:
        table = scenarios.loc[scenarios["비교안"].eq(name)].set_index(KEYS).sort_index()
        flip_count, count_pairs = direction_flips(base["건수전월변화율"], table["건수전월변화율"])
        flip_share, share_pairs = direction_flips(base["비중전월차이"], table["비중전월차이"])
        comparisons.append({"비교안": name, "가정": SCENARIOS[name],
            "최대비중차이_비율": float((table["후보비중"] - base["후보비중"]).abs().max()),
            "최대건수변화율차이": float((table["건수전월변화율"] - base["건수전월변화율"]).abs().max()),
            "건수변화방향반전": flip_count, "건수변화비교가능행수": count_pairs,
            "비중변화방향반전": flip_share, "비중변화비교가능행수": share_pairs,
            "비중계산불가행수": int(table["후보비중"].isna().sum())})
    if np.isinf(scenarios.select_dtypes(include="number").to_numpy()).any():
        raise ValueError("비교 지표에 무한대가 있습니다.")
    scenarios.to_csv(PROCESSED / "industry_sensitivity_features.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(comparisons).to_csv(PROCESSED / "industry_sensitivity_comparison.csv", index=False, encoding="utf-8-sig")
    coverage = card[KEYS].copy()
    for metric in ["결제건수", "결제금액"]:
        total = card[f"카드1_전체_{metric}"]
        coverage[f"해석보류_{metric}비중"] = safe_ratio(card[f"카드1_해석보류_{metric}"], total)
        coverage[f"미분류_{metric}비중"] = safe_ratio(card[f"카드1_미분류_{metric}"], total)
    coverage.to_csv(PROCESSED / "industry_interpretation_coverage.csv", index=False, encoding="utf-8-sig")
    held = review.loc[review["업종그룹"].isin(["해석보류", "미분류"])].copy()
    for metric in ["결제건수", "결제금액"]:
        held[f"전체대비_{metric}비중"] = held[f"카드_{metric}"] / review[f"카드_{metric}"].sum()
    held = held.sort_values("카드_결제건수", ascending=False)
    held.to_csv(PROCESSED / "industry_held_review.csv", index=False, encoding="utf-8-sig")
    summary = {
        "status": "sensitivity_complete_semantic_definition_pending",
        "run_at_utc": datetime.now(timezone.utc).isoformat(), "classification_version": VERSION,
        "unit": "월×가맹점지역×연령, 카드1 개인 거래만 사용", "rows": len(card), "months": MONTHS,
        "held_count_share": float(card["카드1_해석보류_결제건수"].sum() / card["카드1_전체_결제건수"].sum()),
        "held_amount_share": float(card["카드1_해석보류_결제금액"].sum() / card["카드1_전체_결제금액"].sum()),
        "held_count_share_min": float(coverage["해석보류_결제건수비중"].min()),
        "held_count_share_max": float(coverage["해석보류_결제건수비중"].max()),
        "unknown_count": int(card["카드1_미분류_결제건수"].sum()), "comparisons": comparisons,
        "policy": "해석보류·미분류 보존, 후보 분자에서 제외, 전체 분모에 유지. 기존 특징 변경 없음",
        "limitations": ["업종명만으로 상세 범위·대면 여부를 확정하지 않음",
                        "보류전체후보포함은 영향 확인용 극단 가정이며 권장 모델이 아님",
                        "건수 감소/비중 감소는 고립 라벨이 아니며 방향 반전은 분류 정확도 평가가 아님"],
        "sha256": {path.relative_to(REPO).as_posix(): file_hash(path) for path in
                   [card_path, risk_path, review_path, Path(__file__),
                    Path(__file__).with_name("industry_classification.py"),
                    Path(__file__).with_name("build_risk_features.py"), Path(__file__).with_name("data_contract.py")]},
    }
    (PROCESSED / "industry_sensitivity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
