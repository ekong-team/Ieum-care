"""지역×연령 활동 위축 검토 단계 v1. 임계값은 설계 가정이며 고립 확률 아님."""
from pathlib import Path
import sys
import json
import hashlib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/data_processing'))
from data_contract import require_keys
from spatial_review_status import current_spatial_status

KEYS = ['월', '지역', '연령대']
MOVE = '통신_연령유동량_전월변화율'
SPEND = '소비_일평균건수_전월변화율'
ROBUST = '소비_골프레저제외_전월변화율'
CONFIG = {'version': 'activity-review-v1', 'decline': .03, 'large': .05,
          'months': 2, 'min_common_location': .90, 'min_age_coverage': .75}


def classify(frame, config=CONFIG):
    require_keys(frame, KEYS, '단계 입력')
    d = frame.sort_values(['지역', '연령대', '월']).reset_index(drop=True).copy()
    if config['large'] < config['decline'] or config['months'] < 2:
        raise ValueError('큰 감소 기준·지속 기간 확인 필요')
    d['계산가능'] = d[[MOVE, SPEND]].notna().all(axis=1)
    d['자료조건충족'] = (d['계산가능'] & d['통신_전월공통위치비율'].ge(config['min_common_location'])
                          & d['통신_연령관측률'].ge(config['min_age_coverage']))
    d['이동감소'] = d[MOVE].le(-config['decline'])
    d['소비감소'] = d[SPEND].le(-config['decline'])
    d['동시감소'] = d['이동감소'] & d['소비감소'] & d['자료조건충족']
    d['업종제외후동시감소'] = d['동시감소'] & d[ROBUST].le(-config['decline'])
    streak, robust_streak = [], []
    prior_key, prior_month, n, r = None, None, 0, 0
    for _, row in d.iterrows():
        key = tuple(row[k] for k in ['지역', '연령대'])
        month = pd.Period(row['월'], freq='M')
        adjacent = key == prior_key and prior_month is not None and month == prior_month + 1
        n = (n+1 if adjacent else 1) if row['동시감소'] else 0
        r = (r+1 if adjacent else 1) if row['업종제외후동시감소'] else 0
        streak.append(n)
        robust_streak.append(r)
        prior_key, prior_month = key, month
    d['동시감소연속개월'] = streak
    d['업종제외후연속개월'] = robust_streak
    level = pd.Series(1, index=d.index, dtype='Int64')
    level[d['이동감소'] | d['소비감소']] = 2
    level[d['동시감소']] = 3
    level[d['동시감소연속개월'].ge(config['months'])] = 4
    large = d[[MOVE, SPEND]].le(-config['large']).all(axis=1)
    level[large & d['동시감소연속개월'].ge(config['months'])
          & d['업종제외후연속개월'].ge(config['months'])] = 5
    level[~d['자료조건충족']] = pd.NA
    d['활동위축단계'] = level
    d['단계설명'] = level.map({1:'기준 이상 위축 신호 없음', 2:'단일 지표 감소',
        3:'이동·소비 동시 감소', 4:'동시 감소 지속', 5:'큰 동시 감소 지속·업종 민감도 조건 충족'})
    d.loc[~d['계산가능'], '단계설명'] = '판정 보류: 전월 비교 불가'
    d.loc[d['계산가능'] & ~d['자료조건충족'], '단계설명'] = '판정 보류: 관측 조건 미충족'
    d['업종민감도주의'] = d['동시감소연속개월'].ge(config['months']) & d['업종제외후연속개월'].lt(config['months'])
    for col in [MOVE, SPEND]:
        d[col+'_지역연령평균대비차이'] = d[col] - d.groupby(['월','지역'])[col].transform('mean')
    d['지역전연령동시감소'] = d.groupby(['월','지역'])['동시감소'].transform('all')
    d['공간대조상태'] = '로컬 재실행 미완료: 경계 원본 미보유; 코드 기반 시범 결과'
    d['기준버전'] = config['version']
    return d


