"""과거 제출 묶음 없이 인구·달력 배경만 만드는 경로와 근거 보존 검사."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.data_processing import prepare_submission_data_pack as context_builder


class AnalysisContextPreparationTests(unittest.TestCase):
    def test_context_only_preserves_evidence_and_does_not_package_or_write_docs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processed = root / 'data/processed'
            population = processed / 'external_context_20261015'
            population.mkdir(parents=True)
            evidence = [{'월': f'2025{month:02}', 'sample': index} for month in range(7, 13) for index in range(12)]
            joined = [{'analysis_id': f"{row['월']}_{row['sample']}", 'analysis_evidence': row,
                       'resident_population': 100, 'prior_resident_population': 99} for row in evidence]
            (processed / 'agent_activity_evidence.json').write_text(json.dumps({'records': evidence}), encoding='utf-8')
            (population / 'population_activity_review.json').write_text(json.dumps({'records': joined}), encoding='utf-8')
            output = processed / 'submission_data_review_20261015'
            with patch.object(context_builder, 'ROOT', root), patch.object(context_builder, 'DEST', output):
                packet, _ = context_builder.build_analysis_context()
            self.assertEqual([r['analysis_evidence'] for r in packet['records']], evidence)
            self.assertEqual(packet['schema_version'], 'submission-review-context-v1')
            self.assertEqual(packet['records'][0]['calendar_context']['days'], 31)
            self.assertEqual(packet['records'][-1]['calendar_context']['named_holiday_days'], 1)
            self.assertFalse((root / 'docs').exists())
            self.assertEqual(list(output.glob('*.zip')), [])
            self.assertTrue((output / 'analysis_with_population_calendar.json').is_file())


if __name__ == '__main__':
    unittest.main()
