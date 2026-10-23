"""검색에서 찾은 공식 HTML 안내를 제한적으로 읽는다. 첨부·스크립트는 실행하지 않는다."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_PAGES = 2
MAX_BYTES = 1_200_000
MAX_HTTP_REQUESTS = 4  # 안내 2개 × 원주소 및 정규 주소 이동 각 1회


class PageReadError(ValueError):
    """원문 응답이나 예외 문자열 대신 공개 가능한 고정 오류 코드만 전달한다."""
    pass


def failure_info(error):
    if isinstance(error, HTTPError):
        return dict(reason='redirect_blocked' if 300 <= error.code < 400 else 'http_error', http_status=error.code)
    if isinstance(error, URLError):
        if not isinstance(error.reason, (TimeoutError, ssl.SSLError)):
            return dict(reason='connection_failed')
        error = error.reason
    if isinstance(error, TimeoutError):
        return dict(reason='timeout')
    if isinstance(error, ssl.SSLError):
        return dict(reason='tls_error')
    if isinstance(error, UnicodeError):
        return dict(reason='decode_failed')
    if isinstance(error, LookupError):
        return dict(reason='unsupported_encoding')
    if isinstance(error, PageReadError) and error.args and error.args[0] in (
            'page_size_limit', 'non_html', 'invalid_body', 'insufficient_text',
            'redirect_not_allowed', 'redirect_limit', 'request_limit', 'redirect_missing_location'):
        return dict(reason=error.args[0])
    if isinstance(error, OSError):
        return dict(reason='connection_failed')
    return dict(reason='page_read_failed')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_official_html(url):
    # 자동 이동은 끈다. 수집기가 목적지와 횟수를 검사한 뒤 별도 GET한다.
    request = Request(url, headers={'User-Agent': 'Ieum-care-welfare/1.0', 'Accept': 'text/html'})
    with build_opener(NoRedirect()).open(request, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise PageReadError('page_size_limit')
        return raw, response.headers.get('Content-Type', '')


def canonical_redirect(original, target, validate_url):
    """같은 호스트·같은 경로·같은 질의의 정규 주소 이동만 허용한다 (예: 끝의 /)."""
    valid = validate_url(target)
    if not valid:
        return None
    before, after = urlsplit(original), urlsplit(valid)
    if (before.hostname != after.hostname or before.path.rstrip('/') != after.path.rstrip('/')
            or sorted(parse_qsl(before.query, keep_blank_values=True)) != sorted(parse_qsl(after.query, keep_blank_values=True))):
        return None
    return valid


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
        item['search_snippet'] = item['content']
        item['evidence_availability'] = dict(search_excerpt=bool(item['content'].strip()), official_html_excerpt=False)
        item['document'] = {'status': 'not_fetched'}
    requests = 0
    for item in selected:
        if validate_url(item['url']) != item['url']:
            item['document'] = {'status': 'unavailable', 'reason': 'url_not_allowed'}
            continue
        try:
            current, redirects = item['url'], []
            while True:
                if requests >= MAX_HTTP_REQUESTS:
                    raise PageReadError('request_limit')
                requests += 1
                if on_external_call:
                    on_external_call('official_page')
                try:
                    raw, content_type = (getter or fetch_official_html)(current)
                    break
                except HTTPError as error:
                    if error.code not in (301, 302, 303, 307, 308):
                        raise
                    if redirects:
                        raise PageReadError('redirect_limit') from None
                    location = error.headers.get('Location') if error.headers else None
                    if not location:
                        raise PageReadError('redirect_missing_location') from None
                    target = canonical_redirect(current, urljoin(current, location), validate_url)
                    if not target or target == current:
                        raise PageReadError('redirect_not_allowed') from None
                    redirects.append(dict(from_url=current, to_url=target, http_status=error.code))
                    current = target
            if not isinstance(raw, bytes):
                raise PageReadError('invalid_body')
            if len(raw) > MAX_BYTES:
                raise PageReadError('page_size_limit')
            if 'html' not in content_type.lower():
                raise PageReadError('non_html')
            charset = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type, re.I)
            # 헤더에 없으면 HTML에 명시된 인코딩만 따른다. 실패 시 임의 인코딩으로 재시도하지 않는다.
            meta = re.search(rb'<meta[^>]+charset\s*=\s*["\']?([\w-]+)', raw[:4096], re.I)
            encoding = charset.group(1) if charset else meta.group(1).decode('ascii') if meta else 'utf-8-sig'
            parser = PageText()
            parser.feed(raw.decode(encoding))
            text = '\n'.join(parser.text)
            if len(text) < 80:
                raise PageReadError('insufficient_text')
            snippet = item['content']
            item['search_snippet'] = snippet
            item['content'] = '검색 발췌:\n' + snippet + '\n공식 HTML 본문 발췌:\n' + text[:10000]
            item['document'] = dict(status='html_excerpt', sha256=hashlib.sha256(raw).hexdigest(),
                                    text_characters=min(len(text), 10000), truncated=len(text) > 10000,
                                    fetched_at=datetime.now(timezone(timedelta(hours=9))).date().isoformat(),
                                    final_url=current, redirects=redirects)
            item['evidence_availability']['official_html_excerpt'] = True
        except Exception as error:
            # 원문 응답·오류 문자열을 노출하지 않는다. 실패해도 기존 검색 발췌는 보존한다.
            item['document'] = dict(status='unavailable', **failure_info(error), redirects=redirects)
    return result
