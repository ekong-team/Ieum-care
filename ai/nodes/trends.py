"""참고 사례 검색 노드 (설계 문서 부록 A P2): 다른 지자체·해외의 비슷한 프로그램을 찾아 기획의 참고 자료로 넘긴다.

- 검색은 국내 1회 + 해외·연구 1회, 최대 2회. 첫 번째 원인 가설로만 검색한다 (원인마다 검색하면 호출이 늘어난다).
- 검색어에는 연령 표현과 원인 키워드만 넣는다. 지역명(다른 곳 사례가 빠짐)·근거 수치·담당자 입력은 넣지 않는다.
- 검색 호출·키·한도 처리는 복지 추천의 tavily_search()를 그대로 쓴다. 결과 필터는 공식 복지 도메인 전용이라 따로 둔다.
- offline이면 빈 목록이다. 가짜 URL이 실제 기획에 섞이지 않게 한다.
"""

import re
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from ai.contracts import TrendReference
from ai.nodes.context import NodeContext
from ai.welfare_agent.live_agent import AgentError, configuration, tavily_search

AGE_KO = {10: "청소년", 20: "청년", 30: "청년", 40: "중장년", 50: "중장년", 60: "노인"}
AGE_EN = {10: "adolescents", 20: "young adults", 30: "young adults", 40: "middle-aged adults",
          50: "middle-aged adults", 60: "older adults"}
CAUSE_KO = {
    "C0_unknown": "사회적 연결",
    "C1_mobility": "외출 감소 찾아가는",
    "C2_social_consumption": "지역 활동 위축 여가 모임",
    "C3_overall_withdrawal": "일상 활동 위축 단계적 참여",
    "C4_prolonged": "장기 은둔 정기 안부",
    "C5_weekend_gap": "주말 활동",
}
CAUSE_EN = {
    "C0_unknown": "community connection",
    "C1_mobility": "homebound outreach",
    "C2_social_consumption": "reduced local leisure activity group",
    "C3_overall_withdrawal": "activity withdrawal stepwise participation",
    "C4_prolonged": "prolonged withdrawal regular check-in",
    "C5_weekend_gap": "weekend activity",
}
SUMMARY_CHARS = 500  # 외부 문서라 지시문이 섞일 수 있다. 짧게 자르고, 기획 프롬프트가 '자료일 뿐'이라고 못 박는다
TOC_DOTS = re.compile(r"(?:[·.…]\s*){4,}")  # PDF 목차의 점선 '· · · ·'은 요약에서 지운다

# 2026-10-23 실제 검색에서 정부 정책포털(korea.kr)·학술지(tandfonline 등)가 other로 분류되어 추가했다.
PUBLIC = (".go.kr", "korea.kr", ".gov", ".gov.uk", ".gov.au", ".gc.ca", "who.int", "oecd.org", "un.org")
RESEARCH = (".ac.kr", ".re.kr", ".edu", ".ac.uk", "riss.kr", "dbpia.co.kr", "kci.go.kr", "scholar.google.com",
            "doi.org", "tandfonline.com", "sciencedirect.com", "springer.com", "wiley.com", "sagepub.com",
            "nature.com", "bmj.com", "jmir.org", "frontiersin.org", "mdpi.com", "intechopen.com")
MEDIA = ("yna.co.kr", "hani.co.kr", "chosun.com", "joongang.co.kr", "donga.com", "khan.co.kr", "kbs.co.kr",
         "mbc.co.kr", "sbs.co.kr", "ytn.co.kr", "newsis.com", "news1.kr", "bbc.com", "bbc.co.uk",
         "nytimes.com", "theguardian.com", "reuters.com", "apnews.com")


