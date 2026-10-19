"""현재 입력·경계·검증 코드 해시가 일치할 때만 공간 재현 완료로 표시."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]


def current_spatial_status(root=ROOT):
    report = root / 'data/processed/spatial_validation_summary.json'
    pending = '공간 대조 로컬 재현 미확인: 검증 기록 또는 입력 해시 확인 필요'
    if not report.exists():
        return pending
    try:
        data = json.loads(report.read_text(encoding='utf-8'))
        files = {
            'boundary_zip': root / 'data/external/sgis/bnd_sigungu_00_2025_2Q.zip',
            'telecom_features': root / 'data/processed/telecom_features.csv',
            'script': root / 'scripts/data_processing/validate_region_boundaries.py',
        }
        if not data['status'].startswith('comparison_complete'):
            return pending
        if any(not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != data['sha256'][key]
               for key, p in files.items()):
            return pending
    except (KeyError, ValueError, OSError):
        return pending
    return '공간 대조 로컬 재현 완료: EPSG:5179 해석에 따른 조건부 결과; 예외·기관 정의 확인 필요'
