from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai.evaluation.revision_v2 import apply_revision, budget, evaluate, fingerprint, load_context, validate_plan
from ai.evaluation.revision_runtime import RevisionRuntime
from ai.evaluation.revision_provider import AnthropicRevisionProvider
from backend.revision_service import execute_revision
from scripts.integration.run_revision_demo import DemoGenerator, demo_plan

ROOT = Path(__file__).resolve().parents[1]


class RevisionV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.venv-agent')
        self.db = Path(self.temp.name) / 'runs.sqlite3'
        self.plan, self.context = demo_plan(), load_context('202512_32010_30G')

    def tearDown(self):
        self.temp.cleanup()

    def runtime(self):
        return RevisionRuntime(self.db)

    def proposal(self, field='objective', value='참여 기회를 제안한다.'):
        return {'changes': [{'field': field, 'value': value, 'issue_id': 'missing_' + field, 'reason': '누락 계획 보완'}], 'questions': []}

    def test_real_background_and_original_unchanged(self):
        data = json.loads((ROOT / 'data/processed/agent_activity_evidence.json').read_text(encoding='utf-8'))
        record = next(r for r in data['records'] if r['월'] == '202512' and '춘천' in r['지역'] and r['연령대'] == '30대')
        self.assertEqual(record, self.context['activity_evidence'])
        self.assertEqual(self.context['background_context']['resident_population'], 34885)
        self.assertNotIn('weather_context', self.context)

    def test_stale_plan_version_and_hash(self):
        e = evaluate(self.plan, self.context)
        for key, value in [('version', 2), ('title', 'changed')]:
            plan = deepcopy(self.plan)
            plan[key] = value
            with self.assertRaisesRegex(ValueError, 'stale_evaluation'):
                apply_revision(plan, self.context, e, self.proposal())

    def test_stale_background_hash(self):
        e = evaluate(self.plan, self.context)
        c = deepcopy(self.context)
        c['background_context']['resident_population'] = 1
        with self.assertRaisesRegex(ValueError, 'context hash'):
            apply_revision(self.plan, c, e, self.proposal())

    def test_readonly_target_budget_and_unrelated_issue(self):
        e = evaluate(self.plan, self.context)
        for field in ('target', 'budget_items', 'analysis_id'):
            with self.assertRaises(ValueError):
                apply_revision(self.plan, self.context, e, self.proposal(field, 'invented'))
        p = self.proposal()
        p['changes'][0]['issue_id'] = 'missing_title'
        with self.assertRaises(ValueError):
            apply_revision(self.plan, self.context, e, p)

    def test_text_eligibility_tripwire(self):
        with self.assertRaisesRegex(ValueError, 'hard violation'):
            apply_revision(self.plan, self.context, evaluate(self.plan, self.context),
                           self.proposal(value='30대 전원이 지원 자격을 충족한다고 확정한다.'))

    def test_schema_entire_candidate(self):
        with self.assertRaises(ValueError):
            apply_revision(self.plan, self.context, evaluate(self.plan, self.context), self.proposal('activities', ['invalid']))
        plan = deepcopy(self.plan)
        plan['target']['planned_participants'] = True
        with self.assertRaises(ValueError):
            validate_plan(plan)

    def test_duplicate_activity_ids(self):
        plan = deepcopy(self.plan)
        plan['activities'] = [{'activity_id': 'a', 'name': 'a', 'description': 'a'}] * 2
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            validate_plan(plan)

    def test_budget_missing_zero_and_assumption(self):
        self.assertIsNone(budget(self.plan)['total_krw'])
        plan = deepcopy(self.plan)
        plan['source_refs'] = [dict(source_id='s', kind='user_assumption', url=None, title='가상 단가 가정', verified_on=None, note='시연용')]
        item = dict(item_id='i', category='test', description='가정', unit_price_krw=1000,
                    quantity=2, occurrences=3, unit='회', cost_basis='assumption', source_ref='s')
        plan['budget_items'] = [item]
        self.assertEqual(budget(plan)['total_krw'], 6000)
        self.assertEqual(budget(plan)['status'], 'estimated')
        plan['budget_items'][0]['unit_price_krw'] = 0
        self.assertEqual(budget(plan)['total_krw'], 0)
        plan['budget_items'].append(dict(item, item_id='j', quantity=None))
        self.assertIsNone(budget(plan)['total_krw'])
        self.assertEqual(budget(plan)['available_subtotal_krw'], 0)

    def test_fixture_end_to_end_preserves_input(self):
        original = fingerprint(self.plan)
        runtime = self.runtime()
        try:
            state = runtime.run('demo', self.plan, self.context, DemoGenerator())
            self.assertEqual(state['status'], 'needs_input')
            self.assertEqual(state['current_plan']['version'], 2)
            self.assertEqual(state['model_call_count'], 0)
            self.assertFalse(state['actual_llm_execution'])
            self.assertEqual(fingerprint(self.plan), original)
            self.assertEqual(runtime.events('demo')[-1]['step'], 'stopped')
        finally:
            runtime.close()

    def test_durable_idempotent_result_and_conflict(self):
        runtime = self.runtime()
        first = runtime.run('same', self.plan, self.context, DemoGenerator())
        runtime.close()
        runtime = self.runtime()
        try:
            second = runtime.run('same', self.plan, self.context, DemoGenerator())
            self.assertEqual(first, second)
            plan = deepcopy(self.plan)
            plan['title'] = '다른 요청'
            with self.assertRaisesRegex(ValueError, 'conflict'):
                runtime.run('same', plan, self.context, DemoGenerator())
        finally:
            runtime.close()

    def test_unknown_pending_call_not_replayed(self):
        class Interrupted:
            identity = 'interrupted'
            def __call__(self, *args):
                raise KeyboardInterrupt()
        runtime = self.runtime()
        try:
            with self.assertRaises(KeyboardInterrupt):
                runtime.run('pending', self.plan, self.context, Interrupted())
        finally:
            runtime.close()
        runtime = self.runtime()
        try:
            state = runtime.run('pending', self.plan, self.context, Interrupted())
            self.assertEqual(state['status'], 'awaiting_generation_confirmation')
            self.assertEqual(state['attempt_count'], 1)
        finally:
            runtime.close()

    def test_questions_no_change_are_counted_and_stopped(self):
        class Questions:
            identity = 'questions'
            def __call__(self, *args):
                return dict(proposal=dict(changes=[], questions=['확인 필요']), provenance=dict(kind='fixture'))
        runtime = self.runtime()
        try:
            state = runtime.run('q', self.plan, self.context, Questions())
            self.assertEqual(state['attempt_count'], 1)
            self.assertEqual(state['status'], 'no_improvement')
        finally:
            runtime.close()

    def test_limit_after_partial_improvement(self):
        class Partial:
            identity = 'partial'
            def __call__(obj, *args):
                return dict(proposal=self.proposal(), provenance=dict(kind='fixture'))
        runtime = self.runtime()
        try:
            state = runtime.run('limit', self.plan, self.context, Partial(), max_attempts=1)
            self.assertEqual(state['status'], 'limit_reached')
            self.assertEqual(state['generator_call_count'], 1)
        finally:
            runtime.close()

    def test_new_issue_candidate_is_not_committed(self):
        plan = deepcopy(self.plan)
        plan['performance_measures'] = []
        class BadMetric:
            identity = 'bad-metric'
            def __call__(obj, *args):
                metric = dict(metric_id='m', name='m', definition='m', denominator=None, measurement_timing='후',
                              data_collection_method='기록', responsible_party=None, target_value=99, target_basis='unset', source_ref=None)
                return dict(proposal=self.proposal('performance_measures', [metric]), provenance=dict(kind='fixture'))
        runtime = self.runtime()
        try:
            state = runtime.run('new', plan, self.context, BadMetric())
            self.assertEqual(state['status'], 'no_improvement')
            self.assertEqual(state['current_plan'], plan)
        finally:
            runtime.close()

    def test_generator_failure_leaves_original(self):
        class Broken:
            identity = 'broken'
            def __call__(self, *args):
                raise RuntimeError('secret-must-not-log')
        runtime = self.runtime()
        try:
            state = runtime.run('failed', self.plan, self.context, Broken())
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['current_plan'], self.plan)
            self.assertNotIn('secret-must-not-log', json.dumps(runtime.events('failed')))
        finally:
            runtime.close()

    def test_backend_loads_context_server_side(self):
        req = dict(run_id='service', analysis_id=self.plan['analysis_id'], planning_as_of='2026-10-18', program_plan=self.plan)
        state = execute_revision(req, self.db, DemoGenerator())
        self.assertEqual(state['state']['status'], 'needs_input')
        with self.assertRaises(ValueError):
            execute_revision(dict(req, context={'fake': True}), self.db)

    def test_seven_month_hold_still_preserved(self):
        context = load_context('202507_32010_30G')
        self.assertIsNone(context['activity_evidence']['활동위축단계'])

    def test_provider_missing_key_no_network(self):
        with patch.dict('os.environ', {}, clear=True), patch('urllib.request.urlopen') as send:
            with self.assertRaises(RuntimeError):
                AnthropicRevisionProvider('explicit-model')('system', {})
            send.assert_not_called()

    def test_provider_request_and_json_response_mock_only(self):
        response = dict(id='mock-response', model='mock-model', stop_reason='end_turn', usage={'input_tokens': 1},
                        content=[{'type': 'text', 'text': json.dumps({'changes': [], 'questions': []})}])
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-placeholder'}), patch('urllib.request.urlopen') as send:
            send.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            provider = AnthropicRevisionProvider('mock-model', max_calls=1)
            result = provider('system', {})
            self.assertEqual(result['provenance']['response_id'], 'mock-response')
            with self.assertRaises(RuntimeError):
                provider('system', {})
            self.assertEqual(send.call_count, 1)

    def test_truncated_provider_response_keeps_usage_but_no_proposal(self):
        response = dict(id='mock-truncated', model='mock-model', stop_reason='max_tokens', usage={'output_tokens': 2},
                        content=[{'type': 'text', 'text': '{'}])
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-placeholder'}), patch('urllib.request.urlopen') as send:
            send.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            result = AnthropicRevisionProvider('mock-model')('system', {})
            self.assertIsNone(result['proposal'])
            self.assertEqual(result['provenance']['response_id'], 'mock-truncated')
            self.assertEqual(result['provenance']['usage']['output_tokens'], 2)

    def test_nonfinite_and_unknown_field_rejected(self):
        plan = deepcopy(self.plan)
        plan['target']['planned_participants'] = float('nan')
        with self.assertRaises(ValueError):
            validate_plan(plan)

    def test_whitespace_activity_and_fake_documented_cost(self):
        plan = deepcopy(self.plan)
        plan['activities'] = [dict(activity_id='a', name=' ', description=' ')]
        with self.assertRaises(ValueError):
            validate_plan(plan)
        plan = deepcopy(self.plan)
        plan['source_refs'] = [dict(source_id='a', kind='user_assumption', title='가정', url=None, verified_on=None, note='시험')]
        plan['budget_items'] = [dict(item_id='b', category='test', description='가정', unit_price_krw=1000,
                                     quantity=1, occurrences=1, unit='회', cost_basis='documented', source_ref='a')]
        self.assertIsNone(budget(plan)['total_krw'])

    def test_new_activities_add_cost_question_and_refresh_missing_fields(self):
        proposal = self.proposal('activities', [dict(activity_id='a', name='활동 제안', description='시연용 제안')])
        result = apply_revision(self.plan, self.context, evaluate(self.plan, self.context), proposal)
        self.assertNotIn('activities', result['candidate_plan']['missing_fields'])
        self.assertTrue(any('추가 인력' in q for q in result['questions']))
        plan = deepcopy(self.plan)
        plan['invented'] = True
        with self.assertRaises(ValueError):
            validate_plan(plan)


if __name__ == '__main__':
    unittest.main()