def search_plan(planning) -> list[tuple[str, dict, int]]:
    """(단계, Tavily 요청, 남길 결과 수). 첫 번째 원인 가설과 대상 연령으로만 검색어를 만든다."""
    cause = planning.causes[0].code if planning.causes else "C0_unknown"
    age = planning.profile.target.age_group
    domestic = f"{AGE_KO[age]} {CAUSE_KO[cause]} 사회적 고립 예방 프로그램 지자체 사례"
    overseas = f"{CAUSE_EN[cause]} social isolation intervention {AGE_EN[age]}"
    base = {"search_depth": "basic", "auto_parameters": False, "topic": "general", "include_answer": False,
            "include_raw_content": False, "include_usage": True}
    # 해외·연구는 기간을 두지 않는다. 검색 기간 옵션이 일·주·월·년 단위라 '최근 2년'을 지정할 수 없다.
    return [("domestic", {**base, "query": domestic, "max_results": 8, "time_range": "year"}, 5),
            ("overseas", {**base, "query": overseas, "max_results": 8}, 3)]


def safe_url(url) -> str | None:
    """https이고 계정·별도 포트가 없는 URL만. 조각(#…)은 지운다. 아니면 None."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password \
                or parts.port not in (None, 443):
            return None
        return urlunsplit(("https", parts.hostname, parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def grade(url: str) -> Literal["public", "research", "media", "other"]:
    """도메인으로 출처 등급을 정한다. 내용의 정확성 점수가 아니라 출처 종류 표시다."""
    host = urlsplit(url).hostname or ""

    def under(domains):
        return any(host == d.lstrip(".") or host.endswith(d if d.startswith(".") else "." + d) for d in domains)
    if under(RESEARCH):  # kci.go.kr처럼 공공 도메인 안의 학술 DB가 있어 연구를 먼저 본다
        return "research"
    if under(PUBLIC):
        return "public"
    if under(MEDIA) or host.startswith("news."):
        return "media"
    return "other"


def to_references(response: dict, limit: int) -> list[TrendReference]:
    """Tavily 응답 → TrendReference. 안전한 URL·내용이 있는 결과만 앞에서부터 limit개."""
    references, seen = [], set()
    for item in response.get("results", []) if isinstance(response, dict) else []:
        if not isinstance(item, dict):
            continue
        url, content = safe_url(item.get("url")), item.get("content")
        if not url or url in seen or not isinstance(content, str) or not content.strip():
            continue
        seen.add(url)
        # 연도는 검색 API가 날짜를 줄 때만 채운다. 본문에서 연도를 추측하지 않는다 (복지 추천과 같은 원칙).
        published = str(item.get("published_date") or "")
        year = int(published[:4]) if published[:4].isdigit() and 2000 <= int(published[:4]) <= 2100 else None
        references.append(TrendReference(title=(str(item.get("title") or url))[:200], url=url, year=year,
                                         grade=grade(url), summary=" ".join(TOC_DOTS.sub(" ", content).split())[:SUMMARY_CHARS]))
        if len(references) >= limit:
            break
    return references


def search_trends(ctx: NodeContext, planning, *, call=None) -> list[TrendReference]:
    """그래프 trend_search 노드의 계산 함수 (Engines.search_trends 자리).

    call: 테스트용 가짜 Tavily 호출 (요청, 설정) → 응답. 없으면 실제 검색을 한다.
    첫 검색이 실패하면 예외를 그대로 올린다 (노드가 실패를 기록하고 빈 목록으로 계속).
    두 번째가 실패하면 첫 결과는 살리고 경고만 남긴다. 실패 뒤에는 더 검색하지 않는다 (한도 초과 시 계속 두드리지 않음).
    """
    if ctx.mode == "offline":
        return []
    config = configuration()
    if call is None:
        if not config["search_key"].strip():
            raise AgentError("Tavily API 키가 없습니다. 프로젝트 .env에 TAVILY_API_KEY를 설정해주세요.", 503)
        call = lambda payload, settings: tavily_search(payload, settings, on_external_call=ctx.count)  # noqa: E731
    found, seen = [], set()
    for number, (stage, payload, limit) in enumerate(search_plan(planning)):
        try:
            response = call(payload, config)
        except AgentError as error:
            if number == 0:
                raise
            ctx.warn(f"{stage} 사례 검색 실패, 앞선 검색 결과만 사용합니다: {error}")
            break
        for reference in to_references(response, limit):
            if reference.url not in seen:
                seen.add(reference.url)
                found.append(reference)
    return found
