"""근거 검증 노드(ai/nodes/grounding.py) 검증. 외부 호출 없음.

확인하는 규칙:
- 문장 속 %·0으로 시작하는 소수는 근거 값(원래 값·퍼센트 환산·부호 없음)과 맞아야 한다.
- 운영 숫자(주 1회·8주·500.0)와 날짜, KPI 목표치, 검색 결과 사례 제목은 검사하지 않는다.
- 실제 Gemini 호출 결과(2026-10-23, 3회)는 모두 통과한다 (오탐 방지).
"""

from dataclasses import replace
import json
from pathlib import Path
import unittest

from ai.contracts import ExistingResource, ExistingResources, ProgramPlan, TargetProfile, TrendReference
from ai.graph.pipeline import Engines, PlanningInput, run_pipeline
from ai.nodes import grounding, stubs

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = TargetProfile.model_validate(json.loads((FIXTURES / "target_profile_example.json").read_text(encoding="utf-8")))
LIVE = json.loads((FIXTURES / "live_plans_20261023.json").read_text(encoding="utf-8"))["runs"]
BASE = LIVE["run3"][0]  # E1 = -0.083(ratio), E2 = -0.041(ratio)


def plan_with(**changes) -> ProgramPlan:
    return ProgramPlan.model_validate({**BASE, **changes})


def numbers(plan):
    return grounding.check_numbers(plan, PROFILE)


class TextFieldsTests(unittest.TestCase):
    def test_paths_and_skipped_fields(self):
        plan = plan_with(trend_references=[{"title": "사례 30% 증가", "url": "https://www.example.go.kr/a", "year": 2026,
                                            "grade": "public", "how_applied": "주말로 옮김"}])
        paths = dict(grounding.text_fields(plan))
        self.assertIn("activities.0.description", paths)
        self.assertIn("trend_references.0.how_applied", paths)
        for skipped in ("trend_references.0.title", "trend_references.0.url", "plan_id", "format", "target.region"):
            self.assertNotIn(skipped, paths)
        self.assertNotIn("risk_causes_addressed.0", paths)


class CheckNumbersTests(unittest.TestCase):
    def test_evidence_values_in_any_form_pass(self):
        for text in ("사회활동 관련 소비 건수 변화 -8.3%", "소비 건수 변화 수치는 -0.083",
                     "8.3% 감소하고 유동량은 4.1 % 줄었다", "−8.3% (수학 기호 마이너스)", "약 8% 감소, 약 4% 감소"):
            self.assertEqual(numbers(plan_with(problem_statement=text)), [], text)

    def test_extra_precision_is_not_rounding(self):
        # 근거는 -8.3%까지만 있다. -8.25%는 반올림이 아니라 근거에 없는 정밀도를 지어낸 것이다.
        self.assertEqual(len(numbers(plan_with(problem_statement="-8.25% 감소"))), 1)
        self.assertEqual(len(numbers(plan_with(problem_statement="약 9% 감소"))), 1)  # 8.3의 정수 반올림은 8

    def test_unknown_numbers_are_excluded(self):
        issues = numbers(plan_with(problem_statement="20대 외출이 -30% 줄고 비율은 0.25로 떨어졌다"))
        self.assertEqual(len(issues), 1)
        self.assertEqual((issues[0].kind, issues[0].action), ("unknown_evidence", "excluded"))
        self.assertIn("-30%", issues[0].detail)
        self.assertIn("0.25", issues[0].detail)
        self.assertTrue(issues[0].detail.startswith("problem_statement"))

    def test_nested_text_is_checked(self):
        activity = {**BASE["activities"][0], "description": "참여자의 50%가 변화"}
        issues = numbers(plan_with(activities=[activity]))
        self.assertEqual(issues[0].detail.split(":")[0], "activities.0.description")

    def test_operational_numbers_dates_and_kpi_targets_are_ignored(self):
        kpi = {**BASE["kpis"][0], "definition": "재참여율 60% 이상"}
        plan = plan_with(problem_statement="2025-12 기준, 주 1회 8주, 6명, 오후 7시, 수량 500.0",
                         kpis=[kpi] + BASE["kpis"][1:])
        self.assertEqual(numbers(plan), [])

    def test_real_live_outputs_pass(self):
        for run, plans in LIVE.items():
            for data in plans:
                self.assertEqual(numbers(ProgramPlan.model_validate(data)), [], f"{run} {data['plan_id']}")


def phrases(text, field="problem_statement"):
    return [(i.action, i.detail.split("표현")[0].split(": ")[1].strip())
            for i in grounding.check_phrases(plan_with(**{field: text}))]


