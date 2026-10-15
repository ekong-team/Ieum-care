"""5단계 우선순위·정확한 임계값·연속성·업종 제외·판단 보류 검사."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai" / "risk_model"))
from classify_risk import (classify_risk, summarize_card_exclusions, compare_scenarios,
                           analyze_sensitivity, review_temporal_quality, TOTAL, MOVEMENT, FILTERED)


def sample(totals, movements, filtered=None, months=None, region="테스트지역", age="20대"):
    count = len(totals)
    return pd.DataFrame({"월": months or [f"2025{7+i:02d}" for i in range(count)],
                         "지역": [region] * count, "연령대": [age] * count,
                         TOTAL: totals, MOVEMENT: movements,
                         FILTERED: filtered if filtered is not None else totals})


class RiskModelTests(unittest.TestCase):
    def test_first_month_is_held_not_level_one(self):
        row = classify_risk(sample([10000], [np.nan])).iloc[0]
        self.assertTrue(pd.isna(row["위험단계"]))
        self.assertEqual(row["판정상태"], "판단보류")

    def test_exact_three_percent_boundary_and_one_sided_signal(self):
        for current, movement, level in [(9800, -.029999, 1), (9700, -.02, 2),
                                          (9800, -.03, 2), (9700, -.03, 3)]:
            with self.subTest(current=current, movement=movement):
                row = classify_risk(sample([10000, current], [np.nan, movement])).iloc[-1]
                self.assertEqual(row["위험단계"], level)
                if level == 3:
                    self.assertEqual(row["판정상태"], "부분판정")

    def test_level_four_requires_two_comparisons_not_two_rows(self):
        rows = classify_risk(sample([10000, 9600, 9216], [np.nan, -.04, -.04]))
        self.assertEqual(rows["위험단계"].iloc[1:].tolist(), [3, 4])
        self.assertEqual(rows["판정상태"].iloc[-1], "판정완료")

    def test_level_five_priority_and_previous_month_need_not_drop_five_percent(self):
        rows = classify_risk(sample([10000, 9700, 9215], [np.nan, -.03, -.05], [9000, 8730, 8293]))
        row = rows.iloc[-1]
        self.assertEqual(row["위험단계"], 5)
        self.assertTrue(row["5단계조건"])
        self.assertEqual(row["판정상태"], "판정완료")

    def test_large_current_drop_without_persistence_remains_three(self):
        row = classify_risk(sample([10000, 9900, 9000], [np.nan, -.01, -.1])).iloc[-1]
        self.assertEqual(row["위험단계"], 3)
        self.assertEqual(row["판정상태"], "판정완료")

    def test_filtered_consumption_must_drop_in_both_comparisons(self):
        # 전체는 연속 감소하지만 제외 후 첫 비교는 약 1.4% 감소뿐이다.
        row = classify_risk(sample([10000, 9600, 9000], [np.nan, -.04, -.1], [7000, 6900, 6400])).iloc[-1]
        self.assertEqual(row["위험단계"], 4)
        self.assertFalse(row["업종제외연속감소"])
        self.assertEqual(row["판정상태"], "판정완료")

    def test_missing_filtered_denominator_is_not_a_failed_fifth_condition(self):
        row = classify_risk(sample([10000, 9600, 9000], [np.nan, -.04, -.1], [7000, 0, 100])).iloc[-1]
        self.assertEqual(row["위험단계"], 4)
        self.assertTrue(pd.isna(row["5단계조건"]))
        self.assertEqual(row["판정상태"], "부분판정")

    def test_zero_total_denominator_and_missing_movement_are_held(self):
        row = classify_risk(sample([0, 100], [np.nan, -.04], [0, 50])).iloc[-1]
        self.assertEqual(row["판정상태"], "판단보류")
        row = classify_risk(sample([10000, 9000], [np.nan, np.nan])).iloc[-1]
        self.assertEqual(row["판정상태"], "판단보류")

    def test_month_gap_is_not_adjacent(self):
        rows = classify_risk(sample([10000, 9600, 9000], [np.nan, -.04, -.1],
                                    months=["202507", "202509", "202510"]))
        self.assertEqual(rows.iloc[1]["판정상태"], "판단보류")
        self.assertEqual(rows.iloc[2]["위험단계"], 3)
        self.assertEqual(rows.iloc[2]["판정상태"], "부분판정")

    def test_groups_are_separate_and_future_month_cannot_change_past_levels(self):
        a = sample([10000, 9600, 9000], [np.nan, -.04, -.1])
        b = sample([100, 110, 120], [np.nan, .1, .1], age="30대")
        combined = classify_risk(pd.concat([b, a], ignore_index=True).sample(frac=1, random_state=7))
        self.assertEqual(combined.loc[(combined["연령대"] == "30대") & (combined["월"] == "202509"), "위험단계"].iloc[0], 1)
        past = classify_risk(a.iloc[:2])
        pd.testing.assert_frame_equal(past, combined.loc[(combined["연령대"] == "20대") & (combined["월"] != "202509")].reset_index(drop=True))

    def test_invalid_counts_and_duplicate_keys_are_rejected(self):
        bad = sample([100], [np.nan], [101])
        with self.assertRaises(ValueError):
            classify_risk(bad)
        good = sample([100], [np.nan])
        with self.assertRaises(ValueError):
            classify_risk(pd.concat([good, good]))

    def test_raw_exclusion_preserves_other_sports_and_personal_total(self):
        raw = pd.DataFrame({"TA_YMD": ["20250701"] * 5, "MCT_SGG_CD": ["서울 강남구"] * 5,
                            "SEX_CCD": ["남", "여", "남", "여", "법인"],
                            "AGE_CCD": ["60대", "70대", "80대", "90대", "법인"],
                            "MCT_RY_CD": ["실내/실외골프장", "종합레저타운/놀이동산", "스포츠시설", "한식", "한식"],
                            "USE_CNT": [10, 20, 30, 40, 100]})
        result = summarize_card_exclusions(raw)
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["연령대"], "60대이상")
        self.assertEqual(row["원본_전체결제건수"], 100)
        self.assertEqual(row[FILTERED], 70)
        self.assertEqual(row["골프_결제건수"] + row["레저타운놀이동산_결제건수"] + row[FILTERED], row["원본_전체결제건수"])


class RiskSensitivityTests(unittest.TestCase):
    def test_constant_daily_consumption_does_not_decline_with_shorter_month(self):
        data = sample([3100, 3100, 3000], [np.nan, -.04, -.04], [310, 310, 300])
        monthly = classify_risk(data)
        daily = classify_risk(data, consumption_basis="daily")
        self.assertAlmostEqual(monthly.iloc[-1]["소비변화율"], 30/31 - 1)
        self.assertAlmostEqual(daily.iloc[-1]["소비변화율"], 0)
        self.assertAlmostEqual(daily.iloc[-1]["업종제외소비변화율"], 0)
        self.assertEqual(monthly.iloc[-1]["위험단계"], 3)
        self.assertEqual(daily.iloc[-1]["위험단계"], 2)
        pd.testing.assert_series_equal(monthly["이동변화율"], daily["이동변화율"])
        pd.testing.assert_series_equal(monthly[TOTAL], daily[TOTAL])

    def test_real_daily_drop_is_retained_and_leap_february_uses_29_days(self):
        row = classify_risk(sample([3100, 3100, 2940], [np.nan, -.04, -.04], [310, 310, 294]),
                            consumption_basis="daily").iloc[-1]
        self.assertAlmostEqual(row["소비변화율"], -.02)
        self.assertAlmostEqual(row["업종제외소비변화율"], -.02)
        leap = classify_risk(sample([3100, 2900], [np.nan, -.04], months=["202401", "202402"]),
                             consumption_basis="daily")
        self.assertAlmostEqual(leap.iloc[-1]["소비변화율"], 0)

    def test_unknown_levels_are_not_counted_as_changes(self):
        result = classify_risk(sample([10000, 9600, 9216], [np.nan, -.04, -.04]))
        compared = compare_scenarios(result, result)
        self.assertEqual(compared["양쪽단계있음"].sum(), 2)
        self.assertEqual(compared["양쪽판정완료"].sum(), 1)
        self.assertEqual(compared["단계변경"].sum(), 0)
        self.assertEqual(compared["상태변경"].sum(), 0)

    def test_severe_threshold_can_change_four_to_five(self):
        data = sample([10000, 9600, 9216], [np.nan, -.04, -.04])
        self.assertEqual(classify_risk(data, .03, .05).iloc[-1]["위험단계"], 4)
        self.assertEqual(classify_risk(data, .03, .04).iloc[-1]["위험단계"], 5)

    def test_eighteen_scenarios_preserve_inputs_and_separate_the_two_effects(self):
        data = sample([3100, 3100, 3000], [np.nan, -.04, -.04], [310, 310, 300])
        original = data.copy(deep=True)
        comparisons, details, baseline = analyze_sensitivity(data)
        self.assertEqual(len(comparisons), 18)
        self.assertEqual(len(details), 54)
        pd.testing.assert_frame_equal(data, original)
        pd.testing.assert_frame_equal(baseline, classify_risk(data))
        daily = comparisons.loc[comparisons["시나리오"].eq("daily_d03_s05")].iloc[0]
        self.assertEqual(daily["같은소비기준3_5대비단계변경수"], 0)
        self.assertEqual(daily["월합계3_5대비단계변경수"], 1)


def quality_sample(data, flows, positions=None, coverages=None):
    result = data[["월", "지역", "연령대"]].copy()
    count = len(data)
    result["통신_연령유동량"] = flows
    result["통신_전체관측위치수"] = [100] * count
    result["통신_연령관측위치수"] = positions if positions is not None else [99] * count
    result["통신_연령관측률"] = coverages if coverages is not None else [.99] * count
    for kind in ["시간", "요일"]:
        result[f"통신_{kind}관측위치수"] = [100] * count
        result[f"통신_{kind}관측률"] = [1.] * count
    result["통신_전월공통위치비율"] = [np.nan] + [.98] * (count - 1)
    result["카드1_해석보류_결제건수_비중"] = [.1] * count
    return result


class RiskTemporalReviewTests(unittest.TestCase):
    def test_partial_and_held_are_not_counted_as_completed_transitions(self):
        data = sample([10000, 9600, 9216, 9500], [np.nan, -.04, -.04, .01])
        reviewed, region = review_temporal_quality(classify_risk(data), quality_sample(data, [1000, 960, 920, 950]))
        self.assertEqual(reviewed["전이구분"].tolist(), ["전월자료없음", "보류포함", "부분판정포함", "하락"])
        self.assertEqual(reviewed["완료끼리비교"].sum(), 1)
        self.assertEqual(len(region), 4)

    def test_month_gap_and_cohort_boundaries_are_not_bridged(self):
        a = sample([10000, 10000, 10000], [np.nan, .01, .01], months=["202507", "202509", "202510"])
        b = sample([100, 100, 100], [np.nan, .01, .01], months=["202507", "202509", "202510"], age="30대")
        data = pd.concat([a, b], ignore_index=True)
        features = pd.concat([quality_sample(a, [100, 100, 100]), quality_sample(b, [100, 100, 100])], ignore_index=True)
        reviewed, region = review_temporal_quality(classify_risk(data), features)
        self.assertEqual(len(region), 3)
        self.assertFalse(reviewed.loc[reviewed["월"].eq("202509"), "전월연속자료있음"].any())
        self.assertFalse(reviewed["전이구분"].isin(["상승", "하락"]).any())

    def test_observation_range_change_is_context_not_a_grade_override(self):
        data = sample([10000, 10000, 10000], [np.nan, 0., 0.])
        baseline = classify_risk(data)
        reviewed, _ = review_temporal_quality(baseline, quality_sample(data, [1000, 800, 600], [99, 80, 60], [.99, .8, .6]))
        pd.testing.assert_series_equal(reviewed["위험단계"], baseline["위험단계"])
        self.assertEqual(reviewed["관측범위감소동반"].sum(), 2)
        self.assertEqual(reviewed.iloc[-1]["전이구분"], "유지")

    def test_naive_sum_can_change_current_and_persistent_stage_without_changing_baseline(self):
        data = sample([10000, 9600, 9216], [np.nan, -.04, -.04])
        baseline = classify_risk(data)
        reviewed, _ = review_temporal_quality(baseline, quality_sample(data, [1000, 980, 941]))
        self.assertEqual(reviewed["위험단계"].iloc[1:].tolist(), [3, 4])
        self.assertEqual(reviewed["단순유동기준단계"].iloc[1:].tolist(), [2, 3])
        self.assertEqual(reviewed["단순유동기준단계변경"].sum(), 2)
        self.assertEqual(reviewed["단순공통3퍼센트판정다름"].sum(), 1)

    def test_region_context_is_not_multiplied_by_age(self):
        a = sample([10000, 10000, 10000], [np.nan, .01, .01])
        b = sample([100, 100, 100], [np.nan, .01, .01], age="30대")
        features = pd.concat([quality_sample(a, [100, 100, 100]), quality_sample(b, [10, 10, 10])], ignore_index=True)
        baseline = classify_risk(pd.concat([a, b], ignore_index=True))
        reviewed, region = review_temporal_quality(baseline, features)
        self.assertEqual(len(reviewed), 6)
        self.assertEqual(len(region), 3)
        features.loc[features["연령대"].eq("30대"), "통신_시간관측률"] = .5
        with self.assertRaises(ValueError):
            review_temporal_quality(baseline, features)


if __name__ == "__main__":
    unittest.main()
