from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from ai.evaluation.revision_graph import RevisionGraph
from ai.evaluation.revision_v2 import load_context
from scripts.integration.run_revision_demo import DemoGenerator, demo_plan

ROOT = Path(__file__).resolve().parents[1]


class ClearFixtureReviewer:
    identity = 'synthetic-review-fixture'
    kind = 'fixture'
    def __call__(self, *args):
        return dict(proposal=dict(issues=[], summary='고정된 시험용 응답. 실제 도메인 평가 아님.'), provenance=dict(kind='fixture'))


class RevisionGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.venv-agent')
        self.folder = Path(self.temp.name)
        self.plan, self.context = demo_plan(), load_context('202512_32010_30G')

    def tearDown(self):
        self.temp.cleanup()

    def test_persistent_graph_interrupt_and_resume_review(self):
        graph = RevisionGraph(self.folder, DemoGenerator())
        first = graph.start('r', self.plan, self.context)
        self.assertTrue(first['paused'])
        self.assertEqual(first['state']['current_plan']['version'], 2)
        self.assertEqual(first['state']['status'], 'needs_input')
        self.assertEqual(first['actual_llm_responses'], 0)
        self.assertEqual(first['state']['evaluation']['semantic_review'], 'not_run')
        graph.close()
        graph = RevisionGraph(self.folder, DemoGenerator())
        try:
            self.assertEqual(graph.start('r', self.plan, self.context), first)
            done = graph.resume('r', dict(action='record_review', reviewer='test fixture', note='시험 실행 확인'))
            self.assertFalse(done['paused'])
            self.assertEqual(done['state']['status'], 'review_recorded')
            self.assertNotEqual(done['state']['status'], 'approved')
        finally:
            graph.close()

    def test_human_update_and_reassessment(self):
        graph = RevisionGraph(self.folder, DemoGenerator())
        try:
            first = graph.start('r', self.plan, self.context)
            plan = deepcopy(first['state']['current_plan'])
            plan['version'] += 1
            plan['target']['planned_participants'] = 10
            second = graph.resume('r', dict(action='provide_input', reviewer='test fixture', note='가상 인원 입력', program_plan=plan))
            self.assertTrue(second['paused'])
            self.assertEqual(second['state']['current_plan']['version'], 3)
            self.assertNotIn('participants', {i['issue_id'] for i in second['state']['evaluation']['issues']})
            self.assertEqual(second['state']['attempts'], 1)
        finally:
            graph.close()

    def test_reviewer_role_boundary_with_fixture(self):
        graph = RevisionGraph(self.folder, DemoGenerator(), ClearFixtureReviewer())
        try:
            state = graph.start('r', self.plan, self.context)['state']
            self.assertEqual(state['calls'], 3)  # evaluate, revise, reevaluate; no duplicate evaluation
            self.assertEqual(state['confirmed_llm_responses'], 0)
            self.assertEqual(state['evaluation']['semantic_review'], 'fixture_not_domain_evaluation')
        finally:
            graph.close()

    def test_input_conflict_and_bad_review_decision(self):
        graph = RevisionGraph(self.folder, DemoGenerator())
        try:
            graph.start('r', self.plan, self.context)
            with self.assertRaises(ValueError):
                graph.start('r', dict(self.plan, title='changed'), self.context)
            with self.assertRaises(ValueError):
                graph.resume('r', dict(action='approve', reviewer='x', note='x'))
        finally:
            graph.close()

    def test_global_call_limit_counts_reviewer(self):
        graph = RevisionGraph(self.folder, DemoGenerator(), ClearFixtureReviewer())
        try:
            state = graph.start('r', self.plan, self.context, max_calls=1)['state']
            self.assertEqual(state['status'], 'limit_reached')
            self.assertEqual(state['current_plan'], self.plan)
            self.assertEqual(state['calls'], 1)
        finally:
            graph.close()

    def test_no_change_consumes_revision_attempt(self):
        class NoChange:
            identity = 'nochange'
            def __call__(self, *args):
                return dict(proposal=dict(changes=[], questions=['질문']), provenance=dict(kind='fixture'))
        graph = RevisionGraph(self.folder, NoChange())
        try:
            state = graph.start('r', self.plan, self.context)['state']
            self.assertEqual(state['attempts'], 1)
            self.assertEqual(state['status'], 'no_improvement')
        finally:
            graph.close()

    def test_reviewer_cannot_unlock_budget(self):
        class BadReviewer:
            identity = 'badreview'
            def __call__(self, *args):
                return dict(proposal=dict(issues=[dict(issue_id='b', field='budget_items', category='editable', severity='major', message='예산변경')], summary='x'), provenance=dict(kind='fixture'))
        graph = RevisionGraph(self.folder, DemoGenerator(), BadReviewer())
        try:
            state = graph.start('r', self.plan, self.context)['state']
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['attempts'], 0)
        finally:
            graph.close()

    def test_interrupted_call_is_not_blindly_repeated(self):
        class Crash:
            identity = 'crash'
            calls = 0
            def __call__(self, *args):
                self.calls += 1
                raise KeyboardInterrupt()
        actor = Crash()
        graph = RevisionGraph(self.folder, actor)
        try:
            with self.assertRaises(KeyboardInterrupt):
                graph.start('r', self.plan, self.context)
        finally:
            graph.close()
        graph = RevisionGraph(self.folder, actor)
        try:
            with self.assertRaises(ValueError):
                graph.recover_interrupted('r')
            recovered = graph.recover_interrupted('r', confirm_process_stopped=True)
            self.assertEqual(actor.calls, 1)
            self.assertTrue(recovered['paused'])
            self.assertEqual(recovered['state']['status'], 'failed')
        finally:
            graph.close()

    def test_invalid_human_plan_version_keeps_checkpoint(self):
        graph = RevisionGraph(self.folder, DemoGenerator())
        try:
            state = graph.start('r', self.plan, self.context)
            with self.assertRaises(ValueError):
                graph.resume('r', dict(action='provide_input', reviewer='fixture', note='wrong', program_plan=state['state']['current_plan']))
            self.assertEqual(graph.inspect('r')['state']['current_plan']['version'], 2)
        finally:
            graph.close()

    def test_semantic_regression_rejects_candidate(self):
        class RegressionReviewer:
            identity = 'semantic-regression'
            def __call__(self, system, payload):
                issues = []
                if payload['program_plan']['version'] > 1:
                    issues = [dict(issue_id='new_cost', field='budget_items', category='human_input', severity='major', message='새 활동의 추가 비용을 확인해야 함')]
                return dict(proposal=dict(issues=issues, summary='합성 회귀 테스트'), provenance=dict(kind='fixture'))
        graph = RevisionGraph(self.folder, DemoGenerator(), RegressionReviewer())
        try:
            result = graph.start('r', self.plan, self.context)['state']
            self.assertEqual(result['status'], 'no_improvement')
            self.assertEqual(result['current_plan'], self.plan)
        finally:
            graph.close()

    def test_active_run_claim_rejects_second_execution(self):
        graph = RevisionGraph(self.folder, DemoGenerator())
        try:
            graph._claim('active', 'test-input-hash')
            with self.assertRaises(RuntimeError):
                graph._claim('active', 'test-input-hash')
            graph._release('active')
        finally:
            graph.close()


if __name__ == '__main__':
    unittest.main()
