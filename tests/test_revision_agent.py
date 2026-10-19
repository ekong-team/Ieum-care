import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('revision', ROOT / 'ai/evaluation/revision_agent.py')
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.plan = dict(plan_id='p', analysis_id='a', version=1, status='draft', title='원안',
                         objective=None, activities=[], budget_items=[], target={'age_code': '30G'},
                         missing_fields=['objective'])
        self.evaluation = dict(plan_id='p', analysis_id='a', evaluation_id='e',
                               criteria_results=[dict(criterion_id='target_fit', status='needs_revision')])

    def proposal(self, field='objective', value='참여 기회 확대 제안'):
        return dict(changes=[dict(field=field, value=value, criterion_id='target_fit', reason='대상 적합성 보완')], questions=[])

    def test_revision_keeps_inputs_and_requires_new_evaluation(self):
        before = json.dumps(self.plan, ensure_ascii=False)
        r = revision.revise(self.plan, self.evaluation, proposal=self.proposal())
        self.assertEqual(json.dumps(self.plan, ensure_ascii=False), before)
        self.assertEqual(r['revised_plan']['version'], 2)
        self.assertEqual(r['revised_plan']['missing_fields'], ['objective'])
        self.assertTrue(r['requires_reevaluation'])
        self.assertFalse(r['model_executed'])

    def test_protected_values_cannot_be_replaced(self):
        for field in ('analysis_id', 'target', 'budget_items', 'source_refs', 'status'):
            with self.subTest(field=field):
                r = revision.revise(self.plan, self.evaluation, proposal=self.proposal(field, '가짜'))
                self.assertEqual(r['revised_plan'], self.plan)
                self.assertEqual(len(r['rejected_changes']), 1)

    def test_unknown_criterion_rejected(self):
        proposal = self.proposal()
        proposal['changes'][0]['criterion_id'] = 'invented'
        self.assertFalse(revision.revise(self.plan, self.evaluation, proposal=proposal)['changes'])

    def test_id_mismatch_and_malformed_output(self):
        self.evaluation['analysis_id'] = 'wrong'
        with self.assertRaises(ValueError):
            revision.revise(self.plan, self.evaluation)
        self.evaluation['analysis_id'] = 'a'
        with self.assertRaises(ValueError):
            revision.revise(self.plan, self.evaluation, proposal={'changes': 'oops', 'questions': []})

    def test_limit_does_not_invoke_model(self):
        def fail(*args):
            self.fail('model called after limit')
        self.assertEqual(revision.revise(self.plan, self.evaluation, generate=fail, iteration=2)['status'], 'iteration_limit')

    def test_absent_model_and_injected_generator(self):
        self.assertEqual(revision.revise(self.plan, self.evaluation)['status'], 'needs_model')
        r = revision.revise(self.plan, self.evaluation, generate=lambda *_: self.proposal())
        self.assertTrue(r['model_executed'])
        self.assertEqual(r['status'], 'needs_reevaluation')


if __name__ == '__main__':
    unittest.main()
