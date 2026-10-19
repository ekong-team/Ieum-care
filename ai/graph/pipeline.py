"""전체 흐름 그래프 (LangGraph). 설계 문서 4장.

    cause_analysis ─┬─ welfare_recommend ─┐
                    └─ trend_search ──────┴─ gap_analysis ─ plan_generate ─ grounding_check ─ evaluate
                                                               ▲                                 │
                                                               └──── 기준 미달 & 재기획 0회 ──────┘
                                                                                  그 외 → priority_report

이 파일은 '흐름'만 책임진다: 노드 순서, 분기, 재기획 기록, 판단 기록, 실패 처리, 노드 결과의 일관성 검사.
각 노드가 실제로 무엇을 계산하는지는 Engines에 꽂힌 함수(ai/nodes/*)가 맡는다.
그래서 가짜 구현을 실제 구현으로 바꿔도 이 파일은 고치지 않는다.
"""

from dataclasses import dataclass, field
from time import monotonic
from typing import Callable, Literal, Optional
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from ai.contracts import (CAUSE_LABELS, MAX_REVISIONS, CauseHypothesis, ExistingResources, FinalReport, GapItem,
                          GroundingReport, PipelineState, PlanEvaluation, ProgramPlan, TargetProfile, TrendReference)
from ai.graph.trace import TraceRecorder
from ai.nodes import causes as cause_rules
from ai.nodes import stubs
from ai.nodes import welfare
from ai.nodes.context import NodeContext


@dataclass
class PlanningInput:
    """기획·근거 검증·평가 노드가 공통으로 보는 자료 묶음."""

    run_id: str
    profile: TargetProfile
    causes: list[CauseHypothesis]
    existing: ExistingResources
    trends: list[TrendReference]
    gaps: list[GapItem]
    revision_targets: list[tuple[ProgramPlan, PlanEvaluation]] = field(default_factory=list)


@dataclass
class Engines:
    """노드별 계산 함수. 테스트나 단계별 개발 중에 원하는 것만 바꿔 끼운다."""

    analyze_causes: Callable[[NodeContext, TargetProfile], list[CauseHypothesis]] = cause_rules.analyze_causes
    recommend_existing: Callable[[NodeContext, TargetProfile], ExistingResources] = welfare.recommend_existing
    search_trends: Callable[[NodeContext, PlanningInput], list[TrendReference]] = stubs.search_trends
    analyze_gaps: Callable[[NodeContext, PlanningInput], list[GapItem]] = stubs.analyze_gaps
    generate_plans: Callable[[NodeContext, PlanningInput], list[ProgramPlan]] = stubs.generate_plans
    # (통과한 기획안, 리포트). 통과한 기획안은 문제 항목만 지운 수정본일 수 있다.
    check_grounding: Callable[[NodeContext, list[ProgramPlan], PlanningInput],
                              tuple[list[ProgramPlan], GroundingReport]] = stubs.check_grounding
    evaluate_plans: Callable[[NodeContext, list[ProgramPlan], PlanningInput], list[PlanEvaluation]] = stubs.evaluate_plans


class FlowError(ValueError):
    """노드 결과가 흐름 규칙과 맞지 않을 때 (id 중복·누락 등). 조용히 넘어가지 않고 해당 노드를 실패시킨다."""


def _planning(state: PipelineState, revision_targets=None) -> PlanningInput:
    return PlanningInput(run_id=state["run_id"], profile=state["profile"], causes=state.get("causes", []),
                         existing=state.get("existing_resources") or ExistingResources(status="unavailable", reason="미실행"),
                         trends=state.get("trend_references", []), gaps=state.get("gaps", []),
                         revision_targets=revision_targets or [])


def _ids(plans) -> list[str]:
    return [p.plan_id for p in plans]


def _require_unique(plans: list[ProgramPlan], where: str) -> None:
    ids = _ids(plans)
    if len(ids) != len(set(ids)):
        raise FlowError(f"{where}: 기획안 id가 중복되었습니다 {ids}")