class CheckPhrasesTests(unittest.TestCase):
    def test_clear_violations_are_excluded(self):
        cases = {
            "이 프로그램은 효과가 입증된 방식이다": "효과 보장",
            "반드시 고립이 해소된다": "효과 보장",
            "참여자는 신청 자격이 있습니다": "자격 확정",
            "우울증 환자를 대상으로 한다": "개인 진단",
        }
        for text, label in cases.items():
            self.assertEqual(phrases(text), [("excluded", label)], text)

    def test_outcome_claims_and_labels_are_warned(self):
        self.assertEqual(phrases("모임을 통해 고립이 해소됩니다"), [("warned", "결과 단정")])
        self.assertEqual(phrases("고립된 청년을 위한 모임"), [("warned", "개인 낙인")])

    def test_purpose_and_negated_phrases_pass(self):
        for text in ("활동 위축을 해소하기 위해 소모임을 연다",       # 2026-10-23 실제 문장 (목적 표현)
                     "실제 개인의 고립을 단정하지 않습니다",          # 실제 문장 (면책 문구)
                     "효과가 입증되지 않았으므로 지표로 확인한다",
                     "효과를 보장하지 않으며 운영 기록으로 측정한다",
                     "신청 자격이 있는지는 기관 확인이 필요하다"):
            self.assertEqual(phrases(text), [], text)

    def test_kpi_and_nested_fields_are_checked(self):
        kpi = {**BASE["kpis"][0], "definition": "효과가 검증된 지표"}
        issues = grounding.check_phrases(plan_with(kpis=[kpi]))
        self.assertTrue(issues[0].detail.startswith("kpis.0.definition"))

    def test_same_label_in_one_sentence_is_reported_once(self):
        self.assertEqual(len(phrases("효과가 입증되고 효과가 보장된다")), 1)

    def test_real_live_outputs_pass(self):
        for run, plans in LIVE.items():
            for data in plans:
                self.assertEqual(grounding.check_phrases(ProgramPlan.model_validate(data)), [], f"{run} {data['plan_id']}")


# 저장 자료 6개 전체 (춘천 4 + 강남 2). 실제 자원 이름으로 오탐·탐지를 확인한다.
CATALOG = json.loads((Path(__file__).parents[1] / "ai" / "welfare_agent" / "welfare_resources.json").read_text(encoding="utf-8"))
EXISTING = ExistingResources(status="available", resources=[
    ExistingResource(id=r["id"], name=r["name"], purpose=r["purpose"])
    for r in (CATALOG if isinstance(CATALOG, list) else CATALOG["resources"])])


def duplicates(existing=EXISTING, **changes):
    return [(i.detail.split(":")[0], i.detail.split("(")[-1].split(")")[0])
            for i in grounding.check_duplicates(plan_with(**changes), existing)]


class CheckDuplicatesTests(unittest.TestCase):
    def test_core_name_strips_spacing_symbols_and_generic_suffix(self):
        self.assertEqual(grounding.core_name("우유배달(안부확인)서비스"), "우유배달안부확인")
        self.assertEqual(grounding.core_name("고독사 예방 사업"), "고독사예방")

    def test_title_or_activity_containing_resource_name_is_warned(self):
        found = duplicates(title="춘천 고독사 예방 소모임", operation={"lead_candidates": [], "linked_existing_resources": []})
        self.assertEqual(found, [("title", "cc-loneliness-prevention")])
        activity = {**BASE["activities"][0], "name": "일상돌봄"}
        found = duplicates(activities=[activity], operation={"lead_candidates": [], "linked_existing_resources": []})
        self.assertIn(("activities.0.name", "cc-daily-care"), found)
        issue = grounding.check_duplicates(plan_with(title="고독사 예방 모임", operation={"lead_candidates": []}), EXISTING)[0]
        self.assertEqual((issue.kind, issue.action), ("duplicate_suspected", "warned"))

    def test_declared_linkage_is_not_duplicate(self):
        operation = {"lead_candidates": [], "linked_existing_resources": ["cc-loneliness-prevention"]}
        self.assertEqual(duplicates(title="고독사 예방 연계 모임", operation=operation), [])

    def test_short_or_partial_words_do_not_match(self):
        none = {"lead_candidates": [], "linked_existing_resources": []}
        self.assertEqual(duplicates(title="청년 일상 활력 돌봄 모임", operation=none), [])  # '일상'·'돌봄'만으로는 겹침 아님
        short = ExistingResources(status="available", resources=[ExistingResource(id="R", name="돌봄", purpose="daily")])
        self.assertEqual(duplicates(existing=short, title="돌봄 모임", operation=none), [])

    def test_unavailable_existing_resources_skip_check(self):
        self.assertEqual(duplicates(existing=ExistingResources(status="unavailable"), title="고독사 예방 모임"), [])

    def test_real_live_outputs_pass(self):
        for run, plans in LIVE.items():
            for data in plans:
                self.assertEqual(grounding.check_duplicates(ProgramPlan.model_validate(data), EXISTING), [],
                                 f"{run} {data['plan_id']}")


