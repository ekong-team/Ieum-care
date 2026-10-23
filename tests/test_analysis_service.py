"""실제 과금 없이 실행 경계·공유 잠금·실패 보존·HTTP 전달을 검증한다."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore, Event, Thread
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from ai.analysis_agent.inputs import digest
from backend.analysis import AnalysisService
from backend.server import create_server
from tests.test_welfare_analysis_input import bundle_fixture


class AnalysisServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = bundle_fixture()
        self.folder = self.root / 'data/processed/analysis_current/checked'
        self.folder.mkdir(parents=True)
        self.write()
        self.slot = BoundedSemaphore(1)
        self.published = Event()
        self.service = AnalysisService(self.root, self.slot, self.published.set, runner=lambda job: None)

    def write(self):
        for path, value in [(self.folder / 'analysis_bundle.json', self.bundle),
                (self.folder / 'run_status.json', dict(status='passed', bundle_hash=self.bundle['bundle_hash'])),
                (self.folder / 'verification.json', dict(status='passed')),
                (self.folder.parent / 'latest.json', dict(directory='checked', bundle_hash=self.bundle['bundle_hash']))]:
            path.write_text(json.dumps(value), encoding='utf-8')

    def test_result_is_latest_gender_cohorts_with_original_priority(self):
        result = self.service.result()
        self.assertEqual(len(result['cohorts']), 2)
        self.assertEqual(result['total_records'], 6)
        self.assertEqual(result['priority'], self.bundle['priority_review'])
        self.assertEqual({c['profile']['target']['sex'] for c in result['cohorts']}, {'male', 'female'})
        self.assertNotIn('GEMINI_API_KEY', json.dumps(result))

    def test_tampered_snapshot_is_rejected(self):
        self.bundle['cohorts'][0]['profile']['risk']['level'] = 5
        self.write()
        with self.assertRaises(ValueError): self.service.result()

    def test_period_and_path_arguments_rejected_before_running(self):
        for request in (dict(mode='offline', period='2099-01'), dict(mode='offline', features='C:/secret'),
                        dict(mode='offline', allow_external=True), dict(mode='offline', analysis_id='x')):
            with self.subTest(request=request), self.assertRaises(ValueError): self.service.start(request)
        self.assertIsNone(self.service.state()['job'])

    def test_external_run_requires_explicit_consent_complete_target_and_keys(self):
        aid = '202509_32010_30G_female'
        for request in (dict(mode='gemini', analysis_id=aid),
                dict(mode='gemini', analysis_id='202507_32010_30G_female', period='2025-07', allow_external=True),
                dict(mode='gemini', analysis_id='not-a-group', allow_external=True)):
            with self.subTest(request=request), self.assertRaises(ValueError): self.service.start(request)
        with patch('backend.analysis.config_status', return_value=dict(gemini_configured=False, tavily_configured=True)):
            with self.assertRaises(ValueError): self.service.start(dict(mode='gemini', analysis_id=aid, allow_external=True))

    def test_shared_slot_blocks_analysis_while_recommendation_runs(self):
        self.slot.acquire()
        with self.assertRaises(BlockingIOError): self.service.start(dict(mode='offline'))
        self.slot.release()

    def test_completed_publish_and_running_job_conflict(self):
        entered, release = Event(), Event()
        def runner(job): entered.set(); release.wait(3)
        self.service.runner = runner
        result = self.service.start(dict(mode='offline'))
        self.assertEqual(result['job']['status'], 'running')
        self.assertTrue(entered.wait(2))
        with self.assertRaises(BlockingIOError): self.service.start(dict(mode='offline'))
        release.set()
        self.assertTrue(self.published.wait(3))
        # Event는 publish 안에서 설정되므로 최종 상태는 slot 획득 후 읽는다.
        self.assertTrue(self.slot.acquire(timeout=3)); self.slot.release()
        self.assertEqual(self.service.state()['job']['status'], 'completed')

    def test_failure_keeps_last_result_and_does_not_leak_exception(self):
        def failure(job): raise RuntimeError('secret-key-local-path')
        self.service.runner = failure
        before = (self.folder.parent / 'latest.json').read_bytes()
        self.service.start(dict(mode='offline'))
        self.assertTrue(self.slot.acquire(timeout=3)); self.slot.release()
        self.assertEqual(self.service.state()['job']['status'], 'failed')
        self.assertNotIn('secret-key-local-path', json.dumps(self.service.state()))
        self.assertEqual((self.folder.parent / 'latest.json').read_bytes(), before)
        self.assertFalse(self.published.is_set())

    def test_cli_is_fixed_no_shell_and_external_flags_only_on_explicit_job(self):
        with patch('backend.analysis.subprocess.run') as run:
            run.return_value.returncode = 0
            self.service._execute(dict(mode='offline', period='2025-09'))
            command = run.call_args.args[0]
            self.assertNotIn('--allow-external', command)
            self.assertNotIn('shell', run.call_args.kwargs)
            self.service._execute(dict(mode='gemini', period='2025-09', analysis_id='202509_32010_30G_female'))
            self.assertIn('--allow-external', run.call_args.args[0])
            self.assertIn('adaptive', run.call_args.args[0])

    def test_http_results_job_content_type_origin_and_conflict(self):
        server = create_server(0, planning_root=self.root / 'planning')
        server.analysis_service = self.service
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/analysis/result') as response:
                self.assertEqual(json.load(response)['batch_id'], self.bundle['bundle_hash'])
            with urlopen(base + '/api/analysis/job') as response: self.assertIsNone(json.load(response)['job'])
            for headers, body, expected in [({'Content-Type':'text/plain'}, b'{}', 415),
                    ({'Content-Type':'application/json', 'Origin':'https://evil.test'}, b'{}', 403),
                    ({'Content-Type':'application/json'}, b'{}', 400),
                    ({'Content-Type':'application/json'}, b'x'*2049, 413)]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + '/api/analysis/runs', data=body, headers=headers))
                self.assertEqual(error.exception.code, expected)
            self.slot.acquire()
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + '/api/analysis/runs', data=b'{"mode":"offline"}', headers={'Content-Type':'application/json'}))
                self.assertEqual(error.exception.code, 409)
            finally: self.slot.release()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__': unittest.main()
