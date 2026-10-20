import copy
from decimal import Decimal
import unittest
from pathlib import Path
import csv
import json
import tempfile
from unittest.mock import patch

from ai.analysis_agent.assessment import assess
from ai.analysis_agent.inputs import digest, number, load_inputs, file_hash
from ai.analysis_agent.interpretation import profile_for, hypotheses_for, team_causes_for
from ai.analysis_agent.priority import priority_for
from ai.analysis_agent.reviewer import review_cohort
from ai.analysis_agent.context import describe_cohort, background_for
from ai.analysis_agent.workflow import run_analysis

def rows(months, cards, movements, filtered=None):
    result = []
    for i, (month, count, movement) in enumerate(zip(months, cards, movements)):
        result.append(dict(month=month, region="강원 춘천시", age="30대",
            card=None if count is None else Decimal(str(count)),
            movement=None if movement is None else Decimal(str(movement)),
            filtered_daily=None if filtered is None or filtered[i] is None else Decimal(str(filtered[i])),
            common_location=Decimal(".95"), age_coverage=Decimal(".8")))
    # Independent stored cross-check for synthetic fixtures.
    from calendar import monthrange
    for i, row in enumerate(result):
        row["stored_daily"] = None
        if i and row["card"] is not None and result[i-1]["card"] and int(months[i][4:]) == int(months[i-1][4:]) + 1:
            current_days = monthrange(int(months[i][:4]), int(months[i][4:]))[1]
            prior_days = monthrange(int(months[i-1][:4]), int(months[i-1][4:]))[1]
            row["stored_daily"] = row["card"] / result[i-1]["card"] * Decimal(prior_days) / Decimal(current_days) - 1
    return result

