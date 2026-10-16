"""공식 안내에 근거한 복지자원 후보 조회. 개인 자격·효과·위험도는 판단하지 않는다."""

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_VERSION = "welfare-0.3"
RISK_SCHEMA_VERSION = "risk-input-0.1"
RULES_VERSION = "support-review-0.2"
CATALOG_PATH = Path(__file__).with_name("welfare_resources.json")
PURPOSES = {
    "connection": "관계 형성·사회 참여",
    "daily": "일상생활 지원",
    "wellbeing": "정서·마음 돌봄",
}


def validate_request(payload):
    """임의의 나이·지역이나 지원하지 않는 입력을 조용히 무시하지 않는다."""
    if not isinstance(payload, dict):
        raise ValueError("요청은 JSON 객체여야 합니다.")
    if set(payload) - {"target", "risk_assessment", "confirmed_support_needs"}:
        raise ValueError("지원하지 않는 요청 항목이 있습니다.")
    target = payload.get("target")
    if not isinstance(target, dict) or set(target) != {"region", "age_group", "purpose"}:
        raise ValueError("target에는 region, age_group, purpose가 필요합니다.")
    if target["region"] not in ("춘천시", "강남구"):
        raise ValueError("현재 지원 지역은 춘천시·강남구입니다.")
    if type(target["age_group"]) is not int or target["age_group"] not in (10, 20, 30, 40, 50, 60):
        raise ValueError("age_group은 10, 20, 30, 40, 50, 60 중 하나여야 합니다.")
    if target["purpose"] not in ("all", *PURPOSES):
        raise ValueError("지원하지 않는 지원 목적입니다.")
    needs = payload.get("confirmed_support_needs", [])
    if not isinstance(needs, list) or any(not isinstance(need, str) or need not in PURPOSES for need in needs) or len(set(needs)) != len(needs):
        raise ValueError("confirmed_support_needs는 중복 없는 지원 목적 목록이어야 합니다.")
    validate_risk(payload.get("risk_assessment"), target)
    return dict(target)


