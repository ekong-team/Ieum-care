"""정제 경계 조건 회귀 검사. python -m unittest discover -s tests -v"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "data_processing"))
import build_telecom_features as telecom
from data_contract import AGES, require_keys, require_numbers
from industry_classification import classify_industries
from build_risk_features import safe_ratio
from analyze_features import make_scenarios, REGION_SCOPE, correlation_review, feature_rule


class PreprocessingTests(unittest.TestCase):
    def test_duplicate_key_rejected(self):
        with self.assertRaises(ValueError):
            require_keys(pd.DataFrame({"key": ["a", "a"], "value": [1, 2]}), ["key"], "test")

    def test_invalid_numbers_rejected(self):
        for value in [-1, np.inf, np.nan, 1.5]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                require_numbers(pd.DataFrame({"count": [value]}), ["count"], "test", integer=True)

    def test_unknown_industry_preserved(self):
        self.assertEqual(classify_industries(pd.Series(["ZZ_나머지", "신규업종", None])).tolist(),
                         ["해석보류", "미분류", "미분류"])

    def test_zero_denominator_remains_missing(self):
        self.assertTrue(safe_ratio(pd.Series([3., 0.]), pd.Series([0., 0.])).isna().all())

    def test_entropy_of_zero_and_uniform(self):
        result = telecom.normalized_entropy(pd.DataFrame([[0, 0], [1, 1], [2, 0]], columns=["a", "b"]), ["a", "b"])
        self.assertTrue(np.isnan(result[0]))
        np.testing.assert_allclose(result[1:], [1, 0])

    def test_missing_month_not_compared_as_previous_month(self):
        # 같은 위치에 7월과 9월만 있다면 8월 값을 가정해서 비교하지 않는다.
        keys = pd.DataFrame({"STD_YM": ["202507", "202509"], "BLOCK_CD": ["11230x"] * 2,
                             "X_COORD": [1., 1.], "Y_COORD": [2., 2.]})

        def fake_load(kind, metrics):
            table = keys.copy()
            for col in metrics:
                table[col] = [1., 2.]
            return table

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "telecom.csv"
            with patch.object(telecom, "load_files", side_effect=fake_load), patch.object(telecom, "OUTPUT_FILE", output):
                telecom.main()
            result = pd.read_csv(output)
        for code in AGES:
            self.assertTrue(result[f"FLOW_POP_DIFF_{code}"].isna().all())
            self.assertTrue(result[f"FLOW_POP_PCT_{code}"].isna().all())
        self.assertEqual(result.shape, (2, 42))


def sample(months, total, candidate, held):
    return pd.DataFrame({"월": months, "지역": ["테스트지역"] * len(months),
                         "연령대": ["20대"] * len(months), "카드1_전체_결제건수": total,
                         "카드1_외식·카페_결제건수": candidate,
                         "카드1_문화·오락_결제건수": [0] * len(months),
                         "카드1_운동_결제건수": [0] * len(months),
                         "카드1_해석보류_결제건수": held,
                         "카드1_미분류_결제건수": [0] * len(months)})


class IndustrySensitivityTests(unittest.TestCase):
    def test_denominator_changes_share_without_changing_activity_count(self):
        result = make_scenarios(sample(["202507", "202508"], [100, 100], [20, 25], [40, 10]))
        base = result[result["비교안"] == "현재기준"].reset_index(drop=True)
        known = result[result["비교안"] == "보류제외분모"].reset_index(drop=True)
        self.assertAlmostEqual(base.loc[1, "건수전월변화율"], 0.25)
        self.assertAlmostEqual(known.loc[1, "건수전월변화율"], 0.25)
        self.assertGreater(base.loc[1, "비중전월차이"], 0)
        self.assertLess(known.loc[1, "비중전월차이"], 0)

    def test_all_held_leaves_known_share_missing(self):
        result = make_scenarios(sample(["202507"], [100], [0], [100]))
        self.assertTrue(result.loc[result["비교안"] == "보류제외분모", "후보비중"].isna().all())
        self.assertEqual(result.loc[result["비교안"] == "현재기준", "분모건수"].iloc[0], 100)

    def test_nonadjacent_month_does_not_produce_change(self):
        result = make_scenarios(sample(["202507", "202509"], [100, 100], [20, 25], [40, 10]))
        self.assertTrue(result["건수전월변화율"].isna().all())
        self.assertTrue(result["비중전월차이"].isna().all())


class ModelInputReviewTests(unittest.TestCase):
    def test_regional_correlation_counts_contexts_once(self):
        rows = []
        for month, value in [("202507", 1), ("202508", 2), ("202509", 3)]:
            for age in ["10대", "20대", "30대", "40대", "50대", "60대이상"]:
                rows.append({"월": month, "지역": "테스트지역", "연령대": age,
                             "a": value, "b": value * 2})
        registry = pd.DataFrame({"특징": ["a", "b"], "관측단위": [REGION_SCOPE] * 2, "숫자열": [True] * 2})
        result = correlation_review(pd.DataFrame(rows), registry)
        self.assertEqual(result.loc[0, "비교행수"], 3)
        self.assertAlmostEqual(result.loc[0, "피어슨상관"], 1)

    def test_unknown_feature_requires_review(self):
        with self.assertRaises(ValueError):
            feature_rule("새로운_위험관련_특징")


if __name__ == "__main__":
    unittest.main()
