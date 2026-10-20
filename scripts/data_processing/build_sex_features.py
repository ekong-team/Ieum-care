"""원본 남녀 구분으로 특징144건을 만들고 기존 합산72건과 대조한다. 원본은 변경하지 않는다."""
import argparse
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/data_processing"))
from data_contract import AGES as SOURCE_AGES, MONTHS, require_keys, require_numbers
from industry_classification import classify_industries
from ai.analysis_agent.inputs import file_hash
from ai.analysis_agent.policy import REGIONS, AGES, CARD, MOVEMENT, FILTERED, age_code

KEYS = ["월", "지역", "연령대", "성별"]
LOCATION = ["BLOCK_CD", "X_COORD", "Y_COORD"]
SEX_MAP = {"남성": "male", "여성": "female"}
SEX_LABEL = {"male":"남성", "female":"여성", "all":"전체"}
EXCLUDED = ("실내/실외골프장", "종합레저타운/놀이동산")
CANDIDATES = ("외식·카페", "문화·오락", "운동")

def summarize_card(raw):
    """법인을 제외하고 남녀를 섞지 않은 전체/업종 제외 건수와 특성을 계산한다."""
    columns = ["TA_YMD","MCT_SGG_CD","MCT_RY_CD","SEX_CCD","AGE_CCD","USE_CNT"]
    if not set(columns) <= set(raw):
        raise ValueError("카드 필수 열 누락")
    if not raw["SEX_CCD"].isin([*SEX_MAP, "법인"]).all():
        raise ValueError("카드 원본의 성별 코드를 확인해야 합니다.")
    corporate = raw["SEX_CCD"].eq("법인")
    if not corporate.eq(raw["AGE_CCD"].eq("법인")).all():
        raise ValueError("법인 표시 불일치")
    card = raw.loc[~corporate, columns].copy()
    card["월"] = pd.to_datetime(card["TA_YMD"],format="%Y%m%d",errors="raise").dt.strftime("%Y%m")
    card["지역"] = card["MCT_SGG_CD"]
    card["성별"] = card["SEX_CCD"].map(SEX_MAP)
    card["연령대"] = card["AGE_CCD"].str.replace(" ","",regex=False).replace(
        {str(age)+"대":"60대이상" for age in (60,70,80,90)})
    if not card["지역"].isin(REGIONS).all() or not card["연령대"].isin(AGES).all():
        raise ValueError("카드 지역·연령 범위 불일치")
    require_numbers(card,["USE_CNT"],"성별 카드",integer=True)
    card["filtered_count"] = card["USE_CNT"].where(~card["MCT_RY_CD"].isin(EXCLUDED),0)
    names = card["MCT_RY_CD"].drop_duplicates().tolist()
    mapping = dict(zip(names, classify_industries(pd.Series(names))))
    card["industry"] = card["MCT_RY_CD"].map(mapping)
    counts = card.groupby(KEYS,as_index=False)[["USE_CNT","filtered_count"]].sum()
    counts = counts.sort_values(["지역","연령대","성별","월"]).reset_index(drop=True)
    counts["days"] = pd.to_datetime(counts["월"],format="%Y%m").dt.days_in_month
    groups = counts.groupby(["지역","연령대","성별"])
    adjacent = pd.to_datetime(counts["월"],format="%Y%m").dt.to_period("M").astype("int64").groupby(
        [counts[key] for key in ("지역","연령대","성별")]).diff().eq(1)
    for col, out in (("USE_CNT","daily_change"),("filtered_count","filtered_change")):
        counts["daily_"+col] = counts[col]/counts["days"]
        before = groups["daily_"+col].shift()
        counts[out] = (counts["daily_"+col]/before.where(before.gt(0))-1).where(adjacent)
    counts["prior3"] = groups["daily_USE_CNT"].transform(lambda values: values.shift().rolling(3,min_periods=3).mean())
    counts["prior3_change"] = counts["daily_USE_CNT"]/counts["prior3"].where(counts["prior3"].gt(0))-1
    regional = counts.groupby(["월","지역","성별"],as_index=False)["USE_CNT"].sum().sort_values(["지역","성별","월"])
    regional["daily"] = regional["USE_CNT"]/pd.to_datetime(regional["월"],format="%Y%m").dt.days_in_month
    prior = regional.groupby(["지역","성별"])["daily"].shift()
    regional["regional_change"] = regional["daily"]/prior.where(prior.gt(0))-1
    counts = counts.merge(regional[["월","지역","성별","regional_change"]],on=["월","지역","성별"],validate="many_to_one")
    industries = card.groupby(KEYS+["industry"])["USE_CNT"].sum().unstack("industry")
    grid = pd.MultiIndex.from_frame(counts[KEYS])
    candidates = industries.reindex(grid).reindex(columns=CANDIDATES,fill_value=0).fillna(0)
    candidates.index = counts.index
    changes = []
    for col in CANDIDATES:
        current = candidates[col]/counts["days"]
        before = current.groupby([counts[key] for key in ("지역","연령대","성별")]).shift()
        changes.append((current/before.where(before.gt(0))-1).where(adjacent).to_numpy())
    array = np.column_stack(changes)
    counts["candidate_available"] = np.isfinite(array).sum(axis=1)
    counts["candidate_declines"] = np.where(counts["candidate_available"].eq(3),(array <= -.03).sum(axis=1),np.nan)
    return counts