class AssessmentTests(unittest.TestCase):
    def test_daily_constant_activity_does_not_trigger_month_length_signal(self):
        data = rows(["202508", "202509"], [3100, 3000], [None, 0])
        self.assertEqual(assess(data)[1]["level"], 1)
        self.assertEqual(assess(data, basis="monthly")[1]["level"], 2)

    def test_monthly_sensitivity_cannot_masquerade_as_daily_profile(self):
        data = rows(["202508","202509"],[3100,3000],[None,0])
        record = assess(data,basis="monthly")[1]
        with self.assertRaisesRegex(ValueError,"민감도"):
            profile_for(record)

    def test_two_comparisons_require_three_months(self):
        data = rows(["202507", "202508", "202509"], [10000, 9000, 8000], [None, -.1, -.1])
        result = assess(data)
        self.assertEqual([(r["level"], r["status"]) for r in result], [(None,"held"),(3,"partial"),(4,"partial")])
        self.assertIsNone(result[2]["conditions"]["fifth"])

    def test_missing_filtered_is_unknown_not_failed_fifth(self):
        data = rows(["202507","202508","202509"], [10000,9000,8000], [None,-.1,-.1], [None,-.1,-.1])
        result = assess(data)
        self.assertEqual((result[2]["level"],result[2]["status"]), (5,"complete"))

    def test_known_failed_severe_allows_complete_four(self):
        data = rows(["202507","202508","202509"], [10000,9600,9000], [None,-.04,-.04])
        self.assertEqual((assess(data)[2]["level"],assess(data)[2]["status"]), (4,"complete"))

    def test_zero_denominator_holds(self):
        result = assess(rows(["202508","202509"], [0,10], [None,-.1]))
        self.assertEqual(result[1]["status"], "held")

    def test_missing_month_holds_and_breaks_persistence(self):
        result = assess(rows(["202507","202509"], [10000,8000], [None,-.1]))
        self.assertEqual(result[1]["status"], "held")

    def test_duplicate_month_rejected(self):
        with self.assertRaises(ValueError):
            assess(rows(["202508","202508"], [100,90], [None,-.1]))

    def test_quality_warns_without_arbitrary_stage_block(self):
        data = rows(["202508","202509"], [3100,3000], [None,0])
        data[1]["age_coverage"] = Decimal(".5")
        result = assess(data)[1]
        self.assertEqual(result["level"], 1)
        self.assertTrue(result["quality_warnings"])

    def test_stale_full_daily_input_rejected(self):
        data = rows(["202508","202509"], [3100,3000], [None,0])
        data[1]["stored_daily"] = Decimal("-.1")
        with self.assertRaisesRegex(ValueError, "stale"):
            assess(data)

    def test_future_does_not_change_past(self):
        data = rows(["202507","202508","202509"], [10000,9000,8000], [None,-.1,-.1])
        before = assess(data)[:2]
        data[2]["card"] = Decimal(99999)
        data[2]["stored_daily"] = None
        # Only compare when no stale sensitivity source is introduced.
        from calendar import monthrange
        data[2]["stored_daily"] = data[2]["card"]/data[1]["card"]*Decimal(31)/Decimal(30)-1
        self.assertEqual(assess(data)[:2], before)

    def test_input_not_mutated(self):
        data = rows(["202508","202509"], [3100,3000], [None,0])
        before = copy.deepcopy(data)
        assess(data)
        self.assertEqual(data, before)

    def test_profile_contract_and_safe_units(self):
        result = assess(rows(["202508","202509"], [3100,2700], [None,-.04]))[1]
        profile = profile_for(result)
        self.assertEqual(profile["target"], dict(region="춘천시",age_group=30,sex="all"))
        self.assertEqual(profile["evidence"][0]["unit"],"ratio")
        self.assertEqual(profile["evidence"][0]["value"],result["card_change"])
        self.assertEqual(profile["risk"]["status"],"partial")

    def test_partial_does_not_generate_confirmed_cause(self):
        a = assess(rows(["202508","202509"], [3100,2700], [None,-.04]))[1]
        self.assertEqual([h["code"] for h in hypotheses_for(a)], ["C0_unknown"])

    def test_priority_ties_held_and_partial_are_separate(self):
        data = rows(["202508","202509"], [3100,3000], [None,0])
        complete = assess(data)[1]
        def cohort(a, age):
            a = copy.deepcopy(a)
            a["age"] = age
            a["analysis_id"] = "202509_32010_" + age
            return dict(analysis_id=a["analysis_id"],assessment=a,profile=profile_for(a),sensitivity=[])
        items = [cohort(complete,"30대"),cohort(complete,"40대")]
        partial = copy.deepcopy(complete)
        partial.update(status="partial",level=3)
        held = copy.deepcopy(complete)
        held.update(status="held",level=None)
        items += [cohort(partial,"20대"),cohort(held,"10대")]
        p = priority_for(items,"202509")
        self.assertEqual([c["rank"] for c in p["ranked_cohorts"]],[1,1])
        self.assertEqual(len(p["partial_assessments"]),1)
        self.assertEqual(len(p["held_cohorts"]),1)
        self.assertFalse(p["scope"]["coverage_complete"])


    def test_negative_counts_and_boolean_inputs_rejected(self):
        data = rows(["202508","202509"],[3100,3000],[None,0])
        for invalid in (-1, True, Decimal("NaN"), Decimal("Infinity")):
            candidate = copy.deepcopy(data)
            candidate[1]["card"] = invalid
            with self.assertRaises(ValueError):
                assess(candidate)

    def test_exact_threshold_is_included(self):
        data = rows(["202507","202508"],[10000,9700],[None,-.03])
        self.assertEqual(assess(data)[1]["level"],3)

    def test_zero_observation_range_cannot_have_finite_movement(self):
        data = rows(["202508","202509"],[3100,3000],[None,0])
        data[1]["age_coverage"] = Decimal(0)
        with self.assertRaisesRegex(ValueError,"관측 범위"):
            assess(data)

    def test_year_boundary_is_adjacent(self):
        data = rows(["202512","202601"],[3100,3100],[None,0])
        data[1]["stored_daily"] = Decimal(0)
        self.assertEqual(assess(data)[1]["level"],1)

    def test_profile_has_readable_values_for_downstream_bridge(self):
        assessment = assess(rows(["202508","202509"],[3100,2700],[None,-.04]))[1]
        self.assertIn("-4.00%",profile_for(assessment)["evidence"][1]["description"])
        self.assertEqual(team_causes_for(assessment)[0]["code"],"C0_unknown")

    def test_priority_does_not_impose_candidate_cutoff(self):
        bundle = run_analysis(rows(["202508","202509"],[3100,3000],[None,0]),{},[],period="202509")
        item = bundle["priority_review"]["ranked_cohorts"][0]
        self.assertEqual(item["level"],1)
        self.assertNotIn("candidate",item)
        self.assertNotIn("resource_coverage_status",item)

    def test_mismatched_profile_cannot_enter_priority(self):
        bundle = run_analysis(rows(["202508","202509"],[3100,3000],[None,0]),{},[],period="202509")
        bundle["cohorts"][1]["profile"]["risk"]["level"] = 5
        with self.assertRaisesRegex(ValueError,"일치"):
            priority_for(bundle["cohorts"],"202509")

