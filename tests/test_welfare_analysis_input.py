"""분석 객체 수신부터 1차 순위·실제 추천 입력 연결까지 외부 API 없이 검사한다."""
import copy
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.request import urlopen, Request

from ai.analysis_agent.inputs import digest
from ai.analysis_agent.workflow import run_analysis
from ai.welfare_agent.analysis_input import prepare_analysis_inputs, latest_analysis_inputs, publish_analysis_inputs
from backend.server import create_server
from tests.test_analysis_sex import sex_rows


def bundle_fixture(period='202509'):
    data = sex_rows('female', [3100, 2700, 2400], [None, -.1, -.1], [None, -.1, -.1])
    data += sex_rows('male', [3100, 3200, 3300], [None, .01, .01], [None, .01, .01])
    return run_analysis(data, {}, [], period=period)


class AnalysisInputTests(unittest.TestCase):
    def test_priority_and_evidence_are_preserved_without_mutation(self):
        bundle = bundle_fixture()
        before = copy.deepcopy(bundle)
        prepared = prepare_analysis_inputs(bundle)
        self.assertEqual(prepared['priority'], bundle['priority_review'])
        self.assertEqual(len(prepared['entries']), 2)
        self.assertEqual(prepared['entries'][0]['rank'], 1)
        self.assertEqual(prepared['entries'][0]['request']['target']['sex'], 'female')
        for entry in prepared['entries']:
            cohort = next(c for c in bundle['cohorts'] if c['analysis_id'] == entry['analysis_id'])
            self.assertEqual(entry['request']['analysis_context']['profile'], cohort['profile'])
        prepared['entries'][0]['request']['risk_assessment']['level'] = 1
        self.assertEqual(bundle, before)

    def test_partial_targets_are_kept_separate_not_queued_as_complete(self):
        prepared = prepare_analysis_inputs(bundle_fixture('202508'))
        self.assertEqual(len(prepared['priority']['partial_assessments']), 1)
        self.assertEqual(len(prepared['entries']), 1)
        self.assertEqual(prepared['entries'][0]['request']['risk_assessment']['status'], 'complete')

    def test_changed_hash_priority_or_profile_is_rejected(self):
        original = bundle_fixture()
        changed = copy.deepcopy(original)
        changed['bundle_hash'] = 'bad'
        with self.assertRaises(ValueError):
            prepare_analysis_inputs(changed)
        changed = copy.deepcopy(original)
        changed['priority_review']['ranked_cohorts'][0]['rank'] = 99
        changed['bundle_hash'] = digest({k: v for k, v in changed.items() if k != 'bundle_hash'})
        with self.assertRaises(ValueError):
            prepare_analysis_inputs(changed)

    def test_latest_requires_passed_snapshot_and_confined_path(self):
        bundle = bundle_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'current'
            folder.mkdir()
            (folder / 'analysis_bundle.json').write_text(json.dumps(bundle), encoding='utf-8')
            (folder / 'run_status.json').write_text(json.dumps({'status':'passed', 'bundle_hash':bundle['bundle_hash']}), encoding='utf-8')
            (root / 'latest.json').write_text(json.dumps({'directory':'current','bundle_hash':bundle['bundle_hash']}), encoding='utf-8')
            self.assertEqual(latest_analysis_inputs(root)['batch_id'], bundle['bundle_hash'])
            (root / 'latest.json').write_text(json.dumps({'directory':'../outside'}), encoding='utf-8')
            with self.assertRaises(ValueError):
                latest_analysis_inputs(root)

    def test_direct_publish_get_then_recommend_all_inputs_over_http(self):
        server = create_server(0)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            published = publish_analysis_inputs(bundle_fixture(), port=server.server_port)
            self.assertEqual(published['targets'], 2)
            with urlopen(base + '/api/welfare/analysis-inputs') as response:
                prepared = json.load(response)
            for entry in prepared['entries']:
                body = {'mode':'offline', **entry['request']}
                request = Request(base + '/api/welfare/recommendations', data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
                with urlopen(request) as response:
                    result = json.load(response)
                self.assertEqual(result['target'], body['target'])
                self.assertEqual(result['analysis_context'], body['analysis_context'])
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()


if __name__ == '__main__':
    unittest.main()