def validate_risk(risk, target):
    """팀원과 합의할 초안 계약. 단계 계산 없이 전달값의 형식·집단 일치만 검증한다."""
    if risk is None:
        return
    keys = {"schema_version", "assessment_id", "region", "age_group", "period", "status", "level", "signals", "limitations", "model_version", "is_example"}
    if not isinstance(risk, dict) or set(risk) != keys:
        raise ValueError("위험도 입력 필드가 초안 계약과 일치하지 않습니다.")
    if risk["schema_version"] != RISK_SCHEMA_VERSION:
        raise ValueError("지원하지 않는 위험도 입력 버전입니다.")
    if risk["region"] != target["region"] or type(risk["age_group"]) is not int or risk["age_group"] != target["age_group"]:
        raise ValueError("위험도 결과와 추천 대상의 지역·연령대가 다릅니다.")
    if not isinstance(risk["period"], str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", risk["period"]):
        raise ValueError("분석 기준 월은 YYYY-MM 형식이어야 합니다.")
    date.fromisoformat(risk["period"] + "-01")
    if risk["status"] not in ("complete", "partial", "held"):
        raise ValueError("판정 상태는 complete, partial, held 중 하나여야 합니다.")
    level = risk["level"]
    if level is not None and (type(level) is not int or not 1 <= level <= 5):
        raise ValueError("위험 단계는 1~5 정수 또는 null이어야 합니다.")
    if (risk["status"] == "complete" and level is None) or (risk["status"] == "held" and level is not None):
        raise ValueError("완료는 단계가 필요하고, 보류는 단계가 null이어야 합니다.")
    if type(risk["is_example"]) is not bool:
        raise ValueError("is_example은 참/거짓이어야 합니다.")
    for field in ("assessment_id", "model_version"):
        if not isinstance(risk[field], str) or not risk[field].strip() or len(risk[field]) > 200:
            raise ValueError("분석 식별자와 모델 버전이 필요합니다.")
    if not isinstance(risk["limitations"], list) or len(risk["limitations"]) > 20 or any(not isinstance(text, str) or not text.strip() or len(text) > 1000 for text in risk["limitations"]):
        raise ValueError("관측 제한은 문자열 목록이어야 합니다.")
    if not isinstance(risk["signals"], list) or len(risk["signals"]) > 10:
        raise ValueError("위험 신호는 목록이어야 합니다.")
    types = []
    for signal in risk["signals"]:
        if not isinstance(signal, dict) or set(signal) != {"type", "description"}:
            raise ValueError("신호에는 type과 description이 필요합니다.")
        if signal["type"] not in ("activity_decline", "consumption_decline", "movement_decline"):
            raise ValueError("지원하지 않는 신호 유형입니다.")
        if not isinstance(signal["description"], str) or not signal["description"].strip() or len(signal["description"]) > 1000:
            raise ValueError("신호 설명이 필요합니다.")
        types.append(signal["type"])
    if len(set(types)) != len(types):
        raise ValueError("신호 유형이 중복되었습니다.")


def build_review(payload):
    """팀 검토용 규칙. 집단 감소 신호를 개인의 결핍·진단·신청 자격으로 변환하지 않는다."""
    risk = payload.get("risk_assessment")
    needs = list(payload.get("confirmed_support_needs", []))
    questions = []
    suggestions = []
    status = "browse"
    if risk:
        if risk["status"] == "held":
            status = "risk_held"
            questions.append("위험 판정이 보류되었습니다. 보류 사유와 추가 관측을 먼저 확인하세요. 목록은 일반 조회입니다.")
        elif risk["status"] == "partial":
            status = "risk_partial"
            questions.append("불완전한 위험 판정입니다. 누락 근거와 관측 제한을 확인하세요. 목록은 일반 조회입니다.")
        else:
            status = "needs_confirmation"
            types = {signal["type"] for signal in risk["signals"]}
            if types & {"activity_decline", "movement_decline"}:
                suggestions.append({"purpose": "connection", "basis": "signal_hypothesis", "reason": "활동·이동 감소를 계기로 관계 형성 지원 필요를 확인해볼 수 있습니다. 원인·참여 의사 확인 전 가설입니다."})
                questions.append("실제 교류 감소, 참여 의사, 이동·건강·접근성 제약을 확인했나요?")
            if "consumption_decline" in types:
                questions.append("소비 감소의 원인을 확인했나요? 생활 지원 필요 여부는 별도 확인하며 감소만으로 경제적 어려움을 확정하지 않습니다.")
            questions.append("정서 지원은 본인의 이용 의사와 필요한 증빙·기관 상담을 별도로 확인하세요.")
    if needs:
        if status not in ("risk_held", "risk_partial"):
            status = "ready_for_review"
        questions.append("담당자가 선택한 지원 필요는 개인의 신청 자격 확정과 다릅니다. 대상 조건을 추가 확인하세요.")
    if payload["target"]["purpose"] != "all" and needs and payload["target"]["purpose"] not in needs:
        if status not in ("risk_held", "risk_partial"):
            status = "needs_confirmation"
        questions.append("조회 목적과 확인한 지원 필요가 다릅니다. 현재 목적은 일반 탐색으로 처리합니다.")
    return {"rules_version": RULES_VERSION, "status": status, "confirmed_support_needs": needs,
            "suggested_purposes": suggestions, "questions": questions}


def load_catalog():
    """검증되지 않은 링크·불완전한 출처를 정상 후보로 내보내지 않는다."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    ids = set()
    for item in catalog:
        if item["id"] in ids:
            raise ValueError("자원 식별자가 중복되었습니다.")
        ids.add(item["id"])
        if item["region"] not in ("강남구", "춘천시") or item["purpose"] not in PURPOSES:
            raise ValueError("자원의 지역 또는 목적이 올바르지 않습니다.")
        source = item["source"]
        url = urlsplit(source["url"])
        if url.scheme != "https" or url.hostname not in ("www.gangnam.go.kr", "health.gangnam.go.kr", "www.chuncheon.go.kr"):
            raise ValueError("공식 출처 링크를 확인해주세요.")
        date.fromisoformat(source["checked_at"])
        if source["type"] != "official_local_government" or not source["title"]:
            raise ValueError("출처 정보가 올바르지 않습니다.")
        if not item["age_ranges"] or item["availability_status"] not in ("needs_confirmation", "closed"):
            raise ValueError("연령 및 운영 상태를 확인해주세요.")
        for span in item["age_ranges"]:
            low, high = span["min"], span["max"]
            if any(value is not None and (type(value) is not int or value < 0) for value in (low, high)):
                raise ValueError("연령 범위가 올바르지 않습니다.")
            if low is not None and high is not None and low > high:
                raise ValueError("연령 범위가 역전되었습니다.")
        if item["application_end"]:
            date.fromisoformat(item["application_end"])
    return catalog


def age_overlap(age_group, ranges):
    """집단 구간과 서비스 연령의 교집합. 미명시 조건은 전체 연령으로 확정하지 않는다."""
    low, high = (0, 19) if age_group == 10 else (age_group, None if age_group == 60 else age_group + 9)
    unknown = False
    overlaps = []
    for span in ranges:
        if span["min"] is None:
            unknown = True
            continue
        start, end = span["min"], span["max"]
        if (end is None or low <= end) and (high is None or start <= high):
            overlaps.append((max(low, start), min(high if high is not None else float('inf'), end if end is not None else float('inf'))))
    if overlaps:
        # 모든 연령 구간이 이어지는지 확인해 부분 겹침을 전체 겹침으로 잘못 표시하지 않는다.
        cursor = low
        for start, end in sorted(overlaps):
            if start > cursor:
                break
            cursor = max(cursor, end + 1)
        return "overlap" if cursor == float('inf') or (high is not None and cursor > high) else "partial"
    return "unknown" if unknown else "none"


def recommend(payload):
    target = validate_request(payload)
    catalog = load_catalog()
    today = datetime.now(timezone(timedelta(hours=9))).date()
    matches = []
    review = build_review(payload)
    needs = review["confirmed_support_needs"]
    for resource in catalog:
        if resource["availability_status"] == "closed" or (resource["application_end"] and date.fromisoformat(resource["application_end"]) < today):
            continue
        if resource["region"] != target["region"]:
            continue
        if target["purpose"] not in ("all", resource["purpose"]):
            continue
        # 위험 단계나 신호 가설로는 필터링하지 않는다. 담당자가 확인한 필요만 all 조회에 반영한다.
        if target["purpose"] == "all" and needs and resource["purpose"] not in needs:
            continue
        overlap = age_overlap(target["age_group"], resource["age_ranges"])
        if overlap == "none":
            continue
        matches.append({**resource, "match_reasons": [
            f"선택 지역({target['region']})의 공식 안내 자원입니다. 실제 거주지 조건은 별도 확인이 필요합니다.",
            {"overlap": "안내 연령 범위와 선택 집단이 겹칩니다. 개인 자격은 미판정입니다.",
             "partial": "선택 집단 중 일부 연령만 안내 조건과 겹칩니다. 정확한 나이를 확인해야 합니다.",
             "unknown": "안내의 일부 연령 기준이 미명시되어 기관 확인이 필요합니다."}[overlap],
            f"지원 목적: {PURPOSES[resource['purpose']]}",
        ], "age_match": overlap, "eligibility_status": "needs_confirmation",
            "support_basis": "staff_confirmed_need" if resource["purpose"] in needs else "staff_requested_purpose" if target["purpose"] != "all" else "general_browse"})
    return {
        "schema_version": SCHEMA_VERSION,
        "is_demo": False,
        "recommendation_method": "official_candidate_review_v1",
        "catalog_version": "official-seed-2026-10-16",
        "target": target,
        "risk_assessment": payload.get("risk_assessment"),
        "has_example_context": bool(payload.get("risk_assessment") and payload["risk_assessment"]["is_example"]),
        "review": review,
        "purposes": PURPOSES,
        "resources": matches,
        "total": len(matches),
        "coverage": {
            "status": "candidates_found" if matches else "no_candidates_in_catalog",
            "message": "등록 목록 안에서 조건에 맞는 후보를 조회했습니다. 지역 전체 자원 현황을 뜻하지 않습니다." if matches
            else "등록 목록에서 조건에 맞는 후보를 찾지 못했습니다. 실제 서비스 부재나 지원 불필요를 뜻하지 않으며 추가 자원 조사가 필요합니다.",
        },
        "warnings": [
            "공식 안내를 확인해 편집한 소규모 목록입니다. 최신 모집·운영 여부는 기관 확인이 필요합니다.",
            "페이지 확인일은 서비스 운영·신청 자격의 검증일이 아닙니다. 과거 기준이 포함될 수 있습니다.",
            "집단 기준의 후보 조회이며 개인 거주지·나이·소득·가구·돌봄 조건을 판정하지 않습니다.",
            "위험도 입력 계약과 추천 기준은 팀 검토용 초안입니다. 위험도 자동 수신·기획 Agent는 연결 전입니다.",
            *(["위험도 입력은 예시이며 실제 집단의 분석 결과가 아닙니다."] if payload.get("risk_assessment") and payload["risk_assessment"]["is_example"] else []),
        ],
    }
