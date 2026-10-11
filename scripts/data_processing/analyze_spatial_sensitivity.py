"""경계 내부 일치 위치만 사용할 때 통신 특징이 얼마나 바뀌는지 비교한다.

기존 risk_features.csv를 덮어쓰지 않으며, 위험 점수/등급은 계산하지 않는다.
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd

from build_risk_features import KEYS, LOCATION, load_inputs, summarize_telecom, common_location_changes
from validate_processed import file_hash

PROCESSED = Path(__file__).resolve().parents[2] / "data" / "processed"


def main():
    report = json.loads((PROCESSED / "spatial_validation_summary.json").read_text(encoding="utf-8"))
    if report["sha256"]["telecom_features"] != file_hash(PROCESSED / "telecom_features.csv"):
        raise ValueError("통신 특징이 변경되었습니다. 경계 대조부터 다시 실행하세요.")
    telecom, _ = load_inputs()
    locations = pd.read_csv(PROCESSED / "spatial_validation_locations.csv", dtype={"BLOCK_CD": str})
    joined = telecom.merge(locations[LOCATION + ["공간판정"]], on=LOCATION, validate="many_to_one", how="left")
    if joined["공간판정"].isna().any():
        raise ValueError("공간 판정이 없는 위치가 있습니다.")
    strict = joined.loc[joined["공간판정"].eq("interior_match")].drop(columns="공간판정")
    tables = []
    for data in [telecom, strict]:
        table = summarize_telecom(data).merge(common_location_changes(data), on=KEYS, validate="one_to_one")
        tables.append(table.set_index(KEYS).sort_index())
    before, after = tables
    pd.testing.assert_index_equal(before.index, after.index)
    pd.testing.assert_index_equal(before.columns, after.columns)
    rows = []
    for col in before:
        a, b = before[col], after[col]
        delta = b - a
        relative = delta.abs() / a.abs().where(a.abs() > 0)
        rows.append({"특징": col, "최대절대차이": delta.abs().max(),
                     "최대상대차이": relative.max(),
                     "결측위치변경수": int(a.isna().ne(b.isna()).sum())})
    pd.DataFrame(rows).to_csv(PROCESSED / "spatial_sensitivity_metrics.csv", index=False, encoding="utf-8-sig")
    changed = (after - before).reset_index()
    changed.to_csv(PROCESSED / "spatial_sensitivity_deltas.csv", index=False, encoding="utf-8-sig")
    summary = {"excluded_month_location_rows": len(telecom) - len(strict),
               "comparison": "코드 기준 유지 대 경계 내부 일치 위치만 사용",
               "maximum_age_flow_relative_difference": float(
                   ((after["통신_연령유동량"] - before["통신_연령유동량"]).abs()
                    / before["통신_연령유동량"].where(lambda s: s > 0)).max()),
               "maximum_age_change_absolute_difference": float(
                   (after["통신_연령유동량_전월변화율"] - before["통신_연령유동량_전월변화율"]).abs().max()),
               "missing_pattern_changed": bool(any(row["결측위치변경수"] for row in rows)),
               "telecom_sha256": report["sha256"]["telecom_features"],
               "risk_features_sha256_unchanged": file_hash(PROCESSED / "risk_features.csv")}
    if np.isinf((after - before).to_numpy()).any():
        raise ValueError("비교 결과에 무한대가 있습니다.")
    (PROCESSED / "spatial_sensitivity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
