"""저장 결과를 입력에서 재계산해 대조한다. 최적화 실행에서도 검사를 생략하지 않는다."""
from copy import deepcopy
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ai.analysis_agent.assessment import assess
from ai.analysis_agent.context import describe_cohort
from ai.analysis_agent.inputs import digest, file_hash, load_inputs, source_path
from ai.analysis_agent.policy import SENSITIVITY_SCENARIOS
from ai.analysis_agent.priority import priority_for
from ai.analysis_agent.reviewer import validate_review
from ai.contracts.profile import TargetProfile

def require(condition, message):
    if not condition:
        raise ValueError(message)

def verify(folder, *, allow_building=False):
    folder = Path(folder)
    bundle = json.loads((folder / "analysis_bundle.json").read_text(encoding="utf-8"))
    status = json.loads((folder / "run_status.json").read_text(encoding="utf-8"))
    permitted_statuses = ("building", "passed") if allow_building else ("passed",)
    require(status.get("status") in permitted_statuses, "완료되지 않은 출력입니다.")
    require(status.get("bundle_hash") == bundle["bundle_hash"], "실행 상태와 결과가 다릅니다.")
    require(digest({key:value for key,value in bundle.items() if key != "bundle_hash"}) == bundle["bundle_hash"],
            "결과 내용의 해시가 다릅니다.")
    sources = {entry["role"]: source_path(entry) for entry in bundle["source_manifest"]}
    for entry in bundle["source_manifest"]:
        require(file_hash(source_path(entry)) == entry["sha256"], "분석 후 입력이 변경됐습니다.")
    for entry in bundle["implementation_manifest"]:
        require(file_hash(ROOT / entry["path"]) == entry["sha256"], "실행 코드가 변경됐습니다.")
    rows, contexts, _ = load_inputs(sources["features"], sources["industry_sensitivity"], sources["context_packet"])
    expected = {item["analysis_id"]:item for item in assess(rows)}
    require(len(bundle["cohorts"]) == len(expected), "집단 개수가 다릅니다.")
    scenarios = {name:{item["analysis_id"]:item for item in assess(rows, **options)}
                 for name,options in SENSITIVITY_SCENARIOS}
    ids = set()
    for cohort in bundle["cohorts"]:
        aid = cohort["analysis_id"]
        require(aid not in ids and aid in expected, "중복 또는 알 수 없는 집단입니다.")
        ids.add(aid)
        assessment = expected[aid]
        sensitivity = [
            dict(scenario=name, level=values[aid]["level"], status=values[aid]["status"],
                 differs=(values[aid]["level"],values[aid]["status"]) != (assessment["level"],assessment["status"]))
            for name,values in scenarios.items()
        ]
        expected_cohort = describe_cohort(assessment, contexts.get(aid), sensitivity)
        validate_review(cohort)
        actual_cohort = deepcopy(cohort)
        actual_cohort["interpretation"].pop("model_review", None)
        require(actual_cohort == expected_cohort, "재계산한 집단 분석·근거·특성과 다릅니다.")
        profile = TargetProfile.model_validate(cohort["profile"]).model_dump()
        from ai.analysis_agent.research import validate_research_receipt
        for receipt in bundle["execution"]["model_receipts"]:
            if receipt["analysis_id"] == aid:
                validate_research_receipt(receipt, TargetProfile.model_validate(profile))
        stored = json.loads((folder / "profiles" / (aid + ".json")).read_text(encoding="utf-8"))
        require(profile == stored, "팀 전달 파일이 분석 결과와 다릅니다.")
    require({path.stem for path in (folder / "profiles").glob("*.json")} == ids,
            "누락되거나 오래된 전달 파일이 있습니다.")
    period = bundle["priority_review"]["period"].replace("-", "")
    expected_priority = priority_for(bundle["cohorts"], period)
    require(bundle["priority_review"] == expected_priority, "1차 순위가 기준과 다릅니다.")
    require(json.loads((folder / "priority_review.json").read_text(encoding="utf-8")) == expected_priority,
            "순위 전달 파일이 다릅니다.")
    if "aggregate_priority_review" in bundle:
        aggregate = priority_for(bundle["cohorts"], period, sexes=("all",))
        require(bundle["aggregate_priority_review"] == aggregate, "합산 비교 순위가 다릅니다.")
        require(json.loads((folder / "aggregate_priority_review.json").read_text(encoding="utf-8")) == aggregate,
                "합산 비교 파일이 다릅니다.")
    if (folder / "external_research.json").exists():
        research = [dict(model_review=cohort["interpretation"]["model_review"], **receipt)
                    for cohort in bundle["cohorts"] for receipt in bundle["execution"]["model_receipts"]
                    if receipt["analysis_id"] == cohort["analysis_id"] and receipt.get("provider") == "gemini"]
        require(json.loads((folder / "external_research.json").read_text(encoding="utf-8")) == research,
                "검색 자료 전달 파일이 분석 실행 기록과 다릅니다.")
    if (folder / "analysis_explained.md").exists():
        from ai.analysis_agent.research import explain_bundle
        require((folder / "analysis_explained.md").read_text(encoding="utf-8") == explain_bundle(bundle),
                "한국어 설명 보고서가 분석 결과와 다릅니다.")
    groups = expected_priority["ranked_cohorts"] + expected_priority["partial_assessments"] + expected_priority["held_cohorts"]
    return dict(status="passed", checked_profiles=len(ids), checked_priority_groups=len(groups),
                recalculated_from_sources=True, source_hashes_unchanged=True,
                profile_contract="target-profile-0.2",
                actual_llm_responses=bundle["execution"]["confirmed_llm_responses"],
                second_priority="excluded", bundle_hash=bundle["bundle_hash"])

def latest_folder(root):
    root = Path(root)
    pointer = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    folder = (root / pointer["directory"]).resolve()
    require(folder.is_relative_to(root.resolve()), "잘못된 결과 경로입니다.")
    return folder

if __name__ == "__main__":
    supplied = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/processed/analysis_current"
    folder = latest_folder(supplied) if (supplied / "latest.json").exists() else supplied
    result = verify(folder)
    (folder / "verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
