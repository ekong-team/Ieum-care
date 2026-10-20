"""지역코드·좌표 점검 → SGIS 경계 대조 → 불일치 제외 민감도 분석.

실행: python scripts/data_processing/validate_regions.py
일부만 실행: --only coords | boundary | sensitivity. 기본 특징과 매핑은 변경하지 않는다.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import io
import json
import zipfile

import numpy as np
import pandas as pd
import shapefile
import shapely
from pyproj import CRS
import pyproj

from build_risk_features import KEYS, LOCATION, load_inputs, summarize_telecom, common_location_changes
from data_contract import REGIONS, require_keys, require_months, file_hash

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
BOUNDARY = REPO / "data" / "external" / "sgis" / "bnd_sigungu_00_2025_2Q.zip"

# 1. 코드·좌표 형식 및 관측 규모
def audit_coordinates():
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
        "status": "coordinate_audit_passed",
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
        "boundary_validation": "경계 판정은 spatial_validation_summary.json에서 별도 확인",
        "boundary_source": "https://sgis.mods.go.kr/view/pss/openDataIntrcn",
        "required_boundary": "2025년 센서스용 행정구역 경계: 시군구, SHP 및 PRJ/DBF/SHX",
        "notes": ["좌표 범위와 코드 형식만으로 지역 소속을 확정하지 않음",
                  "동일코드 다중좌표는 정의 확인 대상이며 임의 통합하지 않음",
                  "기존 지역 매핑 및 risk_features.csv 변경 없음"],
    }
    (PROCESSED / "region_mapping_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))



# 2. 전국 시군구 경계 대조
def load_boundaries(path):
    """ZIP을 직접 읽으며 경계를 자동 수정하지 않는다."""
    with zipfile.ZipFile(path) as archive:
        shapes = [n for n in archive.namelist() if n.lower().endswith(".shp")]
        if len(shapes) != 1:
            raise ValueError("ZIP에 시군구 SHP 파일이 한 개 필요합니다.")
        base = shapes[0][:-4]
        crs = CRS.from_wkt(archive.read(base + ".prj").decode("utf-8-sig"))
        if crs.to_epsg() != 5179:
            raise ValueError(f"경계 좌표계가 EPSG:5179와 다릅니다: {crs}")
        encoding = archive.read(base + ".cpg").decode().strip()
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(base + ".shp")),
            shx=io.BytesIO(archive.read(base + ".shx")),
            dbf=io.BytesIO(archive.read(base + ".dbf")), encoding=encoding)
        records, geometries = [], []
        for item in reader.iterShapeRecords():
            records.append(item.record.as_dict())
            geometries.append(shapely.geometry.shape(item.shape.__geo_interface__))
    attributes = pd.DataFrame(records)
    require_keys(attributes, ["SIGUNGU_CD"], "시군구 경계")
    if set(attributes["BASE_DATE"]) != {"20250630"}:
        raise ValueError("경계 기준일이 20250630과 다릅니다.")
    geometries = np.array(geometries, dtype=object)
    invalid = ~shapely.is_valid(geometries) | shapely.is_empty(geometries)
    if invalid.any():
        raise ValueError(f"유효하지 않은 경계: {attributes.loc[invalid, 'SIGUNGU_CD'].tolist()}")
    return attributes, geometries


def classify_points(x, y, expected_codes, attributes, geometries):
    """모든 경계 후보를 보존하고 경계 위의 점도 별도 상태로 기록한다."""
    points = shapely.points(x, y)
    pairs = shapely.STRtree(geometries).query(points, predicate="covered_by")
    hits = [[] for _ in points]
    for point_index, boundary_index in pairs.T:
        hits[point_index].append(int(boundary_index))
    code_indices = {code: i for i, code in enumerate(attributes["SIGUNGU_CD"])}
    rows = []
    for i, candidates in enumerate(hits):
        expected = expected_codes[i]
        codes = sorted(attributes.iloc[candidates]["SIGUNGU_CD"].tolist())
        if not candidates:
            status = "no_polygon"
        elif len(candidates) > 1:
            status = "multiple_polygons"
        elif expected not in code_indices:
            status = "unresolved_code"
        elif codes[0] != expected:
            status = "code_mismatch"
        elif shapely.within(points[i], geometries[candidates[0]]):
            status = "interior_match"
        else:
            status = "boundary_match"
        distance = np.nan
        if status != "interior_match" and expected in code_indices:
            # 코드가 가리키는 경계선까지의 거리. 통과 기준이나 재매핑에는 사용하지 않는다.
            distance = float(shapely.distance(points[i], geometries[code_indices[expected]].boundary))
        rows.append((status, "|".join(codes), len(candidates), distance))
    return pd.DataFrame(rows, columns=["공간판정", "좌표지역코드", "경계후보수", "코드경계까지m"])


def compare_boundaries():
    attributes, geometries = load_boundaries(BOUNDARY)
    source = PROCESSED / "telecom_features.csv"
    df = pd.read_csv(source, usecols=["STD_YM"] + LOCATION + ["FLOW_POP_TOTAL"],
                     dtype={"STD_YM": str, "BLOCK_CD": str})
    require_keys(df, ["STD_YM"] + LOCATION, "통신 좌표")
    require_months(df["STD_YM"], "통신 좌표")
    if not df["BLOCK_CD"].str.fullmatch(r"\d{20}").all():
        raise ValueError("BLOCK_CD 형식 오류")
    if not np.isfinite(df[LOCATION[1:]].to_numpy(dtype=float)).all():
        raise ValueError("좌표 결측 또는 무한대")
    unique = df[LOCATION].drop_duplicates().reset_index(drop=True)
    unique["지역코드"] = unique["BLOCK_CD"].str[:5]
    result = classify_points(unique["X_COORD"].to_numpy(), unique["Y_COORD"].to_numpy(),
                             unique["지역코드"].to_numpy(), attributes, geometries)
    unique = pd.concat([unique, result], axis=1)
    names = attributes.set_index("SIGUNGU_CD")["SIGUNGU_NM"].to_dict()
    unique["코드지역명"] = unique["지역코드"].map(names).fillna("현 경계에 코드 없음")
    unique["좌표지역명"] = unique["좌표지역코드"].map(
        lambda codes: "|".join(names.get(code, "") for code in codes.split("|")))
    unique.to_csv(PROCESSED / "spatial_validation_locations.csv", index=False, encoding="utf-8-sig")
    unique.loc[unique["공간판정"].ne("interior_match")].to_csv(
        PROCESSED / "spatial_validation_exceptions.csv", index=False, encoding="utf-8-sig")
    joined = df.merge(unique, on=LOCATION, how="left", validate="many_to_one")
    monthly = joined.groupby(["STD_YM", "지역코드", "공간판정"]).agg(
        위치행수=("BLOCK_CD", "size"), 연령자료관측행수=("FLOW_POP_TOTAL", "count"),
        연령유동량=("FLOW_POP_TOTAL", lambda s: s.sum(min_count=1))).reset_index()
    monthly["코드지역유동량대비비중"] = monthly["연령유동량"] / monthly.groupby(
        ["STD_YM", "지역코드"])["연령유동량"].transform("sum").where(lambda s: s > 0)
    monthly.to_csv(PROCESSED / "spatial_validation_monthly.csv", index=False, encoding="utf-8-sig")
    target = unique["지역코드"].isin(REGIONS)
    summary = {
        "status": "comparison_complete_with_exceptions" if unique["공간판정"].ne("interior_match").any()
                  else "comparison_complete_no_exceptions",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "boundary_file": BOUNDARY.name, "boundary_date": "20250630", "boundary_epsg": 5179,
        "source": "https://sgis.mods.go.kr/view/pss/openDataIntrcn",
        "telecom_crs_assumption": "UTM-K를 EPSG:5179로 해석. 제공기관 확인 전 조건부 결과",
        "boundary_count": len(attributes), "location_count": len(unique),
        "all_location_status_counts": unique["공간판정"].value_counts().to_dict(),
        "target_location_status_counts": unique.loc[target, "공간판정"].value_counts().to_dict(),
        "missing_code_boundaries": sorted(set(unique["지역코드"]) - set(attributes["SIGUNGU_CD"])),
        "versions": {"shapely": shapely.__version__, "pyproj": pyproj.__version__,
                     "pyshp": shapefile.__version__, "pandas": pd.__version__, "numpy": np.__version__},
        "sha256": {"boundary_zip": file_hash(BOUNDARY), "telecom_features": file_hash(source),
                   "script": file_hash(Path(__file__)),
                   "data_contract": file_hash(Path(__file__).with_name("data_contract.py")),
                   "builder": file_hash(Path(__file__).with_name("build_risk_features.py"))},
        "policy": "불일치가 있어도 기존 지역 매핑과 특징 값은 변경하지 않음",
    }
    (PROCESSED / "spatial_validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))



# 3. 불일치 위치 제외 시 특징 차이
def analyze_sensitivity():
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


def main():
    parser = argparse.ArgumentParser(description="코드·좌표·행정경계 검증")
    parser.add_argument("--only", choices=["all", "coords", "boundary", "sensitivity"], default="all")
    section = parser.parse_args().only
    steps = {"coords": audit_coordinates, "boundary": compare_boundaries, "sensitivity": analyze_sensitivity}
    for name, action in steps.items():
        if section in ("all", name):
            print(f"지역 검증: {name}", flush=True)
            action()


if __name__ == "__main__":
    main()