def main():
    source = ROOT/'data/processed/risk_features.csv'
    sensitivity = ROOT/'data/processed/eda/card/golf_leisure_sensitivity.csv'
    d = pd.read_csv(source, dtype={'월':str})
    month = pd.to_datetime(d['월'], format='%Y%m')
    d[SPEND] = (1+d['카드1_전체_결제건수_전월변화율'])*(month-pd.offsets.MonthBegin(1)).dt.days_in_month/month.dt.days_in_month-1
    s = pd.read_csv(sensitivity, dtype={'월':str})
    require_keys(s, KEYS, '업종 민감도 입력')
    d = d.merge(s, on=KEYS, how='outer', validate='one_to_one', indicator=True)
    if not d['_merge'].eq('both').all():
        raise ValueError('민감도·특징 키 불일치')
    if not np.allclose(d[SPEND], d['일평균_결제건수_전월변화율_전체'], equal_nan=True):
        raise ValueError('업종 민감도 입력이 현재 소비 특징과 불일치: 카드 분석 재실행 필요')
    d[ROBUST] = d['일평균_결제건수_전월변화율_골프레저제외']
    d = d.drop(columns=['_merge'])
    result = classify(d)
    result['공간대조상태'] = current_spatial_status()
    out = ROOT/'data/processed'
    result.to_csv(out/'activity_review_levels.csv', index=False, encoding='utf-8-sig')
    summaries, comparisons = [], []
    for threshold in [.02,.03,.05]:
        config = {**CONFIG, 'decline':threshold, 'large':max(.05,threshold)}
        trial = classify(d, config)
        summaries.append({'감소기준':threshold, '큰감소기준':config['large'],
            **{f'{n}단계':int(trial['활동위축단계'].eq(n).sum()) for n in range(1,6)},
            '판정보류':int(trial['활동위축단계'].isna().sum()),
            '기본대비단계변경':int(trial['활동위축단계'].fillna(0).ne(result['활동위축단계'].fillna(0)).sum())})
        part = trial[KEYS+['활동위축단계']].copy()
        part['감소기준'] = threshold
        comparisons.append(part)
    pd.DataFrame(summaries).to_csv(out/'activity_review_sensitivity.csv',index=False,encoding='utf-8-sig')
    pd.concat(comparisons).to_csv(out/'activity_review_sensitivity_rows.csv',index=False,encoding='utf-8-sig')
    quality = []
    for common, coverage in [(.90,.75),(.95,.80)]:
        trial = classify(d, {**CONFIG,'min_common_location':common,'min_age_coverage':coverage})
        quality.append({'공통위치조건':common,'연령관측률조건':coverage,
            '판정보류':int(trial['활동위축단계'].isna().sum()),
            '4단계':int(trial['활동위축단계'].eq(4).sum()),
            '5단계':int(trial['활동위축단계'].eq(5).sum())})
    pd.DataFrame(quality).to_csv(out/'activity_review_quality_sensitivity.csv',index=False,encoding='utf-8-sig')
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    manifest = {'status':'rule_based_prototype_not_isolation_validation', 'config':CONFIG,
        'input_hashes':{p.relative_to(ROOT).as_posix():digest(p) for p in [source,sensitivity]},
        'script_sha256':digest(Path(__file__)), 'sensitivity':summaries, 'quality_sensitivity':quality,
        'scope':'월×가맹점/유동인구 지역×연령',
        'limitations':['3/5%·90/75%와2개월은 설계 가정이며 통계적 유의성·검증된 임계값 아님',
            current_spatial_status(), '실제 고립 정답 없음·개인 확률 아님',
            '지역 공통·계절 변화 미제거; 업종제외는 계절 보정이 아님']}
    (out/'activity_review_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(pd.DataFrame(summaries).to_string(index=False))
    print(result.loc[result['활동위축단계'].ge(4),KEYS+['활동위축단계',MOVE,SPEND,ROBUST,'업종민감도주의']].to_string(index=False))


if __name__ == '__main__':
    main()
