"""상위 오케스트레이터 실행부. 분기·루프 없는 순차 흐름이라 LangGraph 대신 함수로 쓴다 (설계 결정 E).

    ① 분석 결과 읽기 → ② 1차 순위(묶음에 있음) → ③ 복지 결과 모으기 → ④ 2차 순위
    → ⑤ 기획 대상 선택(G2·G3 상위 N개) → ⑥ 집단별 기획 그래프 → ⑦ 최종 리포트

루프는 각 에이전트 안에 있다 (분석 재검색, 기획↔평가 재기획). 여기서는 순서와 대상 선택만 맡는다.
판단 기록은 기획 그래프와 같은 TraceRecorder 형식으로 남겨 화면 타임라인 하나로 이어 볼 수 있게 한다.

    python -m ai.orchestrator.run                         # offline 조회로 끝까지 실행
    python -m ai.orchestrator.run --review 검토표.json    # 화면에서 내려받은 live 추천 결과 재사용
"""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import uuid4

from ai.analysis_agent.agent import make_cause_engine, target_profile
from ai.graph.pipeline import Engines, run_pipeline, state_to_json
from ai.graph.trace import TraceRecorder
from ai.orchestrator.lookups import CohortInput, from_offline, from_review, load_latest
from ai.orchestrator.second_priority import SecondPriority, SecondPriorityItem, rank_second

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_ROOT = ROOT / "data" / "processed" / "analysis_current"
OUTPUT_ROOT = ROOT / "data" / "processed" / "orchestrator"
TOP_N = 3  # 기획 1개 집단 ≈ Gemini 3~4회. 3개면 실행 1회에 10~12회 (설계 결정 D)


def select_targets(second: SecondPriority, top_n: int = TOP_N) -> tuple[list[SecondPriorityItem], list[SecondPriorityItem]]:
    """(기획할 집단, 동률이지만 N을 넘어 기획 대기인 집단). 자원 확보(G1) 집단은 연계 대상이라 기획하지 않는다."""
    needs_plan = [item for item in second.ranked if item.route != "existing_resource_linkage"]
    selected = needs_plan[:top_n]
    if not selected:
        return [], []
    cutoff = selected[-1].second_rank
    return selected, [item for item in needs_plan[top_n:] if item.second_rank == cutoff]


def plan_for(bundle: dict, cause_engine, item: SecondPriorityItem, cohort: CohortInput, *,
             mode: Literal["live", "offline"], run_id: str) -> dict:
    """집단 하나의 기획 그래프. 원인은 분석 Agent 결과를, 복지는 이미 모은 결과를 그대로 쓴다 (다시 조회하지 않음)."""
    engines = replace(Engines(), analyze_causes=cause_engine,
                      recommend_existing=lambda ctx, profile: cohort.existing)
    state = run_pipeline(target_profile(bundle, item.analysis_id), mode=mode, engines=engines, run_id=run_id)
    return state_to_json(state)


