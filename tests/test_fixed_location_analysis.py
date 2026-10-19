import sys
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/data_processing'))
from finish_analysis import fixed_location_comparison
from data_contract import AGES,REGIONS
from build_activity_levels import MOVE


class FixedLocationTests(unittest.TestCase):
    def inputs(self):
        rows=[];keys=[]
        for prefix,region in REGIONS.items():
            for i,month in enumerate(['202507','202508']):
                for loc in [1,2]:
                    rows.append({'STD_YM':month,'BLOCK_CD':prefix+str(loc),'X_COORD':loc,'Y_COORD':loc,
                        **{f'FLOW_POP_{age}':(10 if loc==1 else 100)*(1+i) for age in AGES}})
                for age in AGES.values():keys.append({'월':month,'지역':region,'연령대':age,MOVE:np.nan if i==0 else 1,'활동위축단계':np.nan if i==0 else 1})
        return pd.DataFrame(rows),pd.DataFrame(keys)

    def test_missing_location_not_zero_filled(self):
        telecom,levels=self.inputs()
        telecom.loc[telecom['STD_YM'].eq('202508')&telecom['X_COORD'].eq(2),'FLOW_POP_10G']=np.nan
        result=fixed_location_comparison(telecom,levels,['202507','202508'])
        self.assertTrue(result['고정위치수'].eq(1).all())
        self.assertTrue(result.loc[result['월'].eq('202508'),'고정위치_전월변화율'].eq(1).all())
        self.assertTrue(result.loc[result['월'].eq('202507'),'고정위치_전월변화율'].isna().all())

    def test_zero_base_unavailable(self):
        telecom,levels=self.inputs()
        telecom.loc[telecom['STD_YM'].eq('202507'),'FLOW_POP_10G']=0
        result=fixed_location_comparison(telecom,levels,['202507','202508'])
        ten=result.loc[result['연령대'].eq('10대')]
        self.assertTrue(ten['고정위치_7월대비지수'].isna().all())
        self.assertTrue(ten['고정위치_전월변화율'].isna().all())

    def test_missing_month_rejected(self):
        telecom,levels=self.inputs()
        with self.assertRaises(ValueError):
            fixed_location_comparison(telecom.loc[telecom['STD_YM'].eq('202507')],levels,['202507','202508'])


if __name__=='__main__':unittest.main()
