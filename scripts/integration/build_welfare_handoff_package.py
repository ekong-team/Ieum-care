"""성별 분석 결과와 현지 입력 제안을 전달용 ZIP으로 만든다. 메시지·API 전송은 하지 않는다."""
import argparse
import csv
from collections import Counter
from pathlib import Path
import json
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ai.analysis_agent.welfare_handoff import handoff_record,to_current_aggregate_request,WelfareRequest02
from ai.analysis_agent.inputs import file_hash
from ai.contracts.profile import TargetProfile
from scripts.integration.verify_analysis_agent import latest_folder,verify
from scripts.integration.check_welfare_handoff import check_package

HYEONJI_SHA="53b9619"

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

def build(results_root,output_root):
    analysis_folder=latest_folder(results_root)
    verification=verify(analysis_folder)
    bundle=json.loads((analysis_folder/"analysis_bundle.json").read_text(encoding="utf-8"))
    records=[handoff_record(cohort) for cohort in bundle["cohorts"]]
    folder=output_root/bundle["bundle_hash"][:16]
    folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/"data/handoff_records.json",records)
    write_json(folder/"data/analysis_bundle.json",bundle)
    write_json(folder/"data/priority_sex.json",bundle["priority_review"])
    write_json(folder/"data/priority_aggregate.json",bundle["aggregate_priority_review"])
    write_json(folder/"data/analysis_verification.json",verification)
    receiver_check=results_root/"current_receiver_contract_check.json"
    if receiver_check.exists():
        receiver_record=json.loads(receiver_check.read_text(encoding="utf-8"))
        if receiver_record.get("analysis_bundle_hash")==bundle["bundle_hash"]:
            write_json(folder/"data/current_receiver_contract_check.json",receiver_record)
    write_json(folder/"contracts/welfare_risk_input_0_2.schema.json",WelfareRequest02.model_json_schema())
    write_json(folder/"contracts/target_profile.schema.json",TargetProfile.model_json_schema())
    for cohort in bundle["cohorts"]:
        write_json(folder/"profiles"/(cohort["analysis_id"]+".json"),cohort["profile"])
    chosen={}
    for name,aid in (
        ("female_complete","202512_32010_30G_female"),
        ("male_complete","202512_32010_40G_male"),
        ("female_three","202512_32010_40G_female"),
        ("held","202507_32010_30G_female"),
    ):
        cohort=next(c for c in bundle["cohorts"] if c["analysis_id"]==aid)
        write_json(folder/"examples"/(name+"_proposed_request.json"),handoff_record(cohort)["request_v02"])
        chosen[name]=cohort
    partial=next(c for c in bundle["cohorts"] if c["assessment"]["sex"]!="all" and c["assessment"]["status"]=="partial")
    write_json(folder/"examples/partial_proposed_request.json",handoff_record(partial)["request_v02"])
    aggregate=next(c for c in bundle["cohorts"] if c["analysis_id"]=="202512_32010_30G")
    write_json(folder/"examples/current_offline_aggregate_request.json",dict(mode="offline",**to_current_aggregate_request(aggregate)))
    for path in [
        *sorted((ROOT/"ai/analysis_agent").glob("*.py")),
        ROOT/"ai/contracts/profile.py",ROOT/"ai/contracts/causes.py",
        ROOT/"scripts/integration/check_welfare_handoff.py",
        ROOT/"requirements-agent.txt",
    ]:
        relative=path.relative_to(ROOT)
        destination=folder/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)
    table=["|지역·연령|합산|남성|여성|","|---|---:|---:|---:|"]
    for region in ("춘천시","강남구"):
        for age in (10,20,30,40,50,60):
            matched={c["profile"]["target"]["sex"]:c["assessment"]["level"] for c in bundle["cohorts"]
                if c["profile"]["period"]=="2025-12" and c["profile"]["target"]["region"]==region and c["profile"]["target"]["age_group"]==age}
            table.append(f"|{region} {str(age)+'대' if age<60 else '60세 이상'}|{matched['all']}|{matched['male']}|{matched['female']}|")
    gender=[c for c in bundle["cohorts"] if c["assessment"]["sex"]!="all"]
    comparisons={}
    for cohort in bundle["cohorts"]:
        a=cohort["assessment"]
        key=(a["month"],a["region"],a["age"])
        comparisons.setdefault(key,{})[a["sex"]]=a
    comparison_rows=[]
    for (month,region,age),members in sorted(comparisons.items()):
        row=dict(month=month,region=region,age=age)
        for sex in ("all","male","female"):
            for key in ("level","status","card_change","movement_change"):
                row[sex+"_"+key]=members[sex][key]
        row["both_sexes_complete"]=all(members[sex]["status"]=="complete" for sex in ("male","female"))
        row["different_complete_levels"]=members["male"]["level"]!=members["female"]["level"] if row["both_sexes_complete"] else None
        comparison_rows.append(row)
    with (folder/"data/sex_comparison.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(comparison_rows[0]))
        writer.writeheader()
        writer.writerows(comparison_rows)
    distribution=Counter(str(c["assessment"]["level"]) for c in gender)
    status=Counter(c["assessment"]["status"] for c in gender)
    summary=(
        "# 한수 담당 성별 분석 결과\n\n"
        "남녀 합산72건을 보존하고 남녀별144건을 추가해 총216건을 만들었다. "
        "성별별 결과는 같은 개인의 통신·카드 결합이 아니며 고립 확정이 아닌 활동 위축 검토다.\n\n"
        "원본 MAN/WMAN과 남성/여성을 male/female로 명시 변환했다. 법인은 제외했고 60세 이상은60GU로 통합했다. "
        "남녀 결제건수 합계는 기존 합산에 정확히 일치하고, 유동량 합계도 수치 오차 범위에서 일치함을 검증했다. "
        "남녀 변화율을 단순 평균해 합산하지 않는다. 통신은 성별별 공통 위치 비교, 카드는 성별별 일평균으로 재계산했다.\n\n"
        f"남녀144건 단계 분포: {dict(distribution)}. 판정 상태: {dict(status)}.\n\n"
        "## 12월 비교\n\n"+"\n".join(table)+"\n\n"
        "합산4단계였던 춘천40대는 남성4·여성3으로 나뉜다. 여성의 현재 감소가 작아서가 아니라 지속 조건이 다르기 때문이다. "
        "강남20대는 합산1·남성2·여성1이며 남성 유동량이3% 경계에 가깝다는 민감도를 함께 봐야 한다. "
        "차이를 성별 자체의 고립 원인이나 통계적으로 입증된 위험 차이라고 해석하지 않는다.\n\n"
        "남녀24개 집단의1차 순위와 합산12개 집단의 비교 순위를 분리했다. "
        "남녀 목록의 공동1순위는 춘천30대 남녀·40대 남성이다. 복지자원 기준2차 판단은 포함하지 않는다.\n\n"
        "원인 가설·수치 근거·배경·민감도는 data/handoff_records.json과 analysis_bundle.json에 있다. "
        f"이 실행의 실제 모델 응답 수는 {bundle['execution']['confirmed_llm_responses']}회다. 원본·좌표별 파일·API키는 이 묶음에 없다.\n"
    )
    (folder/"분석결과_설명.md").write_text(summary,encoding="utf-8")
    readme=(
        "# 현지에게 전달하는 분석 입력 묶음\n\n"
        "이 ZIP의 risk-input-0.2는 한수가 기준으로 확정한 출력 계약이다. 현지 추천 수신부가 이 형식에 맞춘다. 외부API를 실행하지 않는다.\n\n"
        "## 먼저 볼 파일\n\n"
        "1. 분석결과_설명.md: 내가 맡은 분석 범위·결과·한계.\n"
        "2. examples/female_complete_proposed_request.json: 성별을 보존한 기준 입력. 파일명의 proposed는 이전 식별자다.\n"
        "3. contracts/welfare_risk_input_0_2.schema.json: 기준 입력의 검사 규칙.\n"
        "4. data/handoff_records.json: 집단별 입력과 상세 근거 전체216건.\n"
        "5. ai/analysis_agent/welfare_handoff.py: 분석 결과를 추천 입력으로 바꾸는 함수.\n\n"
        "## 현재 코드와 맞춰야 하는 부분\n\n"
        f"확인 기준 main 병합 커밋 {HYEONJI_SHA}. "
        "현재 risk-input-0.1은 target.sex/risk_assessment.sex를 받지 않는다. "
        "따라서 proposed_request 파일을 현재 서버에 그대로 넣으면 거부되는 것이 정상이다. "
        "risk-input-0.2를 한수 출력 기준으로 확정했다. 이 문구가 수신부의 적용 완료를 뜻하지는 않는다. 수신부 변경은 현지 담당이다.\n\n"
        "- target.sex를 all/male/female 필수값으로 받고 risk_assessment.sex와 일치하는지 검사하기.\n"
        "- risk_assessment의 schema_version을 risk-input-0.2로 받고 지역·연령·성별·기준월·상태를 보존하기.\n"
        "- 모델 입력과 추천 응답·선택파일에서도 성별을 유지하기. 성별이 다르면 같은 추천 실행으로 취급하지 않기.\n"
        "- 성별이 같다는 이유로 경제·정서·건강 욕구를 만들어내지 않기. confirmed_support_needs는 확인 전 빈 목록.\n"
        "- 복지자원의 성별 자격은 공식 출처에 따라 확인하기. 분석 대상의 성별만으로 자격을 확정하지 않기.\n"
        "- 분석10대는10~19세인데 현재 추천10구간은0~19세다. 이 차이도 맞추기.\n"
        "- 정욱의 to_welfare_payload도 지금 성별을 버리는 경고 경로가 있으므로 함께 수정해야 함.\n\n"
        "## 파일별 역할\n\n"
        "profiles/: 정욱 TargetProfile-0.2 입력216개. 이 형식은 이미 sex를 지원한다.\n"
        "data/handoff_records.json: 각 record의 request_v02가 기준 추천 입력이다. "
        "analysis_context는 근거·가설·특성·배경·민감도 별도 자료이며 현재HTTP요청에 통째로 붙이지 않는다.\n"
        "data/priority_sex.json: 같은 기준월 남녀24집단 순위. priority_aggregate.json은 합산12집단 비교용. 두 목록을 섞지 않는다.\n"
        "examples/current_offline_aggregate_request.json: 현재 서버용 합산 조회 예시. mode=offline이며 남녀별 입력의 대체물이 아니다.\n"
        "held/partial 예시: 낮은 위험으로 바꾸지 않고 보류/하한을 보존해야 한다.\n\n"
        "## API 없이 형식 확인\n\n"
        "압축을 푼 폴더에서 pydantic·jsonschema가 설치된Python으로 실행:\n"
        "python scripts/integration/check_welfare_handoff.py .\n\n"
        "JSON형식·집단일치·근거와요청일치·파일해시를 확인한다. 실제추천품질·운영여부·예방효과검증이 아니다. "
        "분석을 원본부터 재현하려면 공통 저장소의 전처리 코드와 보유 원본이 별도로 필요하다.\n\n"
        "## 연결 순서\n\n"
        "여성완료 → 남성완료 → 부분판정 → 보류 → 성별불일치거부 →10대범위 확인 순서로 점검하자. "
        "기준 입력을 받은 뒤에도 실제 모델 응답 품질 검증은 따로 해야 한다.\n"
    )
    (folder/"README_현지에게.md").write_text(readme,encoding="utf-8")
    for source,destination in (("docs/hyeonji_analysis_handoff_20261019.md","입출력_맞추기.md"),
                               ("docs/analysis_sex_results_20261019.md","상세_성별분석.md"),
                               ("docs/hansu_analysis_pipeline.md","전체_분석과정.md")):
        if (ROOT/source).exists():
            shutil.copyfile(ROOT/source,folder/destination)
    if (analysis_folder/"analysis_explained.md").exists():
        shutil.copyfile(analysis_folder/"analysis_explained.md",folder/"실행결과_설명.md")
    manifest=dict(schema_version="hansu-hyeonji-package-v1",analysis_bundle_hash=bundle["bundle_hash"],
        profiles=len(records),proposed_contract="risk-input-0.2",receiver_update_required=True,
        contract_status="producer_fixed_by_user",receiver_update_owner="welfare_receiver",
        hyeonji_reference_commit=HYEONJI_SHA,
        files=[dict(path=str(path.relative_to(folder)).replace("\\","/"),sha256=file_hash(path))
               for path in sorted(folder.rglob("*")) if path.is_file() and path.name!="MANIFEST.json"])
    write_json(folder/"MANIFEST.json",manifest)
    checked=check_package(folder)
    archive=output_root/("hansu_to_hyeonji_"+folder.name+".zip")
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in sorted(folder.rglob("*")):
            if path.is_file():zip_file.write(path,str(path.relative_to(folder)))
    zip_checked=check_package(archive)
    result=dict(folder=str(folder),zip=str(archive),zip_bytes=archive.stat().st_size,**zip_checked)
    write_json(output_root/"latest_package.json",result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results",type=Path,default=ROOT/"data/processed/analysis_current")
    parser.add_argument("--output",type=Path,default=ROOT/"data/processed/hyeonji_handoff_current")
    args=parser.parse_args()
    build(args.results,args.output)
