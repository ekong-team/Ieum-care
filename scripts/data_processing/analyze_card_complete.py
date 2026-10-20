"""카드 전체 EDA: 모든 월·지역·연령, 업종·시간대·거주지. 원본 변경 없음."""
from pathlib import Path
from html import escape
import pandas as pd
import numpy as np
from industry_classification import classify_industries, ALL_GROUPS
from analyze_risk_features import heatmap

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/processed/eda/card'
KEYS = ['월', '지역', '연령대']
AGES = ['10대', '20대', '30대', '40대', '50대', '60대이상']
METRICS = ['결제금액', '결제건수']


def load(number):
    df = pd.read_csv(ROOT / f'data/raw/신한카드_빅콘테스트2026_데이터{number}.txt',
                     sep='\t', encoding='cp949', dtype=str)
    if df.isna().any().any():
        raise ValueError(f'카드{number}: 원본 결측 확인 필요')
    corp = df.SEX_CCD.eq('법인')
    if not corp.eq(df.AGE_CCD.eq('법인')).all():
        raise ValueError('법인 표시 불일치')
    df = df.loc[~corp].copy()
    dates = pd.to_datetime(df.TA_YMD, format='%Y%m%d', errors='raise')
    df['월'] = dates.dt.strftime('%Y%m')
    df['지역'] = df.MCT_SGG_CD
    df['연령대'] = df.AGE_CCD.str.replace(' ', '', regex=False).replace(
        {f'{age}대': '60대이상' for age in [60, 70, 80, 90]})
    if not df.연령대.isin(AGES).all():
        raise ValueError('지원하지 않는 연령 구간')
    for original, col in [('TS_AT', '결제금액'), ('USE_CNT', '결제건수')]:
        df[col] = pd.to_numeric(df[original], errors='raise')
        if (df[col] < 0).any() or not np.isfinite(df[col]).all():
            raise ValueError('금액·건수 음수 또는 무한대')
    return df


def ratio(a, b):
    return a / b.where(b > 0)


def changes(table, extra=()):
    table = table.sort_values(['지역', '연령대', *extra, '월']).reset_index(drop=True)
    groups = ['지역', '연령대', *extra]
    month = pd.to_datetime(table.월, format='%Y%m')
    table['월일수'] = month.dt.days_in_month
    adjacent = month.dt.to_period('M').astype('int64').groupby(
        [table[k] for k in groups]).diff().eq(1)
    for metric in METRICS:
        daily = f'일평균_{metric}'
        table[daily] = table[metric] / table.월일수
        previous = table.groupby(groups)[daily].shift()
        table[daily + '_전월변화율'] = (ratio(table[daily], previous) - 1).where(adjacent)
        table[daily + '_전월차이'] = (table[daily] - previous).where(adjacent)
    table['건당금액'] = ratio(table.결제금액, table.결제건수)
    return table


def save(name, table):
    table.to_csv(OUT / f'{name}.csv', index=False, encoding='utf-8-sig')


