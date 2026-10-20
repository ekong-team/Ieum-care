"""한 번에 정제 → 특징 분석 → 최종 검증. --with-spatial로 지역 검증까지 실행."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STEPS = ["build_telecom_features.py", "build_card_features.py", "build_risk_features.py", "analyze_features.py"]


def main():
    parser = argparse.ArgumentParser(description="통신·카드 정제 및 분석 통합 실행")
    parser.add_argument("--with-spatial", action="store_true", help="SGIS 경계 대조와 민감도 분석도 실행")
    args = parser.parse_args()
    if args.with_spatial:
        boundary = REPO / "data" / "external" / "sgis" / "bnd_sigungu_00_2025_2Q.zip"
        if not boundary.exists():
            parser.error(f"SGIS 원본 파일이 필요합니다: {boundary}")
    steps = STEPS + (["validate_regions.py"] if args.with_spatial else []) + ["validate_processed.py"]
    manifest = REPO / "data" / "processed" / "preprocessing_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    for step in steps:
        print(f"\n실행: {step}", flush=True)
        try:
            subprocess.run([sys.executable, "-u", str(HERE / step)], cwd=REPO, check=True)
        except subprocess.CalledProcessError:
            manifest.write_text(json.dumps({"status": "failed", "step": step}), encoding="utf-8")
            raise SystemExit(f"{step} 실패. 입력을 수정한 후 전체 실행을 다시 진행하세요.")
    print("\n정제·특징 분석·최종 검증 완료. 검증 범위와 해석 한계는 manifest와 문서를 확인하세요.")


if __name__ == "__main__":
    main()
