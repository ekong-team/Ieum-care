"""실제 호출 검증 (설계 문서 12장): 대표 대상 4개로 기획 그래프를 한 번씩 실행하고 보고서용 숫자를 모은다.

대상 프로필과 원인 가설은 최신 분석 결과(analysis_current)에서 만들고, 복지 추천·사례 검색·기획·평가는
기본 Engines를 그대로 쓴다. 즉 화면의 통합 실행과 같은 경로다. 기본값은 offline이며 --live일 때만 과금 API를 부른다.

    python scripts/integration/run_validation.py           # offline 확인 (외부 호출 0)
    python scripts/integration/run_validation.py --live    # 실제 Gemini·Tavily 호출
"""
import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import re
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai.analysis_agent.agent import make_cause_engine, target_profile  # noqa: E402
from ai.graph.pipeline import Engines, run_pipeline, state_to_json  # noqa: E402
from ai.orchestrator.lookups import load_latest  # noqa: E402

ANALYSIS_ROOT = ROOT / "data" / "processed" / "analysis_current"
# 설계 12장의 춘천·강남 × 20대·60대 이상. 분석 결과는 성별로 나뉘어 있어 강남 20대는 1차 순위가 높은 남성(3위)을,
# 나머지는 성별이 한쪽으로 몰리지 않게 번갈아 골랐다.
TARGETS = ("202512_32010_20G_female", "202512_32010_60GU_male", "202512_11230_20G_male", "202512_11230_60GU_female")
SCORE = re.compile(r"(P-[\w-]+)=([\d.]+)([✓✗])")


def summarize_run(result: dict, seconds: float) -> dict:
    """실행 결과 하나 → 보고서에 넣을 숫자. 평가 점수는 evaluate 기록 순서대로 (원안, 재기획 후)."""
    trace = [e for e in result["trace"] if e["status"] != "started"]
    calls = Counter()
    for event in trace:
        calls.update(event["external_calls"])
    rounds = [[{"plan_id": m[0], "total": float(m[1]), "passed": m[2] == "✓"} for m in SCORE.findall(e["decision"])]
              for e in trace if e["node"] == "evaluate" and e["status"] == "done"]
    report = result["grounding_report"] or {}
    return {
        "run_id": result["run_id"],
        "status": result["report"]["status"],
        "seconds": round(seconds, 1),
        "external_calls": dict(calls),
        "llm_nodes": sorted({e["node"] for e in trace if e["llm_called"]}),
        "failed_nodes": [e["node"] for e in trace if e["status"] == "failed"],
        "plans_generated": len(result["plans"] or []) + len(report.get("excluded_plan_ids", [])),
        "grounding_excluded": report.get("excluded_plan_ids", []),
        "grounding_issues": [f"{issue['kind']}:{issue['action']}" for issue in report.get("issues", [])],
        "evaluation_rounds": rounds,
        "revision_count": result["revision_count"],
        "recommended": result["report"]["recommended_plan_ids"],
        "summary": result["report"]["summary"],
        "warnings": result["warnings"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="실제 Gemini·Tavily 호출 (과금)")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "processed" / "validation_20261026")
    args = parser.parse_args()
    mode = "live" if args.live else "offline"

    bundle, _ = load_latest(ANALYSIS_ROOT)
    engines = replace(Engines(), analyze_causes=make_cause_engine(bundle))
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for analysis_id in TARGETS:
        profile = target_profile(bundle, analysis_id)
        clock = monotonic()
        result = state_to_json(run_pipeline(profile, mode=mode, engines=engines))
        row = {"analysis_id": analysis_id, "target": profile.target.model_dump(mode="json"), "mode": mode,
               **summarize_run(result, monotonic() - clock)}
        (args.out / f"{mode}_{analysis_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(row)
        print(f"{analysis_id}: {row['summary']} · {row['seconds']}초 · 호출 {row['external_calls']}")
    (args.out / f"{mode}_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과: {args.out}")


if __name__ == "__main__":
    main()
