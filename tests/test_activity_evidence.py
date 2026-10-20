import importlib.util
from pathlib import Path
import unittest
import pandas as pd

spec = importlib.util.spec_from_file_location('evidence', Path(__file__).resolve().parents[1]/'ai/risk_model/build_activity_evidence.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BaselineTests(unittest.TestCase):
    def frame(self, months, values):
        return pd.DataFrame({'월':months,'지역':'지역','연령대':'30대','value':values})

    def test_no_current_or_future_leakage(self):
        d = module.prior_baseline(self.frame(['202507','202508','202509','202510','202511'],[10,20,30,1000,5000]), 'value')
        self.assertEqual(d.iloc[3]['과거3개월평균'],20)
        self.assertTrue(d.iloc[:3]['과거3개월평균'].isna().all())

    def test_gap_and_zero_are_missing(self):
        d = module.prior_baseline(self.frame(['202507','202508','202510','202511'],[1,2,3,4]), 'value')
        self.assertTrue(d['과거3개월대비변화율'].isna().all())
        d = module.prior_baseline(self.frame(['202507','202508','202509','202510'],[0,0,0,10]), 'value')
        self.assertTrue(d['과거3개월대비변화율'].isna().all())

    def test_year_boundary(self):
        d = module.prior_baseline(self.frame(['202511','202512','202601','202602'],[10,10,10,5]), 'value')
        self.assertEqual(d.iloc[3]['과거3개월대비변화율'],-.5)


if __name__ == '__main__':
    unittest.main()
