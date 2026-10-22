"""분석 묶음에서 집단 하나를 골라 복지 추천에 직접 연결한다. ZIP은 사용하지 않는다."""
from typing import Literal

from ai.analysis_agent.handoff import make_cause_engine, target_profile
from ai.analysis_agent.welfare_handoff import to_welfare_request
from ai.contracts import WelfareAnalysisContext
from ai.nodes.welfare import to_existing_resources
from ai.welfare_agent.recommender import recommend, validate_request


def recommendation_request(bundle: dict, analysis_id: str) -> dict:
    """분석 수치·성별·가설을 검증하고 현지 추천 입력을 만든다. 파일/API 호출 없음."""
    profile = target_profile(bundle, analysis_id)
    causes = make_cause_engine(bundle)(None, profile)
    cohort = next(item for item in bundle["cohorts"] if item["analysis_id"] == analysis_id)
    payload = to_welfare_request(cohort)
    payload["analysis_context"] = WelfareAnalysisContext(
        profile=profile, causes=causes,
    ).model_dump(mode="json")
    validate_request(payload)
    return payload


def recommend_from_analysis(bundle: dict, analysis_id: str, *,
                            mode: Literal["offline", "live"] = "offline") -> dict:
    """run_analysis() 반환값을 그대로 받는다. live일 때만 실제 외부 API를 사용한다."""
    if mode not in ("offline", "live"):
        raise ValueError("mode는 offline 또는 live여야 합니다.")
    payload = recommendation_request(bundle, analysis_id)
    if mode == "live":
        from ai.welfare_agent.live_agent import recommend_live
        result = recommend_live(payload)
    else:
        result = {**recommend(payload), "mode": "offline"}
        result["warnings"].insert(0, "저장된 자원 후보 조회입니다. 외부 검색·LLM을 실행하지 않았습니다.")
    result["response_routing"] = to_existing_resources(result, []).response_routing.model_dump(mode="json")
    return result
