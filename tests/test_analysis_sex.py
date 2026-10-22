"""남녀 집계를 섞지 않는지와 현지 전달에서 성별이 보존되는지 확인한다."""
import copy
import unittest
import json
from pathlib import Path
from decimal import Decimal
from pydantic import ValidationError
from ai.analysis_agent.assessment import assess
from ai.analysis_agent.workflow import run_analysis
from ai.analysis_agent.priority import priority_for
from ai.analysis_agent.agent import to_welfare_request,WelfareRequest02
from tests.test_analysis_agent import rows

def sex_rows(sex, cards, movement, filtered=None):
    result = rows(["202507","202508","202509"],cards,movement,filtered)
    for row in result:
        row["sex"] = sex
    return result

class SexAnalysisTests(unittest.TestCase):
    def data(self):
        return (sex_rows("male",[3100,2700,2400],[None,-.1,-.1],[None,-.1,-.1])
                + sex_rows("female",[3100,3200,3300],[None,.01,.01],[None,.01,.01]))

    def bundle(self):
        return run_analysis(self.data(),{},[],period="202509")

    def test_male_female_history_and_ids_are_independent(self):
        result = assess(self.data())
        last = {r["sex"]:r for r in result if r["month"]=="202509"}
        self.assertEqual(last["male"]["level"],5)
        self.assertEqual(last["female"]["level"],1)
        self.assertEqual(len({r["analysis_id"] for r in result}),6)
        self.assertTrue(last["male"]["analysis_id"].endswith("_male"))

    def test_existing_sixty_code_is_preserved(self):
        data = sex_rows("female",[3100,3200,3300],[None,.01,.01])
        for row in data: row["age"]="60대이상"
        self.assertEqual(assess(data)[-1]["analysis_id"],"202509_32010_60GU_female")

    def test_parent_and_children_have_separate_priority_lists(self):
        combined = self.data()+rows(["202507","202508","202509"],[3100,3200,3300],[None,.01,.01])
        bundle = run_analysis(combined,{},[],period="202509")
        self.assertEqual(bundle["priority_review"]["scope"]["sexes"],["male","female"])
        self.assertEqual(len(bundle["priority_review"]["ranked_cohorts"]),2)
        self.assertEqual(len(bundle["aggregate_priority_review"]["ranked_cohorts"]),1)
        with self.assertRaisesRegex(ValueError,"섞을"):
            priority_for(bundle["cohorts"],"202509",sexes=("all","male"))

    def test_unknown_sex_is_rejected(self):
        bad=self.data()
        bad[0]["sex"]="unknown"
        with self.assertRaisesRegex(ValueError,"성별"):
            assess(bad)

    def test_gender_context_cannot_be_reused_for_other_gender(self):
        aid=assess(self.data())[0]["analysis_id"]
        record=next(r for r in assess(self.data()) if r["analysis_id"]==aid)
        context={aid:dict(analysis_evidence={"월":record["month"],"지역":record["region"],
                         "연령대":record["age"],"성별":"male" if record["sex"]=="female" else "female"})}
        with self.assertRaisesRegex(ValueError,"identity"):
            run_analysis(self.data(),context,[],period="202509")

    def test_request_preserves_sex_and_native_identity(self):
        for cohort in self.bundle()["cohorts"]:
            request=to_welfare_request(cohort)
            self.assertEqual(request["target"]["sex"],cohort["assessment"]["sex"])
            self.assertEqual(request["risk_assessment"]["sex"],request["target"]["sex"])
            self.assertEqual(request["risk_assessment"]["assessment_id"],cohort["analysis_id"])
            self.assertEqual(request["confirmed_support_needs"],[])

    def test_native_request_requires_sex(self):
        payload=to_welfare_request(self.bundle()["cohorts"][0])
        payload["target"].pop("sex")
        with self.assertRaises(ValidationError):
            WelfareRequest02.model_validate(payload)

    def test_request_rejects_mismatched_sex(self):
        payload=to_welfare_request(self.bundle()["cohorts"][0])
        payload["risk_assessment"]["sex"]="all"
        with self.assertRaisesRegex(ValidationError,"성별"):
            WelfareRequest02.model_validate(payload)



    def test_native_schema_rejects_float_age_and_non_bool_example(self):
        original=to_welfare_request(self.bundle()["cohorts"][0])
        for key,value in (("age_group",30.0),("is_example",1)):
            payload=copy.deepcopy(original)
            payload["risk_assessment"][key]=value
            with self.assertRaises(ValidationError):
                WelfareRequest02.model_validate(payload)



try:
    import pandas as pd
except ImportError:
    pd=None

@unittest.skipIf(pd is None,"원본 집계 검사는 분석 환경의 pandas가 필요")
class SexSourceTests(unittest.TestCase):
    def test_card_source_sex_mapping_and_corporate_exclusion(self):
        from scripts.data_processing.build_sex_features import summarize_card
        raw=pd.DataFrame([
            dict(TA_YMD="20250701",MCT_SGG_CD="강원 춘천시",MCT_RY_CD="가구",SEX_CCD="남성",AGE_CCD="30 대",USE_CNT="10"),
            dict(TA_YMD="20250701",MCT_SGG_CD="강원 춘천시",MCT_RY_CD="실내/실외골프장",SEX_CCD="여성",AGE_CCD="30 대",USE_CNT="20"),
            dict(TA_YMD="20250701",MCT_SGG_CD="강원 춘천시",MCT_RY_CD="가구",SEX_CCD="법인",AGE_CCD="법인",USE_CNT="100"),
        ])
        result=summarize_card(raw).set_index("성별")
        self.assertEqual(result.loc["male","USE_CNT"],10)
        self.assertEqual(result.loc["female","USE_CNT"],20)
        self.assertEqual(result.loc["female","filtered_count"],0)

    def test_common_locations_are_used_for_each_gender(self):
        from scripts.data_processing.build_sex_features import summarize_telecom
        from ai.analysis_agent.inputs import REGIONS
        age_codes=["10G","20G","30G","40G","50G","60GU"]
        monthly,reference={},[]
        for month in ("202511","202512"):
            table=[]
            for region,(_,code) in REGIONS.items():
                row=dict(STD_YM=month,BLOCK_CD=code+"001",X_COORD=100,Y_COORD=200,지역=region)
                for age in age_codes:
                    row["MAN_FLOW_POP_CNT_"+age]=100 if month=="202511" else 90
                    row["WMAN_FLOW_POP_CNT_"+age]=200 if month=="202511" else 210
                table.append(row)
                reference.append(dict(월=month,지역=region,통신_전체관측위치수=2,통신_연령관측위치수=1))
            monthly[month]=pd.DataFrame(table)
        result=summarize_telecom(monthly,pd.DataFrame(reference))
        target=result.loc[result.월.eq("202512")&result.지역.eq("강원 춘천시")&result.연령대.eq("30대")].set_index("성별")
        self.assertAlmostEqual(target.loc["male","통신_연령유동량_전월변화율"],-.1)
        self.assertAlmostEqual(target.loc["female","통신_연령유동량_전월변화율"],.05)
        self.assertEqual(target["통신_연령유동량"].sum(),300)

if __name__=="__main__":
    unittest.main()
