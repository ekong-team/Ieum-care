from copy import deepcopy
import json
import tempfile
import unittest

from ai.welfare_agent.live_agent import AgentError
from ai.welfare_agent.recommender import recommend
from scripts.integration.validate_welfare_quality import prepare_case, run_case


def inputs_fixture():
    return dict(batch_id='a'*64, period='2025-12', entries=[dict(analysis_id='CC30F', rank=1,
        request=dict(target=dict(region='춘천시', age_group=30, sex='female', purpose='all'),
                     confirmed_support_needs=[], risk_assessment=None))])


class WelfareQualityTests(unittest.TestCase):
    def test_prepare_preserves_input_and_default_does_not_call(self):
        inputs = inputs_fixture()
        before = deepcopy(inputs)
        snapshot = prepare_case(inputs, 'CC30F')
        self.assertEqual(inputs, before)
        self.assertEqual(snapshot['request'], before['entries'][0]['request'])
        with tempfile.TemporaryDirectory() as temporary:
            def forbidden(*args, **kwargs):
                self.fail('기본 준비는 외부 호출을 하면 안 됩니다.')
            folder, manifest = run_case(snapshot, temporary, agent=forbidden)
            self.assertEqual(manifest['status'], 'prepared')
            self.assertIsNone(manifest['candidate_count'])
            self.assertTrue((folder / 'request.json').exists())
            self.assertTrue((folder / 'review.csv').exists())

    def test_explicit_run_records_calls_and_never_repeats_completed_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = prepare_case(inputs_fixture(), 'CC30F')
            count = []
            def fake(payload, on_external_call):
                count.append(1)
                on_external_call('tavily'); on_external_call('gemini')
                return {**recommend(payload), 'schema_version':'welfare-0.4', 'mode':'live'}
            folder, first = run_case(snapshot, temporary, allow_external=True, agent=fake)
            self.assertEqual(first['status'], 'completed')
            self.assertEqual(first['external_calls'], {'tavily':1, 'gemini':1})
            (folder / 'review.csv').write_text('manual review retained', encoding='utf-8')
            _, repeated = run_case(snapshot, temporary, allow_external=True, agent=fake)
            self.assertEqual(first, repeated)
            self.assertEqual(len(count), 1)
            self.assertEqual((folder / 'review.csv').read_text(encoding='utf-8'), 'manual review retained')
            self.assertEqual(first['quality_status'], 'pending_manual_review')

    def test_failed_attempt_is_not_zero_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            count = []
            def failure(payload, on_external_call):
                count.append(1); on_external_call('gemini')
                raise AgentError('Gemini HTTP 503', 503)
            snapshot = prepare_case(inputs_fixture(), 'CC30F')
            folder, first = run_case(snapshot, temporary, allow_external=True, agent=failure)
            self.assertEqual(first['status'], 'failed')
            self.assertIsNone(first['candidate_count'])
            self.assertFalse((folder / 'result.json').exists())
            run_case(snapshot, temporary, allow_external=True, agent=failure)
            self.assertEqual(len(count), 1)
            first['status'] = 'running'
            (folder / 'manifest.json').write_text(json.dumps(first), encoding='utf-8')
            run_case(snapshot, temporary, allow_external=True, agent=failure)
            self.assertEqual(len(count), 1)

    def test_missing_target_does_not_fabricate_input(self):
        with self.assertRaises(ValueError):
            prepare_case(inputs_fixture(), 'GN10M')