class _Node:
    """노드 공통 처리: 시작·종료 기록, 소요 시간, 외부 호출 수, 예외 처리.

    on_error="continue": 예외가 나도 fallback 결과로 계속 (원인 분석·복지 추천·트렌드 검색·공백 분석·리포트)
    on_error="fail":     예외가 나면 failed=True로 표시하고 리포트로 건너뜀 (기획 생성·근거 검증·평가)
    """

    def __init__(self, name: str, recorder: TraceRecorder, body, on_error: Literal["continue", "fail"], fallback=None):
        self.name, self.recorder, self.body, self.on_error, self.fallback = name, recorder, body, on_error, fallback

    def __call__(self, state: PipelineState) -> dict:
        ctx = NodeContext(run_id=state["run_id"], mode=state["mode"])
        started = self.recorder.emit(self.name, "started")
        clock = monotonic()
        try:
            update, decision, reasons = self.body(ctx, state)
            status, extra = "done", {}
        except Exception as error:  # noqa: BLE001 - 노드 실패를 기록하고 정책대로 처리한다
            message = f"{self.name}: {type(error).__name__}: {error}"
            if self.on_error == "continue":
                update, decision, reasons = self.fallback(state), "실패했지만 대체 결과로 계속", [message]
                extra = {"warnings": [message]}
            else:
                update, decision, reasons = {"failed": True}, "실패로 실행 중단", [message]
                extra = {"errors": [message]}
            status = "failed"
        finished = self.recorder.emit(self.name, status, decision=decision, reasons=reasons,
                                      llm_called=ctx.calls.get("gemini", 0) > 0, external_calls=dict(ctx.calls),
                                      duration_ms=int((monotonic() - clock) * 1000))
        return {**update, **extra, "trace": [started, finished]}