def html(table):
    return '<div class="scroll">' + table.to_html(index=False, border=0,
        na_rep='—', float_format=lambda x: f'{x:,.3f}') + '</div>'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw = load(1)
    total = changes(raw.groupby(KEYS, as_index=False)[METRICS].sum())
    feature = pd.read_csv(ROOT / 'data/processed/card_features.csv', dtype={'월': str})
    matched = total.merge(feature, on=KEYS, validate='one_to_one', how='outer', indicator=True)
    if not matched._merge.eq('both').all():
        raise ValueError('특징과 원본 키 불일치')
    for metric in METRICS:
        if not matched[metric].eq(matched[f'카드1_전체_{metric}']).all():
            raise ValueError('특징과 원본 합계 불일치')
    expected = pd.MultiIndex.from_product([sorted(raw.월.unique()), sorted(raw.지역.unique()), AGES], names=KEYS)
    if len(total) != len(expected) or set(map(tuple, total[KEYS].to_numpy())) != set(expected):
        raise ValueError('전체 분석 키 누락')
    raw['업종'] = raw.MCT_RY_CD
    raw['업종그룹'] = classify_industries(raw.업종)
    group_index = pd.MultiIndex.from_tuples([(*key, group) for key in expected for group in ALL_GROUPS], names=KEYS+['업종그룹'])
    grouped = raw.groupby(KEYS+['업종그룹'])[METRICS].sum().reindex(group_index, fill_value=0).reset_index()
    grouped = changes(grouped, ['업종그룹']).merge(total[KEYS+['결제건수']], on=KEYS, suffixes=('', '_전체'), validate='many_to_one')
    grouped['건수비중'] = ratio(grouped.결제건수, grouped.결제건수_전체)
    observed = sorted(raw.업종.unique())
    industry_index = pd.MultiIndex.from_tuples([(*key, name) for key in expected for name in observed], names=KEYS+['업종'])
    industry = changes(raw.groupby(KEYS+['업종'])[METRICS].sum().reindex(industry_index, fill_value=0).reset_index(), ['업종'])
    for table in [grouped, industry]:
        control = table.groupby(KEYS)[METRICS].sum().sort_index()
        pd.testing.assert_frame_equal(control, total.set_index(KEYS)[METRICS].sort_index(), check_dtype=False)
    # 일평균 건수 차이는 업종별로 더할 수 있어 전체 변화의 기여를 설명한다.
    drivers = industry.loc[industry['일평균_결제건수_전월차이'].notna()].copy()
    drivers['변화방향'] = np.where(drivers['일평균_결제건수_전월차이'] >= 0, '증가', '감소')
    drivers['변화절대값'] = drivers['일평균_결제건수_전월차이'].abs()
    top = drivers.sort_values('변화절대값', ascending=False).groupby(KEYS+['변화방향']).head(3)
    time = raw.groupby(KEYS+['TIME_GB'], as_index=False)[METRICS].sum().merge(
        total[KEYS+['결제건수']], on=KEYS, suffixes=('', '_전체'), validate='many_to_one')
    time['건수비중'] = ratio(time.결제건수, time.결제건수_전체)
    card2 = load(2)
    residence = card2.groupby(KEYS+['CLN_SGG_CD'], as_index=False)[METRICS].sum()
    residence['거주지건수비중'] = ratio(residence.결제건수, residence.groupby(KEYS).결제건수.transform('sum'))
    card2_control = residence.groupby(KEYS)[METRICS].sum().reset_index().merge(feature, on=KEYS, validate='one_to_one', how='outer', indicator=True)
    if not card2_control._merge.eq('both').all():
        raise ValueError('카드2 원본·특징 키 불일치')
    for metric in METRICS:
        if not card2_control[metric].eq(card2_control[f'카드2_{metric}']).all():
            raise ValueError('카드2 원본·특징 합계 불일치')
    daily_change = '일평균_결제건수_전월변화율'
    total['지역연령평균대비차이'] = total[daily_change] - total.groupby(['월', '지역'])[daily_change].transform('mean')
    total['3퍼센트감소연속개월'] = 0
    for _, part in total.groupby(['지역', '연령대']):
        streak = 0
        for i in part.index:
            value = total.at[i, daily_change]
            streak = streak+1 if pd.notna(value) and value <= -.03 else 0
            total.at[i, '3퍼센트감소연속개월'] = streak
    excluded = changes(industry.loc[~industry.업종.isin(
        ['실내/실외골프장', '종합레저타운/놀이동산'])].groupby(KEYS, as_index=False)[METRICS].sum())
    sensitivity = total[KEYS+['일평균_결제건수_전월변화율']].merge(
        excluded[KEYS+['일평균_결제건수_전월변화율']], on=KEYS,
        suffixes=('_전체', '_골프레저제외'), validate='one_to_one')
    save('golf_leisure_sensitivity', sensitivity)
    regional = raw.groupby(['월', '지역'], as_index=False)[METRICS].sum()
    regional['월일수'] = pd.to_datetime(regional.월, format='%Y%m').dt.days_in_month
    for metric in METRICS:
        regional['일평균_'+metric] = regional[metric]/regional.월일수
        previous = regional.groupby('지역')['일평균_'+metric].shift()
        regional['일평균_'+metric+'_전월변화율'] = ratio(regional['일평균_'+metric], previous)-1
    for name, table in [('monthly_age', total), ('monthly_region', regional), ('industry_groups', grouped),
                        ('industries', industry), ('top_industry_drivers', top), ('time_composition', time), ('residence_composition_card2', residence)]:
        save(name, table)
    comparable = total.loc[total[daily_change].notna()]
    extremes = pd.concat([comparable.nsmallest(6, daily_change), comparable.nlargest(6, daily_change)])
    case_keys = [('202509', '강원 춘천시', '10대'), ('202511', '강원 춘천시', '30대'),
                 ('202512', '강원 춘천시', '30대'), ('202511', '강원 춘천시', '40대'), ('202512', '강원 춘천시', '40대')]
    cases = []
    for month, region, age in case_keys:
        selected = drivers.loc[drivers.월.eq(month)&drivers.지역.eq(region)&drivers.연령대.eq(age)]
        cases.append(f'<h3>{escape(month+" "+region+" "+age)}</h3>'+html(selected.nlargest(5, '변화절대값')[KEYS+['업종','일평균_결제건수_전월차이',daily_change]]))
    panels = ''.join(heatmap(total.pivot(index=['지역','연령대'], columns='월', values=col), title)
                     for col, title in [(daily_change,'하루 평균 결제건수 전월 변화'), ('일평균_결제금액_전월변화율','하루 평균 결제금액 전월 변화')])
    report = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>카드 전체 분석</title>