class ReviewTests(unittest.TestCase):
    def cohort(self):
        assessment = assess(rows(["202508","202509"],[3100,3000],[None,0]))[1]
        return describe_cohort(assessment,None,[])

    def test_model_receives_evidence_and_returns_checked_selection(self):
        def provider(system,payload):
            self.assertIn("hypotheses",payload)
            return dict(proposal=dict(observation_ids=["E1"],hypothesis_codes=["C0_unknown"],question_codes=["data_quality"]),
                        provenance=dict(kind="fixture"))
        review,execution = review_cohort(self.cohort(),provider)
        self.assertEqual(review["status"],"fixture_only")
        self.assertTrue(review["questions"])
        self.assertEqual(execution["provider_attempts"],1)
        self.assertEqual(execution["confirmed_llm_responses"],0)

    def test_model_cannot_invent_evidence_hypothesis_or_level(self):
        for bad in (
            dict(observation_ids=["E999"],hypothesis_codes=[],question_codes=[]),
            dict(observation_ids=[],hypothesis_codes=["C4_prolonged"],question_codes=[]),
            dict(observation_ids=[],hypothesis_codes=[],question_codes=[],level=5),
        ):
            def provider(system,payload):
                return dict(proposal=bad,provenance=dict(kind="fixture"))
            review,execution = review_cohort(self.cohort(),provider)
            self.assertEqual(review["status"],"failed")
            self.assertEqual(execution["provider_attempts"],1)

    def test_model_mutation_cannot_change_protected_input(self):
        cohort = self.cohort()
        original = copy.deepcopy(cohort)
        def provider(system,payload):
            payload["profile"]["risk"]["level"] = 5
            return dict(proposal=dict(observation_ids=[],hypothesis_codes=[],question_codes=[]),provenance=dict(kind="fixture"))
        review_cohort(cohort,provider)
        self.assertEqual(cohort,original)

    def test_provider_error_preserves_analysis_without_retry(self):
        cohort = self.cohort()
        original = copy.deepcopy(cohort)
        def provider(system,payload):
            raise RuntimeError("test")
        review,execution = review_cohort(cohort,provider)
        self.assertEqual(review["status"],"failed")
        self.assertEqual(execution["provider_attempts"],1)
        self.assertEqual(cohort,original)

    def test_no_provider_is_explicit(self):
        review,execution = review_cohort(self.cohort())
        self.assertEqual(review["status"],"not_run")
        self.assertEqual(execution["provider_attempts"],0)

    def test_missing_population_is_not_available(self):
        cohort = self.cohort()
        raw = dict(calendar_context=dict(month="202509",days=30))
        context = background_for(cohort["assessment"],raw)
        self.assertEqual(context["status"],"partial")
        self.assertIn("resident_population",context["missing_fields"])

    def test_context_without_characteristics_does_not_claim_them_available(self):
        assessment = self.cohort()["assessment"]
        source = {"월":"202509","지역":"강원 춘천시","연령대":"30대",
                  "소비_일평균건수_전월변화율":0,"통신_연령유동량_전월변화율":0}
        described = describe_cohort(assessment,dict(analysis_evidence=source),[])
        self.assertEqual(described["characteristics"]["availability"],"unavailable")
        self.assertTrue(described["characteristics"]["missing_fields"])

    def test_wrong_population_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"인구"):
            background_for(self.cohort()["assessment"],dict(resident_population=101,prior_resident_population=100,population_mom_change=-.5))

    def test_wrong_calendar_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"달력"):
            background_for(self.cohort()["assessment"],dict(calendar_context=dict(month="202508",days=31)))

    def test_context_errors_checked_before_any_paid_call(self):
        data = rows(["202508","202509"],[3100,3000],[None,0])
        aid = assess(data)[1]["analysis_id"]
        contexts = {aid:dict(analysis_evidence={"월":"202509","지역":"서울 강남구","연령대":"30대"})}
        provider = unittest.mock.Mock()
        with self.assertRaisesRegex(ValueError,"identity"):
            run_analysis(data,contexts,[],period="202509",provider=provider,model_analysis_id=assess(data)[0]["analysis_id"])
        provider.assert_not_called()

    def test_bundle_repeatable_and_graph_has_real_stages(self):
        data = rows(["202508","202509"],[3100,3000],[None,0])
        first = run_analysis(data,{},[],period="202509")
        second = run_analysis(data,{},[],period="202509")
        self.assertEqual(first["bundle_hash"],second["bundle_hash"])
        self.assertEqual([t["node"] for t in first["trace"]],["calculate","describe","interpret","first_priority"])

