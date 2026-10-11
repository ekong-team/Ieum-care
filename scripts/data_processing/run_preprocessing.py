"""한 번에 정제 → 결합 → EDA → 최종 검증. 실패하면 즉시 중단한다."""
from pathlib import Path
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STEPS = ["build_telecom_features.py", "build_card_features.py", "build_risk_features.py",
         "analyze_risk_features.py", "validate_processed.py"]


def main():
    manifest = REPO / "data" / "processed" / "preprocessing_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    for step in STEPS:
        print(f"\n실행: {step}", flush=True)
        try:
            subprocess.run([sys.executable, "-u", str(HERE / step)], cwd=REPO, check=True)
        except subprocess.CalledProcessError:
            manifest.write_text(json.dumps({"status": "failed", "step": step}), encoding="utf-8")
            raise SystemExit(f"{step} 실패. 입력을 수정한 후 전체 실행을 다시 진행하세요.")
    print("\n정제·EDA·최종 검증 완료. 지역 경계 검증 등 해석 한계는 문서를 확인하세요.")


if __name__ == "__main__":
    main()
