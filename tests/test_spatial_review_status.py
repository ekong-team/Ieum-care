import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/data_processing'))
from spatial_review_status import current_spatial_status


class SpatialStatusTests(unittest.TestCase):
    def test_only_matching_artifacts_report_reproduced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIn('미확인', current_spatial_status(root))
            paths = {'boundary_zip':'data/external/sgis/bnd_sigungu_00_2025_2Q.zip',
                'telecom_features':'data/processed/telecom_features.csv',
                'script':'scripts/data_processing/validate_region_boundaries.py'}
            hashes = {}
            for key, name in paths.items():
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'original')
                hashes[key] = hashlib.sha256(p.read_bytes()).hexdigest()
            report = root / 'data/processed/spatial_validation_summary.json'
            report.write_text(json.dumps({'status':'comparison_complete_with_exceptions','sha256':hashes}),encoding='utf-8')
            self.assertIn('재현 완료', current_spatial_status(root))
            for name in paths.values():
                p = root / name
                p.write_bytes(b'changed')
                self.assertIn('미확인', current_spatial_status(root))
                p.write_bytes(b'original')
            report.write_text('{}',encoding='utf-8')
            self.assertIn('미확인', current_spatial_status(root))


if __name__ == '__main__':
    unittest.main()
