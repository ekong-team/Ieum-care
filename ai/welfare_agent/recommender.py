"""공식 안내에 근거한 복지자원 후보 조회. 개인 자격·효과·위험도는 판단하지 않는다."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_VERSION = "welfare-0.2"
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
    if set(payload) - {"target", "risk_assessment"}:
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
    if payload.get("risk_assessment") is not None:
        raise ValueError("위험도 입력 계약은 연동 전입니다. 현재 risk_assessment는 null만 지원합니다.")
    return dict(target)


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
    for resource in catalog:
        if resource["availability_status"] == "closed" or (resource["application_end"] and date.fromisoformat(resource["application_end"]) < today):
            continue
        if resource["region"] != target["region"]:
            continue
        if target["purpose"] not in ("all", resource["purpose"]):
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
        ], "age_match": overlap, "eligibility_status": "needs_confirmation"})
    return {
        "schema_version": SCHEMA_VERSION,
        "is_demo": False,
        "recommendation_method": "official_candidate_filter_v1",
        "catalog_version": "official-seed-2026-10-16",
        "target": target,
        "risk_assessment": None,
        "purposes": PURPOSES,
        "resources": matches,
        "total": len(matches),
        "warnings": [
            "공식 안내를 확인해 편집한 소규모 목록입니다. 최신 모집·운영 여부는 기관 확인이 필요합니다.",
            "페이지 확인일은 서비스 운영·신청 자격의 검증일이 아닙니다. 과거 기준이 포함될 수 있습니다.",
            "집단 기준의 후보 조회이며 개인 거주지·나이·소득·가구·돌봄 조건을 판정하지 않습니다.",
            "위험도 및 기획 Agent는 연결 전입니다.",
        ],
    }
