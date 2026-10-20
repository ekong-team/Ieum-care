"""현지에게 보낼 묶음을 API 호출 없이 검사한다. ZIP 내부 코드를 실행하지 않는다."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from jsonschema import Draft202012Validator
from ai.contracts.profile import TargetProfile
from ai.analysis_agent.welfare_handoff import WelfareRequest02, to_welfare_request

def check_package(path):
    path=Path(path)
    archive=zipfile.ZipFile(path) if path.is_file() else None
    def read(name):
        return archive.read(name) if archive else (path/name).read_bytes()
    try:
        if archive:
            for name in archive.namelist():
                parts=PurePosixPath(name).parts
                if PurePosixPath(name).is_absolute() or ".." in parts or ".env" in parts or "raw" in parts:
                    raise ValueError("허용하지 않은 ZIP 항목입니다.")
        manifest=json.loads(read("MANIFEST.json"))
        for entry in manifest["files"]:
            if hashlib.sha256(read(entry["path"])).hexdigest()!=entry["sha256"]:
                raise ValueError("전달 파일 해시가 다릅니다.")
        records=json.loads(read("data/handoff_records.json"))
        validator=Draft202012Validator(json.loads(read("contracts/welfare_risk_input_0_2.schema.json")))
        identities=set()
        maximum=0
        for record in records:
            profile=TargetProfile.model_validate(record["profile"])
            request=WelfareRequest02.model_validate(record["request_v02"])
            validator.validate(record["request_v02"])
            identity=(request.risk_assessment.period,request.target.region,request.target.age_group,request.target.sex)
            if identity in identities:
                raise ValueError("전달 집단이 중복입니다.")
            identities.add(identity)
            if profile.target.model_dump()!=dict(region=request.target.region,age_group=request.target.age_group,sex=request.target.sex):
                raise ValueError("분석과 추천 입력의 대상이 다릅니다.")
            if record["analysis_id"]!=request.risk_assessment.assessment_id:
                raise ValueError("분석 식별자가 다릅니다.")
            expected=to_welfare_request(dict(analysis_id=record["analysis_id"],profile=record["profile"],
                assessment=record["analysis_context"]["assessment"],profile_hash=record["profile_hash"]))
            if record["request_v02"]!=expected:
                raise ValueError("추천 입력이 원래 분석 결과와 다릅니다.")
            stored=json.loads(read("profiles/"+record["analysis_id"]+".json"))
            if stored!=record["profile"]:
                raise ValueError("집단별 파일과 전달 자료가 다릅니다.")
            maximum=max(maximum,len(json.dumps(record["request_v02"],ensure_ascii=False).encode("utf-8")))
        return dict(status="passed",records=len(records),
            sexes=sorted({identity[3] for identity in identities}),
            proposed_contract="risk-input-0.2",maximum_request_bytes=maximum,
            current_hyeonji_gender_support="requires_update",actual_api_calls=0)
    finally:
        if archive: archive.close()

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("사용법: python scripts/integration/check_welfare_handoff.py 전달ZIP또는폴더")
    print(json.dumps(check_package(sys.argv[1]),ensure_ascii=False,indent=2))
