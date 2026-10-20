"""전체 흐름 그래프(ai/graph/pipeline.py) 검증. 외부 호출 없이 가짜 노드로 흐름 규칙만 확인한다.

확인하는 규칙 (설계 문서 4.1):
- 병렬 노드(복지 추천·트렌드 검색)의 판단 기록이 모두 남는다.
- 기준 미달 기획안이 있으면 재기획하고, 재기획은 최대 1회다.
- 복지 추천·트렌드 검색이 실패해도 기획은 계속된다.
- 근거 검증에서 기획안이 모두 빠지면 실패로 끝나고, 재기획안만 모두 빠지면 원안을 유지한다.
"""

from dataclasses import replace
import json
from pathlib import Path
import unittest

from ai.contracts import AxisScore, ExistingResources, GroundingReport, TargetProfile, summarize
from ai.graph.pipeline import Engines, run_pipeline
from ai.nodes import stubs

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = TargetProfile.model_validate(json.loads((FIXTURES / "target_profile_example.json").read_text(encoding="utf-8")))
NAMES = ("target_fit", "novelty", "grounding", "budget", "measurability", "feasibility")


def fixed_scores(total_by_revision):
    """revision 0/1별로 같은 점수를 주는 가짜 평가. 예: {0: 50, 1: 50}이면 항상 미달."""
    def evaluate(ctx, plans, planning):
        results = []
        for plan in plans:
            target = total_by_revision[plan.revision]
            values = [round(target * w / 100, 2) for w in (25, 20, 15, 15, 10, 15)]
            axes = [AxisScore(axis=n, score=v, method="llm" if n == "feasibility" else "rule") for n, v in zip(NAMES, values)]
            results.append(summarize(plan.plan_id, axes, []))
        return results
    return evaluate


def drop_revisions(ctx, plans, planning):
    kept = [p for p in plans if p.revision == 0]
    return kept, GroundingReport(kept_plan_ids=[p.plan_id for p in kept],
                                 excluded_plan_ids=[p.plan_id for p in plans if p.revision])


def nodes_run(state, name):
    return [e for e in state["trace"] if e.node == name and e.status != "started"]


