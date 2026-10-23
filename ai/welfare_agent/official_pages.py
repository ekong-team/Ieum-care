"""검색에서 찾은 공식 HTML 안내를 제한적으로 읽는다. 첨부·스크립트는 실행하지 않는다."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_PAGES = 2
MAX_BYTES = 1_200_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_official_html(url):
    # URL 검사는 enrich_evidence에서 수행한다. 리디렉션을 따라 새 주소를 수집하지 않는다.
    request = Request(url, headers={'User-Agent': 'Ieum-care-welfare/1.0', 'Accept': 'text/html'})
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('page_size_limit')
        return raw, response.headers.get('Content-Type', '')


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip, self.text = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'head', 'nav', 'footer', 'header', 'form'):
            self.skip.append(tag)

    def handle_endtag(self, tag):
        if self.skip and tag == self.skip[-1]:
            self.skip.pop()

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(' '.join(data.split()))


def enrich_evidence(evidence, validate_url, *, getter=None, on_external_call=None):
    """짧은 사업 안내를 먼저 최대 2개 읽고 성공·실패·미수집을 구분한다."""
    result = deepcopy(evidence)
    candidates = [item for item in result if item['source_kind'] == 'web_page']
    # 특정 프로그램 목록 대신 안내·신청 문구와 발췌 길이로 수집 순서를 결정한다.
    candidates.sort(key=lambda item: (
        not any(word in item['title'] for word in ('신청', '지원', '상담', '모집')),
        len(item['content']) >= 1000,
        item.get('recency_hint') == 'older_years_only',
    ))
    selected = candidates[:MAX_PAGES]
    for item in result:
        item['document'] = {'status': 'not_fetched'}
    for item in selected:
        if validate_url(item['url']) != item['url']:
            item['document'] = {'status': 'unavailable', 'reason': 'url_not_allowed'}
            continue
        try:
            if on_external_call:
                on_external_call('official_page')
            raw, content_type = (getter or fetch_official_html)(item['url'])
            if not isinstance(raw, bytes) or len(raw) > MAX_BYTES or 'html' not in content_type.lower():
                raise ValueError('unsupported_page')
            charset = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type, re.I)
            encoding = charset.group(1) if charset else 'utf-8'
            parser = PageText()
            parser.feed(raw.decode(encoding))
            text = '\n'.join(parser.text)
            if len(text) < 80:
                raise ValueError('insufficient_text')
            snippet = item['content']
            item['search_snippet'] = snippet
            item['content'] = '검색 발췌:\n' + snippet + '\n공식 HTML 본문 발췌:\n' + text[:10000]
            item['document'] = dict(status='html_excerpt', sha256=hashlib.sha256(raw).hexdigest(),
                                    text_characters=min(len(text), 10000), truncated=len(text) > 10000,
                                    fetched_at=datetime.now(timezone(timedelta(hours=9))).date().isoformat())
        except Exception:
            # 원문 응답·오류 문자열을 노출하지 않는다. 실패해도 기존 검색 발췌는 보존한다.
            item['document'] = {'status': 'unavailable', 'reason': 'page_read_failed'}
    return result
