"""최종 특징의 계약과 값 보존을 검증하고 재현용 파일 해시를 기록한다."""
from pathlib import Path
import hashlib
import json
import platform
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from data_contract import AGES, MONTHS, REGIONS, require_keys
from industry_classification import ALL_GROUPS, VERSION

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
MANIFEST = PROCESSED / "preprocessing_manifest.json"
KEYS = ["월", "지역", "연령대"]


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    card = pd.read_csv(PROCESSED / "card_features.csv", dtype={key: str for key in KEYS})
    risk = pd.read_csv(PROCESSED / "risk_features.csv", dtype={key: str for key in KEYS})
    expected = set(pd.MultiIndex.from_product([MONTHS, REGIONS.values(), AGES.values()]).tolist())
    for name, df in [("카드", card), ("최종 특징", risk)]:
        require_keys(df, KEYS, name)
        if set(map(tuple, df[KEYS].to_numpy())) != expected:
            raise ValueError(f"{name}: 월×지역×연령 조합이 완전하지 않습니다.")
    pd.testing.assert_frame_equal(
        risk.sort_values(KEYS).reset_index(drop=True)[card.columns],
        card.sort_values(KEYS).reset_index(drop=True), check_dtype=False)
    for metric in ["결제금액", "결제건수"]:
        if not card[[f"카드1_{group}_{metric}" for group in ALL_GROUPS]].sum(axis=1).eq(card[f"카드1_전체_{metric}"]).all():
            raise ValueError(f"그룹별 {metric} 합계가 전체와 다릅니다.")
    numeric = risk.select_dtypes(include="number")
    if np.isinf(numeric.to_numpy()).any():
        raise ValueError("최종 특징에 무한대가 있습니다.")
    # 현재 데이터의 계산 불가 값은 첫 달 전월 변화뿐이다. 예상 밖 결측은 중단.
    changes = [col for col in risk if "전월변화율" in col or "건수전월변화율" in col
               or col.endswith("비중전월차이")] + ["통신_전월공통위치비율"]
    for col in numeric:
        expected_missing = risk["월"].eq(MONTHS[0]) if col in changes else pd.Series(False, index=risk.index)
        if not risk[col].isna().eq(expected_missing).all():
            raise ValueError(f"{col}: 예상 밖 결측 또는 첫 달의 잘못된 변화 값이 있습니다.")
    for col in [col for col in numeric if "비중" in col and "전월" not in col or col.endswith("관측률") or col == "통신_전월공통위치비율"]:
        if not risk[col].dropna().between(0, 1).all():
            raise ValueError(f"{col}: 비율이 0~1 범위 밖입니다.")
    if not np.allclose(risk.groupby(["월", "지역"])["통신_연령비중"].sum(), 1):
        raise ValueError("통신 연령비중 합계가 1이 아닙니다.")

    # 코드 매핑에 포함된/제외된 소지역의 범위를 모두 기록. 경계 대조 결과는 아님.
    telecom = pd.read_csv(PROCESSED / "telecom_features.csv", dtype={"STD_YM": str, "BLOCK_CD": str},
                          usecols=["STD_YM", "BLOCK_CD", "X_COORD", "Y_COORD"])
    telecom["지역코드"] = telecom["BLOCK_CD"].str[:5]
    mapping = telecom.groupby("지역코드").agg(
        월별위치행수=("BLOCK_CD", "size"), X최소=("X_COORD", "min"), X최대=("X_COORD", "max"),
        Y최소=("Y_COORD", "min"), Y최대=("Y_COORD", "max")).reset_index()
    mapping["연결지역"] = mapping["지역코드"].map(REGIONS).fillna("대상 밖: 결합 제외")
    mapping.to_csv(PROCESSED / "region_mapping_review.csv", index=False, encoding="utf-8-sig")
    files = list((REPO / "data" / "raw").glob("flow_*_pop_*.csv"))
    files += list((REPO / "data" / "raw").glob("신한카드*데이터*.txt"))
    files += list(Path(__file__).parent.glob("*.py")) + [REPO / "requirements.txt"]
    files += [PROCESSED / name for name in ["telecom_features.csv", "card_features.csv", "risk_features.csv",
                                           "region_mapping_review.csv", "industry_classification_review.csv"]]
    spatial_status = "지역코드 기반 매핑. 좌표와 행정경계의 대조는 미검증"
    spatial_report = PROCESSED / "spatial_validation_summary.json"
    if spatial_report.exists():
        spatial = json.loads(spatial_report.read_text(encoding="utf-8"))
        boundary = REPO / "data" / "external" / "sgis" / spatial["boundary_file"]
        spatial_script = Path(__file__).parent / "validate_region_boundaries.py"
        fresh = (boundary.exists()
                 and spatial["sha256"]["telecom_features"] == file_hash(PROCESSED / "telecom_features.csv")
                 and spatial["sha256"]["boundary_zip"] == file_hash(boundary)
                 and spatial["sha256"]["script"] == file_hash(spatial_script))
        if fresh:
            spatial_status = ("EPSG:5179 가정으로 경계 대조 완료. 예외와 제공기관 CRS 확인은 별도 기록: "
                              + spatial["status"])
            files += [spatial_report, boundary]
            files += [PROCESSED / name for name in ["spatial_validation_locations.csv",
                        "spatial_validation_exceptions.csv", "spatial_validation_monthly.csv"]]
        else:
            spatial_status = "공간 검증 기록의 입력/코드 해시가 달라 재실행 필요"
    industry_status = "업종 처리 가정의 민감도 분석 미실행"
    industry_report = PROCESSED / "industry_sensitivity_summary.json"
    if industry_report.exists():
        industry = json.loads(industry_report.read_text(encoding="utf-8"))
        fresh = (industry["classification_version"] == VERSION
                 and all((REPO / name).exists() and file_hash(REPO / name) == digest
                         for name, digest in industry["sha256"].items()))
        if fresh:
            industry_status = "민감도 분석 완료, 상세 업종 의미 확인은 보류: " + industry["status"]
            files += [industry_report]
            files += [PROCESSED / name for name in ["industry_held_review.csv",
                "industry_interpretation_coverage.csv", "industry_sensitivity_features.csv",
                "industry_sensitivity_comparison.csv"]]
        else:
            industry_status = "업종 민감도 기록의 입력/코드 해시가 달라 재실행 필요"
    manifest = {
        "status": "passed", "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        "classification_version": VERSION, "months": MONTHS,
        "card_shape": list(card.shape), "risk_shape": list(risk.shape),
        "spatial_validation": spatial_status,
        "industry_sensitivity": industry_status,
        "limitations": ["해석보류 업종은 분류 의미가 확정되지 않음", "관측률은 인구 대표성 지표가 아님",
                        "집계 특징이며 개인의 고립 라벨이나 검증된 위험 점수가 아님"],
        "sha256": {path.relative_to(REPO).as_posix(): file_hash(path) for path in sorted(files)},
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"최종 검증 통과: 카드 {card.shape}, 결합 특징 {risk.shape}")
    print(f"재현 기록: {MANIFEST}")


if __name__ == "__main__":
    main()