def summarize_telecom(monthly, aggregate):
    """각 성별/연령의 현재·전월 공통 위치 합계로 변화율을 계산한다."""
    records = []
    reference = aggregate.groupby(["월","지역"])[["통신_전체관측위치수","통신_연령관측위치수"]].first()
    for region in REGIONS:
        previous = None
        for month in sorted(monthly):
            current = monthly[month].loc[monthly[month]["지역"].eq(region)].copy()
            if current.empty:
                raise ValueError("통신 대상 지역 관측 없음")
            location_count = len(current)
            expected = reference.loc[(month,region)]
            if location_count != expected["통신_연령관측위치수"]:
                raise ValueError("원본 AGE 위치 수와 기존 관측 수가 다릅니다.")
            pair = None if previous is None else current.merge(previous,on=LOCATION,suffixes=("_now","_prior"),validate="one_to_one")
            for age_code, age in SOURCE_AGES.items():
                for source_sex, sex in (("MAN","male"),("WMAN","female")):
                    column = f"{source_sex}_FLOW_POP_CNT_{age_code}"
                    before = np.nan if pair is None else pair[column+"_prior"].sum(min_count=1)
                    change = np.nan if pd.isna(before) or before <= 0 else pair[column+"_now"].sum()/before-1
                    records.append(dict(월=month,지역=region,연령대=age,성별=sex,
                        통신_연령유동량=current[column].sum(min_count=1),
                        통신_연령유동량_전월변화율=change,
                        통신_연령관측률=location_count/expected["통신_전체관측위치수"],
                        통신_전월공통위치비율=np.nan if pair is None else len(pair)/location_count))
            previous = current
    return pd.DataFrame(records)