SEARCHED = TrendReference(title="청년 식사 모임", url="https://www.example.go.kr/case", grade="public")


def planning(*, trends=(SEARCHED,), existing=EXISTING):
    return PlanningInput(run_id="run-ground0001", profile=PROFILE, causes=[], existing=existing,
                         trends=list(trends), gaps=[])


def manual(**changes):
    return plan_with(source="manual", plan_id="P-manual-01", **changes)


def ref(url):
    return {"title": "사례", "url": url, "year": 2026, "grade": "other", "how_applied": "주말 운영으로 바꿈"}


class CheckManualTests(unittest.TestCase):
    def test_generated_plans_are_left_to_planner(self):
        plan = plan_with(data_evidence=["E9"])  # source=generated: planner 스키마가 이미 막는 영역
        self.assertEqual(grounding.check_manual(plan, planning()), (plan, []))

    def test_target_mismatch_is_excluded(self):
        _, issues = grounding.check_manual(manual(target={"region": "강남구", "age_group": 60, "sex": "all"}), planning())
        self.assertEqual([(i.kind, i.action) for i in issues], [("target_mismatch", "excluded")])

    def test_unknown_evidence_id_is_removed_without_mutating_input(self):
        original = manual(data_evidence=["E1", "E9"])
        cleaned, issues = grounding.check_manual(original, planning())
        self.assertEqual((cleaned.data_evidence, original.data_evidence), (["E1"], ["E1", "E9"]))
        self.assertEqual([(i.kind, i.action) for i in issues], [("unknown_evidence", "removed_item")])

    def test_unsearched_url_is_kept_with_warning(self):
        plan = manual(trend_references=[ref(SEARCHED.url), ref("https://www.mohw.go.kr/other")])
        cleaned, issues = grounding.check_manual(plan, planning())
        self.assertEqual(len(cleaned.trend_references), 2)
        self.assertEqual([(i.kind, i.action, i.detail.split(":")[0]) for i in issues],
                         [("unknown_url", "warned", "trend_references.1.url")])


class CheckGroundingTests(unittest.TestCase):
    def test_excluded_and_kept_partition_matches_report(self):
        good = plan_with(plan_id="P-good-01")
        warned = plan_with(plan_id="P-warn-01", problem_statement="고립이 해소됩니다")
        bad = plan_with(plan_id="P-bad-01", problem_statement="외출이 -30% 줄었다")
        manual_fix = manual(data_evidence=["E1", "E9"])
        kept, report = grounding.check_grounding(None, [good, warned, bad, manual_fix], planning())
        self.assertEqual([p.plan_id for p in kept], ["P-good-01", "P-warn-01", "P-manual-01"])
        self.assertEqual(report.kept_plan_ids, [p.plan_id for p in kept])
        self.assertEqual(report.excluded_plan_ids, ["P-bad-01"])
        self.assertEqual(kept[2].data_evidence, ["E1"])  # 통과본은 정리된 수정본
        self.assertEqual({i.plan_id for i in report.issues}, {"P-warn-01", "P-bad-01", "P-manual-01"})

    def test_real_live_outputs_all_pass(self):
        for run, plans in LIVE.items():
            kept, report = grounding.check_grounding(None, [ProgramPlan.model_validate(p) for p in plans], planning())
            self.assertEqual((len(kept), report.issues), (3, []), run)


class GraphConnectionTests(unittest.TestCase):
    def run_graph(self, plans_for):
        engines = replace(Engines(), generate_plans=plans_for)
        return run_pipeline(PROFILE, mode="offline", engines=engines, run_id="run-ground0002")

    def test_default_engine_is_grounding(self):
        self.assertIs(Engines().check_grounding, grounding.check_grounding)

    def test_excluded_plan_is_dropped_and_reasons_are_traced(self):
        def plans(ctx, planning_input):
            first, second = stubs.generate_plans(ctx, planning_input)
            return [first, second.model_copy(update={"problem_statement": "외출이 -30% 줄었다"})]
        state = self.run_graph(plans)
        event = next(e for e in state["trace"] if e.node == "grounding_check" and e.status == "done")
        self.assertIn("1개 통과, 1개 제외", event.decision)
        self.assertTrue(any("unknown_evidence" in r for r in event.reasons))
        self.assertEqual(state["report"].status, "completed")

    def test_all_excluded_fails_the_run(self):
        def plans(ctx, planning_input):
            return [p.model_copy(update={"problem_statement": "효과가 입증된 방식"})
                    for p in stubs.generate_plans(ctx, planning_input)]
        state = self.run_graph(plans)
        self.assertEqual(state["report"].status, "failed")
        self.assertIn("근거 검증을 통과한 기획안이 없습니다.", state["errors"])


if __name__ == "__main__":
    unittest.main()
