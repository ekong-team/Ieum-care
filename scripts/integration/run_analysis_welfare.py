"""최신 분석 JSON을 읽어 현지 복지추천에 직접 연결한다. ZIP 생성/읽기 없음."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai.analysis_agent.agent import recommend_from_analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "data/processed/analysis_current")
    parser.add_argument("--analysis-id", required=True, help="例: 202512_32010_30G_female")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/analysis_welfare_current/result.json")
    args = parser.parse_args()
    if args.mode == "live" and not args.allow_external:
        parser.error("실제 검색·Gemini 호출은 --allow-external을 명시해야 합니다.")
    folder = args.results
    if not (folder / "analysis_bundle.json").exists():
        latest = json.loads((folder / "latest.json").read_text(encoding="utf-8"))
        folder = folder / latest["directory"]
    bundle = json.loads((folder / "analysis_bundle.json").read_text(encoding="utf-8"))
    result = recommend_from_analysis(bundle, args.analysis_id, mode=args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "mode": args.mode, "target": result["target"],
                      "resources": result["total"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
