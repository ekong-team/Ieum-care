"""지역 공통값 반복을 표본 증가로 오해하거나 새 특징을 임의 채택하지 않는지 확인."""
from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "data_processing"))
from audit_model_inputs import REGION_SCOPE, correlation_review, feature_rule


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
