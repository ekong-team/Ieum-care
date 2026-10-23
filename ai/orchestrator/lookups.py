"""입력 어댑터: 분석 결과 + 복지 결과(review JSON 또는 offline 조회) → 집단별 CohortInput.

복지 결과를 받는 방법은 두 가지다 (설계 결정 C).
- review JSON: 화면 일괄 추천(live)을 내려받은 welfare-cohort-review-0.1. 이미 비용을 낸 결과를 다시 쓴다.
- offline 조회: 저장 자료로 집단마다 recommend()를 부른다. 키 없이 시연할 때 쓴다.
오케스트레이터가 live 추천을 직접 부르지는 않는다 (24개 집단 × 검색·Gemini → 무료 한도 초과).
"""

from dataclasses import dataclass
import json
from pathlib import Path

from ai.contracts import ExistingResources
from ai.nodes.welfare import attach_response_routes, to_existing_resources
from ai.orchestrator.second_priority import Candidate, CohortLookup
from ai.welfare_agent.analysis_input import latest_analysis_inputs
from ai.welfare_agent.recommender import recommend

REVIEW_SCHEMA = "welfare-cohort-review-0.1"


@dataclass
class CohortInput:
    """집단 하나에 대해 2차 순위(lookup)와 기획 그래프(existing)가 함께 쓰는 복지 결과."""

    lookup: CohortLookup
    existing: ExistingResources


def load_latest(root: Path) -> tuple[dict, dict]:
    """최신 분석 결과 → (분석 묶음, 1차 순위별 복지 입력). 검증은 현지 님 latest_analysis_inputs를 그대로 쓴다."""
    inputs = latest_analysis_inputs(root)  # 경로·완료 상태·해시·1차 순위 일치를 검사한다
    latest = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    bundle = json.loads((root.resolve() / latest["directory"] / "analysis_bundle.json").read_text(encoding="utf-8"))
    if bundle.get("bundle_hash") != inputs["batch_id"]:
        raise ValueError("분석 묶음과 1차 순위 입력이 서로 다른 실행 결과입니다.")
    return bundle, inputs


def _first_rank_items(inputs: dict) -> dict[str, dict]:
    return {item["analysis_id"]: item for item in inputs["priority"]["ranked_cohorts"]}


def _lookup(entry: dict, ranked: dict, status: str, candidates: list[dict]) -> CohortLookup:
    item = ranked[entry["analysis_id"]]
    return CohortLookup(analysis_id=entry["analysis_id"], target=item["target"], first_rank=entry["rank"],
                        level=item["level"], lookup_status=status,
                        candidates=[Candidate(**{k: c[k] for k in Candidate.model_fields if c.get(k) is not None})
                                    for c in candidates])


def _unavailable(reason: str) -> ExistingResources:
    return attach_response_routes(ExistingResources(status="unavailable", reason=reason))


def from_offline(inputs: dict, *, call=recommend) -> list[CohortInput]:
    """1차 대상마다 저장 자료로 복지 후보를 조회한다. 외부 호출 없음. call은 테스트용 교체 자리."""
    ranked, result = _first_rank_items(inputs), []
    for entry in inputs["entries"]:
        try:
            response = call(entry["request"])
        except ValueError as error:
            result.append(CohortInput(_lookup(entry, ranked, "unavailable", []), _unavailable(f"복지 조회 실패: {error}")))
            continue
        status = "candidates_found" if response["resources"] else "no_candidates_found"
        existing = to_existing_resources(response, ["저장된 자료 조회(offline)입니다. 외부 검색·LLM을 실행하지 않았습니다."])
        result.append(CohortInput(_lookup(entry, ranked, status, response["resources"]), existing))
    return result


def from_review(inputs: dict, review: dict) -> list[CohortInput]:
    """화면에서 내려받은 review JSON → 집단별 입력. 다른 분석 실행의 결과면 거부한다."""
    if review.get("schema_version") != REVIEW_SCHEMA:
        raise ValueError(f"{REVIEW_SCHEMA} 형식의 복지 검토 파일이 필요합니다.")
    if review.get("batch_id") != inputs["batch_id"]:
        # 분석을 다시 돌린 뒤 예전 추천 결과를 섞지 않는다 (화면의 배치 일치 원칙과 같다).
        raise ValueError("복지 검토 파일이 현재 분석 결과와 다른 배치입니다. 화면에서 다시 내려받아 주세요.")
    rows = {row["analysis_id"]: row for row in review.get("rows", [])}
    ranked, result = _first_rank_items(inputs), []
    for entry in inputs["entries"]:
        row = rows.get(entry["analysis_id"])
        row = row or {"lookup_status": "pending", "error": "복지 조회 전입니다."}  # 검토표에 없는 집단은 미조회로 본다
        status, candidates = row["lookup_status"], row.get("candidates") or []
        if status in ("candidates_found", "no_candidates_found"):
            # 검토표 후보는 요약본이라 source가 url 하나뿐이다. 기획 그래프가 읽는 형태로 맞춘다.
            response = {"resources": [{**c, "source": {"url": c.get("source_url")}} for c in candidates],
                        "warnings": ["화면 일괄 추천(live) 결과를 재사용했습니다. 추가 검색·LLM 호출은 없습니다."]}
            existing = to_existing_resources(response, [])
        else:
            existing = _unavailable(row.get("error") or "복지 조회 실패")
        result.append(CohortInput(_lookup(entry, ranked, status, candidates), existing))
    return result
