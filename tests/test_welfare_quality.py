from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai.welfare_agent.live_agent import AgentError
from ai.welfare_agent.recommender import recommend
from scripts.integration.validate_welfare_quality import (
    coverage_values, prepare_analysis_case, prepare_case, prepare_latest_plan, run_case, save_latest_plan,
)


def inputs_fixture():
    return dict(batch_id='a'*64, period='2025-12', entries=[dict(analysis_id='CC30F', rank=1,
        request=dict(target=dict(region='춘천시', age_group=30, sex='female', purpose='all'),
                     confirmed_support_needs=[], risk_assessment=None))])


class WelfareQualityTests(unittest.TestCase):
    def latest_fixture(self):
        inputs = inputs_fixture()
        inputs['entries'] = []
        for analysis_id, rank, region, age, sex, level in [
            ('a', 1, '춘천시', 30, 'female', 4),
            ('b', 1, '춘천시', 30, 'male', 4),
            ('c', 1, '춘천시', 40, 'male', 4),
            ('d', 2, '강남구', 20, 'female', 3),
            ('e', 3, '강남구', 10, 'male', 2),
            ('f', 4, '춘천시', 60, 'female', 1),
            ('g', 2, '강남구', 20, 'male', 3),
        ]:
            inputs['entries'].append(dict(analysis_id=analysis_id, rank=rank,
                request=dict(target=dict(region=region, age_group=age, sex=sex, purpose='all'),
                             risk_assessment=dict(level=level), confirmed_support_needs=[])))
        inputs['priority'] = dict(partial_assessments=[{}], held_cohorts=[{}, {}])
        return inputs

    def test_plan_preserves_all_ties_and_covers_observed_conditions_deterministically(self):
        inputs = self.latest_fixture()
        before = deepcopy(inputs)
        plan = prepare_latest_plan(inputs)
        self.assertEqual(inputs, before)
        self.assertEqual([row['analysis_id'] for row in plan['selected'][:3]], ['a', 'b', 'c'])
        self.assertTrue(all(row['reasons'] == ['joint_first_priority'] for row in plan['selected'][:3]))
        selected_ids = {row['analysis_id'] for row in plan['selected']}
        expected = set().union(*(coverage_values(entry) for entry in inputs['entries']))
        actual = set().union(*(coverage_values(entry) for entry in inputs['entries']
                               if entry['analysis_id'] in selected_ids))
        self.assertEqual(actual, expected)
        self.assertEqual({row['analysis_id'] for row in plan['not_selected']}, {'g'})
        self.assertEqual((plan['partial_count'], plan['held_count']), (1, 2))
        inputs['entries'].reverse()
        self.assertEqual(prepare_latest_plan(inputs), plan)

    def test_new_batch_and_priorities_change_plan_without_fixed_cohorts(self):
        inputs = self.latest_fixture()
        previous = prepare_latest_plan(inputs)
        inputs['batch_id'] = 'b' * 64
        inputs['period'] = '2026-01'
        for entry in inputs['entries']:
            entry['rank'] = 1 if entry['analysis_id'] == 'g' else 2
        updated = prepare_latest_plan(inputs)
        self.assertNotEqual(updated['batch_id'], previous['batch_id'])
        self.assertEqual(updated['period'], '2026-01')
        self.assertEqual(updated['selected'][0]['analysis_id'], 'g')
        self.assertEqual(sum('joint_first_priority' in row['reasons'] for row in updated['selected']), 1)
        with self.assertRaises(ValueError):
            prepare_analysis_case(inputs, 'removed-id')

    def test_plan_only_prepares_requests_without_network_and_keeps_review(self):
        inputs = self.latest_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            with patch('scripts.integration.validate_welfare_quality.recommend_live',
                       side_effect=AssertionError('계획 생성 중 외부 추천 금지')):
                folder, plan = save_latest_plan(inputs, temporary)
                manifests = list(Path(temporary).rglob('manifest.json'))
                self.assertEqual(len(manifests), len(plan['selected']))
                for path in manifests:
                    manifest = json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(manifest['external_calls'], {})
                    self.assertEqual(manifest['status'], 'prepared')
                review = manifests[0].parent / 'review.csv'
                review.write_text('담당자 검토 유지', encoding='utf-8')
                save_latest_plan(inputs, temporary)
                self.assertEqual(review.read_text(encoding='utf-8'), '담당자 검토 유지')
                self.assertTrue((folder / 'plan.json').exists())
        snapshot = prepare_analysis_case(inputs, 'b')
        self.assertEqual(snapshot['request'], inputs['entries'][1]['request'])
        self.assertEqual(snapshot['first_rank'], 1)

    def test_empty_plan_and_duplicate_ids(self):
        inputs = inputs_fixture()
        inputs['entries'] = []
        plan = prepare_latest_plan(inputs)
        self.assertEqual(plan['selected'], [])
        self.assertEqual(plan['eligible_count'], 0)
        inputs = inputs_fixture()
        inputs['entries'].append(deepcopy(inputs['entries'][0]))
        with self.assertRaises(ValueError):
            prepare_latest_plan(inputs)

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
