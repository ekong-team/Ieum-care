"""공식 HTML 보완 수집은 실제 네트워크 없이 제한·실패·근거 보존을 검사한다."""
import copy
import unittest
from unittest.mock import Mock, MagicMock, patch
from urllib.error import HTTPError

from ai.welfare_agent.live_agent import official_url
from ai.welfare_agent.official_pages import enrich_evidence, fetch_official_html, MAX_BYTES, NoRedirect


def page(url, title='신청 안내', content='짧은 검색 발췌'):
    return dict(url=url, title=title, content=content, source_kind='web_page', recency_hint='current_year_mentioned')


class OfficialPagesTests(unittest.TestCase):
    def test_bounded_html_enrichment_keeps_snippet_and_never_reads_directory_or_pdf(self):
        evidence = [page(f'https://www.chuncheon.go.kr/service{i}') for i in range(3)]
        evidence += [{**page('https://www.chuncheon.go.kr/cityhall'), 'source_kind':'directory'},
                     {**page('https://www.chuncheon.go.kr/guide.pdf'), 'source_kind':'reference_document'}]
        before = copy.deepcopy(evidence)
        html = ('<html><head>제외할 머리말</head><body><nav>제외할 메뉴</nav><script>위험한 지시문</script>'
                '<main><h1>지원사업 신청 안내</h1><p>' + '지원대상은 시민이며 소득·거주 요건을 확인해야 합니다. ' * 8 +
                '</p></main><footer>제외할 꼬리말</footer></body></html>').encode()
        getter = Mock(return_value=(html, 'text/html; charset=utf-8'))
        calls = []
        result = enrich_evidence(evidence, official_url, getter=getter, on_external_call=calls.append)
        self.assertEqual(evidence, before)
        self.assertEqual(getter.call_count, 2)
        self.assertEqual(calls, ['official_page', 'official_page'])
        self.assertEqual(result[0]['document']['status'], 'html_excerpt')
        self.assertEqual(result[0]['search_snippet'], '짧은 검색 발췌')
        self.assertIn('소득·거주 요건', result[0]['content'])
        for text in ('위험한 지시문', '제외할 메뉴', '제외할 머리말', '제외할 꼬리말'):
            self.assertNotIn(text, result[0]['content'])
        self.assertEqual(result[2]['document']['status'], 'not_fetched')
        self.assertEqual(result[3]['document']['status'], 'not_fetched')

    def test_failed_non_html_oversized_and_empty_pages_preserve_search_evidence(self):
        item = page('https://www.chuncheon.go.kr/test')
        for value in ((b'pdf', 'application/pdf'), (b'a' * (MAX_BYTES+1), 'text/html'),
                      (b'<html><body></body></html>', 'text/html'), ValueError('private test detail')):
            getter = Mock(side_effect=value) if isinstance(value, Exception) else Mock(return_value=value)
            with self.subTest(kind=type(value)):
                result = enrich_evidence([item], official_url, getter=getter)[0]
                self.assertEqual(result['document']['status'], 'unavailable')
                self.assertEqual(result['content'], item['content'])
                self.assertNotIn('private test detail', str(result))

    def test_unapproved_url_is_not_requested(self):
        getter = Mock()
        result = enrich_evidence([page('https://evil.com/data')], official_url, getter=getter)
        getter.assert_not_called()
        self.assertEqual(result[0]['document']['reason'], 'url_not_allowed')

    def test_transport_has_no_credentials_size_bound_and_no_redirect_follow(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'<html>test</html>'
        response.headers = {'Content-Type':'text/html; charset=utf-8'}
        opener = Mock()
        opener.open.return_value = response
        with patch('ai.welfare_agent.official_pages.build_opener', return_value=opener):
            fetch_official_html('https://www.chuncheon.go.kr/test')
        request = opener.open.call_args.args[0]
        self.assertIsNone(request.get_header('Authorization'))
        self.assertIsNone(request.get_header('Cookie'))
        self.assertIsNone(request.get_header('X-goog-api-key'))
        response.read.assert_called_once_with(MAX_BYTES + 1)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)
        self.assertIsNone(NoRedirect().redirect_request(None, None, None, None, None, None))
        opener.open.side_effect = HTTPError('https://www.chuncheon.go.kr/test', 302, 'redirect', {}, None)
        with patch('ai.welfare_agent.official_pages.build_opener', return_value=opener), self.assertRaises(HTTPError):
            fetch_official_html('https://www.chuncheon.go.kr/test')

