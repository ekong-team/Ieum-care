import sys
from pathlib import Path
import unittest
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ai/risk_model'))
from build_activity_levels import classify, MOVE, SPEND, ROBUST


class ActivityLevelsTests(unittest.TestCase):
    def data(self, months, values, robust=None):
        return pd.DataFrame({'월':months,'지역':'강원 춘천시','연령대':'30대',
            MOVE:values,SPEND:values,ROBUST:values if robust is None else robust,
            '통신_전월공통위치비율':.95,'통신_연령관측률':.8})

    def test_all_five_stages_and_missing(self):
        d=self.data(['202507','202508','202509','202510','202511','202512'],
                    [None,0,-.03,-.03,-.05,0])
        d.loc[5,SPEND]=-.03
        result=classify(d)['활동위축단계']
        self.assertTrue(pd.isna(result.iloc[0]))
        self.assertEqual(result.iloc[1:].tolist(),[1,3,4,5,2])

    def test_missing_month_breaks_persistence(self):
        self.assertEqual(classify(self.data(['202508','202510'],[-.06,-.06]))['활동위축단계'].tolist(),[3,3])

    def test_low_coverage_blocks_and_breaks_persistence(self):
        d=self.data(['202508','202509','202510'],[-.06]*3)
        d.loc[1,'통신_연령관측률']=.7
        result=classify(d)['활동위축단계']
        self.assertTrue(pd.isna(result.iloc[1]))
        self.assertEqual(result.iloc[2],3)

    def test_industry_fragility_prevents_level_five(self):
        d=self.data(['202508','202509'],[-.06,-.06],[-.01,-.04])
        result=classify(d)
        self.assertEqual(result['활동위축단계'].tolist(),[3,4])
        self.assertTrue(result['업종민감도주의'].iloc[1])


if __name__=='__main__': unittest.main()
