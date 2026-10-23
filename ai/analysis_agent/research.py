"""부족한 정보별 검색 계획, 발췌 적합성 검사, 사람이 읽는 분석 설명."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
import hashlib
import json
import re
from urllib.parse import urlsplit, urljoin

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from ai.analysis_agent.model import EvidenceReview

QUESTIONS = {
    "population": "주민 인구·구성 변화가 함께 나타났는가?",
    "economy": "지역 경기·소비 전반의 변화가 함께 나타났는가?",
    "calendar": "공휴일·행사 같은 달력 요인을 확인할 수 있는가?",
}
KEYWORDS = {
    "population": ("인구", "주민등록", "세대", "전입", "전출"),
    "economy": ("경제", "경기", "소비", "상권", "소매", "관광", "방문객", "방문자"),
    "calendar": ("공휴일", "휴일", "행사", "축제", "월력", "성탄절", "기상", "계절", "기후", "기온"),
}

# 수동 원문 검토로 확보한 출처의 주소만 등록한다. 다른 기준월에 재사용하지 않는다.
# 검색 자동 발견과 구분하며 숫자는 입력 지표에 병합하지 않는다.
def known_sources(profile, question_id):
    if (profile.target.region, profile.period, question_id) != ('춘천시', '2025-12', 'economy'):
        return []
    return [dict(title='최근 강원지역 실물경제동향(2026.2월)',
        url='https://www.bok.or.kr/fileSrc/portal/3adafa1239c243f782ef5352d8edddb8/1/43cfd903ac08443db7c83214c06df39d.pdf',
        snippet='', published_date='2026-02-10', temporal_status='publication_after_target_period',
        verification='registered_official_url_not_yet_fetched', discovery='previously_reviewed_official_reference',
        reviewed_pages=[1, 3],
        expected_sha256='6a152956be45dde6655897865dfccb9a97a6e9e891e159c4a50e3c6dde183c17')]


class _DocumentHTML(HTMLParser):
    """정적 본문과 공개 PDF 링크만 읽는다. 스크립트·폼을 실행하지 않는다."""
    def __init__(self):
        super().__init__()
        self.text, self.links, self.anchor = [], [], None
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag == "a":
            self.anchor = [dict(attrs).get("href", ""), ""]

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.anchor is not None:
                self.anchor[1] += data

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)
        if tag == "a" and self.anchor is not None:
            self.links.append(tuple(self.anchor))
            self.anchor = None


class OfficialDocuments:
    """집단 실행당 GET4회·PDF2개·파일30MB까지. 키 없이 공식 자료만 수집한다."""
    def __init__(self, getter, cache=None):
        self.getter, self.cache = getter, Path(cache) if cache else None
        self.requests, self.pdfs = 0, 0
        self.receipts = []

    def _read(self, url, chain=()):
        from ai.analysis_agent.model import official_url
        if not official_url(url):
            raise ValueError("document_domain_not_allowed")
        if url in chain or len(chain) > 2:
            raise ValueError("document_redirect_limit")
        key = hashlib.sha256(url.encode()).hexdigest()
        if self.cache:
            path = self.cache / (key + ".bin")
            meta_path = self.cache / (key + ".json")
            if path.exists() and meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("url") != url or path.stat().st_size > 30_000_000:
                    raise ValueError("document_cache_invalid")
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != meta.get("sha256"):
                    raise ValueError("document_cache_hash_changed")
                self.receipts.append(dict(url=url, status="cache_hit", sha256=meta["sha256"], bytes=len(raw)))
                return raw, meta.get("content_type", "")
        if self.requests >= 4:
            raise ValueError("document_request_limit")
        self.requests += 1
        record = dict(url=url, status="attempted")
        self.receipts.append(record)
        try:
            raw, content_type = self.getter(url)
            if not isinstance(raw, bytes) or len(raw) > 30_000_000:
                raise ValueError("document_size_limit")
            meta = dict(url=url, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                        content_type=content_type, retrieved_at=datetime.now(timezone.utc).isoformat())
            record.update(status="downloaded", sha256=meta["sha256"], bytes=len(raw))
            if self.cache:
                self.cache.mkdir(parents=True, exist_ok=True)
                (self.cache / (key + ".bin")).write_bytes(raw)
                (self.cache / (key + ".json")).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            return raw, content_type
        except Exception as error:
            record.update(status="failed", error_type=type(error).__name__)
            if isinstance(error, HTTPError) and error.code in (301, 302, 303, 307, 308):
                target = urljoin(url, error.headers.get("Location", ""))
                error.close()
                if not official_url(target):
                    raise ValueError("document_redirect_domain_not_allowed") from None
                record.update(status="redirect", redirect_url=target)
                return self._read(target, chain + (url,))
            raise

    def _extract(self, url):
        raw, content_type = self._read(url)
        digest = hashlib.sha256(raw).hexdigest()
        if raw.startswith(b"%PDF"):
            if self.pdfs >= 2:
                raise ValueError("document_pdf_limit")
            self.pdfs += 1
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw))
            if reader.is_encrypted or len(reader.pages) > 150:
                raise ValueError("document_pdf_not_supported")
            pages = [(i+1, (page.extract_text() or "")[:20_000]) for i, page in enumerate(reader.pages)]
            return pages, [], digest, "pdf_text" if any(t.strip() for _, t in pages) else "image_only_requires_review"
        if len(raw) > 2_000_000 or ("html" not in content_type.lower() and not raw.lstrip().startswith((b"<!", b"<html"))):
            raise ValueError("document_type_not_supported")
        match = re.search(r"charset\s*=\s*([\w-]+)", content_type, re.I)
        encoding = match.group(1) if match else "utf-8"
        parser = _DocumentHTML()
        parser.feed(raw.decode(encoding, errors="replace"))
        links = [urljoin(url, href) for href, title in parser.links if ".pdf" in (href + title).lower()]
        return [(None, "\n".join(parser.text))], links, digest, "html_text"

    def enrich(self, source, profile, question_id):
        """검색 후보에 실제 본문 발췌와 출처 페이지를 붙인다. 숫자는 자동 병합하지 않는다."""
        from ai.analysis_agent.model import official_url
        result = dict(source)
        start = len(self.receipts)
        try:
            pages, links, digest, status = self._extract(source["url"])
            if source.get('expected_sha256') and source['expected_sha256'] != digest:
                raise ValueError('registered_document_changed')
            document_url = source["url"]
            if status == "html_text" and self.pdfs < 2:
                for link in links[:2]:
                    if not official_url(link):
                        continue
                    try:
                        pages, _, digest, status = self._extract(link)
                        document_url = link
                        break
                    except Exception:
                        continue
            year, month = profile.period.split("-")
            pattern = rf"{year}\s*(?:년|[-./])\s*0?{int(month)}\s*(?:월|[^0-9]|$)"
            def score(entry):
                text = compact(entry[1])
                return (4 * bool(re.search(pattern, entry[1])) +
                        4 * (profile.target.region.removesuffix("시").removesuffix("구") in text) +
                        2 * any(word in text for word in KEYWORDS[question_id]))
            # 등록된 원문도 실제로 읽고 검사한다. 3쪽은 사전 표 검토로 확인한 소비 본문이다.
            selected = ([page for page in pages if page[0] in source['reviewed_pages']][:2] if
                source.get('expected_sha256') and source.get('reviewed_pages') else
                sorted(pages, key=score, reverse=True)[:2])
            excerpts = []
            page_budget = (1500 - max(0, len(selected)-1)) // max(1, len(selected))
            for _, text in selected:
                match = re.search(pattern, text)
                offset = max(0, match.start()-100) if match else 0
                excerpts.append(text[offset:offset+page_budget])
            result.update(discovery_url=source["url"], url=document_url,
                snippet="\n".join(excerpts)[:1500] if status != "image_only_requires_review" else "",
                verification="document_text_not_independent_fact_check",
                document=dict(status=status, sha256=digest, pages=[n for n, _ in selected if n],
                    table_alignment="not_verified", collection="automatic_official_fetch"))
        except Exception as error:
            result["document"] = dict(status="unavailable", error_type=type(error).__name__)
            if source.get('expected_sha256'):
                result['snippet'] = ''
        result["document_receipts"] = self.receipts[start:]
        return result


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: Literal["population", "economy", "calendar"]
    source_id: str = Field(max_length=10)
    quote: str = Field(min_length=20, max_length=400)
    relevance: str = Field(min_length=1, max_length=500)


class FocusedSelection(EvidenceReview):
    source_ids: list[str] = Field(default_factory=list, max_length=9)
    findings: list[Finding] = Field(default_factory=list, max_length=3)


class ResearchTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question_id: Literal["population", "economy", "calendar"]
    question: str = Field(min_length=1, max_length=240)
    search_terms: str = Field(min_length=1, max_length=120)


class ResearchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    search_needed: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=500)
    tasks: list[ResearchTask] = Field(max_length=2)

    @model_validator(mode="after")
    def consistent(self):
        if self.search_needed != bool(self.tasks):
            raise ValueError("검색 여부와 질문 목록이 다릅니다.")
        ids = [task.question_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("검색 질문이 중복입니다.")
        for task in self.tasks:
            if any(char in task.search_terms for char in ("\n", "\r", "@")) or "://" in task.search_terms:
                raise ValueError("검색어에는 공개 주제만 사용합니다.")
            if not any(word in task.search_terms for word in KEYWORDS[task.question_id]):
                raise ValueError("검색어가 질문 주제와 맞지 않습니다.")
        return self


def research_options(cohort):
    """관측 부족은 웹으로 대체하지 않는다. 이미 확보한 배경은 검색 누락과 구분한다."""
    profile = cohort["profile"]
    values = cohort["background_context"].get("values", {})
    known, gaps = [], []
    if profile["risk"]["status"] != "complete":
        return dict(eligible=False, reason="부분판정·보류는 원본 관측 보완이 먼저이며 웹으로 대체하지 않습니다.", known=[], gaps=[])
    if not profile["signals"]:
        return dict(eligible=False, reason="현재 감소 신호가 없어 자동 원인 검색을 생략합니다.", known=[], gaps=[])
    if all(values.get(key) is not None for key in ("resident_population", "prior_resident_population", "population_mom_change")):
        known.append("같은 집단의 주민인구와 전월 변화 확보. 주민과 방문객 모집단은 다름.")
    else:
        gaps.append(dict(question_id="population", reason="같은 기준월·지역의 인구 변화 배경이 부족함"))
    calendar = values.get("calendar_context") or {}
    if calendar.get("days") is not None and calendar.get("weekend_or_holiday_days") is not None:
        known.append("달 길이·휴일 수 확보. 같은 달력 수치 재검색은 불필요하며 지역 행사·기상·계절 효과는 미확인.")
    gaps.append(dict(question_id="calendar", reason="관측 활동 변화와 겹치는 지역 행사·기상·계절 배경은 미확인. 기본 휴일 수와 구분."))
    gaps.append(dict(question_id="economy", reason="지역 전체 소비 변화의 배경을 설명할 공식 경기·상권 자료는 미확인"))
    return dict(eligible=True, reason="원인 설명에 필요한 미확인 배경을 검토합니다.", known=known, gaps=gaps)


def adaptive_query(profile, task, *, retry=False):
    """지역·기준월과 공식 도메인은 코드가 고정하고 주제어는 모델이 선택한다."""
    plan = next(p for p in search_plan(profile) if p["question_id"] == task["question_id"])
    year, month = profile.period.split("-")
    terms = task["search_terms"]
    if retry:
        terms = {"population": "주민등록 인구 현황 통계표 본문",
                 "economy": "지역경제동향 소비 상권 통계 보고서",
                 "calendar": "지역 행사 기상 월간 보고서 일정"}[task["question_id"]]
    payload = dict(plan["payload"])
    payload["query"] = f"{profile.target.region} {year}년 {int(month)}월 {terms}"
    if retry and terms == task["search_terms"]:
        payload["query"] += " 원문 세부자료"
    if retry and task["question_id"] == "economy":
        parent = {"춘천시": "강원", "강남구": "서울"}[profile.target.region]
        payload["query"] = f"{parent} {year}년 {int(month)}월 실물경제동향 소비 관광 보고서"
    return payload


def search_plan(profile):
    """사후 해석용 검색. 익월 발표 자료도 찾되 과거 실시간 검증으로 표시하지 않는다."""
    year, month = map(int, profile.period.split("-"))
    region = profile.target.region
    cutoff = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    prefix = f"{region} {year}년 {month}월"
    plans = []
    for key, terms, domains in (
        ("population", "주민등록 인구 현황 월별 통계", ["chuncheon.go.kr", "gangnam.go.kr", "mois.go.kr", "kosis.kr", "kostat.go.kr"]),
        ("economy", "지역 경제 동향 소비 소매판매 보고서", ["chuncheon.go.kr", "gangnam.go.kr", "kostat.go.kr", "kosis.kr", "bok.or.kr", "gwto.or.kr"]),
        ("calendar", "공휴일 월력요항 행사 일정", ["chuncheon.go.kr", "gangnam.go.kr", "kasi.re.kr", "kma.go.kr"]),
    ):
        # 전국 공휴일은 지역명을 필수 검색어로 넣으면 누락될 수 있다.
        if key == "population":
            query = f"{region} {year}년 {month}월말 주민등록 인구 현황 통계표"
        elif key == "calendar":
            query = f"{year}년 {month}월 공휴일 휴일 날짜 월력요항"
        else:
            query = f"{prefix} {terms}"
        plans.append(dict(question_id=key, question=QUESTIONS[key], payload=dict(
            query=query, topic="general", search_depth="basic", auto_parameters=False,
            max_results=3, include_domains=domains, include_answer=False,
            include_raw_content=False, include_images=False, include_usage=True,
            include_published_date=True, filter_by_published_date=True, end_date=cutoff)))
    return plans


def compact(text):
    return re.sub(r"\s+", "", text).lower()


def source_scope(source, profile, question_id):
    """문자열 기반 최소 적합성 검사다. 통계 기준·인과관계의 사실 검증이 아니다."""
    # 페이지 수정일은 통계 기준월이 아니다. 메뉴의 단어도 주제 근거로 승격하지 않는다.
    content = re.sub(
        r"(?:최종\s*수정일|수정일|작성일|등록일|게시일|입력일)\s*[:：]?\s*\d{4}[-./]\d{1,2}[-./]\d{1,2}",
        "", source["title"] + " " + source["snippet"],
    )
    text = compact(content)
    title = compact(source["title"])
    year, month = profile.period.split("-")
    period_markers = (f"{year}년{int(month)}월", f"{year}-{month}", f"{year}.{month}",
                      f"{year}.{int(month)}", f"{year}/{month}", f"{year}{month}")
    period_match = any(marker in text for marker in period_markers)
    region_match = profile.target.region.removesuffix("시").removesuffix("구") in text
    topic_match = any(word in text for word in KEYWORDS[question_id])
    navigation_heavy = sum(word in text for word in (
        "시정정보", "고시/공고", "채용정보", "조직인사정보", "바로가기", "최근이용서비스",
    )) >= 3
    menu_topic_only = navigation_heavy and not any(word in title for word in KEYWORDS[question_id])
    if menu_topic_only:
        topic_match = False
    parts = urlsplit(source["url"])
    path = parts.path.rstrip("/").lower()
    is_index = path.rsplit("/", 1)[-1] in ("index.do", "index.html", "index.jsp", "main.do", "main")
    listing_page = (bool(re.search(r"총\d+건의게시물", text)) or
                    ("번호제목" in text and "작성자작성일" in text) or
                    ("현재페이지" in text and "다음" in text and "마지막" in text))
    detail_page = bool(path or parts.query) and not is_index and not listing_page
    national_calendar = question_id == "calendar" and any(word in text for word in ("공휴일", "월력요항"))
    document_status = source.get("document", {}).get("status")
    parent = {"춘천시": "강원", "강남구": "서울"}[profile.target.region]
    wider = (document_status in ("pdf_text", "html_text") and parent in title and parent in text
             and profile.target.region.removesuffix("시").removesuffix("구") not in title)
    reasons = []
    if not detail_page: reasons.append("일반 홈페이지여서 구체적 통계표·보고서가 아님")
    if listing_page: reasons.append("게시판 목록이므로 개별 통계표 본문을 확인해야 함")
    if not period_match: reasons.append("발췌에서 분석 기준월을 확인하지 못함")
    if not (region_match or national_calendar or wider): reasons.append("발췌에서 대상 지역을 확인하지 못함")
    if not topic_match: reasons.append("질문에 맞는 주제 표현을 확인하지 못함")
    if menu_topic_only: reasons.append("주제 단어가 메뉴에 있으나 페이지 제목은 해당 자료가 아님")
    if document_status == "image_only_requires_review": reasons.append("이미지형 PDF여서 본문을 읽지 못함·별도 확인 필요")
    if source.get('expected_sha256') and document_status == 'unavailable':
        reasons.append('등록된 원문의 해시·본문 재확인 실패')
    return dict(status="reference_candidate" if not reasons else "discovery_only",
                region_text_match=region_match, period_text_match=period_match,
                topic_text_match=topic_match, detail_page=detail_page,
                national_calendar=national_calendar, listing_page=listing_page, reasons=reasons,
                geographic_scope="wider_region_context" if wider else "target_or_national_context",
                limitation="문자열 검사 통과도 수치·통계 단위·인과관계의 사실 검증을 뜻하지 않음")


def collect_context(profile, transport, key, receipt):
    from ai.analysis_agent.model import sources_from, ExternalCallError
    receipt.update(research_mode="focused", temporal_use="retrospective_not_historical_live_backtest",
                   search_questions=[], sources=[], search_usage={"credits": 0})
    plans = search_plan(profile)
    for index, plan in enumerate(plans):
        record = dict(question_id=plan["question_id"], question=plan["question"],
                      query=plan["payload"]["query"], status="attempted", source_ids=[])
        receipt["search_questions"].append(record)
        receipt["search_attempts"] += 1
        try:
            response = transport("https://api.tavily.com/search", {"Authorization": "Bearer " + key}, plan["payload"])
            found = sources_from(response, plan["payload"]["end_date"])
            for source in found:
                source["id"] = f"S{len(receipt['sources'])+1}"
                source["question_id"] = plan["question_id"]
                source["scope_check"] = source_scope(source, profile, plan["question_id"])
                source["publication_after_target_period"] = bool(source["published_date"] and source["published_date"][:7] > profile.period)
                receipt["sources"].append(source)
                record["source_ids"].append(source["id"])
                if len(record["source_ids"]) == 3: break
            credits = response.get("usage", {}).get("credits")
            record["reported_credits"] = credits if type(credits) in (int, float) else None
            if type(credits) in (int, float): receipt["search_usage"]["credits"] += credits
            record["status"] = "results" if record["source_ids"] else "no_usable_results"
        except Exception as error:
            record.update(status="failed", error_code=str(error) if isinstance(error, ExternalCallError) else type(error).__name__)
            if isinstance(error, ExternalCallError) and str(error) in ("http_401", "http_403", "http_402", "http_429", "http_432", "http_433"):
                for remaining in plans[index+1:]:
                    receipt["search_questions"].append(dict(question_id=remaining["question_id"],
                        question=remaining["question"], query=remaining["payload"]["query"],
                        status="not_run_auth_or_quota_limit", source_ids=[]))
                break
    failed = sum(question["status"] == "failed" for question in receipt["search_questions"])
    receipt["search_status"] = "failed" if failed and not receipt["sources"] else "partial_failure" if failed else "results" if receipt["sources"] else "no_usable_results"


def check_findings(selection, sources):
    """번호·질문·인용을 대조한다. 홈페이지를 선택해도 분석 근거로 승격하지 않는다."""
    indexed = {source["id"]: source for source in sources}
    accepted, rejected, seen = [], [], set()
    for finding in selection.findings:
        reason = None
        source = indexed.get(finding.source_id)
        if finding.question_id in seen: reason = "duplicate_question"
        elif not source or finding.source_id not in selection.source_ids: reason = "unknown_or_unselected_source"
        elif source.get("question_id") != finding.question_id: reason = "question_source_mismatch"
        elif source["scope_check"]["status"] != "reference_candidate": reason = "insufficient_source_scope"
        elif not compact(finding.quote) or compact(finding.quote) not in compact(source["snippet"]): reason = "quote_not_in_excerpt"
        if reason:
            rejected.append(dict(question_id=finding.question_id, source_id=finding.source_id, reason=reason))
        else:
            seen.add(finding.question_id)
            accepted.append(dict(**finding.model_dump(), status="quoted_reference_candidate",
                                 interpretation_status="model_interpretation_not_independently_verified"))
    return accepted, rejected


def validate_research_receipt(receipt, profile):
    """저장 후에도 범위·인용 검사를 반복한다. 실제 원문 사실 확인과는 구분한다."""
    if receipt.get("research_mode") not in ("focused", "adaptive"): return
    adaptive = receipt["research_mode"] == "adaptive"
    if not 0 <= receipt["search_attempts"] <= 3 or not 0 <= receipt["gemini_attempts"] <= (2 if adaptive else 1):
        raise ValueError("research_call_limit")
    if adaptive:
        if not 0 <= receipt.get("document_requests", 0) <= 4:
            raise ValueError("document_request_limit")
        decision = ResearchDecision.model_validate(receipt["research_decision"])
        planned = {task.question_id for task in decision.tasks}
        if len(receipt["search_questions"]) != receipt["search_attempts"]:
            raise ValueError("research_search_count_changed")
        if receipt["planner_attempts"] not in (0, 1) or receipt["review_attempts"] not in (0, 1) or (
                receipt["planner_attempts"] + receipt["review_attempts"] != receipt["gemini_attempts"]):
            raise ValueError("research_model_count_changed")
        for question in receipt["search_questions"]:
            if question["question_id"] not in planned or question["attempt"] not in (1, 2):
                raise ValueError("research_task_changed")
        pairs = [(q["question_id"], q["attempt"]) for q in receipt["search_questions"]]
        if len(pairs) != len(set(pairs)):
            raise ValueError("research_retry_limit")
    sources = receipt["sources"]
    ids = {s["id"] for s in sources}
    if len(ids) != len(sources) or len(sources) > 9:
        raise ValueError("duplicate_or_excessive_sources")
    selected = receipt["selected_source_ids"]
    if len(selected) != len(set(selected)) or not set(selected) <= ids:
        raise ValueError("invalid_selected_sources")
    for source in sources:
        if source.get("question_id") not in QUESTIONS or source["scope_check"] != source_scope(source, profile, source["question_id"]):
            raise ValueError("source_scope_changed")
    expected = receipt.get("research_findings", [])
    selection = FocusedSelection(source_ids=selected, findings=[
        {key:f[key] for key in ("question_id", "source_id", "quote", "relevance")} for f in expected])
    accepted, rejected = check_findings(selection, sources)
    if rejected or accepted != expected:
        raise ValueError("research_quote_or_scope_changed")


def explain_bundle(bundle):
    """수치는 기존 프로필에서 읽고 외부 해석은 별도로 표시한다."""
    lines = ["# 데이터 분석 에이전트 결과 설명", "",
             "기존 데이터로 계산한 결과와 외부 검색의 보완 내용을 구분해 읽는 보고서입니다.", ""]
    receipts = bundle["execution"]["model_receipts"]
    selected = {r["analysis_id"] for r in receipts if r.get("provider") == "gemini"}
    cohorts = [c for c in bundle["cohorts"] if c["analysis_id"] in selected]
    if not cohorts:
        lines += ["이번 실행은 외부 검색·Gemini 검토를 수행하지 않았습니다. 외부 근거가 보강됐다고 해석하지 마세요."]
        first_ids = {item["analysis_id"] for item in bundle["priority_review"]["ranked_cohorts"] if item["rank"] == 1}
        cohorts = [c for c in bundle["cohorts"] if c["analysis_id"] in first_ids]
        lines += ["", "아래는 해당 기준월 공동1순위 집단의 기존 계산 결과입니다.", ""]
    for cohort in cohorts:
        p = cohort["profile"]
        sex = {"female":"여성", "male":"남성", "all":"남녀 합산"}[p["target"]["sex"]]
        age = "60세 이상" if p["target"]["age_group"] == 60 else f"{p['target']['age_group']}대"
        status = {"complete":"판정 완료", "partial":"일부 조건만 판단", "held":"자료 부족으로 보류"}[p["risk"]["status"]]
        lines += [f"## {p['period']} · {p['target']['region']} · {age} · {sex}", "",
                  "### 1. 원래 데이터에서 확인한 결과", "",
                  f"- 활동 위축 검토 단계: {p['risk']['level']} / 판정 상태: {status}"]
        for evidence in p["evidence"]:
            value = f"{evidence['value']*100:+.2f}%" if evidence["unit"] == "ratio" else f"{evidence['value']:g}"
            lines.append(f"- {evidence['name']}: {value}")
        lines += ["", "이 계산은 파이썬이 수행했습니다. Gemini가 계산·진단한 결과가 아니며 사회적 고립 확정 등급도 아닙니다.", "",
                  "### 2. 왜 이 단계가 나왔는가", "", cohort["assessment"]["reason"], "",
                  f"기본 감소 기준은 각 지표 전월 대비 {bundle['method']['decline_ratio']*100:g}%입니다. "
                  "동시 감소가 전월 비교 두 번 이어졌는지 판단하려면 원자료 세 달이 필요합니다. 이 기준은 프로젝트의 시범 규칙입니다.", "",
                  "이미 확보한 배경자료도 함께 보면 다음과 같습니다.", ""]
        values = cohort["background_context"].get("values", {})
        current, previous = values.get("resident_population"), values.get("prior_resident_population")
        change = values.get("population_mom_change")
        if current is not None and previous is not None:
            change_label = f" ({change*100:+.3f}%)" if change is not None else ""
            lines.append(f"- 해당 지역·연령·성별 주민등록 인구: 전월 {previous:,}명 → 해당 월 {current:,}명{change_label}.")
        calendar = values.get("calendar_context", {})
        if calendar:
            lines.append(f"- 해당 월은 {calendar.get('days')}일, 주말·공휴일 합계 {calendar.get('weekend_or_holiday_days')}일입니다.")
        lines += [f"- {text}" for text in cohort["interpretation"]["contextual_observations"]]
        lines += ["- 주민등록 인구와 통신·카드의 활동지역 집계는 대상이 다릅니다. 위 비교만으로 감소 원인을 확정할 수 없습니다.", "",
                  "### 3. 무엇을 더 확인하려고 검색했는가", ""]
        for receipt in [r for r in receipts if r["analysis_id"] == cohort["analysis_id"] and r.get("provider") == "gemini"]:
            lines += [f"- 이번 집단의 Tavily 검색 시도: {receipt.get('search_attempts', 0)}회 / "
                      f"Gemini 검토 시도: {receipt.get('gemini_attempts', 0)}회", ""]
            lines.append(f"- 공식 문서 GET 시도: {receipt.get('document_requests', 0)}회. 검색·모델 API 호출과 별도로 집계합니다.")
            for source in receipt.get("sources", []):
                document = source.get("document")
                if not document:
                    continue
                label = {"pdf_text":"PDF 텍스트 추출", "html_text":"정적 HTML 본문 추출",
                         "deferred":"등록 출처 우선 수집으로 본문 수집 보류·검색 발췌만 있음",
                         "image_only_requires_review":"이미지형 PDF·본문 미확인", "unavailable":"본문 수집 실패·검색 발췌만 보존"}.get(document["status"], document["status"])
                pages = ", ".join(map(str, document.get("pages", []))) or "해당 없음"
                lines.append(f"- {source['id']}: {label} / PDF 페이지: {pages}. 표 행·열 대응은 미검증이며 광역 수치는 집단 수치가 아닙니다.")
            if receipt.get("research_mode") == "adaptive":
                decision = receipt["research_decision"]
                stop_labels = {"not_needed":"기존 자료·관측 상태에 따라 검색 생략",
                    "model_not_needed":"모델이 추가 검색 불필요로 판단", "planning_failed":"검색 계획 검증 실패",
                    "candidate_sources_available":"계획한 질문의 최소 출처 후보 확보·사실 검증 전",
                    "search_budget_exhausted":"검색 호출 한도 도달·미확인 사항 보존",
                    "no_more_usable_sources":"재검색 종료·추가 근거 미확보", "auth_or_quota_limit":"인증·호출 한도로 검색 중단"}
                lines += [f"- 검색 필요 판단: {'필요' if decision['search_needed'] else '생략'} — {decision['reason']}",
                          f"- Gemini 호출 구성: 계획 {receipt['planner_attempts']}회 + 최종 검토 {receipt['review_attempts']}회",
                          f"- 검색 종료 사유: {stop_labels.get(receipt.get('search_stop_reason'), '검토 완료')}", ""]
                for task in decision["tasks"]:
                    lines.append(f"- 선택한 질문: {task['question']}")
            for question in receipt.get("search_questions", []):
                label = {"results":"검색 발췌 수신", "no_usable_results":"사용할 검색 발췌 없음", "failed":"검색 실패",
                         "not_run_auth_or_quota_limit":"키·한도 문제로 실행하지 않음"}.get(question["status"], question["status"])
                lines += [f"- {question['question']} — {label}"]
            if not receipt.get("search_questions"):
                lines += [f"- 검색어: {receipt.get('search_query', '검색 미실행')}"]
            lines += ["", "### 4. 외부 자료가 실제로 보완한 내용", ""]
            accepted = receipt.get("research_findings", [])
            for finding in accepted:
                source = next(s for s in receipt["sources"] if s["id"] == finding["source_id"])
                lines += [f"- 질문: {QUESTIONS[finding['question_id']]}",
                          f"  - 제공된 검색·문서 발췌에서 확인한 문장: {finding['quote']}",
                          f"  - 모델의 관련성 해석(별도 사실 검증 전): {finding['relevance']}",
                          f"  - 출처: [{source['title']}]({source['url']})",
                          "  - 상태: 인용·최소 범위 검사를 통과한 참고 후보. 인과관계나 새 수치 지표로 반영하지 않음."]
            missing = set(QUESTIONS) - {f["question_id"] for f in accepted}
            for question in QUESTIONS:
                if question in missing:
                    planned = {task["question_id"] for task in receipt.get("research_decision", {}).get("tasks", [])}
                    if receipt.get("research_mode") == "adaptive" and question not in planned:
                        lines.append(f"- {QUESTIONS[question]} → 이번 검색 대상에서 제외했습니다. 기존 배경 또는 필요성 판단을 참고하세요.")
                    else:
                        lines.append(f"- {QUESTIONS[question]} → 구체적인 보완 근거를 확보하지 못했습니다.")
            lines += ["", "### 5. 찾았지만 분석 근거로 쓰기 어려운 자료", ""]
            weak = [s for s in receipt.get("sources", []) if s.get("scope_check", {}).get("status") != "reference_candidate"]
            if not weak:
                lines.append("- 해당 항목이 없습니다. 참고 후보도 독립적인 사실 검증이 완료된 자료는 아닙니다.")
            for source in weak:
                reasons = source.get("scope_check", {}).get("reasons", ["질문·지역·기준월 검사를 수행하지 않은 이전 검색 결과"])
                lines.append(f"- [{source['title']}]({source['url']}): {'; '.join(reasons)}")
            lines += ["", "### 6. 그래서 무엇이 달라졌는가", "",
                      f"- 검토 가능한 외부 인용 후보: {len(accepted)}개. 새로운 숫자 데이터를 자동으로 추가한 것은 아닙니다.",
                      "- 위험 단계와 우선순위는 기존 계산 기준을 유지합니다.",
                      "- 검색·모델 실패는 위험이 없다는 뜻이 아닙니다. 자료 부족으로 남깁니다.",
                      "- 이 검색은 사후 해석용입니다. 발표 시점·통계 기준월 확인 없이 과거 실시간 판단에 사용하면 안 됩니다.", ""]
            review = cohort["interpretation"]["model_review"]
            evidence_names = {entry["id"]: entry["name"] for entry in p["evidence"]}
            hypotheses = {item["code"]: item["label"] for item in cohort["interpretation"]["hypotheses"]}
            lines += ["- Gemini가 검토에서 선택한 기존 근거: " +
                      ", ".join(evidence_names[code] for code in review["selected_observation_ids"]),
                      "- Gemini가 추가 확인 대상으로 선택한 기존 가설: " +
                      ", ".join(hypotheses[code] for code in review["selected_hypothesis_codes"])]
            if not accepted:
                lines += ["- 외부 근거로 원인 설명을 보강하지 못했습니다. 이번 검토의 추가 결과는 기존 근거·가설의 선택과 아래 확인 질문입니다."]
            lines += [""]
        review = cohort["interpretation"]["model_review"]
        review_label = {"executed":"실제 Gemini 검토 완료(원인 확정 아님)", "fixture_only":"가상 응답으로 동작 점검",
                        "failed":"외부 검토 실패·기존 분석 유지", "not_run":"외부 검토 미실행"}[review["status"]]
        lines += ["### 7. 담당자가 다음에 확인할 사항", "", f"모델 검토 상태: {review_label}", ""]
        lines += [f"- {question}" for question in review["questions"]]
        lines += ["- 원본 통계표의 단위·지역·기준월·이용 조건을 확인한 뒤 추가 지표 채택 여부를 결정합니다.", ""]
    return "\n".join(lines) + "\n"
