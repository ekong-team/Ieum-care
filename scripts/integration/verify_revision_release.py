"""Reproducible local checks and release evidence; never invokes an external model."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from jsonschema import Draft202012Validator
from ai.evaluation.revision_v2 import fingerprint, load_context


def main():
    packet = ROOT / 'data/processed/submission_data_review_20261015/analysis_with_population_calendar.json'
    approved = json.loads(packet.read_text(encoding='utf-8'))
    original = json.loads((ROOT / 'data/processed/agent_activity_evidence.json').read_text(encoding='utf-8'))
    assert [r['analysis_evidence'] for r in approved['records']] == original['records']
    for record in approved['records']:
        context = load_context(record['analysis_id'])
        assert context['activity_evidence'] == record['analysis_evidence']
        assert context['background_context']['resident_population'] == record['resident_population']
        assert 'weather_context' not in context and 'economic_context' not in context
    schema = json.loads((ROOT / 'docs/contracts/revision_v2.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_revision*.py')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    files = sorted((ROOT / 'ai/evaluation').glob('*.py')) + [ROOT / 'backend/revision_service.py',
            ROOT / 'docs/contracts/revision_v2.schema.json', ROOT / 'requirements-agent.txt', ROOT / 'requirements-agent-lock.txt']
    report = dict(checked_on='2026-10-18', analysis_records_verified=len(approved['records']),
                  approved_packet_sha256=hashlib.sha256(packet.read_bytes()).hexdigest(),
                  tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                  source_hashes={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                  package_versions={k: importlib.metadata.version(k) for k in ('langgraph', 'langgraph-checkpoint-sqlite', 'jsonschema')},
                  actual_provider_calls=0, test_mode='offline fixtures and mocked provider transport',
                  incomplete=['live model quality/cost evaluation', 'verified welfare resources/prices',
                              'team evaluator adapter and frontend/server integration', 'authenticated deployment'])
    target = ROOT / 'data/processed/revision_graph_20261018/verification.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('analysis_records_verified', 'tests_run', 'failures', 'errors', 'actual_provider_calls')}, ensure_ascii=False))
    raise SystemExit(not result.wasSuccessful())


if __name__ == '__main__':
    main()