def build_graph(engines: Optional[Engines] = None, recorder: Optional[TraceRecorder] = None, run_id: str = "run"):
    engines = engines or Engines()
    recorder = recorder or TraceRecorder(run_id)

    # ── 노드 본체: (갱신할 상태, 판단 요약, 판단 이유)를 돌려준다 ──────────────────────
    def cause_analysis(ctx, state):
        found = engines.analyze_causes(ctx, state["profile"])
        return ({"causes": found}, "원인 가설: " + ", ".join(c.code for c in found),
                [f"{c.code} {CAUSE_LABELS[c.code]} (근거 {', '.join(c.evidence_ids) or '없음'})" for c in found])

    def welfare_recommend(ctx, state):
        result = engines.recommend_existing(ctx, state["profile"])
        if result.status == "available":
            return {"existing_resources": result}, f"기존 자원 {len(result.resources)}개 확인", result.warnings[:3]
        return ({"existing_resources": result, "warnings": [result.reason or "기존 자원 확인 불가"]},
                "기존 자원 확인 불가, 기획은 계속", [result.reason or ""])

    def trend_search(ctx, state):
        found = engines.search_trends(ctx, _planning(state))
        return {"trend_references": found}, f"참고 사례 {len(found)}건", [t.title for t in found[:3]]

    def gap_analysis(ctx, state):
        gaps = engines.analyze_gaps(ctx, _planning(state))
        return {"gaps": gaps}, ", ".join(f"{g.cause}={g.coverage}" for g in gaps), [g.reason for g in gaps]

    def plan_generate(ctx, state):
        # evaluate 노드에서 되돌아온 경우(평가 결과가 있음)만 재기획이다. 첫 기획은 평가 결과가 없다.
        is_revision = bool(state.get("evaluations"))
        if not is_revision:
            plans = engines.generate_plans(ctx, _planning(state))
            _require_unique(plans, "기획 생성")
            if not plans:
                raise FlowError("기획 생성 결과가 비어 있습니다.")
            plans = [p.model_copy(update={"revision": 0}) for p in plans]
            return {"plans": plans, "revision_count": 0}, f"기획안 {len(plans)}개 생성", [p.title for p in plans]

        # 재기획: 기준 미달 기획안만 개선 요청과 함께 다시 쓰고, 통과한 기획안은 그대로 둔다.
        by_id = {e.plan_id: e for e in state["evaluations"]}
        failing = [(p, by_id[p.plan_id]) for p in state["plans"] if not by_id[p.plan_id].passed]
        failing_ids = {p.plan_id for p, _ in failing}
        revised = engines.generate_plans(ctx, _planning(state, revision_targets=failing))
        _require_unique(revised, "재기획")
        # 수정안 표시는 생성기(LLM)에 맡기지 않고 여기서 강제한다. 요청하지 않은 id는 버린다.
        revised_by_id = {p.plan_id: p.model_copy(update={"revision": MAX_REVISIONS})
                         for p in revised if p.plan_id in failing_ids}
        warnings = [f"{pid}: 재기획 결과가 없어 원안을 유지합니다." for pid in sorted(failing_ids - set(revised_by_id))]
        if set(_ids(revised)) - failing_ids:
            warnings.append(f"요청하지 않은 재기획 결과를 버렸습니다: {sorted(set(_ids(revised)) - failing_ids)}")
        merged = [revised_by_id.get(p.plan_id, p) for p in state["plans"]]
        reasons = [f"{p.plan_id}: " + "; ".join(r.request for r in e.revision_requests) for p, e in failing]
        return ({"plans": merged, "plans_original": state["plans"], "evaluations_original": state["evaluations"],
                 "revision_count": state.get("revision_count", 0) + 1, "warnings": warnings},
                f"기준 미달 {len(failing)}개 재기획", reasons)

    def grounding_check(ctx, state):
        revising = bool(state.get("revision_count", 0))
        # 재기획 뒤에는 새로 쓴 수정안만 검증한다. 통과한 원안은 이미 첫 검증을 거쳤다.
        plans = [p for p in state["plans"] if p.revision] if revising else state["plans"]
        kept, report = engines.check_grounding(ctx, plans, _planning(state))
        # 리포트와 실제 결과가 서로 맞는지 확인한다. 어느 쪽에도 없는 기획안이 조용히 사라지지 않게 한다.
        input_ids, kept_ids, excluded_ids = set(_ids(plans)), _ids(kept), set(report.excluded_plan_ids)
        _require_unique(kept, "근거 검증")
        if set(kept_ids) != set(report.kept_plan_ids) or set(kept_ids) & excluded_ids \
                or set(kept_ids) | excluded_ids != input_ids:
            raise FlowError("근거 검증 결과의 통과·제외 목록이 입력 기획안과 맞지 않습니다.")
        reasons = [f"{i.plan_id} {i.kind}: {i.detail}" for i in report.issues]
        update = {"grounding_report": report}

        if revising:
            # 재기획 후: 제외된 수정안은 기획안별로 원안으로 되돌린다 (설계 문서 4.1). 통과 원안은 그대로 둔다.
            originals = {p.plan_id: p for p in state["plans_original"]}
            kept_by_id = {p.plan_id: p for p in kept}
            restored = [pid for pid in _ids(plans) if pid not in kept_by_id]
            update["plans"] = [kept_by_id.get(p.plan_id, originals[p.plan_id]) if p.revision else p
                               for p in state["plans"]]
            update["warnings"] = [f"{pid}: 재기획안이 근거 검증에서 제외되어 원안을 유지합니다." for pid in restored]
            if not any(p.revision for p in update["plans"]):
                # 살아남은 수정안이 없으면 다시 평가할 필요 없이 원안 평가 결과로 마무리한다.
                update["evaluations"] = state["evaluations_original"]
                update["revision_settled"] = True
                return update, "재기획안 모두 제외 → 원안 결과로 마무리", reasons
            return update, f"{len(kept)}개 통과, 원안 복원 {len(restored)}개", reasons

        update["plans"] = kept
        if not kept:
            update.update(failed=True, errors=["근거 검증을 통과한 기획안이 없습니다."])
            return update, "통과한 기획안 없음 → 실행 중단", reasons
        return update, f"{len(kept)}개 통과, {len(excluded_ids)}개 제외", reasons

    def evaluate(ctx, state):
        evaluations = engines.evaluate_plans(ctx, state["plans"], _planning(state))
        evaluated_ids = [e.plan_id for e in evaluations]
        if sorted(evaluated_ids) != sorted(_ids(state["plans"])):
            raise FlowError(f"평가 결과 id {evaluated_ids}가 기획안 id {_ids(state['plans'])}와 맞지 않습니다.")
        summary = ", ".join(f"{e.plan_id}={e.total:g}{'✓' if e.passed else '✗'}" for e in evaluations)
        return {"evaluations": evaluations}, summary, [r.request for e in evaluations for r in e.revision_requests]

    def priority_report(ctx, state):
        update, notes = {}, []
        failed = bool(state.get("failed"))
        if failed and state.get("evaluations"):
            # 평가 결과가 이미 있는데 실패했다면 재기획 단계(재기획 생성·근거 검증·재평가)의 실패다.
            # 이미 평가가 끝난 원안 결과로 마무리한다. 재기획 생성에서 실패하면 *_original이 아직 없으므로 현재 값이 원안이다.
            update = {"plans": state.get("plans_original") or state["plans"],
                      "evaluations": state.get("evaluations_original") or state["evaluations"], "failed": False}
            notes.append("재기획 단계에서 오류가 나서 원안 평가 결과를 사용했습니다: " + "; ".join(state.get("errors", [])))
            failed = False
        plans = update.get("plans", state.get("plans", []))
        evaluations = sorted(update.get("evaluations", state.get("evaluations") or []), key=lambda e: e.total, reverse=True)
        recommended = [] if failed else [e.plan_id for e in evaluations if e.passed]
        # 전후 비교는 실제로 수정안이 최종 결과에 남은 기획안만 쓴다 (원안 재평가로 생기는 점수 흔들림을 비교로 오해하지 않게).
        revised_ids = {p.plan_id for p in plans if p.revision}
        before = {e.plan_id: e.total for e in state.get("evaluations_original", [])}
        notes += [f"{e.plan_id}: 재기획 전 {before[e.plan_id]:g} → 후 {e.total:g}"
                  for e in evaluations if e.plan_id in revised_ids and e.plan_id in before]
        summary = ("실행 실패: " + "; ".join(state.get("errors", []))) if failed else f"추천 기획안 {len(recommended)}개"
        update["report"] = FinalReport(run_id=state["run_id"], status="failed" if failed else "completed",
                                       summary=summary, recommended_plan_ids=recommended, notes=notes)
        return update, summary, notes

    def report_fallback(state):
        return {"report": FinalReport(run_id=state["run_id"], status="failed", summary="리포트 생성 실패")}

    # ── 그래프 조립 ────────────────────────────────────────────────────────────────
    def node(name, body, on_error, fallback=None):
        return _Node(name, recorder, body, on_error, fallback)

    graph = StateGraph(PipelineState)
    graph.add_node("cause_analysis", node("cause_analysis", cause_analysis, "continue",
                                          lambda s: {"causes": [CauseHypothesis(code="C0_unknown")]}))
    graph.add_node("welfare_recommend", node("welfare_recommend", welfare_recommend, "continue",
                                             lambda s: {"existing_resources": ExistingResources(status="unavailable", reason="노드 오류")}))
    graph.add_node("trend_search", node("trend_search", trend_search, "continue", lambda s: {"trend_references": []}))
    graph.add_node("gap_analysis", node("gap_analysis", gap_analysis, "continue",
                                        lambda s: {"gaps": [GapItem(cause=c.code, coverage="unknown", reason="공백 분석 실패")
                                                            for c in s.get("causes", [])]}))
    graph.add_node("plan_generate", node("plan_generate", plan_generate, "fail"))
    graph.add_node("grounding_check", node("grounding_check", grounding_check, "fail"))
    graph.add_node("evaluate", node("evaluate", evaluate, "fail"))
    graph.add_node("priority_report", node("priority_report", priority_report, "continue", report_fallback))

    graph.add_edge(START, "cause_analysis")
    graph.add_edge("cause_analysis", "welfare_recommend")   # 병렬 시작
    graph.add_edge("cause_analysis", "trend_search")
    graph.add_edge(["welfare_recommend", "trend_search"], "gap_analysis")  # 둘 다 끝나야 진행
    graph.add_edge("gap_analysis", "plan_generate")
    graph.add_conditional_edges("plan_generate", route_after_plan, ["grounding_check", "priority_report"])
    graph.add_conditional_edges("grounding_check", route_after_grounding, ["evaluate", "priority_report"])
    graph.add_conditional_edges("evaluate", route_after_evaluate, ["plan_generate", "priority_report"])
    graph.add_edge("priority_report", END)
    return graph.compile()