def build(output, raw_folder=ROOT/"data/raw"):
    output.mkdir(parents=True,exist_ok=True)
    aggregate_path = ROOT/"data/processed/risk_features.csv"
    sensitivity_path = ROOT/"data/processed/eda/card/golf_leisure_sensitivity.csv"
    packet_path = ROOT/"data/processed/submission_data_review_20261015/analysis_with_population_calendar.json"
    population_path = ROOT/"data/processed/external_context_20261015/population_age_sex.csv"
    aggregate = pd.read_csv(aggregate_path,dtype={"월":str})
    source_files = [aggregate_path,sensitivity_path,packet_path,population_path]
    monthly = {}
    columns = [f"{sex}_FLOW_POP_CNT_{age}" for sex in ("MAN","WMAN") for age in SOURCE_AGES]
    for month in MONTHS:
        path = raw_folder/f"flow_age_pop_{month}.csv"
        source_files.append(path)
        table = pd.read_csv(path,sep="|",dtype={"STD_YM":str,"BLOCK_CD":str})
        table = table.drop_duplicates().copy()
        require_keys(table,["STD_YM",*LOCATION],path.name)
        require_numbers(table,["X_COORD","Y_COORD",*columns],path.name)
        if not table["STD_YM"].eq(month).all():
            raise ValueError("통신 파일 기준월 불일치")
        table["지역"] = table["BLOCK_CD"].str[:5].map({value[1]:key for key,value in REGIONS.items()})
        monthly[month] = table.loc[table["지역"].notna(),["STD_YM",*LOCATION,"지역",*columns]]
    telecom = summarize_telecom(monthly,aggregate)
    card_path = raw_folder/"신한카드_빅콘테스트2026_데이터1.txt"
    source_files.append(card_path)
    raw_card = pd.read_csv(card_path,sep="\t",encoding="cp949",dtype=str,
        usecols=["TA_YMD","MCT_SGG_CD","MCT_RY_CD","SEX_CCD","AGE_CCD","USE_CNT"])
    card = summarize_card(raw_card)
    sex = card.merge(telecom,on=KEYS,how="outer",validate="one_to_one",indicator=True)
    if not sex["_merge"].eq("both").all():
        raise ValueError("성별 카드·통신 집단 불일치")
    expected = {(m,r,a,s) for m in MONTHS for r in REGIONS for a in AGES for s in ("male","female")}
    if set(map(tuple,sex[KEYS].to_numpy())) != expected:
        raise ValueError("성별144개 집단 누락/추가")
    reconciled = sex.groupby(KEYS[:3])[["USE_CNT","통신_연령유동량"]].sum()
    base = aggregate.set_index(KEYS[:3]).loc[reconciled.index]
    if not np.array_equal(reconciled["USE_CNT"].to_numpy(),base[CARD].to_numpy()):
        raise ValueError("남녀 카드 합계가 기존 합산과 다릅니다.")
    if not np.allclose(reconciled["통신_연령유동량"],base["통신_연령유동량"],rtol=1e-12,atol=1e-6):
        raise ValueError("남녀 통신 유동량 합계가 기존 합산과 다릅니다.")
    sex[CARD] = sex["USE_CNT"]
    feature_columns = [*KEYS,CARD,MOVEMENT,"통신_연령관측률","통신_전월공통위치비율"]
    original = aggregate.assign(성별="all")
    combined = pd.concat([original[feature_columns],sex[feature_columns]],ignore_index=True)
    combined.to_csv(output/"features.csv",index=False,encoding="utf-8-sig")
    old_sensitivity = pd.read_csv(sensitivity_path,dtype={"월":str}).assign(성별="all")
    new_sensitivity = sex[KEYS+["daily_change","filtered_change"]].rename(columns={
        "daily_change":"일평균_결제건수_전월변화율_전체","filtered_change":FILTERED})
    pd.concat([old_sensitivity,new_sensitivity],ignore_index=True).to_csv(output/"sensitivity.csv",index=False,encoding="utf-8-sig")
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    aggregate_context = {(r["analysis_evidence"]["월"],r["analysis_evidence"]["지역"],r["analysis_evidence"]["연령대"]):r
                         for r in packet["records"]}
    population = pd.read_csv(population_path,dtype={"month":str})
    population["age_group"] = population["age_group"].str.replace(" ","",regex=False)
    population["sex"] = population["sex"].map({"전체":"all",**SEX_MAP})
    require_keys(population,["month","region","age_group","sex"],"성별 인구")
    pop = population.set_index(["month","region","age_group","sex"])["population"].to_dict()
    for _,row in sex.iterrows():
        month,region,age,gender = (row[key] for key in KEYS)
        aid = month+"_"+REGIONS[region][1]+"_"+age_code(age)+"_"+gender
        matching = aggregate_context[(month,region,age)]
        current = pop[(month[:4]+"-"+month[4:],REGIONS[region][0],age,gender)]
        previous_month = str(pd.Period(month,freq="M")-1)
        previous = pop[(previous_month,REGIONS[region][0],age,gender)]
        packet["records"].append(dict(analysis_id=aid,analysis_evidence=dict(
            월=month,지역=region,연령대=age,성별=gender,
            소비_일평균건수_전월변화율=row["daily_change"],
            통신_연령유동량_전월변화율=row[MOVEMENT],
            과거3개월대비변화율=row["prior3_change"],
            지역전체_소비전월변화율=row["regional_change"],
            소비_지역전체대비차이=row["daily_change"]-row["regional_change"],
            후보업종_비교가능수=int(row["candidate_available"]),
            후보업종_감소수_3퍼센트=row["candidate_declines"],
            업종민감도주의=None),
            resident_population=int(current),prior_resident_population=int(previous),
            population_mom_change=None if previous<=0 else float(current/previous-1),
            calendar_context=matching["calendar_context"]))
    # Pandas 결측을 표준 JSON null로 변환한다.
    packet["records"] = json.loads(pd.DataFrame(packet["records"]).to_json(orient="records",force_ascii=False))
    for record in packet["records"]:
        evidence = record["analysis_evidence"]
        for key,value in list(evidence.items()):
            if isinstance(value,float) and not np.isfinite(value): evidence[key]=None
    packet["sex_extension"] = dict(source_codes={"telecom":{"MAN":"male","WMAN":"female"},"card":SEX_MAP},
        warning="성별별 통신·카드도 동일 개인 결합이 아님. 시간/요일은 성별별 관측이 아님.")
    (output/"context.json").write_text(json.dumps(packet,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    sex[KEYS+["USE_CNT","filtered_count","통신_연령유동량","daily_change",MOVEMENT]].to_csv(output/"sex_measurements.csv",index=False,encoding="utf-8-sig")
    manifest = dict(schema_version="sex-preprocessing-v1",status="passed",aggregate_records=72,sex_records=len(sex),combined_records=len(combined),
        script_sha256=file_hash(Path(__file__)),
        card_sex_sum_matches=True,telecom_sex_sum_matches=True,
        sources=[dict(path=str(path.relative_to(ROOT)),sha256=file_hash(path)) for path in source_files],
        outputs={name:file_hash(output/name) for name in ("features.csv","sensitivity.csv","context.json","sex_measurements.csv")})
    (output/"sex_preprocessing_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"data/processed/analysis_inputs")
    args = parser.parse_args()
    result = build(args.output)
    print(json.dumps({key:value for key,value in result.items() if key not in ("sources","outputs")},ensure_ascii=False,indent=2))
