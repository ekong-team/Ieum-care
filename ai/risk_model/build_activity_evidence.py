"""논문을 참고한 집단 활동 검토 근거. 고립 예측 정답·임계값은 제공하지 않는다."""
from pathlib import Path
import json
import hashlib
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/data_processing'))
from spatial_review_status import current_spatial_status
KEYS = ['월', '지역', '연령대']
CANDIDATES = ['외식·카페', '문화·오락', '운동']


def prior_baseline(frame, value):
    """현재 월을 제외한 인접 3개월만 사용. 월 누락·0 분모는 보류."""
    d = frame.sort_values(['지역', '연령대', '월']).copy()
    if d.duplicated(KEYS).any():
        raise ValueError('중복 월·지역·연령 키')
    d['과거3개월평균'] = np.nan
    for _, part in d.groupby(['지역', '연령대']):
        periods = pd.PeriodIndex(part['월'], freq='M')
        for position in range(3, len(part)):
            if all(periods[position-j] == periods[position]-j for j in range(1, 4)):
                past = part[value].iloc[position-3:position]
                if past.notna().all():
                    d.loc[part.index[position], '과거3개월평균'] = past.mean()
    d['과거3개월대비변화율'] = d[value]/d['과거3개월평균'].where(d['과거3개월평균'].gt(0))-1
    return d


def enrich(levels, monthly, groups):
    for name, table, keys in [('단계', levels, KEYS), ('카드', monthly, KEYS),
                              ('업종', groups, KEYS+['업종그룹'])]:
        if table.duplicated(keys).any():
            raise ValueError(name+' 중복 키')
    keep = KEYS+['활동위축단계','단계설명','소비_일평균건수_전월변화율',
        '통신_연령유동량_전월변화율','동시감소연속개월','업종민감도주의',
        '통신_연령관측률','통신_전월공통위치비율']
    d = levels[keep].merge(prior_baseline(monthly, '일평균_결제건수')[
        KEYS+['과거3개월평균', '과거3개월대비변화율']], on=KEYS,
        how='outer', validate='one_to_one', indicator=True)
    if not d['_merge'].eq('both').all():
        raise ValueError('단계·카드 키 불일치')
    d = d.drop(columns='_merge')
    # 연령별 변화율 평균 대신 결제건수를 합산한 지역 변화와 비교.
    regional = monthly.groupby(['월', '지역'], as_index=False)['결제건수'].sum()
    regional['일평균'] = regional['결제건수']/pd.to_datetime(regional['월'], format='%Y%m').dt.days_in_month
    regional = regional.sort_values(['지역', '월'])
    previous = regional.groupby('지역')['일평균'].shift()
    ordinal = pd.to_datetime(regional['월'], format='%Y%m').dt.to_period('M').astype('int64')
    adjacent = ordinal.groupby(regional['지역']).diff().eq(1)
    regional['지역전체_소비전월변화율'] = (regional['일평균']/previous.where(previous.gt(0))-1).where(adjacent)
    d = d.merge(regional[['월', '지역', '지역전체_소비전월변화율']], on=['월', '지역'], validate='many_to_one')
    d['소비_지역전체대비차이'] = d['소비_일평균건수_전월변화율']-d['지역전체_소비전월변화율']
    change = '일평균_결제건수_전월변화율'
    wide = groups.loc[groups['업종그룹'].isin(CANDIDATES)].pivot(index=KEYS, columns='업종그룹', values=change)
    if set(wide.index) != set(pd.MultiIndex.from_frame(d[KEYS])) or not set(CANDIDATES).issubset(wide.columns):
        raise ValueError('후보 업종·키 누락')
    wide = wide[CANDIDATES]
    wide.columns = ['후보_'+c+'_전월변화율' for c in CANDIDATES]
    d = d.merge(wide.reset_index(), on=KEYS, validate='one_to_one')
    columns = list(wide.columns)
    d['후보업종_비교가능수'] = d[columns].notna().sum(axis=1)
    for threshold in [0, .02, .03, .05]:
        # 0 기준은 변동 없음과 구분하여 실제 감소만 집계한다.
        mask = d[columns].lt(0) if threshold == 0 else d[columns].le(-threshold)
        d[f'후보업종_감소수_{int(threshold*100)}퍼센트'] = mask.sum(axis=1).astype('Int64').where(d['후보업종_비교가능수'].eq(3))
    d['해석상태'] = np.where(d['활동위축단계'].isna(), '자료부족으로 단계 보류', '집단 활동 검토용 잠정 단계')
    return d.sort_values(KEYS).reset_index(drop=True)


def main():
    sources = [ROOT/'data/processed/activity_review_levels.csv',
               ROOT/'data/processed/eda/card/monthly_age.csv',
               ROOT/'data/processed/eda/card/industry_groups.csv']
    frames = [pd.read_csv(p, dtype={'월':str}) for p in sources]
    result = enrich(*frames)
    out = ROOT/'data/processed'
    result.to_csv(out/'activity_evidence.csv', index=False, encoding='utf-8-sig')
    limitations = ['개인 고립 여부·확률을 측정하지 않음', '같은 개인의 통신·카드 결합이 아님',
        '연간 계절성 미보정', '소비는 가맹점 지역이며 거주민 분석이 아님',
        '업종 후보는 실제 교류를 검증한 분류가 아님', '과거3개월 비교는 만성 고립을 확인하지 못함',
        'v1 단계와 관측 임계값은 설계 가정; 독립 정답 검증 없음', current_spatial_status()]
    selected = KEYS+['활동위축단계','단계설명','해석상태','소비_일평균건수_전월변화율',
        '통신_연령유동량_전월변화율','동시감소연속개월','과거3개월대비변화율',
        '지역전체_소비전월변화율','소비_지역전체대비차이','후보업종_비교가능수',
        '후보업종_감소수_3퍼센트','업종민감도주의','통신_연령관측률','통신_전월공통위치비율']
    records = json.loads(result[selected].to_json(orient='records', force_ascii=False))
    payload = {'schema_version':'activity-evidence-v1', 'scope':'월×활동지역×연령의 집단 검토',
        'limitations':limitations, 'agent_instructions':['보류를 낮은 위험으로 바꾸지 않는다',
        '숫자·단계에서 개인 고립이나 지원 자격을 확정하지 않는다',
        '지역 공통 변화·업종 편중·관측 변화 등 대안 설명을 함께 제시한다',
        '프로그램은 제안으로 작성하고 실제 집행은 담당자 검토 대상으로 둔다'], 'records':records}
    (out/'agent_activity_evidence.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    manifest = {'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'inputs':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'rows':len(result), 'baseline_available':int(result['과거3개월대비변화율'].notna().sum()),
        'status':'descriptive_evidence_not_validated_isolation_model'}
    (out/'activity_evidence_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(result.loc[result['활동위축단계'].ge(4), KEYS+['과거3개월대비변화율','소비_지역전체대비차이','후보업종_감소수_3퍼센트']].to_string(index=False))


if __name__ == '__main__':
    main()
