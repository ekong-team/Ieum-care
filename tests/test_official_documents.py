"""공식 본문·PDF 추출, 캐시·리디렉션·다운로드 예산을 외부 호출 없이 검증한다."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
import unittest
import json
import hashlib
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ai.analysis_agent.research import OfficialDocuments, source_scope, search_plan, known_sources
from ai.analysis_agent.model import official_url, GeminiTavilyProvider
from ai.contracts.profile import TargetProfile
from tests.test_analysis_gemini import dataset, CONFIG, model_response
from tests.test_adaptive_analysis import plan, source
from ai.analysis_agent.workflow import run_analysis


def pdf(text=True):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if text:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 200 Td (2025-09 monthly value 123.4) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class OfficialDocumentTests(unittest.TestCase):
    def profile(self):
        return TargetProfile.model_validate(run_analysis(dataset(), {}, [], period='202509')['cohorts'][-1]['profile'])

    def source(self, url='https://www.chuncheon.go.kr/report.pdf'):
        return dict(id='S1', url=url, title='춘천시 2025년 9월 소비 경제 자료', snippet='검색 발췌만 존재')

    def test_pdf_text_and_hash_are_attached_without_numeric_import(self):
        collector = OfficialDocuments(lambda url: (pdf(), 'application/pdf'))
        result = collector.enrich(self.source(), self.profile(), 'economy')
        self.assertEqual(result['document']['status'], 'pdf_text')
        self.assertEqual(result['document']['pages'], [1])
        self.assertIn('123.4', result['snippet'])
        self.assertEqual(len(result['document']['sha256']), 64)
        self.assertEqual(result['document']['table_alignment'], 'not_verified')
        self.assertNotIn('risk', result)

    def test_static_html_pdf_attachment_is_followed(self):
        calls = []
        def getter(url):
            calls.append(url)
            return ((b'<html><body>2025-09<script>bad instruction</script><a href="/attached.pdf">PDF</a></body></html>', 'text/html')
                    if url.endswith('.html') else (pdf(), 'application/pdf'))
        collector = OfficialDocuments(getter)
        result = collector.enrich(self.source('https://www.chuncheon.go.kr/report.html'), self.profile(), 'economy')
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['url'], 'https://www.chuncheon.go.kr/attached.pdf')
        self.assertNotIn('bad instruction', result['snippet'])
        self.assertEqual(result['document']['status'], 'pdf_text')

    def test_image_or_blank_pdf_is_never_text_evidence(self):
        collector = OfficialDocuments(lambda url: (pdf(False), 'application/pdf'))
        result = collector.enrich(self.source(), self.profile(), 'economy')
        self.assertEqual(result['document']['status'], 'image_only_requires_review')
        self.assertEqual(result['snippet'], '')
        self.assertEqual(source_scope(result, self.profile(), 'economy')['status'], 'discovery_only')

    def test_official_redirect_counts_as_two_requests(self):
        def getter(url):
            if url.endswith('start'):
                raise HTTPError(url, 302, 'redirect', {'Location': 'https://file-cdn.bok.or.kr/a.pdf'}, BytesIO())
            return pdf(), 'application/pdf'
        collector = OfficialDocuments(getter)
        result = collector.enrich(self.source('https://www.bok.or.kr/start'), self.profile(), 'economy')
        self.assertEqual(collector.requests, 2)
        self.assertEqual(result['document']['status'], 'pdf_text')

    def test_external_redirect_is_blocked(self):
        calls = []
        def getter(url):
            calls.append(url)
            raise HTTPError(url, 302, 'redirect', {'Location': 'http://127.0.0.1/private.pdf'}, BytesIO())
        collector = OfficialDocuments(getter)
        result = collector.enrich(self.source(), self.profile(), 'economy')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['document']['status'], 'unavailable')

    def test_cache_is_hash_checked_and_no_new_get_occurs(self):
        with TemporaryDirectory() as temporary:
            collector = OfficialDocuments(lambda url: (pdf(), 'application/pdf'), cache=temporary)
            collector.enrich(self.source(), self.profile(), 'economy')
            cached = OfficialDocuments(lambda url: self.fail('Unexpected network'), cache=temporary)
            result = cached.enrich(self.source(), self.profile(), 'economy')
            self.assertEqual(cached.requests, 0)
            self.assertEqual(result['document_receipts'][0]['status'], 'cache_hit')
            next(Path(temporary).glob('*.bin')).write_bytes(b'changed')
            result = cached.enrich(self.source(), self.profile(), 'economy')
            self.assertEqual(result['document']['status'], 'unavailable')

    def test_total_requests_bounded_even_after_failures(self):
        calls = []
        def getter(url):
            calls.append(url)
            raise OSError('unavailable')
        collector = OfficialDocuments(getter)
        for i in range(8):
            collector.enrich(self.source(f'https://www.chuncheon.go.kr/{i}.pdf'), self.profile(), 'economy')
        self.assertEqual(len(calls), 4)
        self.assertEqual(collector.requests, 4)

    def test_unsupported_and_oversized_files_are_not_parsed(self):
        for raw, mime in ((b'not pdf', 'application/octet-stream'), (b'x' * 30_000_001, 'application/pdf')):
            collector = OfficialDocuments(lambda url: (raw, mime))
            self.assertEqual(collector.enrich(self.source(), self.profile(), 'economy')['document']['status'], 'unavailable')

    def test_broader_report_is_labelled_as_context(self):
        source = self.source('https://www.bok.or.kr/report.pdf')
        source.update(title='강원지역 실물경제동향 2026.2월', snippet='2025년 9월 강원지역 소비 경제 동향', document={'status':'pdf_text'})
        scope = source_scope(source, self.profile(), 'economy')
        self.assertEqual(scope['status'], 'reference_candidate')
        self.assertEqual(scope['geographic_scope'], 'wider_region_context')
        source.pop('document')
        self.assertEqual(source_scope(source, self.profile(), 'economy')['status'], 'discovery_only')

    def test_domains_include_discovered_official_publishers(self):
        self.assertTrue(official_url('https://www.bok.or.kr/report.pdf'))
        self.assertTrue(official_url('https://www.gwto.or.kr/report.pdf'))
        domains = next(p['payload']['include_domains'] for p in search_plan(self.profile()) if p['question_id']=='economy')
        self.assertIn('bok.or.kr', domains)
        self.assertIn('gwto.or.kr', domains)

    def test_registered_sources_are_not_reused_for_other_months_or_regions(self):
        profile = self.profile()
        self.assertEqual(known_sources(profile, 'economy'), [])
        december = profile.model_copy(update={'period':'2025-12'})
        source = known_sources(december, 'economy')[0]
        self.assertEqual(source['discovery'], 'previously_reviewed_official_reference')
        self.assertEqual(known_sources(december, 'calendar'), [])
        gangnam = december.model_copy(update={'target':december.target.model_copy(update={'region':'강남구'})})
        self.assertEqual(known_sources(gangnam, 'economy'), [])

    def test_registered_document_hash_mismatch_cannot_become_evidence(self):
        source = self.source()
        source.update(expected_sha256='0'*64, snippet='춘천시 2025년 9월 소비 경제 자료의 미리보기입니다.')
        result = OfficialDocuments(lambda url:(pdf(),'application/pdf')).enrich(source,self.profile(),'economy')
        self.assertEqual(result['document']['status'],'unavailable')
        self.assertEqual(result['snippet'],'')
        self.assertEqual(source_scope(result,self.profile(),'economy')['status'],'discovery_only')

    def test_graph_sends_document_text_to_review_and_preserves_ranking(self):
        baseline = run_analysis(dataset(), {}, [], period='202509')
        downloads, inputs = [], []
        def getter(url):
            downloads.append(url)
            html = '<html><body>춘천시 2025년 9월 소비 경제 공식 본문입니다. 원인 확정 근거가 아닙니다.</body></html>'
            return html.encode('utf-8'), 'text/html; charset=utf-8'
        def transport(url, headers, body):
            if 'tavily' in url:
                return source()
            if 'search_needed' in body['generationConfig']['responseJsonSchema']['properties']:
                return model_response(plan('economy'))
            payload = json.loads(body['contents'][0]['parts'][0]['text'])
            inputs.append(payload)
            return model_response(dict(observation_ids=['E1'], hypothesis_codes=[],
                question_codes=['data_quality'], source_ids=[], findings=[]))
        with TemporaryDirectory() as cache:
            provider = GeminiTavilyProvider(config=CONFIG, transport=transport, document_getter=getter,
                document_cache=cache)
            result = run_analysis(dataset(), {}, [], period='202509', provider=provider,
                model_analysis_id=baseline['cohorts'][-1]['analysis_id'])
        receipt = result['execution']['model_receipts'][0]
        self.assertEqual(len(downloads), 1)
        self.assertEqual(receipt['document_requests'], 1)
        self.assertEqual(receipt['search_attempts'], 1)
        self.assertEqual(receipt['gemini_attempts'], 2)
        self.assertEqual(result['execution']['confirmed_llm_responses'], 0)
        self.assertIn('원인 확정 근거가 아닙니다', inputs[0]['external_sources'][0]['snippet'])
        self.assertEqual(inputs[0]['external_sources'][0]['document']['status'], 'html_text')
        self.assertNotIn('document_receipts', inputs[0]['external_sources'][0])
        self.assertEqual(result['priority_review'], baseline['priority_review'])
        self.assertEqual([c['profile'] for c in result['cohorts']], [c['profile'] for c in baseline['cohorts']])
        from ai.analysis_agent.research import explain_bundle
        self.assertIn('공식 문서 GET 시도: 1회', explain_bundle(result))

    def test_generic_pages_do_not_exhaust_budget_before_registered_report(self):
        baseline = run_analysis(dataset(), {}, [], period='202509')
        report = pdf()
        registered = dict(title='춘천시 2025년 9월 소비 경제 보고서',url='https://www.bok.or.kr/report.pdf',
            snippet='',published_date='2025-10-10',expected_sha256=hashlib.sha256(report).hexdigest(),
            reviewed_pages=[1],discovery='previously_reviewed_official_reference')
        downloads=[]
        def getter(url):
            downloads.append(url)
            return (report,'application/pdf') if 'bok.or.kr' in url else (b'<html>menu</html>','text/html')
        def transport(url,headers,body):
            if 'tavily' in url:
                return dict(results=[dict(url=f'https://www.chuncheon.go.kr/menu{i}',title='행사',content='일반 안내') for i in range(3)])
            if 'search_needed' in body['generationConfig']['responseJsonSchema']['properties']:
                return model_response(plan('calendar','economy'))
            return model_response(dict(observation_ids=['E1'],hypothesis_codes=[],question_codes=[],source_ids=[],findings=[]))
        with TemporaryDirectory() as cache, patch('ai.analysis_agent.research.known_sources',side_effect=lambda profile,q:[registered] if q=='economy' else []):
            provider=GeminiTavilyProvider(config=CONFIG,transport=transport,document_getter=getter,document_cache=cache)
            result=run_analysis(dataset(),{},[],period='202509',provider=provider,model_analysis_id=baseline['cohorts'][-1]['analysis_id'])
        self.assertIn('bok.or.kr',downloads[0])
        receipt=result['execution']['model_receipts'][0]
        self.assertLessEqual(receipt['document_requests'],4)
        matched=next(s for s in receipt['sources'] if s.get('discovery'))
        self.assertEqual(matched['document']['status'],'pdf_text')
        self.assertEqual(matched['scope_check']['status'],'reference_candidate')


if __name__ == '__main__':
    unittest.main()
