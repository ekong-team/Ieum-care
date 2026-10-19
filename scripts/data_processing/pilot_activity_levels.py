"""활동 위축 검토 단계 시범안. 고립 위험 확률이나 개인 진단이 아니다."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
data = pd.read_csv(ROOT / 'data/processed/risk_features.csv')
data = data.sort_values(['지역', '연령대', '월']).reset_index(drop=True)
month = pd.to_datetime(data['월'].astype(str), format='%Y%m')
data['카드_일평균건수_전월변화율'] = (
    (1 + data['카드1_전체_결제건수_전월변화율'])
    * (month - pd.offsets.MonthBegin(1)).dt.days_in_month / month.dt.days_in_month - 1
)
move = '통신_연령유동량_전월변화율'
spend = '카드_일평균건수_전월변화율'
keys = ['지역', '연령대']
for col in [move, spend]:
    # 동일가중 연령 평균과의 차이이며 인구가중 지역 전체 변화는 아니다.
    data[col + '_지역연령평균대비차이'] = data[col] - data.groupby(['월', '지역'])[col].transform('mean')

def classify(threshold):
    valid = data[[move, spend]].notna().all(axis=1)
    both = data[[move, spend]].le(-threshold).all(axis=1) & valid
    any_decline = data[[move, spend]].le(-threshold).any(axis=1) & valid
    streak = []
    previous_key, previous_month, count = None, None, 0
    for i, row in data.iterrows():
        key = tuple(row[k] for k in keys)
        period = pd.Period(str(row['월']), freq='M')
        adjacent = key == previous_key and previous_month is not None and period == previous_month + 1
        count = (count + 1 if adjacent else 1) if both.iloc[i] else 0
        streak.append(count)
        previous_key, previous_month = key, period
    streak = pd.Series(streak, index=data.index)
    level = pd.Series(1, index=data.index, dtype='Int64')
    level[any_decline] = 2
    level[both] = 3
    level[streak >= 2] = 4
    level[~valid] = pd.NA
    # 5단계는 큰 감소·지속·업종 및 자료 점검 기준 확정 전 자동 배정하지 않는다.
    return level, streak

summary = []
for threshold in [.02, .03, .05]:
    level, streak = classify(threshold)
    summary.append({'감소기준': threshold, **{f'{n}단계': int(level.eq(n).sum()) for n in range(1, 6)}, '판정보류': int(level.isna().sum())})
    if threshold == .03:
        data['시범단계'], data['동시감소연속개월'] = level, streak
data['설계가정'] = '이동·일평균소비 각각 3% 이상 감소 / 5단계 미확정'
out = ROOT / 'data/processed/eda'
out.mkdir(parents=True, exist_ok=True)
data.to_csv(out / 'activity_levels_pilot.csv', index=False, encoding='utf-8-sig')
pd.DataFrame(summary).to_csv(out / 'activity_level_sensitivity.csv', index=False, encoding='utf-8-sig')
print(pd.DataFrame(summary).to_string(index=False))
print(data.loc[data['시범단계'].eq(4), ['월', '지역', '연령대', move, spend, '동시감소연속개월']].to_string(index=False))
