"""공간 내부 일치 위치만 사용한 통신 특징 변화가 시범 단계에 주는 영향."""
from pathlib import Path
import sys
import json
import hashlib
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ai/risk_model'))
from build_activity_levels import classify, CONFIG, KEYS


def main():
    data = ROOT / 'data/processed'
    original = pd.read_csv(data/'activity_review_levels.csv',dtype={'월':str}).set_index(KEYS).sort_index()
    delta = pd.read_csv(data/'spatial_sensitivity_deltas.csv',dtype={'월':str}).set_index(KEYS).sort_index()
    pd.testing.assert_index_equal(original.index,delta.index)
    summary = json.loads((data/'spatial_sensitivity_summary.json').read_text(encoding='utf-8'))
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if summary['telecom_sha256'] != digest(data/'telecom_features.csv'):
        raise ValueError('공간 민감도 입력 변경: 다시 실행 필요')
    strict = original.copy()
    for col in delta.columns:
        strict[col] = original[col] + delta[col]
    comparisons = []
    for threshold in [.02,.03,.05]:
        config = {**CONFIG,'decline':threshold}
        before = classify(original.reset_index(),config).set_index(KEYS)['활동위축단계']
        after = classify(strict.reset_index(),config).set_index(KEYS)['활동위축단계']
        compared = pd.DataFrame({'코드기준단계':before,'내부일치단계':after})
        compared['단계변경'] = before.fillna(0).ne(after.fillna(0))
        compared['감소기준'] = threshold
        comparisons.append(compared.reset_index())
    result = pd.concat(comparisons,ignore_index=True)
    result.to_csv(data/'spatial_activity_level_comparison.csv',index=False,encoding='utf-8-sig')
    report = {'stage_changes_by_threshold':{str(k):int(v) for k,v in result.groupby('감소기준')['단계변경'].sum().items()},
        'scope':'기본 관측조건 90%/75%에서 공간 불일치 제외 민감도; 고립 정확도 검증 아님',
        'sha256':{name:digest(data/name) for name in ['activity_review_levels.csv','spatial_sensitivity_deltas.csv','spatial_sensitivity_summary.json']}}
    (data/'spatial_activity_level_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
