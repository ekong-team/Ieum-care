"""Run/inspect/resume the persisted graph. External calls require explicit CLI flags."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai.evaluation.revision_graph import RevisionGraph
from ai.evaluation.revision_provider import AnthropicRevisionProvider
from ai.evaluation.revision_v2 import load_context
from scripts.integration.run_revision_demo import DemoGenerator, demo_plan


class DemoReviewer:
    identity = 'offline-reviewer-fixture-v2'
    kind = 'fixture'
    def __call__(self, system, payload):
        return dict(proposal=dict(issues=[], summary='시연 고정 응답으로 의미평가의 호출 경로만 확인. 실제 판단 아님.'),
                    provenance=dict(kind='fixture', provider=None, model=None, response_id=None))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'inspect', 'resume', 'recover'])
    parser.add_argument('--folder', type=Path, default=ROOT / 'data/processed/revision_graph_20261018')
    parser.add_argument('--run-id', default='study-fixture-v2')
    parser.add_argument('--mode', choices=['fixture', 'disabled', 'anthropic'], default='fixture')
    parser.add_argument('--model')
    parser.add_argument('--allow-external', action='store_true')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--decision', type=Path)
    parser.add_argument('--analysis-id', default='202512_32010_30G')
    parser.add_argument('--planning-as-of', default='2026-10-18')
    parser.add_argument('--confirm-process-stopped', action='store_true')
    args = parser.parse_args()
    generator, reviewer = None, None
    if args.mode == 'fixture':
        generator, reviewer = DemoGenerator(), DemoReviewer()
    elif args.mode == 'anthropic':
        if not args.model or not args.allow_external:
            parser.error('External mode requires --model and --allow-external; API charges and data transfer occur.')
        generator = reviewer = AnthropicRevisionProvider(args.model, max_calls=8, max_tokens=2000, timeout=30)
    graph = RevisionGraph(args.folder, generator, reviewer)
    try:
        if args.action == 'start':
            if args.mode == 'anthropic' and args.plan is None:
                parser.error('External mode requires an explicit reviewed --plan file')
            plan = json.loads(args.plan.read_text(encoding='utf-8')) if args.plan else demo_plan()
            result = graph.start(args.run_id, plan, load_context(args.analysis_id, planning_as_of=args.planning_as_of))
        elif args.action == 'inspect':
            result = graph.inspect(args.run_id)
        elif args.action == 'recover':
            result = graph.recover_interrupted(args.run_id, confirm_process_stopped=args.confirm_process_stopped)
        else:
            if not args.decision:
                parser.error('--decision JSON required for resume')
            result = graph.resume(args.run_id, json.loads(args.decision.read_text(encoding='utf-8')))
    finally:
        graph.close()
    args.folder.mkdir(parents=True, exist_ok=True)
    # Fixed filename: run_id is a DB identifier, never interpolated into a filesystem path.
    (args.folder / 'latest_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    state = result['state']
    print(json.dumps(dict(run_id=state['run_id'], status=state['status'], paused=result['paused'],
                          version=state['current_plan']['version'], attempts=state['attempts'],
                          calls=state['calls'], real_llm_responses=result['actual_llm_responses'],
                          remaining_issues=[i['issue_id'] for i in state.get('evaluation', {}).get('issues', [])],
                          requires_human_review=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
