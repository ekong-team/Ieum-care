"""공동 검토: 집계 전 통신 특징과 카드 합계에서 보고서 수치를 대조한다."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from data_contract import AGES, REGIONS

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/processed'
KEYS = ['월', '지역', '연령대']
LOC = ['BLOCK_CD', 'X_COORD', 'Y_COORD']


def main():
    paths = [DATA / n for n in ['telecom_features.csv', 'card_features.csv',
             'activity_review_levels.csv', 'activity_evidence.csv']]
    t = pd.read_csv(paths[0], dtype={'STD_YM': str, 'BLOCK_CD': str},
        usecols=['STD_YM'] + LOC + [f'FLOW_POP_{a}' for a in AGES])
    card, levels, evidence = [pd.read_csv(p, dtype={'월': str}) for p in paths[1:]]
    t['지역'] = t['BLOCK_CD'].str[:5].map(REGIONS)
    t = t.loc[t['지역'].notna()]
    assert not t.duplicated(['STD_YM'] + LOC).any()
    rows = []
    for region, group in t.groupby('지역'):
        months = {m: part.set_index(LOC) for m, part in group.groupby('STD_YM')}
        for month, current in months.items():
            prev = (pd.Period(month, freq='M') - 1).strftime('%Y%m')
            for code, age in AGES.items():
                column = f'FLOW_POP_{code}'
                valid_now = current[column].dropna()
                change = now_ratio = prev_ratio = np.nan
                count = 0
                if prev in months:
                    valid_prev = months[prev][column].dropna()
                    shared = valid_now.index.intersection(valid_prev.index)
                    count = len(shared)
                    now_ratio = count / len(valid_now) if len(valid_now) else np.nan
                    prev_ratio = count / len(valid_prev) if len(valid_prev) else np.nan
                    before = valid_prev.loc[shared].sum(min_count=1)
                    if before > 0:
                        change = valid_now.loc[shared].sum(min_count=1) / before - 1
                rows.append({'월': month, '지역': region, '연령대': age,
                    '재계산_통신변화율': change, '재계산_공통위치수': count,
                    '현재월기준_공통위치비율': now_ratio, '전월기준_공통위치비율': prev_ratio})
    audit = levels.merge(pd.DataFrame(rows), on=KEYS, validate='one_to_one')
    checks = {}
    for original, recomputed in [
        ('통신_연령유동량_전월변화율', '재계산_통신변화율'),
        ('통신_전월공통위치수', '재계산_공통위치수'),
        ('통신_전월공통위치비율', '현재월기준_공통위치비율')]:
        checks[original] = bool(np.allclose(audit[original], audit[recomputed], rtol=1e-10, atol=1e-12, equal_nan=True))
    card = card.sort_values(['지역','연령대','월'])
    card['日평균'] = card['카드1_전체_결제건수'] / pd.to_datetime(card['월'],format='%Y%m').dt.days_in_month
    card['재계산_소비변화율'] = card.groupby(['지역','연령대'])['日평균'].pct_change(fill_method=None)
    ordinals = pd.to_datetime(card['월'],format='%Y%m').dt.to_period('M').astype('int64')
    adjacent = ordinals.groupby([card['지역'],card['연령대']]).diff().eq(1)
    card['재계산_소비변화율'] = card['재계산_소비변화율'].where(adjacent)
    audit = audit.merge(card[KEYS+['재계산_소비변화율']], on=KEYS, validate='one_to_one')
    checks['소비_일평균건수_전월변화율'] = bool(np.allclose(audit['소비_일평균건수_전월변화율'],audit['재계산_소비변화율'],rtol=1e-10,atol=1e-12,equal_nan=True))
    for name, frame in [('단계',levels),('근거',evidence)]:
        checks[name+'_72개키'] = len(frame)==72 and not frame.duplicated(KEYS).any()
    pairs = levels[KEYS+['활동위축단계']].merge(evidence[KEYS+['활동위축단계']],on=KEYS,validate='one_to_one')
    checks['단계_근거파일일치'] = bool(np.allclose(pairs['활동위축단계_x'],pairs['활동위축단계_y'],equal_nan=True))
    manifest_checks = {}
    for name, field in [('activity_review_manifest.json','input_hashes'),('activity_evidence_manifest.json','inputs')]:
        m = json.loads((DATA/name).read_text(encoding='utf-8'))
        manifest_checks[name] = all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in m[field].items())
    checks.update(manifest_checks)
    if not all(checks.values()):
        raise ValueError(checks)
    out = DATA / 'eda/joint_review'
    out.mkdir(parents=True,exist_ok=True)
    audit[KEYS+['재계산_통신변화율','재계산_소비변화율','현재월기준_공통위치비율','전월기준_공통위치비율']].to_csv(out/'independent_numeric_audit.csv',index=False,encoding='utf-8-sig')
    summary = {'checks':checks,'rows':len(audit),
        'current_month_common_min':audit['현재월기준_공통위치비율'].min(),
        'previous_month_common_min':audit['전월기준_공통위치비율'].min(),
        'previous_month_below_90_rows':int(audit['전월기준_공통위치비율'].lt(.9).sum()),
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'scope':'가공 특징에서 재계산. 원본 통신 전체 재구축·공간 검증·고립 정확도 검증 아님'}
    (out/'numeric_audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
