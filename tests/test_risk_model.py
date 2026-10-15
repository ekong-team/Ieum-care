"""5단계 우선순위·정확한 임계값·연속성·업종 제외·판단 보류 검사."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai" / "risk_model"))
from classify_risk import classify_risk, summarize_card_exclusions, TOTAL, MOVEMENT, FILTERED


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


if __name__ == "__main__":
    unittest.main()
