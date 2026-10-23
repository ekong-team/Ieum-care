"""상위 오케스트레이터(ai/orchestrator/lookups.py, run.py) 검증. 외부 호출 없음.

확인하는 규칙:
- offline 조회와 review JSON 모두 같은 CohortLookup·ExistingResources로 바뀐다.
- 다른 분석 배치의 review JSON은 거부하고, 검토표에 없는 집단은 미조회(보류)로 둔다.
- 자원 확보(G1) 집단은 기획하지 않고 연계 대상으로만 올린다. 기획은 상위 N개, N 경계 동률은 대기로 남긴다.
- 기획 그래프는 분석 Agent의 원인 가설과 이미 모은 복지 결과를 쓴다 (복지를 다시 조회하지 않는다).
- 한 집단의 기획이 실패해도 나머지 집단과 리포트는 남는다.
"""

import copy
import unittest
from unittest.mock import patch

from ai.orchestrator import run as orchestrator
from ai.orchestrator.lookups import from_offline, from_review
from ai.orchestrator.second_priority import CohortLookup, SecondPriority, rank_second
from ai.welfare_agent.analysis_input import prepare_analysis_inputs
from tests.test_welfare_analysis_input import bundle_fixture

BUNDLE = bundle_fixture()  # 춘천 30대 여성(1차 1순위)·남성(2순위)
INPUTS = prepare_analysis_inputs(BUNDLE)
FEMALE, MALE = (entry["analysis_id"] for entry in INPUTS["entries"])


def review(rows):
    return {"schema_version": "welfare-cohort-review-0.1", "batch_id": INPUTS["batch_id"], "rows": rows}


def row(analysis_id, status, candidates=()):
    return {"analysis_id": analysis_id, "lookup_status": status, "candidates": list(candidates), "error": None}


DIRECT = {"id": "R1", "name": "청년 마음 모임", "age_match": "overlap", "isolation_relevance": "direct",
          "source_url": "https://www.chuncheon.go.kr/r1", "eligibility_status": "needs_confirmation"}


class LookupTests(unittest.TestCase):
    def test_offline_lookup_keeps_first_rank_and_resources(self):
        cohorts = from_offline(INPUTS)
        self.assertEqual([(c.lookup.analysis_id, c.lookup.first_rank) for c in cohorts], [(FEMALE, 1), (MALE, 2)])
        self.assertTrue(all(c.existing.status == "available" and c.existing.resources for c in cohorts))

    def test_offline_failure_is_unavailable_not_empty(self):
        def broken(request):
            raise ValueError("지원하지 않는 입력")
        cohort = from_offline(INPUTS, call=broken)[0]
        self.assertEqual((cohort.lookup.lookup_status, cohort.existing.status), ("unavailable", "unavailable"))

    def test_review_rows_become_lookups(self):
        cohorts = from_review(INPUTS, review([row(FEMALE, "candidates_found", [DIRECT]), row(MALE, "no_candidates_found")]))
        female, male = cohorts
        self.assertEqual(female.lookup.candidates[0].isolation_relevance, "direct")
        self.assertEqual(female.existing.resources[0].source_url, DIRECT["source_url"])
        self.assertEqual((male.lookup.lookup_status, male.existing.status), ("no_candidates_found", "available"))

    def test_missing_row_is_pending(self):
        cohorts = from_review(INPUTS, review([row(FEMALE, "no_candidates_found")]))
        self.assertEqual(cohorts[1].lookup.lookup_status, "pending")
        self.assertEqual([h.analysis_id for h in rank_second([c.lookup for c in cohorts]).held], [MALE])

    def test_other_batch_or_format_is_rejected(self):
        with self.assertRaises(ValueError):
            from_review(INPUTS, {**review([]), "batch_id": "other"})
        with self.assertRaises(ValueError):
            from_review(INPUTS, {**review([]), "schema_version": "x"})


def ranked(*items):
    """(id, 1차 순위, 상태) → 2차 순위 결과."""
    return rank_second([CohortLookup(analysis_id=i, target={"region": "춘천시", "age_group": 30}, first_rank=r, level=4,
                                     lookup_status=s) for i, r, s in items])


class SelectTargetsTests(unittest.TestCase):
    def test_top_n_with_tie_waiting(self):
        second = ranked(("a", 1, "no_candidates_found"), ("b", 1, "no_candidates_found"), ("c", 2, "no_candidates_found"))
        selected, waiting = orchestrator.select_targets(second, top_n=1)
        self.assertEqual(([i.analysis_id for i in selected], [i.analysis_id for i in waiting]), (["a"], ["b"]))

    def test_covered_cohorts_are_not_planned(self):
        second = SecondPriority(ranked=[], held=[], limitations=[])
        self.assertEqual(orchestrator.select_targets(second), ([], []))


class RunOrchestratorTests(unittest.TestCase):
    def run_with(self, rows, **kwargs):
        return orchestrator.run_orchestrator(BUNDLE, INPUTS, from_review(INPUTS, review(rows)),
                                             welfare_source="test", **kwargs)

    def test_plans_gap_cohorts_with_analysis_causes_and_given_welfare(self):
        report = self.run_with([row(FEMALE, "no_candidates_found"), row(MALE, "candidates_found", [DIRECT])])
        self.assertEqual(report["planning_targets"], [FEMALE])
        self.assertEqual(report["linkage_only"], [MALE])  # G1은 기획하지 않는다
        run = report["runs"][FEMALE]
        self.assertEqual(run["report"]["status"], "completed")
        cohort = next(c for c in BUNDLE["cohorts"] if c["analysis_id"] == FEMALE)
        self.assertEqual([c["code"] for c in run["causes"]], [c["code"] for c in cohort["team_causes"]])
        self.assertEqual(run["existing_resources"]["resources"], [])  # 검토표 결과 그대로, 재조회 없음
        nodes = [event["node"] for event in report["trace"]]
        self.assertEqual(nodes[:3], ["first_priority", "second_priority", "select_targets"])
        self.assertEqual(report["status"], "needs_human_review")

    def test_one_failed_plan_does_not_stop_others(self):
        calls = []
        def flaky(bundle, engine, item, cohort, *, mode, run_id):
            calls.append(item.analysis_id)
            if len(calls) == 1:
                raise RuntimeError("기획 실패")
            return {"report": {"summary": "ok", "notes": []}}
        with patch.object(orchestrator, "plan_for", side_effect=flaky):
            report = self.run_with([row(FEMALE, "no_candidates_found"), row(MALE, "no_candidates_found")])
        self.assertIn("error", report["runs"][FEMALE])
        self.assertEqual(report["runs"][MALE]["report"]["summary"], "ok")
        self.assertIn("failed", [event["status"] for event in report["trace"]])

    def test_inputs_are_not_mutated(self):
        before = copy.deepcopy(INPUTS)
        self.run_with([row(FEMALE, "no_candidates_found")])
        self.assertEqual(INPUTS, before)


if __name__ == "__main__":
    unittest.main()
