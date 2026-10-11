"""경계 대조 전 코드·좌표 품질 점검. 기존 특징과 지역 매핑은 변경하지 않는다.

실행: python scripts/data_processing/audit_region_mapping.py
코드 앞 5자리만으로 공간 검증 통과를 선언하지 않는다.
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd

from data_contract import REGIONS, require_keys, require_months
from validate_processed import file_hash

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"


def main():
    source = PROCESSED / "telecom_features.csv"
    cols = ["STD_YM", "BLOCK_CD", "X_COORD", "Y_COORD", "FLOW_POP_TOTAL"]
    df = pd.read_csv(source, usecols=cols, dtype={"STD_YM": str, "BLOCK_CD": str})
    require_keys(df, cols[:4], "통신 위치")
    require_months(df["STD_YM"], "통신 위치")
    coords = df[["X_COORD", "Y_COORD"]].to_numpy(dtype=float)
    if not np.isfinite(coords).all():
        raise ValueError("좌표에 결측 또는 무한대가 있습니다.")
    if not df["BLOCK_CD"].str.fullmatch(r"\d{20}").all():
        raise ValueError("소지역코드가 20자리 숫자 형식이 아닙니다.")

    df["지역코드"] = df["BLOCK_CD"].str[:5]
    df["연결지역"] = df["지역코드"].map(REGIONS).fillna("대상 밖: 결합 제외")
    # 동일 코드의 좌표가 여러 개인지 기록한다. 코드가 격자/구역인지 확인 전 오류로 단정하지 않음.
    locations = df[["BLOCK_CD", "X_COORD", "Y_COORD", "지역코드", "연결지역"]].drop_duplicates()
    counts = locations.groupby("BLOCK_CD").size()
    locations["동일코드좌표수"] = locations["BLOCK_CD"].map(counts)
    locations["동일좌표지역코드수"] = locations.groupby(["X_COORD", "Y_COORD"])["지역코드"].transform("nunique")
    locations.sort_values(["지역코드", "BLOCK_CD", "X_COORD", "Y_COORD"]).to_csv(
        PROCESSED / "region_mapping_locations.csv", index=False, encoding="utf-8-sig")

    # 제외 규모는 유동량 기준으로도 확인한다. 유동량은 고유 인원 수가 아니다.
    monthly = df.groupby(["STD_YM", "지역코드", "연결지역"]).agg(
        위치행수=("BLOCK_CD", "size"), 연령자료관측행수=("FLOW_POP_TOTAL", "count"),
        연령유동량=("FLOW_POP_TOTAL", lambda values: values.sum(min_count=1))).reset_index()
    totals = monthly.groupby("STD_YM")["연령유동량"].transform("sum")
    monthly["전체대비유동량비중"] = monthly["연령유동량"] / totals.where(totals > 0)
    monthly.to_csv(PROCESSED / "region_mapping_monthly.csv", index=False, encoding="utf-8-sig")

    summary = {
        "status": "coordinate_audit_passed_boundary_validation_pending",
        "source_sha256": file_hash(source),
        "rows": len(df), "unique_locations": len(locations),
        "block_codes_with_multiple_coordinates": int(counts.gt(1).sum()),
        "maximum_coordinates_per_block_code": int(counts.max()),
        "month_block_pairs_with_multiple_coordinates": int(
            df.groupby(["STD_YM", "BLOCK_CD"]).size().gt(1).sum()),
        "coordinates_shared_by_multiple_region_codes": int(
            locations.loc[locations["동일좌표지역코드수"].gt(1), ["X_COORD", "Y_COORD"]].drop_duplicates().shape[0]),
        "outside_target_rows": int((~df["지역코드"].isin(REGIONS)).sum()),
        "outside_target_flow_share_by_month": {
            str(month): float(share) for month, share in
            monthly.loc[~monthly["지역코드"].isin(REGIONS)]
            .groupby("STD_YM")["전체대비유동량비중"].sum().items()},
        "rows_by_region_code": {str(k): int(v) for k, v in df["지역코드"].value_counts().items()},
        "raw_coordinate_reference": "제공 정의서: UTM-K. 전체 CRS와 좌표 대표점 의미는 미확정",
        "boundary_validation": "미실행: 공식 경계 파일 필요",
        "boundary_source": "https://sgis.mods.go.kr/view/pss/openDataIntrcn",
        "required_boundary": "2025년 센서스용 행정구역 경계: 시군구, SHP 및 PRJ/DBF/SHX",
        "notes": ["좌표 범위와 코드 형식만으로 지역 소속을 확정하지 않음",
                  "동일코드 다중좌표는 정의 확인 대상이며 임의 통합하지 않음",
                  "기존 지역 매핑 및 risk_features.csv 변경 없음"],
    }
    (PROCESSED / "region_mapping_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
