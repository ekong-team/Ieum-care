"""2차 우선순위 규칙(ai/orchestrator/second_priority.py) 검증. 외부 호출 없음.

확인하는 규칙:
- 공백 등급: 연령이 확인된(overlap) 직접 연결 자원이 있으면 G1, 후보만 있으면 G2, 없으면 G3.
- 직접 연결 판단은 live AI 분류가 있으면 그것을, 없으면(offline) 지원 목적을 쓴다.
- 조회 실패·미조회는 자원 없음으로 보지 않고 보류 목록에 둔다.
- 1차 순위가 먼저이고, 같은 1차 순위 안에서만 G3 > G2 > G1. 같은 순위·같은 등급은 공동 순위.
"""

import unittest

from ai.orchestrator.second_priority import Candidate, CohortLookup, gap_tier, rank_second


def cohort(analysis_id, *, rank=1, status="candidates_found", candidates=(), age=30):
    return CohortLookup(analysis_id=analysis_id, target={"region": "춘천시", "age_group": age, "sex": "male"},
                        first_rank=rank, level=4, lookup_status=status, candidates=list(candidates))


DIRECT = Candidate(id="R-direct", name="청년 마음 모임", age_match="overlap", isolation_relevance="direct")
INDIRECT = Candidate(id="R-indirect", name="생활비 지원", age_match="overlap", isolation_relevance="indirect")
DIRECT_PARTIAL_AGE = Candidate(id="R-partial", name="중장년 모임", age_match="partial", isolation_relevance="direct")
OFFLINE_CONNECTION = Candidate(id="R-offline", name="고독사 예방", age_match="overlap", purpose="connection")


class GapTierTests(unittest.TestCase):
    def tier(self, *candidates, status="candidates_found"):
        return gap_tier(cohort("A", status=status, candidates=candidates))[0]

    def test_confirmed_direct_resource_is_covered(self):
        tier, ids, _ = gap_tier(cohort("A", candidates=[INDIRECT, DIRECT]))
        self.assertEqual((tier, ids), ("G1_covered", ["R-direct"]))

    def test_candidates_without_confirmed_direct_are_partial(self):
        self.assertEqual(self.tier(INDIRECT), "G2_partial")
        self.assertEqual(self.tier(DIRECT_PARTIAL_AGE), "G2_partial")  # 직접 자원이지만 연령이 일부만 맞음

    def test_no_usable_candidates_is_gap(self):
        self.assertEqual(self.tier(status="no_candidates_found"), "G3_gap")
        self.assertEqual(self.tier(DIRECT.model_copy(update={"age_match": "none"})), "G3_gap")

    def test_offline_uses_purpose_but_live_label_wins(self):
        self.assertEqual(self.tier(OFFLINE_CONNECTION), "G1_covered")
        # AI가 indirect로 분류했다면 목적이 connection이어도 직접 자원으로 보지 않는다
        self.assertEqual(self.tier(OFFLINE_CONNECTION.model_copy(update={"isolation_relevance": "indirect"})), "G2_partial")

    def test_failed_or_pending_lookup_is_not_a_gap(self):
        self.assertIsNone(self.tier(status="unavailable"))
        self.assertIsNone(self.tier(status="pending"))


class RankSecondTests(unittest.TestCase):
    def test_first_rank_comes_first_then_gap(self):
        result = rank_second([
            cohort("rank2-gap", rank=2, status="no_candidates_found"),
            cohort("rank1-covered", rank=1, candidates=[DIRECT]),
            cohort("rank1-gap", rank=1, status="no_candidates_found"),
            cohort("rank1-partial", rank=1, candidates=[INDIRECT]),
        ])
        order = [(item.analysis_id, item.second_rank) for item in result.ranked]
        # 공백이 커도 1차 2순위는 1차 1순위 집단보다 앞서지 않는다
        self.assertEqual(order, [("rank1-gap", 1), ("rank1-partial", 2), ("rank1-covered", 3), ("rank2-gap", 4)])
        self.assertEqual([item.route for item in result.ranked][:3],
                         ["preventive_planning", "linkage_and_planning", "existing_resource_linkage"])

    def test_same_rank_and_tier_share_rank(self):
        result = rank_second([cohort("b", status="no_candidates_found"), cohort("a", status="no_candidates_found")])
        self.assertEqual([(i.analysis_id, i.second_rank) for i in result.ranked], [("a", 1), ("b", 1)])

    def test_held_cohorts_stay_out_of_ranking(self):
        result = rank_second([cohort("done", status="no_candidates_found"), cohort("failed", status="unavailable")])
        self.assertEqual([i.analysis_id for i in result.ranked], ["done"])
        self.assertEqual([(h.analysis_id, h.lookup_status) for h in result.held], [("failed", "unavailable")])
        self.assertTrue(any("보류" in text for text in result.limitations))

    def test_duplicate_cohort_is_rejected(self):
        with self.assertRaises(ValueError):
            rank_second([cohort("A"), cohort("A")])

    def test_every_item_requires_human_confirmation(self):
        result = rank_second([cohort("A", candidates=[DIRECT])])
        self.assertTrue(all(item.human_confirmation_required for item in result.ranked))


if __name__ == "__main__":
    unittest.main()