# ── 분기 규칙: LLM이 아니라 규칙으로 정한다 ─────────────────────────────────────────
def route_after_plan(state: PipelineState) -> str:
    return "priority_report" if state.get("failed") else "grounding_check"


def route_after_grounding(state: PipelineState) -> str:
    return "priority_report" if state.get("failed") or state.get("revision_settled") else "evaluate"


def route_after_evaluate(state: PipelineState) -> str:
    """기준 미달 기획안이 있고 아직 재기획하지 않았을 때만 재기획한다."""
    if state.get("failed"):
        return "priority_report"
    needs = any(not e.passed for e in state.get("evaluations", []))
    return "plan_generate" if needs and state.get("revision_count", 0) < MAX_REVISIONS else "priority_report"


def run_pipeline(profile: TargetProfile, mode: Literal["live", "offline"] = "offline", engines: Optional[Engines] = None,
                 recorder: Optional[TraceRecorder] = None, run_id: Optional[str] = None) -> PipelineState:
    """그래프를 한 번 실행하고 최종 상태를 돌려준다. 판단 기록은 순서 번호(seq)대로 정렬한다."""
    if recorder and run_id and recorder.run_id != run_id:
        raise ValueError("run_id와 판단 기록기의 run_id가 다릅니다.")
    run_id = run_id or (recorder.run_id if recorder else f"run-{uuid4().hex[:12]}")
    recorder = recorder or TraceRecorder(run_id)
    app = build_graph(engines, recorder, run_id)
    state = app.invoke({"run_id": run_id, "mode": mode, "profile": profile, "revision_count": 0,
                        "trace": [], "errors": [], "warnings": []})
    state["trace"] = sorted(state["trace"], key=lambda event: event.seq)
    return state


def state_to_json(state: PipelineState) -> dict:
    """저장·API 응답용으로 Pydantic 객체를 일반 JSON 값으로 바꾼다."""
    def plain(value):
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [plain(item) for item in value]
        return value
    return {key: plain(value) for key, value in state.items()}
