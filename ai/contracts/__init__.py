"""이음케어 AI 로직이 공유하는 입출력 형식 (Pydantic). 설계 문서: docs/system_design.md 5장."""

from ai.contracts.causes import CAUSE_LABELS, CauseCode, CauseHypothesis
from ai.contracts.evaluation import (AXIS_LABELS, AXIS_MAX, PASS_SCORE, AxisScore, PlanEvaluation,
                                     RevisionRequest, summarize, total_score)
from ai.contracts.pipeline import (ExistingResource, ExistingResources, FinalReport, GapItem, GroundingIssue,
                                   GroundingReport, PipelineState, TraceEvent, TrendReference)
from ai.contracts.plan import (KPI, MAX_REVISIONS, Activity, BudgetItem, Novelty, Operation, ProgramPlan,
                               RiskMitigation, Schedule, TrendRef)
from ai.contracts.profile import SIGNAL_LABELS, Evidence, RiskInfo, Target, TargetProfile

__all__ = [
    "Activity", "AXIS_LABELS", "AXIS_MAX", "AxisScore", "BudgetItem", "CAUSE_LABELS", "CauseCode", "CauseHypothesis",
    "Evidence", "ExistingResource", "ExistingResources", "FinalReport", "GapItem", "GroundingIssue", "GroundingReport",
    "KPI", "MAX_REVISIONS", "Novelty", "Operation", "PASS_SCORE", "PipelineState", "PlanEvaluation", "ProgramPlan", "RevisionRequest",
    "RiskInfo", "RiskMitigation", "Schedule", "SIGNAL_LABELS", "Target", "TargetProfile", "TraceEvent", "TrendRef",
    "TrendReference", "summarize", "total_score",
]
