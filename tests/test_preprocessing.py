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


if __name__ == "__main__":
    unittest.main()