class PipelineFlowTests(unittest.TestCase):
    def run_with(self, **overrides):
        return run_pipeline(PROFILE, mode="offline", engines=replace(Engines(), **overrides), run_id="run-test0001")

    def test_full_run_with_stubs(self):
        state = self.run_with()
        self.assertEqual(state["report"].status, "completed")
        seqs = [e.seq for e in state["trace"]]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), len(set(seqs)))
        # 병렬 노드 둘 다 기록이 남는다 (리듀서로 이어 붙이기)
        self.assertEqual(len(nodes_run(state, "welfare_recommend")), 1)
        self.assertEqual(len(nodes_run(state, "trend_search")), 1)
        self.assertEqual(len(nodes_run(state, "gap_analysis")), 1)  # 두 갈래가 모두 끝난 뒤 한 번만

    def test_welfare_receives_graph_causes_and_keeps_context_for_planning(self):
        seen = {}
        def gaps(ctx, planning):
            seen["context"] = planning.existing.recommendation["analysis_context"]
            seen["resource"] = planning.existing.resources[0]
            seen["routes"] = planning.existing.response_routing
            return stubs.analyze_gaps(ctx, planning)
        state = self.run_with(analyze_gaps=gaps)
        self.assertEqual(seen["context"]["profile"], PROFILE.model_dump(mode="json"))
        self.assertEqual(seen["context"]["causes"], [c.model_dump(mode="json") for c in state["causes"]])
        self.assertTrue(seen["resource"].description)
        self.assertTrue(seen["resource"].eligibility)
        self.assertTrue(seen["resource"].source)
        self.assertEqual(nodes_run(state, "welfare_recommend")[0].external_calls, {})
        self.assertIn("preventive_planning", [r.route for r in seen["routes"].routes])

    def test_unexpected_welfare_error_preserves_preventive_planning_option(self):
        def broken(ctx, profile):
            raise RuntimeError("가짜 노드 오류")
        state = self.run_with(recommend_existing=broken)
        routing = state["existing_resources"].response_routing
        self.assertEqual(routing.candidate_status, "unavailable")
        self.assertEqual({r.route for r in routing.routes}, {"preventive_planning", "further_review"})
        self.assertEqual(state["report"].status, "completed")

    def test_replan_once_then_compare(self):
        state = self.run_with()  # 가짜 평가: 2번 원안 54점 → 재기획 66점
        self.assertEqual(state["revision_count"], 1)
        self.assertEqual(len(nodes_run(state, "plan_generate")), 2)
        self.assertEqual(len(state["plans_original"]), 2)
        self.assertTrue(any("54 → 후 66" in note for note in state["report"].notes))

    def test_no_replan_when_all_pass(self):
        state = self.run_with(evaluate_plans=fixed_scores({0: 80, 1: 80}))
        self.assertEqual(state["revision_count"], 0)
        self.assertEqual(len(nodes_run(state, "plan_generate")), 1)
        self.assertNotIn("plans_original", state)

    def test_replan_at_most_once(self):
        state = self.run_with(evaluate_plans=fixed_scores({0: 50, 1: 50}))
        self.assertEqual(len(nodes_run(state, "plan_generate")), 2)
        self.assertEqual(state["report"].status, "completed")
        self.assertEqual(state["report"].recommended_plan_ids, [])

    def test_only_failing_plans_are_rewritten(self):
        state = self.run_with()
        revisions = {p.plan_id: p.revision for p in state["plans"]}
        self.assertEqual(sorted(revisions.values()), [0, 1])

    def test_welfare_failure_continues(self):
        def unavailable(ctx, profile):
            return ExistingResources(status="unavailable", reason="Gemini 한도 초과(가짜)")
        state = self.run_with(recommend_existing=unavailable)
        self.assertEqual(state["report"].status, "completed")
        self.assertTrue(all(g.coverage == "unknown" for g in state["gaps"]))
        self.assertIn("Gemini 한도 초과(가짜)", state["warnings"])

    def test_trend_exception_continues_with_warning(self):
        def broken(ctx, planning):
            raise RuntimeError("검색 서버 오류")
        state = self.run_with(search_trends=broken)
        self.assertEqual(state["trend_references"], [])
        self.assertEqual(nodes_run(state, "trend_search")[0].status, "failed")
        self.assertEqual(state["report"].status, "completed")

    def test_all_plans_excluded_fails_run(self):
        state = self.run_with(check_grounding=lambda ctx, plans, planning: ([], GroundingReport(
            excluded_plan_ids=[p.plan_id for p in plans])))
        self.assertTrue(state["failed"])
        self.assertEqual(state["report"].status, "failed")
        self.assertEqual(nodes_run(state, "evaluate"), [])

    def test_revised_plans_excluded_keeps_originals(self):
        state = self.run_with(check_grounding=drop_revisions)
        self.assertEqual([p.revision for p in state["plans"]], [0, 0])
        self.assertTrue(any("원안을 유지" in text for text in state["warnings"]))
        # 원안 결과로 마무리하므로 다시 평가하지 않는다
        self.assertEqual(len(nodes_run(state, "evaluate")), 1)
        self.assertEqual(state["report"].notes, [])

    def test_partial_exclusion_restores_only_that_original(self):
        # 원안 3개 중 2·3번이 미달 → 둘 다 재기획 → 3번 수정안만 근거 검증에서 제외
        def three_plans(ctx, planning):
            if planning.revision_targets:
                return [stubs._plan(planning, 0, revision=1, plan_id=p.plan_id) for p, _ in planning.revision_targets]
            return [stubs._plan(planning, n) for n in (1, 2, 3)]

        def scores(ctx, plans, planning):
            # 1번 원안 80점(통과), 2·3번 원안 50점(미달), 수정안 70점(통과)
            results = []
            for plan in plans:
                total = 70 if plan.revision else (80 if plan.plan_id.endswith("-01") else 50)
                results += fixed_scores({0: total, 1: total})(ctx, [plan], planning)
            return results

        def drop_third_revision(ctx, plans, planning):
            kept = [p for p in plans if not (p.revision and p.plan_id.endswith("-03"))]
            excluded = [p.plan_id for p in plans if p not in kept]
            return kept, GroundingReport(kept_plan_ids=[p.plan_id for p in kept], excluded_plan_ids=excluded)

        state = self.run_with(generate_plans=three_plans, evaluate_plans=scores, check_grounding=drop_third_revision)
        by_id = {p.plan_id[-2:]: p.revision for p in state["plans"]}
        self.assertEqual(by_id, {"01": 0, "02": 1, "03": 0})  # 3번은 원안으로 복원, 사라지지 않음
        self.assertTrue(any("-03: 재기획안이 근거 검증에서 제외" in text for text in state["warnings"]))

    def test_revision_flag_is_forced_by_graph(self):
        def forgets_revision_flag(ctx, planning):
            if planning.revision_targets:
                return [stubs._plan(planning, 0, revision=0, plan_id=p.plan_id) for p, _ in planning.revision_targets]
            return stubs.generate_plans(ctx, planning)
        state = self.run_with(generate_plans=forgets_revision_flag)
        self.assertEqual(sorted(p.revision for p in state["plans"]), [0, 1])

    def test_inconsistent_grounding_report_fails(self):
        def lost_plan(ctx, plans, planning):
            return plans[:1], GroundingReport(kept_plan_ids=[plans[0].plan_id])  # 2번이 어느 목록에도 없음
        state = self.run_with(check_grounding=lost_plan)
        self.assertEqual(state["report"].status, "failed")
        self.assertTrue(any("맞지 않습니다" in text for text in state["errors"]))

    def test_evaluation_id_mismatch_fails(self):
        def wrong_ids(ctx, plans, planning):
            return [e.model_copy(update={"plan_id": "P-ghost"}) for e in stubs.evaluate_plans(ctx, plans, planning)]
        state = self.run_with(evaluate_plans=wrong_ids)
        self.assertEqual(state["report"].status, "failed")
        self.assertEqual(state["report"].recommended_plan_ids, [])

    def test_duplicate_plan_ids_fail(self):
        state = self.run_with(generate_plans=lambda ctx, planning: [stubs._plan(planning, 1), stubs._plan(planning, 1)])
        self.assertEqual(state["report"].status, "failed")

    def test_failure_during_revision_uses_original_results(self):
        calls = {"n": 0}

        def breaks_second_time(ctx, plans, planning):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("두 번째 근거 검증 오류")
            return stubs.check_grounding(ctx, plans, planning)
        state = self.run_with(check_grounding=breaks_second_time)
        report = state["report"]
        self.assertEqual(report.status, "completed")
        self.assertEqual([p.revision for p in state["plans"]], [0, 0])
        self.assertEqual(len(report.recommended_plan_ids), 1)  # 원안 중 통과한 1번만
        self.assertTrue(any("원안 평가 결과를 사용" in note for note in report.notes))

    def test_failure_in_regeneration_uses_original_results(self):
        calls = {"n": 0}

        def breaks_on_revision(ctx, planning):
            calls["n"] += 1
            if planning.revision_targets:
                raise RuntimeError("재기획 LLM 오류")
            return stubs.generate_plans(ctx, planning)
        state = self.run_with(generate_plans=breaks_on_revision)
        self.assertEqual(state["report"].status, "completed")
        self.assertEqual(len(state["report"].recommended_plan_ids), 1)

    def test_revision_grounding_checks_only_revised_plans(self):
        seen = []

        def record_inputs(ctx, plans, planning):
            seen.append(sorted(p.revision for p in plans))
            return stubs.check_grounding(ctx, plans, planning)
        self.run_with(check_grounding=record_inputs)
        self.assertEqual(seen, [[0, 0], [1]])  # 두 번째 검증에는 수정안만 들어간다

    def test_trace_callback_can_read_recorder(self):
        from ai.graph.trace import TraceRecorder
        recorder = TraceRecorder("run-test0009")
        seen = []
        recorder._on_event = lambda event: seen.append(len(recorder.after(-1)))  # 콜백 안에서 after() 호출
        run_pipeline(PROFILE, recorder=recorder)
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(len(seen), 0)

    def test_run_id_must_match_recorder(self):
        from ai.graph.trace import TraceRecorder
        with self.assertRaises(ValueError):
            run_pipeline(PROFILE, recorder=TraceRecorder("run-a"), run_id="run-b")

    def test_plan_generation_error_fails_run(self):
        def broken(ctx, planning):
            raise RuntimeError("LLM 응답 형식 오류")
        state = self.run_with(generate_plans=broken)
        self.assertEqual(state["report"].status, "failed")
        self.assertTrue(any("LLM 응답 형식 오류" in text for text in state["errors"]))

    def test_cause_rules_without_risk(self):
        profile = PROFILE.model_copy(update={"risk": None})
        state = run_pipeline(profile, mode="offline", run_id="run-test0002")
        self.assertEqual([c.code for c in state["causes"]], ["C0_unknown"])


class StubMarkingTests(unittest.TestCase):
    def test_stub_outputs_are_marked(self):
        state = run_pipeline(PROFILE, mode="offline", run_id="run-test0003")
        self.assertTrue(all(p.title.startswith(stubs.STUB) for p in state["plans"]))


if __name__ == "__main__":
    unittest.main()