def write_fixture(folder):
    """실데이터가 없어도 실행·저장·재검산을 시험할 작은 입력."""
    from ai.analysis_agent.policy import KEYS,CARD,MOVEMENT,FILTERED
    feature = folder/"features.csv"
    sensitivity = folder/"sensitivity.csv"
    packet = folder/"context.json"
    data = rows(["202508","202509"],[3100,3000],[None,0])
    feature_columns = [*KEYS,CARD,MOVEMENT,"통신_연령관측률","통신_전월공통위치비율"]
    with feature.open("w",encoding="utf-8",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=feature_columns)
        writer.writeheader()
        for row in data:
            writer.writerow(dict(zip(feature_columns,[row["month"],row["region"],row["age"],row["card"],row["movement"],row["age_coverage"],row["common_location"]])))
    sensitivity_columns = [*KEYS,FILTERED,"일평균_결제건수_전월변화율_전체"]
    with sensitivity.open("w",encoding="utf-8",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=sensitivity_columns)
        writer.writeheader()
        for row in data:
            writer.writerow(dict(zip(sensitivity_columns,[row["month"],row["region"],row["age"],None,row["stored_daily"]])))
    packet.write_text(json.dumps(dict(schema_version="submission-review-context-v1",records=[])),encoding="utf-8")
    loaded,contexts,manifest = load_inputs(feature,sensitivity,packet)
    bundle = run_analysis(loaded,contexts,manifest,period="202509")
    policy = Path(__file__).resolve().parents[1]/"ai/analysis_agent/policy.py"
    bundle["implementation_manifest"] = [dict(path="ai/analysis_agent/policy.py",sha256=file_hash(policy))]
    bundle.pop("bundle_hash")
    bundle["bundle_hash"] = digest(bundle)
    return bundle,contexts

