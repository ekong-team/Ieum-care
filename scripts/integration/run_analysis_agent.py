"""분석 → 원인 가설 → 1차 우선 검토 목록. 실제 API는 기본 비활성화."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai.analysis_agent.inputs import load_inputs, file_hash, digest
from ai.analysis_agent.workflow import run_analysis
from scripts.integration.verify_analysis_agent import verify
from ai.analysis_agent.research import explain_bundle

def save_results(bundle, contexts, folder):
    """결과별 폴더에 기록·재검산한 뒤에만 최신 결과로 공개한다."""
    output_root = Path(folder)
    folder = output_root / bundle["bundle_hash"][:16]
    folder.mkdir(parents=True, exist_ok=True)
    def write_json(path, value):
        text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    write_json(folder / "run_status.json", dict(status="building", bundle_hash=bundle["bundle_hash"]))
    write_json(folder / "analysis_bundle.json", bundle)
    write_json(folder / "priority_review.json", bundle["priority_review"])
    write_json(folder / "external_research.json", [
        dict(model_review=cohort["interpretation"]["model_review"], **receipt)
        for cohort in bundle["cohorts"]
        for receipt in bundle["execution"]["model_receipts"]
        if receipt["analysis_id"] == cohort["analysis_id"] and receipt.get("provider") == "gemini"
    ])
    if "aggregate_priority_review" in bundle:
        write_json(folder / "aggregate_priority_review.json", bundle["aggregate_priority_review"])
    profiles = folder / "profiles"
    profiles.mkdir(exist_ok=True)
    for cohort in bundle["cohorts"]:
        write_json(profiles / (cohort["analysis_id"] + ".json"), cohort["profile"])
    distribution = Counter(str(c["assessment"]["level"]) for c in bundle["cohorts"])
    statuses = Counter(c["assessment"]["status"] for c in bundle["cohorts"])
    changes = []
    for c in bundle["cohorts"]:
        old = contexts.get(c["analysis_id"], {}).get("analysis_evidence", {})
        if "활동위축단계" in old and old["활동위축단계"] != c["assessment"]["level"]:
            changes.append(dict(analysis_id=c["analysis_id"], before=old["활동위축단계"], after=c["assessment"]["level"]))
    write_json(folder / "comparison_with_previous.json", dict(
        note="기존 제출 준비본 대비; 동일 이름의 새 판정으로 덮어쓰지 않음",
        level_changes=changes, partial_assessments=[c["analysis_id"] for c in bundle["cohorts"] if c["assessment"]["status"] == "partial"]))
    priority = bundle["priority_review"]
    lines = ["# 데이터 분석·원인 가설·1차 우선 검토 결과", "",
        "상태: 실행 가능한 제안 버전. 실제 고립 검증·팀 기준 합의·2차 복지 필터링 완료 아님.", "",
        f"- 분석 조합 수: {len(bundle['cohorts'])}",
        f"- 단계 분포: {dict(distribution)}", f"- 판정 상태: {dict(statuses)}",
        f"- 기존 자료 대비 단계 값 변경: {len(changes)}",
        f"- 실제 모델 응답: {bundle['execution']['confirmed_llm_responses']}; 기본 실행은 계산·규칙 해석",
        "- 원인 해석은 관측 신호 가설. 확정 인과관계 없음.",
        f"- Tavily 검색 시도: {bundle['execution'].get('search_attempts', 0)}회. 검색 발췌는 미검증 참고 후보이며 단계 재가중 없음.", "",
        "## 같은 기준월의 1차 검토 순위", "",
        "완료 판정의 단계 내림차순·동일 단계 공동 밀집순위. 별도 후보 제외 기준 없음.", "",
        "|순위|지역|연령|성별|단계|민감도 변경|품질 경고|", "|---|---|---|---|---|---|---|"]
    for item in priority["ranked_cohorts"]:
        age = item["target"]["age_group"]
        age_label = "60세 이상" if age == 60 else f"{age}대"
        sex_label = {"all":"남녀 합산","male":"남성","female":"여성"}[item["target"]["sex"]]
        lines.append(f"|{item['rank']}|{item['target']['region']}|{age_label}|{sex_label}|{item['level']}|{sum(s['differs'] for s in item['sensitivity'])}|{len(item['quality_warnings'])}|")
    lines += ["", f"부분판정: {len(priority['partial_assessments'])} / 보류: {len(priority['held_cohorts'])}",
              "", "전체 집단·근거·가설·배경·출처 해시·실행 기록은 analysis_bundle.json 참조."]
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "analysis_explained.md").write_text(explain_bundle(bundle), encoding="utf-8")
    verification = verify(folder, allow_building=True)
    write_json(folder / "verification.json", verification)
    write_json(folder / "run_status.json", dict(status="passed", bundle_hash=bundle["bundle_hash"]))
    write_json(output_root / "latest.json", dict(directory=folder.name, bundle_hash=bundle["bundle_hash"]))
    return dict(records=len(bundle["cohorts"]), distribution=dict(distribution), statuses=dict(statuses),
        previous_level_changes=len(changes), priority_period=priority["period"],
        priority_rows=len(priority["ranked_cohorts"]), llm_responses=bundle["execution"]["confirmed_llm_responses"],
        output=str(folder.resolve()))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path)
    parser.add_argument("--sensitivity", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--period", default="202512")
    parser.add_argument("--input-folder", type=Path, help="features.csv/sensitivity.csv/context.json을 가진 준비 폴더")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/analysis_current")
    parser.add_argument("--mode", choices=("offline", "gemini"), default="offline")
    parser.add_argument("--web-search", action="store_true", help="분석 중 공식 자료 검색 허용. adaptive에서는 필요할 때만 검색")
    parser.add_argument("--research-mode", choices=("adaptive", "basic", "focused"), default="adaptive",
                        help="adaptive: 검색 필요 판단·조건부 검색/재검색. 검색최대3회·Gemini최대2회")
    parser.add_argument("--check-config", action="store_true", help="키 값 없이 Gemini/Tavily 설정 여부만 표시")
    parser.add_argument("--model")
    parser.add_argument("--analysis-id", help="실제 모델을 사용할 단일 집단. 전체 수치 계산은 동일하게 유지")
    parser.add_argument("--allow-external", action="store_true")
    args = parser.parse_args()
    if args.check_config:
        from ai.analysis_agent.model import config_status
        print(json.dumps(config_status(), ensure_ascii=False, indent=2))
        return
    if args.web_search and args.mode != "gemini":
        parser.error("--web-search는 --mode gemini에서만 사용할 수 있습니다.")
    if args.research_mode == "focused" and not (args.mode == "gemini" and args.web_search):
        parser.error("focused는 --mode gemini --web-search에서만 사용할 수 있습니다.")
    individual = (args.features, args.sensitivity, args.context)
    if args.input_folder or not any(individual):
        if args.input_folder and any(individual):
            parser.error("--input-folder와 개별 입력 경로는 함께 사용하지 않습니다.")
        args.input_folder = args.input_folder or ROOT / "data/processed/analysis_inputs"
        args.features = args.input_folder / "features.csv"
        args.sensitivity = args.input_folder / "sensitivity.csv"
        args.context = args.input_folder / "context.json"
    elif not all(individual):
        parser.error("개별 입력 경로를 사용할 때는 --features --sensitivity --context 세 경로가 모두 필요합니다.")
    provider = None
    if args.mode == "gemini":
        if not args.allow_external or not args.analysis_id:
            parser.error("Gemini 실행은 --allow-external --analysis-id가 필요합니다.")
        from ai.analysis_agent.model import GeminiTavilyProvider
        try:
            provider = GeminiTavilyProvider(model=args.model, use_search=args.web_search, research_mode=args.research_mode)
        except ValueError as error:
            parser.error(str(error))
    rows, contexts, manifest = load_inputs(args.features, args.sensitivity, args.context)
    bundle = run_analysis(rows, contexts, manifest, period=args.period, provider=provider, model_analysis_id=args.analysis_id)
    bundle.pop("bundle_hash")
    implementation_files = sorted((ROOT / "ai/analysis_agent").glob("*.py")) + [
        ROOT / "ai/contracts/profile.py", ROOT / "ai/contracts/causes.py", ROOT / "scripts/integration/run_analysis_agent.py",
        ROOT / "scripts/integration/verify_analysis_agent.py",
    ]
    bundle["implementation_manifest"] = [dict(path=str(path.relative_to(ROOT)), sha256=file_hash(path))
                                         for path in implementation_files]
    bundle["bundle_hash"] = digest(bundle)
    print(json.dumps(save_results(bundle, contexts, args.output), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