def run_orchestrator(bundle: dict, inputs: dict, cohorts: list[CohortInput], *, welfare_source: str,
                     mode: Literal["live", "offline"] = "offline", top_n: int = TOP_N) -> dict:
    """③에서 모은 집단별 입력부터 ⑦ 리포트까지. 집단 하나의 기획이 실패해도 나머지는 계속한다."""
    run_id = f"orch-{uuid4().hex[:12]}"
    recorder = TraceRecorder(run_id)

    def step(node: str, decision: str, reasons: list[str], started: float) -> None:
        recorder.emit(node, "done", decision=decision, reasons=reasons, duration_ms=int((monotonic() - started) * 1000))

    clock = monotonic()
    priority = inputs["priority"]
    step("first_priority", f"1차 순위 대상 {len(inputs['entries'])}개", [
        f"부분판정 {len(priority['partial_assessments'])}개·보류 {len(priority['held_cohorts'])}개는 1차 순위 밖",
        f"복지 결과: {welfare_source}"], clock)

    clock = monotonic()
    second = rank_second([cohort.lookup for cohort in cohorts])
    tiers = [item.gap_tier for item in second.ranked]
    step("second_priority", f"2차 순위 {len(second.ranked)}개, 조회 보류 {len(second.held)}개",
         [f"{tier} {tiers.count(tier)}개" for tier in ("G3_gap", "G2_partial", "G1_covered")], clock)

    clock = monotonic()
    selected, waiting = select_targets(second, top_n)
    step("select_targets", f"기획 대상 {len(selected)}개 (상위 {top_n}개, G2·G3)",
         [f"{i.second_rank}위 {i.analysis_id} {i.gap_tier}" for i in selected]
         + [f"동률 기획 대기: {i.analysis_id}" for i in waiting], clock)

    by_id = {cohort.lookup.analysis_id: cohort for cohort in cohorts}
    cause_engine = make_cause_engine(bundle)  # 분석 묶음 검증·색인은 한 번만 한다
    runs = {}
    for number, item in enumerate(selected, start=1):
        clock = monotonic()
        try:
            runs[item.analysis_id] = plan_for(bundle, cause_engine, item, by_id[item.analysis_id],
                                              mode=mode, run_id=f"{run_id}-{number:02d}")
            report = runs[item.analysis_id]["report"]
            step(f"plan:{item.analysis_id}", report["summary"], report["notes"][:3], clock)
        except Exception as error:  # noqa: BLE001 - 한 집단의 실패로 전체 리포트를 잃지 않는다
            runs[item.analysis_id] = {"error": f"{type(error).__name__}: {error}"}
            recorder.emit(f"plan:{item.analysis_id}", "failed", decision="기획 실행 실패, 다음 집단 계속",
                          reasons=[runs[item.analysis_id]["error"]], duration_ms=int((monotonic() - clock) * 1000))

    return {
        "schema_version": "orchestrator-report-0.1",
        "run_id": run_id,
        "batch_id": inputs["batch_id"],
        "period": inputs["period"],
        "mode": mode,
        "welfare_source": welfare_source,
        "second_priority": second.model_dump(mode="json"),
        "planning_targets": [i.analysis_id for i in selected],
        "waiting_for_planning": [i.analysis_id for i in waiting],
        "linkage_only": [i.analysis_id for i in second.ranked if i.route == "existing_resource_linkage"],
        "runs": runs,
        "trace": [event.model_dump(mode="json") for event in recorder.events],
        "status": "needs_human_review",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ANALYSIS_ROOT, help="분석 결과 폴더 (latest.json 위치)")
    parser.add_argument("--review", type=Path, help="화면에서 내려받은 welfare-cohort-review-0.1 JSON")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline", help="기획 그래프 실행 방식")
    parser.add_argument("--top-n", type=int, default=TOP_N)
    args = parser.parse_args()

    if not (args.root / "latest.json").exists():
        raise SystemExit(f"분석 결과가 없습니다: {args.root}\n먼저 scripts/integration/prepare_analysis_welfare.py를 실행하세요.")
    bundle, inputs = load_latest(args.root)
    if args.review:
        cohorts = from_review(inputs, json.loads(args.review.read_text(encoding="utf-8")))
        source = f"review JSON ({args.review.name})"
    else:
        cohorts, source = from_offline(inputs), "offline 저장 자료 조회"
    report = run_orchestrator(bundle, inputs, cohorts, welfare_source=source, mode=args.mode, top_n=args.top_n)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_ROOT / f"{report['run_id']}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{report['period']} · 복지 결과: {source} · 기획: {args.mode}\n")
    for event in report["trace"]:
        mark = "✓" if event["status"] == "done" else "✗"
        print(f"{mark} {event['node']:<28} {event['decision']}")
        for reason in event["reasons"][:4]:
            print(f"{'':>31}· {reason}")
    print(f"\n연계 우선(G1): {report['linkage_only']}\n결과 파일: {out}")


if __name__ == "__main__":
    main()