class PublicationTests(unittest.TestCase):
    def test_model_questions_reach_team_engine_without_changing_risk(self):
        from ai.analysis_agent.handoff import target_profile, make_cause_engine
        from ai.analysis_agent.reviewer import QUESTION_TEXT
        def provider(system,payload):
            return dict(proposal=dict(observation_ids=["E1"],hypothesis_codes=["C0_unknown"],question_codes=["population_scope"]),
                        provenance=dict(kind="fixture"))
        bundle = run_analysis(rows(["202508","202509"],[3100,3000],[None,0]),{},[],period="202509",
                              provider=provider,model_analysis_id="202509_32010_30G")
        profile = target_profile(bundle,"202509_32010_30G")
        causes = make_cause_engine(bundle)(None,profile)
        self.assertEqual(profile.risk.level,1)
        self.assertIn(QUESTION_TEXT["population_scope"],causes[0].questions)

    def test_tampered_model_selection_cannot_enter_team_engine(self):
        from ai.analysis_agent.handoff import make_cause_engine
        bundle = run_analysis(rows(["202508","202509"],[3100,3000],[None,0]),{},[],period="202509")
        review = bundle["cohorts"][1]["interpretation"]["model_review"]
        review.update(status="executed",selected_observation_ids=["E999"])
        with self.assertRaisesRegex(ValueError,"없는 근거"):
            make_cause_engine(bundle)

    def test_team_engine_accepts_exact_profile_and_returns_shared_cause_models(self):
        from ai.analysis_agent.handoff import target_profile, make_cause_engine
        bundle = run_analysis(rows(["202508","202509"],[3100,3000],[None,0]),{},[],period="202509")
        engine = make_cause_engine(bundle)
        profile = target_profile(bundle,"202509_32010_30G")
        causes = engine(None,profile)
        self.assertEqual(causes[0].code,"C0_unknown")
        causes[0].questions.clear()
        self.assertTrue(engine(None,profile)[0].questions)

    def test_team_engine_rejects_changed_analysis(self):
        from ai.analysis_agent.handoff import target_profile, make_cause_engine
        bundle = run_analysis(rows(["202508","202509"],[3100,3000],[None,0]),{},[],period="202509")
        engine = make_cause_engine(bundle)
        profile = target_profile(bundle,"202509_32010_30G")
        profile.risk.level = 5
        with self.assertRaisesRegex(ValueError,"일치"):
            engine(None,profile)

    def test_success_is_recalculated_before_publication(self):
        from scripts.integration.run_analysis_agent import save_results
        from scripts.integration.verify_analysis_agent import verify
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bundle,contexts = write_fixture(folder)
            result = save_results(bundle,contexts,folder/"output")
            checked = verify(result["output"])
            self.assertTrue(checked["recalculated_from_sources"])
            self.assertEqual(checked["checked_profiles"],2)

    def test_failed_save_does_not_replace_latest_success(self):
        from scripts.integration.run_analysis_agent import save_results
        from scripts.integration.verify_analysis_agent import verify
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bundle,contexts = write_fixture(folder)
            root = folder/"output"
            save_results(bundle,contexts,root)
            previous = (root/"latest.json").read_text(encoding="utf-8")
            candidate = copy.deepcopy(bundle)
            candidate.pop("bundle_hash")
            candidate["test_run"] = "failed-second"
            candidate["bundle_hash"] = digest(candidate)
            with patch("scripts.integration.run_analysis_agent.verify",side_effect=ValueError("test failure")):
                with self.assertRaisesRegex(ValueError,"test failure"):
                    save_results(candidate,contexts,root)
            self.assertEqual((root/"latest.json").read_text(encoding="utf-8"),previous)
            with self.assertRaisesRegex(ValueError,"완료"):
                verify(root/candidate["bundle_hash"][:16])

    def test_rehashed_false_assessment_is_detected_by_recalculation(self):
        from scripts.integration.run_analysis_agent import save_results
        from scripts.integration.verify_analysis_agent import verify
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bundle,contexts = write_fixture(folder)
            saved = Path(save_results(bundle,contexts,folder/"output")["output"])
            altered = json.loads((saved/"analysis_bundle.json").read_text(encoding="utf-8"))
            altered["cohorts"][1]["assessment"]["level"] = 5
            altered.pop("bundle_hash")
            altered["bundle_hash"] = digest(altered)
            (saved/"analysis_bundle.json").write_text(json.dumps(altered),encoding="utf-8")
            (saved/"run_status.json").write_text(json.dumps(dict(status="passed",bundle_hash=altered["bundle_hash"])),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"재계산"):
                verify(saved)

if __name__ == "__main__":
    unittest.main()
