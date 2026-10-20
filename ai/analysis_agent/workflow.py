"""계산 → 배경·가설 정리 → 선택적 모델 검토 → 1차 순위의 전체 실행 흐름."""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context

from ai.analysis_agent.assessment import assess
from ai.analysis_agent.context import describe_cohort
from ai.analysis_agent.inputs import digest, month_number
from ai.analysis_agent.policy import VERSION, LIMITATIONS, SENSITIVITY_SCENARIOS, DECLINE_THRESHOLD, SEVERE_THRESHOLD
from ai.analysis_agent.priority import priority_for
from ai.analysis_agent.reviewer import review_cohort

class AnalysisState(TypedDict, total=False):
    rows: list[dict]
    contexts: dict
    manifest: list[dict]
    period: str
    assessments: list[dict]
    scenarios: dict
    cohorts: list[dict]
    execution: dict
    trace: list[dict]
    bundle: dict

def build_analysis_graph(provider=None, model_analysis_id=None):
    """모델 함수는 실행 상태 바깥에서 주입한다. 계산·순위에 모델 의견을 넣지 않는다."""
    def calculate(state):
        baseline = assess(state["rows"])
        if model_analysis_id and model_analysis_id not in {a["analysis_id"] for a in baseline}:
            raise ValueError("model target missing")
        scenarios = {}
        for name, options in SENSITIVITY_SCENARIOS:
            scenarios[name] = {a["analysis_id"]: a for a in assess(state["rows"], **options)}
        return dict(assessments=baseline, scenarios=scenarios,
                    trace=[dict(node="calculate", status="done", cohorts=len(baseline))])

    def describe(state):
        cohorts = []
        for assessment in state["assessments"]:
            aid = assessment["analysis_id"]
            sensitivity = [
                dict(scenario=name, level=values[aid]["level"], status=values[aid]["status"],
                     differs=(values[aid]["level"], values[aid]["status"]) != (assessment["level"], assessment["status"]))
                for name, values in state["scenarios"].items()
            ]
            cohorts.append(describe_cohort(assessment, state["contexts"].get(aid), sensitivity))
        # Validate comparison scope before any external model call.
        priority_for(cohorts, state["period"])
        return dict(cohorts=cohorts, trace=state["trace"] + [
            dict(node="describe", status="done", source="local_snapshot",
                 external_search="tavily_in_interpret" if getattr(provider, "use_search", False) else "not_run")])

    def interpret(state):
        execution = dict(provider_attempts=0, confirmed_llm_responses=0, model_receipts=[],
                         llm_status="not_run", model_role="evidence_hypothesis_question_selection")
        trace = list(state["trace"])
        for cohort in state["cohorts"]:
            selected_provider = provider if cohort["analysis_id"] == model_analysis_id else None
            review, receipt = review_cohort(cohort, selected_provider)
            cohort["interpretation"]["model_review"] = review
            execution["provider_attempts"] += receipt["provider_attempts"]
            execution["confirmed_llm_responses"] += receipt["confirmed_llm_responses"]
            execution["model_receipts"] += [
                dict(analysis_id=cohort["analysis_id"], **entry) for entry in receipt["receipts"]
            ]
            if selected_provider is not None:
                execution["llm_status"] = review["status"]
                trace.append(dict(node="interpret", analysis_id=cohort["analysis_id"], status=review["status"]))
        if provider is None:
            trace.append(dict(node="interpret", status="not_run", reason="규칙 해석만 사용; 모델 미호출"))
        execution["search_attempts"] = sum(r.get("search_attempts", 0) for r in execution["model_receipts"])
        execution["gemini_attempts"] = sum(r.get("gemini_attempts", 0) for r in execution["model_receipts"])
        execution["external_context_policy"] = "reference_only_no_numeric_import_no_risk_override"
        return dict(cohorts=state["cohorts"], execution=execution, trace=trace)

    def rank(state):
        priority = priority_for(state["cohorts"], state["period"])
        trace = state["trace"] + [dict(node="first_priority", status="done", period=priority["period"])]
        bundle = dict(
            schema_version="analysis-bundle-0.3", release_status="implemented_proposal_not_team_approved",
            scope="provided_data_analysis_through_first_priority_only",
            method=dict(
                version=VERSION, card_basis="daily_average", decline_ratio=float(DECLINE_THRESHOLD), severe_ratio=float(SEVERE_THRESHOLD),
                temporal_use="retrospective_2025_snapshot_not_historical_live_backtest",
                quality_policy="warning_only_missing_required_comparison_held",
                unknown_policy="tri_state_with_partial_lower_bound", context_policy="background_only",
                sex_scopes=sorted({record.get("sex", "all") for record in state["assessments"]}),
                age_definition={"10":"10~19","20":"20~29","30":"30~39","40":"40~49","50":"50~59","60":"60세 이상"},
                priority_policy=priority["policy_version"],
            ),
            source_manifest=state["manifest"], cohorts=state["cohorts"], priority_review=priority,
            limitations=LIMITATIONS + [
                "Tavily 검색은 선택적으로 실행하며 발췌는 미검증 참고 후보. 실제 실행 여부는 execution 참조",
                "웹 자료를 수치 데이터로 자동 반영하지 않으며 위험 단계·1차 순위를 변경하지 않음",
                "위험 영향 요인은 검토 후보이며 인과관계·개인 고립 원인을 검증하지 않음",
                "복지자원 추천 및 2차 필터링은 이번 담당 범위에서 제외",
            ],
            execution=state["execution"], trace=trace,
        )
        if {cohort["assessment"].get("sex", "all") for cohort in state["cohorts"]} >= {"all", "male", "female"}:
            bundle["aggregate_priority_review"] = priority_for(state["cohorts"], state["period"], sexes=("all",))
        bundle["bundle_hash"] = digest(bundle)
        return dict(bundle=bundle, trace=trace)

    graph = StateGraph(AnalysisState)
    for name, function in (("calculate",calculate), ("describe",describe), ("interpret",interpret), ("first_priority",rank)):
        graph.add_node(name, function)
    graph.add_edge(START, "calculate")
    graph.add_edge("calculate", "describe")
    graph.add_edge("describe", "interpret")
    graph.add_edge("interpret", "first_priority")
    graph.add_edge("first_priority", END)
    return graph.compile()

def run_analysis(rows: list[dict], contexts: dict, manifest: list[dict], *, period: str,
                 provider=None, model_analysis_id=None) -> dict:
    """검증된 집단 자료를 받아 팀 전달 묶음을 반환한다. 파일 저장은 실행 도구가 맡는다."""
    month_number(period)
    if provider is not None and not model_analysis_id:
        raise ValueError("explicit model target required")
    graph = build_analysis_graph(provider, model_analysis_id)
    with tracing_context(enabled=False):
        state = graph.invoke(dict(rows=rows, contexts=contexts, manifest=manifest, period=period))
    return state["bundle"]
