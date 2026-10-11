"""해석 불확실한 거래를 삭제하거나 분모 변화와 활동 변화를 혼동하지 않는지 확인."""
from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "data_processing"))
from analyze_industry_sensitivity import make_scenarios


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


if __name__ == "__main__":
    unittest.main()
