"""통신 좌표와 2025년 2분기 SGIS 시군구 경계 대조. 특징 값은 변경하지 않는다.

통신의 UTM-K를 EPSG:5179로 해석한 조건부 대조이며, 제공기관의 전체 CRS 확인을 대신하지 않는다.
경계 위/복수 경계/경계 밖을 정상 내부 점과 구분한다. 거리로 임의 통과시키지 않는다.
"""
from pathlib import Path
from datetime import datetime, timezone
import io
import json
import zipfile

import numpy as np
import pandas as pd
import shapefile
import shapely
from pyproj import CRS
import pyproj

from data_contract import REGIONS, require_keys, require_months
from validate_processed import file_hash

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
BOUNDARY = REPO / "data" / "external" / "sgis" / "bnd_sigungu_00_2025_2Q.zip"
LOCATION = ["BLOCK_CD", "X_COORD", "Y_COORD"]


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


def main():
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
                   "script": file_hash(Path(__file__))},
        "policy": "불일치가 있어도 기존 지역 매핑과 특징 값은 변경하지 않음",
    }
    (PROCESSED / "spatial_validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