<style>body{{font:15px/1.7 'Malgun Gothic',sans-serif;margin:0;background:#f4f6f8;color:#17243a}}main{{max-width:1150px;margin:auto;padding:28px}}section{{background:white;padding:24px;margin:18px 0;border-radius:10px}}table{{border-collapse:collapse;white-space:nowrap;width:100%;font-size:12px}}td,th{{padding:7px;border-bottom:1px solid #ddd;text-align:right}}.scroll{{overflow:auto}}svg{{width:100%;font-size:12px}}</style><main>
<h1>카드 전체 분석 1차 결과</h1><p>2025년 7~12월 · 강남/춘천 · 6연령대 · 카드1 개인 기록 {len(raw):,}행. 카드1·2 합계 각각 최종 특징과 대조 완료.</p>
<section><h2>해석 기준</h2><p>지역은 가맹점 위치다. 결제건수는 사람 수가 아니며 실제 사회적 교류를 직접 측정하지 않는다. 월 일수로 나눈 하루 평균을 비교하지만 요일·공휴일·계절 영향은 제거되지 않았다. 금액 단위는 원본 정의서 확인 전 원 단위로 단정하지 않는다. 카드1·2는 합산하지 않는다. 기록 없는 업종의 0은 해당 집계 키의 관측 결제 없음이며 활동 부재의 증명이 아니다.</p><p>비율 표의 0.1은 10%, 전월차이 단위는 건/일이다. 7월 및 전월 분모 0인 변화율은 계산 불가로 남긴다.</p></section>
<section><h2>전체 지역·연령 월별 변화</h2>{panels}<p>그래프 색은 고립 위험 등급이 아니다.</p></section>
<section><h2>지역 전체 합계 기준</h2>{html(regional)}<p>연령별 변화율 단순 평균과 다른 지표다.</p></section>
<section><h2>큰 증가·감소 사례</h2>{html(extremes[KEYS+['일평균_결제건수',daily_change,'일평균_결제금액_전월변화율']])}{''.join(cases)}</section>
<section><h2>모든 집단의 업종 그룹 구성</h2>{html(grouped[KEYS+['업종그룹','결제건수','건수비중',daily_change]])}</section>
<section><h2>골프장·놀이동산 제외 민감도</h2><p>업종 제외가 올바른 처리라는 뜻이 아니라 분류 결과가 업종 선택에 얼마나 영향을 받는지 비교한다. 제외해도 계절 효과가 제거되는 것은 아니다.</p>{html(sensitivity)}</section>
<section><h2>모든 집단의 시간대 구성</h2>{html(time[KEYS+['TIME_GB','결제건수','건수비중']])}</section>
<section><h2>카드2 고객 거주지 구성</h2><p>거주지 정보는 시·도 수준이다. 강원 고객을 춘천 주민, 서울 고객을 강남 주민으로 동일시하지 않는다. 아래는 비중 상위 3개 거주지이며 전체는 별도 CSV에 보존했다.</p>{html(residence.sort_values('거주지건수비중',ascending=False).groupby(KEYS).head(3))}</section>
<section><h2>Agent에 전달할 분석 정보</h2><p>월·가맹점지역·연령, 이동/일평균 소비 변화, 업종별 변화 기여, 지속 기간, 관측 범위, 대안 설명, 자료 부족을 전달한다. 본 분석에서 프로그램 적합성이나 고립 여부를 확정하지 않는다. 현지의 통신 분석과 공동 해석, 업종 정의 검토, 5단계 기준 확정 및 검증은 후속 작업이다.</p></section></main></html>'''
    (OUT/'report.html').write_text(report, encoding='utf-8')
    print('원본·카드 특징·업종 합계 대조 완료')
    print(extremes[KEYS+[daily_change]].to_string(index=False))
    print('상세 사례 기여 업종:')
    for key in case_keys:
        sel = drivers.loc[(drivers[KEYS] == list(key)).all(axis=1)]
        print(key, sel.nlargest(3, '변화절대값')[['업종','일평균_결제건수_전월차이']].to_dict('records'))
    print('지역별 12월 일평균 건수 변화:', regional.loc[regional.월.eq('202512'), ['지역',daily_change]].to_dict('records'))
    print('보고서:', OUT/'report.html')


if __name__ == '__main__':
    main()
