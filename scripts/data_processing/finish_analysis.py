"""1번 분석 최종 정리: 전체 집단·고정 위치·지속 기간·설명 자료.

기존 특징/단계를 변경하지 않는다. 고정 위치는 6개월 전체 관측을 사용한
사후 민감도 비교이며 실시간 판단 입력이 아니다.
"""
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/processed'
OUT = DATA / 'eda/final_analysis_20261014'
sys.path.insert(0, str(ROOT / 'ai/risk_model'))
from build_activity_levels import classify, CONFIG, MOVE, SPEND, ROBUST
from data_contract import AGES, REGIONS, MONTHS, require_keys
from spatial_review_status import current_spatial_status

KEYS = ['월', '지역', '연령대']
LOC = ['BLOCK_CD', 'X_COORD', 'Y_COORD']
CHANGE = '일평균_결제건수_전월변화율'
COLORS = ['#216a8d', '#cf694b', '#4b8767', '#9777ad', '#c99b41', '#6e8190', '#b8c3cb']


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(name):
    return pd.read_csv(DATA / name, dtype={'월': str, 'STD_YM': str, 'BLOCK_CD': str})


def write_table(name, frame):
    frame.to_csv(OUT / f'{name}.csv', index=False, encoding='utf-8-sig')


def fixed_location_comparison(telecom, levels, months=MONTHS):
    """모든 월·모든 연령값이 유효한 동일 위치를 비교. 결측을 0으로 채우지 않음."""
    require_keys(telecom, ['STD_YM'] + LOC, '고정위치 입력')
    cols = [f'FLOW_POP_{age}' for age in AGES]
    d = telecom.copy()
    d['지역'] = d['BLOCK_CD'].str[:5].map(REGIONS)
    rows = []
    for region in sorted(REGIONS.values()):
        part = d.loc[d['지역'].eq(region)]
        by_month = {m: part.loc[part['STD_YM'].eq(m)].set_index(LOC)[cols].dropna()
                    for m in months}
        if any(frame.empty for frame in by_month.values()):
            raise ValueError(f'{region}: 고정위치 비교 월 누락 또는 유효 관측 없음')
        common = by_month[months[0]].index
        for month in months[1:]:
            common = common.intersection(by_month[month].index)
        if len(common) == 0:
            raise ValueError(f'{region}: 전체 기간 공통 위치 없음')
        sums = {m: by_month[m].loc[common].sum(min_count=1) for m in months}
        for i, month in enumerate(months):
            adjacent = i > 0 and pd.Period(month, freq='M') == pd.Period(months[i-1], freq='M') + 1
            for code, age in AGES.items():
                col = f'FLOW_POP_{code}'
                now, start = sums[month][col], sums[months[0]][col]
                before = sums[months[i-1]][col] if adjacent else np.nan
                rows.append({'월': month, '지역': region, '연령대': age,
                    '고정위치수': len(common), '해당월유효위치수': len(by_month[month]),
                    '고정위치보존비율': len(common)/len(by_month[month]),
                    '고정위치_연령유동량': now,
                    '고정위치_7월대비지수': now/start*100 if start > 0 else np.nan,
                    '고정위치_전월변화율': now/before-1 if before > 0 else np.nan})
    result = pd.DataFrame(rows).merge(levels[KEYS+[MOVE, '활동위축단계']],
        on=KEYS, how='outer', validate='one_to_one', indicator=True)
    if not result['_merge'].eq('both').all():
        raise ValueError('고정 위치 비교의 분석 키 불일치')
    result = result.drop(columns='_merge')
    result['전월변화율차이'] = result['고정위치_전월변화율'] - result[MOVE]
    return result


def stage_trials(levels, fixed):
    original = classify(levels)
    original_stage = original.set_index(KEYS)['활동위축단계']
    fixed_input = levels.copy().set_index(KEYS)
    fixed_input[MOVE] = fixed.set_index(KEYS)['고정위치_전월변화율']
    fixed_result = classify(fixed_input.reset_index()).set_index(KEYS)
    # 단계 비교에서는 기본 관측 조건을 유지해 위치 선택의 영향만 분리한다.
    comparison = original[KEYS+['활동위축단계']].copy().set_index(KEYS)
    comparison['고정위치_단계'] = fixed_result['활동위축단계']
    comparison['단계변경'] = comparison['활동위축단계'].fillna(0).ne(comparison['고정위치_단계'].fillna(0))
    persistence = []
    for duration in [2, 3]:
        trial = classify(levels, {**CONFIG, 'months': duration})
        ordered = trial.set_index(KEYS)['활동위축단계'].reindex(original_stage.index)
        persistence.append({'지속조건_연속전월비횟수': duration,
            '최소필요월수': duration+1,
            **{f'{n}단계': int(ordered.eq(n).sum()) for n in range(1,6)},
            '판정보류': int(ordered.isna().sum()),
            '기본대비단계변경': int(ordered.fillna(0).ne(original_stage.fillna(0)).sum())})
    return comparison.reset_index(), pd.DataFrame(persistence)


def format_table(frame, percent=(), points=(), ints=(), decimals=(), ratios=()):
    d = frame.copy()
    for col in percent:
        if col in d:
            d[col] = d[col].map(lambda v: '—' if pd.isna(v) else f'{v:+.2%}')
    for col in points:
        if col in d:
            d[col] = d[col].map(lambda v: '—' if pd.isna(v) else f'{v*100:+.2f}%p')
    for col in ratios:
        if col in d:
            d[col] = d[col].map(lambda v: '—' if pd.isna(v) else f'{v:.2%}')
    for col in ints:
        if col in d:
            d[col] = d[col].map(lambda v: '보류' if pd.isna(v) else f'{int(v):,}')
    for col in decimals:
        if col in d:
            d[col] = d[col].map(lambda v: '—' if pd.isna(v) else f'{v:,.2f}')
    return d


def html_table(frame):
    return '<div class="scroll">'+frame.to_html(index=False, border=0, escape=True,
        na_rep='—', float_format=lambda v: f'{v:,.3f}')+'</div>'


def md_table(frame):
    lines = ['| '+' | '.join(frame.columns)+' |', '| '+' | '.join(['---']*len(frame.columns))+' |']
    for row in frame.itertuples(index=False, name=None):
        lines.append('| '+' | '.join('—' if pd.isna(v) else str(v).replace('|','/') for v in row)+' |')
    return '\n'.join(lines)


def charts(levels, regional, groups, times, fixed, context):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font = Path('C:/Windows/Fonts/malgun.ttf')
    if not font.exists():
        raise FileNotFoundError('한글 그래프용 맑은 고딕 폰트 없음')
    font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
        'font.size': 10, 'svg.fonttype': 'path', 'axes.spines.top': False,
        'axes.spines.right': False, 'figure.facecolor': 'white'})
    output = []

    def save(fig, name, title, caption):
        fig.savefig(OUT / f'{name}.svg', bbox_inches='tight')
        fig.savefig(OUT / f'{name}.png', bbox_inches='tight', dpi=160)
        plt.close(fig)
        output.append({'name': name, 'title': title, 'caption': caption})

    index = pd.MultiIndex.from_product([sorted(REGIONS.values()), list(AGES.values())])
    for name, column, title in [('01_card_change', SPEND, '카드 일평균 결제건수 전월 변화'),
                                  ('02_telecom_change', MOVE, '통신 공통 위치 연령유동량 전월 변화'),
                                  ('03_amount_change', '일평균_결제금액_전월변화율', '카드 일평균 결제금액 전월 변화')]:
        matrix = levels.pivot(index=['지역','연령대'], columns='월', values=column).reindex(index)
        fig, ax = plt.subplots(figsize=(10.8, 6.7), layout='constrained')
        ax.imshow(matrix.to_numpy(dtype=float)*100, cmap='RdBu', vmin=-20, vmax=20, aspect='auto')
        ax.set_xticks(range(6), [m[4:]+'월' for m in MONTHS])
        ax.set_yticks(range(12), [f'{r.replace("강원 ","").replace("서울 ","")} {a}' for r,a in index])
        for i, row in enumerate(matrix.to_numpy(dtype=float)):
            for j, value in enumerate(row):
                ax.text(j,i,'—' if pd.isna(value) else f'{value:+.1%}',ha='center',va='center',
                        color='white' if pd.notna(value) and abs(value) >= .15 else '#152a3b', fontsize=9)
        ax.set_title(title, loc='left', pad=15, fontsize=15, fontweight='bold')
        save(fig,name,title,'7월은 전월 자료 없음. 색 범위 ±20%, 숫자는 실제 변화율. 파랑 증가·빨강 감소. 고립 등급이 아님.')

    fig, axes = plt.subplots(1,2, figsize=(11,4.6),layout='constrained')
    for region,color in zip(sorted(REGIONS.values()),COLORS):
        p = regional.loc[regional['지역'].eq(region)].sort_values('월')
        for ax,col,title in zip(axes,['일평균_결제건수','일평균_결제금액'],['건수','금액']):
            values=p[col]/p[col].iloc[0]*100
            ax.plot(range(6),values,marker='o',label=region,color=color,linewidth=2)
            ax.set_title(f'지역 전체 일평균 {title} 지수',loc='left')
    for ax in axes:
        ax.set_xticks(range(6),[m[4:]+'월' for m in MONTHS]); ax.set_ylabel('2025년 7월 = 100')
        ax.grid(axis='y',alpha=.2); ax.legend(frameon=False,fontsize=9)
    save(fig,'04_regional_card','지역 전체 카드 변화','각 지역 7월=100. 규모 차이를 제거한 변화 지수이며 인구당 값·계절 보정이 아님.')

    fig,axes=plt.subplots(1,2,figsize=(11,4.8),layout='constrained')
    for ax,region in zip(axes,sorted(REGIONS.values())):
        for i,age in enumerate(AGES.values()):
            p=fixed.loc[fixed['지역'].eq(region)&fixed['연령대'].eq(age)].sort_values('월')
            ax.plot(range(6),p['고정위치_7월대비지수'],marker='o',linewidth=1.6,label=age,color=COLORS[i])
        ax.set_title(region,loc='left');ax.set_ylabel('고정 위치 유동량, 7월 = 100')
        ax.set_xticks(range(6),[m[4:]+'월' for m in MONTHS]);ax.grid(axis='y',alpha=.2)
        ax.legend(ncol=3,frameon=False,fontsize=8)
    save(fig,'05_fixed_locations','6개월 동일 위치에서 본 통신 변화','모든 월·연령값이 관측된 위치만 유지. 두 지역의 세로축 범위는 다름. 전체 기간을 이용한 사후 설명용 비교이며 실시간 판단에는 사용하지 않음.')

    for metric,suffix in [('결제건수','count'),('결제금액','amount')]:
        totals=groups.groupby(['월','지역','업종그룹'])[metric].sum().reset_index()
        top=totals.groupby('업종그룹')[metric].sum().nlargest(6).index.tolist()
        totals['표시업종']=totals['업종그룹'].where(totals['업종그룹'].isin(top),'나머지 업종')
        fig,axes=plt.subplots(1,2,figsize=(11,5.8),layout='constrained')
        labels=top+['나머지 업종']
        for ax,region in zip(axes,sorted(REGIONS.values())):
            p=totals.loc[totals['지역'].eq(region)].pivot_table(index='월',columns='표시업종',values=metric,aggfunc='sum',fill_value=0).reindex(index=MONTHS,columns=labels,fill_value=0)
            shares=p.div(p.sum(axis=1),axis=0)*100;bottom=np.zeros(6)
            for label,color in zip(labels,COLORS):
                ax.bar(range(6),shares[label],bottom=bottom,label=label,color=color,width=.64)
                bottom+=shares[label].to_numpy()
            ax.set_title(region,loc='left');ax.set_xticks(range(6),[m[4:]+'월' for m in MONTHS])
            ax.set_ylim(0,100);ax.set_ylabel('지역 전체 구성비 (%)')
        handles,labels=axes[0].get_legend_handles_labels()
        fig.legend(handles,labels,loc='outside lower center',ncol=4,frameon=False,fontsize=9)
        save(fig,f'06_industry_{suffix}',f'업종별 {metric} 구성','연령별 수치를 합산한 지역 전체 비중. 해당 지표의 전체 기간 상위 6그룹과 나머지. 미분류·해석보류도 분모에 포함.')

    fig,axes=plt.subplots(1,2,figsize=(11,4.9),layout='constrained')
    buckets=sorted(times['TIME_GB'].unique())
    for ax,region in zip(axes,sorted(REGIONS.values())):
        p=times.loc[times['지역'].eq(region)].groupby(['월','TIME_GB'])['결제건수'].sum().unstack().reindex(MONTHS)
        shares=p.div(p.sum(axis=1),axis=0)*100;bottom=np.zeros(6)
        for bucket,color in zip(buckets,COLORS):
            ax.bar(range(6),shares[bucket],bottom=bottom,label=bucket.replace('_','~')+'시',color=color,width=.64)
            bottom+=shares[bucket].to_numpy()
        ax.set_title(region,loc='left');ax.set_xticks(range(6),[m[4:]+'월' for m in MONTHS]);ax.set_ylabel('결제건수 비중 (%)')
        ax.set_ylim(0,100)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='outside lower center',ncol=4,frameon=False)
    save(fig,'07_card_time','카드 결제 시간대 구성','6시간 단위 관측 결제건수. 결제 시각만으로 동행·사회적 만남을 추정하지 않음.')

    fig,axes=plt.subplots(1,2,figsize=(11,4.8),layout='constrained')
    for ax,region in zip(axes,sorted(REGIONS.values())):
        p=context.loc[context['지역'].eq(region)].sort_values('월')
        for col,label,color in zip(['통신_연령관측률','통신_시간관측률','통신_요일관측률'],['연령','시간','요일'],COLORS):
            ax.plot(range(6),p[col]*100,marker='o',color=color,label=label)
        ax.set_title(region,loc='left');ax.set_xticks(range(6),[m[4:]+'월' for m in MONTHS])
        ax.set_ylim(65,102);ax.set_ylabel('결합 위치 중 관측 비율 (%)');ax.legend(frameon=False);ax.grid(axis='y',alpha=.2)
    save(fig,'08_observation','통신 자료별 관측 범위','지역 공통 값은 12개 지역·월만 사용. 관측률은 인구 대표성이나 데이터 정확도 점수가 아님.')

    stage=levels.copy();stage['표시단계']=stage['활동위축단계'].map(lambda v:'보류' if pd.isna(v) else f'{int(v)}단계')
    fig,axes=plt.subplots(1,2,figsize=(11,4.8),layout='constrained')
    labels=['1단계','2단계','3단계','4단계','5단계','보류']
    for ax,region in zip(axes,sorted(REGIONS.values())):
        p=stage.loc[stage['지역'].eq(region)].groupby(['월','표시단계']).size().unstack(fill_value=0).reindex(index=MONTHS,columns=labels,fill_value=0)
        bottom=np.zeros(6)
        for label,color in zip(labels,['#bacbd7','#729cb5','#47708b','#bc6a4e','#914a42','#dedede']):
            ax.bar(range(6),p[label],bottom=bottom,label=label,color=color,width=.64)
            bottom+=p[label].to_numpy()
        ax.set_title(region,loc='left');ax.set_xticks(range(6),[m[4:]+'월' for m in MONTHS]);ax.set_yticks(range(7));ax.set_ylabel('집단 수 (각 월 6연령)')
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=6,frameon=False)
    save(fig,'09_stages','월별 시범 단계 분포','3%·2회 지속·90%/75% 관측 조건. 집단 수이며 인원 수·고립 확률이 아님.')
    return output


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    names=['activity_review_levels.csv','activity_evidence.csv','activity_review_sensitivity.csv',
        'activity_review_quality_sensitivity.csv','eda/card/monthly_age.csv','eda/card/monthly_region.csv',
        'eda/card/industries.csv','eda/card/industry_groups.csv','eda/card/time_composition.csv',
        'eda/card/residence_composition_card2.csv','eda/raw_telecom_quality.csv',
        'telecom_features.csv','card_features.csv','risk_features.csv',
        'spatial_validation_summary.json','spatial_sensitivity_summary.json','spatial_activity_level_summary.json',
        'eda/joint_review/numeric_audit_summary.json','activity_review_manifest.json',
        'activity_evidence_manifest.json','agent_activity_evidence.json']
    initial_hashes={n:digest(DATA/n) for n in names}
    levels,evidence,threshold,quality,monthly,regional,industry,groups,times,residence,raw_quality=[read(n) for n in names[:11]]
    telecom=pd.read_csv(DATA/'telecom_features.csv',dtype={'STD_YM':str,'BLOCK_CD':str},
        usecols=['STD_YM']+LOC+[f'FLOW_POP_{code}' for code in AGES])
    require_keys(levels,KEYS,'최종 단계');require_keys(evidence,KEYS,'근거')
    expected=set(pd.MultiIndex.from_product([MONTHS,REGIONS.values(),AGES.values()]))
    if set(map(tuple,levels[KEYS].to_numpy())) != expected:
        raise ValueError('전체 72개 분석 키 누락/추가')
    align=levels.merge(monthly[KEYS+['결제건수','결제금액',CHANGE,'일평균_결제금액_전월변화율']],on=KEYS,validate='one_to_one')
    if not np.allclose(align[SPEND],align[CHANGE],equal_nan=True):
        raise ValueError('현재 카드 상세 분석과 단계 입력 불일치')
    for frame in [industry,groups,times]:
        actual=frame.groupby(KEYS)[['결제건수','결제금액']].sum().sort_index()
        pd.testing.assert_frame_equal(actual,monthly.set_index(KEYS)[['결제건수','결제금액']].sort_index(),check_dtype=False)
    fixed=fixed_location_comparison(telecom,levels)
    fixed_stages,persistence=stage_trials(levels,fixed)
    write_table('fixed_location_comparison',fixed);write_table('fixed_location_stage_comparison',fixed_stages)
    write_table('persistence_sensitivity',persistence)

    context_cols=['통신_전체관측위치수','통신_연령관측률','통신_시간관측률','통신_요일관측률',
        '통신_지역공통_새벽비중','통신_지역공통_주간비중','통신_지역공통_저녁비중','통신_지역공통_주말평일비']
    context=levels[['월','지역']+context_cols].drop_duplicates().sort_values(['지역','월'])
    require_keys(context,['월','지역'],'지역 공통 맥락')
    if len(context)!=12:raise ValueError('지역 공통 정보는 12개 조합이어야 함')
    write_table('telecom_region_context',context)
    counts=levels.copy();counts['단계']=counts['활동위축단계'].fillna(0).astype(int)
    stage_counts=counts.groupby(['월','지역','단계']).size().unstack(fill_value=0).reindex(columns=range(6),fill_value=0)
    stage_counts.columns=['보류']+[f'{n}단계' for n in range(1,6)]
    write_table('monthly_stage_counts',stage_counts.reset_index())
    directions=levels[KEYS+['계산가능','자료조건충족','이동감소','소비감소','동시감소','동시감소연속개월']].copy()
    directions['신호유형']=np.select([~directions['계산가능'],~directions['자료조건충족'],directions['동시감소'],directions['이동감소'],directions['소비감소']],['전월 비교 불가','관측 조건 미달','동시 감소','이동만 감소','소비만 감소'],default='기준 이상 감소 없음')
    write_table('signal_types',directions)

    focus_keys=[('202509','강원 춘천시','10대'),('202510','강원 춘천시','10대'),
        ('202508','서울 강남구','20대'),('202511','강원 춘천시','30대'),('202512','강원 춘천시','30대'),
        ('202511','강원 춘천시','40대'),('202512','강원 춘천시','40대')]
    contributions=industry.loc[industry['일평균_결제건수_전월차이'].notna()].copy()
    contributions=contributions.merge(monthly[KEYS+['일평균_결제건수_전월차이']],on=KEYS,suffixes=('','_전체'),validate='many_to_one')
    contribution_sum=contributions.groupby(KEYS)['일평균_결제건수_전월차이'].sum()
    expected_sum=monthly.set_index(KEYS)['일평균_결제건수_전월차이'].dropna()
    if not np.allclose(contribution_sum.reindex(expected_sum.index),expected_sum,atol=1e-7):
        raise ValueError('업종 기여 합계가 전체 일평균 차이와 불일치')
    selected=[]
    for key in focus_keys:
        p=contributions.loc[(contributions[KEYS]==list(key)).all(axis=1)].copy()
        if p['일평균_결제건수_전월차이_전체'].iloc[0] >= 0:
            top=p.nlargest(5,'일평균_결제건수_전월차이')
        else:top=p.nsmallest(5,'일평균_결제건수_전월차이')
        selected.append(top[KEYS+['업종','일평균_결제건수_전월차이','일평균_결제건수_전월차이_전체']])
    drivers=pd.concat(selected,ignore_index=True);write_table('focus_industry_drivers',drivers)
    full=evidence.merge(fixed[KEYS+['고정위치_전월변화율','고정위치보존비율']],on=KEYS,validate='one_to_one')
    full=full.merge(levels[KEYS+[ROBUST,'업종제외후연속개월','단계설명']],on=KEYS,suffixes=('','_확인'),validate='one_to_one')
    full=full.merge(directions[KEYS+['신호유형']],on=KEYS,validate='one_to_one')
    write_table('all_72_results',full)
    strict=levels['계산가능'] & (levels['통신_전월공통위치비율'].lt(.95)|levels['통신_연령관측률'].lt(.8))
    quality_held=levels.loc[strict,KEYS+['활동위축단계','통신_전월공통위치비율','통신_연령관측률']]
    write_table('strict_quality_held',quality_held)

    audit=json.loads((DATA/'eda/joint_review/numeric_audit_summary.json').read_text(encoding='utf-8'))
    if not all(audit['checks'].values()):raise ValueError('수치 대조 실패')
    for name,value in audit['source_sha256'].items():
        if digest(ROOT/Path(name))!=value:raise ValueError(f'수치 감사 결과가 오래됨: {name}')
    for manifest_name in ['activity_review_manifest.json','activity_evidence_manifest.json']:
        m=json.loads((DATA/manifest_name).read_text(encoding='utf-8'))
        script_name={'activity_review_manifest.json':'build_activity_levels.py',
                     'activity_evidence_manifest.json':'build_activity_evidence.py'}[manifest_name]
        if m['script_sha256']!=digest(ROOT/'ai/risk_model'/script_name):
            raise ValueError(f'단계/근거 코드 기록 불일치: {script_name}')
        recorded_inputs=m.get('input_hashes',m.get('inputs',{}))
        if not recorded_inputs:raise ValueError(f'입력 기록 없음: {manifest_name}')
        for name,value in recorded_inputs.items():
            if digest(ROOT/Path(name))!=value:raise ValueError(f'판정/근거 입력 기록 불일치: {name}')
    spatial=json.loads((DATA/'spatial_validation_summary.json').read_text(encoding='utf-8'))
    spatial_sensitivity=json.loads((DATA/'spatial_sensitivity_summary.json').read_text(encoding='utf-8'))
    spatial_stages=json.loads((DATA/'spatial_activity_level_summary.json').read_text(encoding='utf-8'))
    spatial_status=current_spatial_status()
    if '로컬 재현 완료' not in spatial_status:raise ValueError('현재 입력의 공간 재현 미확인')
    if spatial_sensitivity['telecom_sha256']!=initial_hashes['telecom_features.csv']:
        raise ValueError('공간 민감도와 현재 통신 입력 불일치')
    if spatial_sensitivity['risk_features_sha256_unchanged']!=initial_hashes['risk_features.csv']:
        raise ValueError('공간 민감도와 현재 결합 특징 불일치')
    for name,value in spatial_stages['sha256'].items():
        if digest(DATA/name)!=value:raise ValueError(f'공간 단계 비교 기록 불일치: {name}')

    stage_summary={str(n):int(levels['활동위축단계'].eq(n).sum()) for n in range(1,6)}
    stage_summary['보류']=int(levels['활동위축단계'].isna().sum())
    fixed_change=int(fixed_stages['단계변경'].sum())
    figures=charts(align,regional,groups,times,fixed,context)
    summary={'status':'analysis_outputs_complete_team_signoff_pending','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'rows':len(levels),'comparison_rows':int(levels['계산가능'].sum()),'stage_counts':stage_summary,
        'fixed_location_counts':fixed.groupby('지역')['고정위치수'].first().to_dict(),
        'fixed_location_retention_min':float(fixed['고정위치보존비율'].min()),
        'fixed_location_max_change_difference':float(fixed['전월변화율차이'].abs().max()),
        'fixed_location_stage_changes':fixed_change,
        'fixed_location_stage_change_rows':fixed_stages.loc[fixed_stages['단계변경']].to_dict('records'),
        'persistence_sensitivity':persistence.to_dict('records'),
        'strict_quality_new_held_rows':len(quality_held),'numeric_checks_passed':len(audit['checks']),
        'charts':figures,'scope':'2025년 7~12월 × 활동지역 2개 × 연령 6개; 집계 기술 분석',
        'spatial_status':spatial_status,'risk_features_unchanged':True,
        'team_signoff':False,'isolation_model_validation':False,'fixed_locations_use_future_months':True}
    # 직렬화용 결측은 null. 보류를 0단계로 외부 전달하지 않는다.
    changes=fixed_stages.loc[fixed_stages['단계변경']].copy()
    summary['fixed_location_stage_change_rows']=json.loads(changes.to_json(orient='records',force_ascii=False))
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

    fmt_cols={SPEND:'소비 전월비',MOVE:'통신 전월비',ROBUST:'업종 제외 소비 전월비',
        '고정위치_전월변화율':'고정 위치 통신 전월비','활동위축단계':'단계',
        '통신_전월공통위치비율':'공통 위치 비율','통신_연령관측률':'연령 관측률',
        '소비_지역전체대비차이':'지역 전체 소비 대비 차이','과거3개월대비변화율':'직전 3개월 대비 소비'}
    focus=full.loc[full['지역'].eq('강원 춘천시')&full['연령대'].isin(['30대','40대'])&full['월'].isin(['202511','202512'])]
    focus_view=format_table(focus[KEYS+['활동위축단계',SPEND,MOVE,ROBUST,'고정위치_전월변화율','동시감소연속개월']],
        percent=[SPEND,MOVE,ROBUST,'고정위치_전월변화율'],ints=['활동위축단계']).rename(columns=fmt_cols)
    regional_view=format_table(regional[['월','지역','일평균_결제건수',CHANGE,'일평균_결제금액_전월변화율']],
        percent=[CHANGE,'일평균_결제금액_전월변화율'],decimals=['일평균_결제건수'])
    threshold_view=threshold.copy();threshold_view['감소기준']=threshold_view['감소기준'].map(lambda v:f'{v:.0%}')
    threshold_view['큰감소기준']=threshold_view['큰감소기준'].map(lambda v:f'{v:.0%}')
    quality_view=format_table(quality,ratios=['공통위치조건','연령관측률조건'])
    retention=fixed.groupby('지역',as_index=False).agg(고정위치수=('고정위치수','first'),최소보존비율=('고정위치보존비율','min'),최대보존비율=('고정위치보존비율','max'))
    retention_view=format_table(retention,ratios=['최소보존비율','최대보존비율'],ints=['고정위치수'])
    tables={'대표 지속 감소':focus_view,'지역 전체 카드':regional_view,'감소 기준':threshold_view,
        '관측 조건':quality_view,'지속 기간':persistence,'고정 위치 범위':retention_view}
    notes=build_notes(summary,levels,evidence,regional,fixed,drivers,context,residence,raw_quality,changes,groups,times)
    charts_html=''.join(f'<figure><img src="{f["name"]}.svg" alt="{escape(f["title"])}"><figcaption>{escape(f["caption"])}</figcaption></figure>' for f in figures)
    note_html=''.join(f'<p>{escape(n)}</p>' for n in notes)
    full_view=format_table(full[KEYS+['활동위축단계',SPEND,MOVE,'고정위치_전월변화율','동시감소연속개월','신호유형','업종민감도주의','소비_지역전체대비차이','통신_연령관측률','통신_전월공통위치비율']],
        percent=[SPEND,MOVE,'고정위치_전월변화율'],ratios=['통신_연령관측률','통신_전월공통위치비율'],
        points=['소비_지역전체대비차이'],ints=['활동위축단계']).rename(columns=fmt_cols)
    rows=''.join('<tr data-region="'+escape(str(row['지역']))+'" data-age="'+escape(str(row['연령대']))+'" data-month="'+escape(str(row['월']))+'">'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for _,row in full_view.iterrows())
    table_html='<div class="scroll"><table id="all-results"><thead><tr>'+''.join('<th>'+escape(c)+'</th>' for c in full_view.columns)+'</tr></thead><tbody>'+rows+'</tbody></table></div>'
    filters=''.join('<label>'+label+' <select id="filter-'+key+'"><option value="">전체</option>'+''.join('<option>'+escape(v)+'</option>' for v in values)+'</select></label>' for key,label,values in [('region','지역',sorted(REGIONS.values())),('age','연령',list(AGES.values())),('month','월',MONTHS)])
    methods='''<p>소비 전월비 = (현재 월 건수 / 현재 월 일수) ÷ (전월 건수 / 전월 일수) − 1. 통신 전월비 = 두 달 모두 연령값이 유효한 동일 위치에서의 현재 합계 ÷ 전월 합계 − 1. 통신 원본은 이미 일평균이므로 월 일수로 다시 나누지 않는다. 전월 분모가 0이면 계산 불가다.</p>
<p>공통 위치 비율의 분모는 현재 월 유효 위치 수다. 현재월 분모 최솟값 93.52%, 전월 분모로 추가 대조한 최솟값 92.59%. 연령 관측률은 세 통신 자료 결합 위치 중 연령값이 유효한 위치의 비율이다.</p>
<p>1단계는 기준 이상 감소 없음, 2단계는 단일 지표 감소, 3단계는 동시 감소, 4단계는 동시 감소가 2회 이상 지속, 5단계는 지속 조건과 현재 두 지표 5% 감소 및 업종 제외 후 지속 조건을 함께 만족할 때다. 보류는 단계 밖 상태다. 2회 연속 전월비에는 최소 3개월이 필요하다.</p>
<p>3%·5%·2회·90%·75%는 시범 가정이다. 통신 시간·요일 맥락은 지역×월 12개 조합만 사용하며 연령별 값으로 중복 합산하지 않는다. 6개월·두 지역의 집계자료에 고립 정답은 없어 개인 고립 확률·예측 정확도·인과효과를 산출하지 않았다.</p>'''
    sources='''<ul><li>대회 제공 카드1·2 및 연령·시간·요일 통신 원본, 2025년 7~12월. 카드 지역은 오프라인 가맹점, 고객 거주지는 시도 단위. 연령 통신은 일평균 유동량.</li>
<li>제공 정의서: [별첨1] 이동전화 가입자·이동 정보, Sheet1 C4(연령 일평균), C32(시간대 일평균), C72(요일 일평균), I8:I9(UTM-K). 2026빅콘테스트 신한카드 레이아웃 안, 주제1_데이터셋2 A6(오프라인 가맹점), 주제2_데이터셋2 G13(시도 거주지). 금액 배율은 명시되지 않아 원 단위 금액·예산으로 변환하지 않았다.</li>
<li><a href="https://sgis.mods.go.kr/view/pss/openDataIntrcn">SGIS 센서스용 시군구 경계</a>, 2025년 2분기, BASE_DATE 20250630. 사용자 제공 ZIP. 통신 UTM-K를 EPSG:5179로 해석한 조건부 검증.</li>
<li><a href="https://mhealth.jmir.org/2019/7/e13209">Doryab et al. 2019</a>, <a href="https://mhealth.jmir.org/2022/4/e34638/">Qirtas et al. 2022</a>: 이동·활동과 외로움의 관련성 탐색 및 검증 필요성. 우리 집계 규칙의 정확도 근거가 아님.</li>
<li><a href="https://doi.org/10.1111/jgs.19331">Yu et al. 2025</a>, <a href="https://doi.org/10.1186/s11556-022-00286-0">ActiFE 2022</a>: 고령층 활동 및 날씨라는 대안 설명의 참고 근거. 효과크기·임계값을 가져오지 않았다.</li></ul>'''
    html=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Ieum-care 데이터 분석 1번 최종 정리</title>
<style>body{{margin:0;background:#f2f5f7;color:#193047;font:15px/1.8 'Malgun Gothic',sans-serif}}main{{max-width:1100px;margin:auto;padding:36px}}section{{background:#fff;padding:28px;margin:24px 0;border-radius:12px}}h1{{font-size:30px;line-height:1.35}}h2{{font-size:22px}}h3{{font-size:17px}}.intro{{border-left:5px solid #216a8d;padding:16px 22px;background:#e9f1f6}}nav a{{display:inline-block;margin-right:18px}}a{{color:#216a8d}}figure{{margin:30px 0}}img{{width:100%;height:auto}}figcaption,.muted{{font-size:13px;color:#5e7080}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}}th,td{{padding:9px 12px;border-bottom:1px solid #dce4ea;text-align:right}}th{{background:#edf2f5}}td:first-child,th:first-child{{text-align:left}}label{{display:inline-block;margin:0 18px 14px 0}}select{{font:inherit;padding:5px;border:1px solid #bccbd5;border-radius:4px}}details{{margin-top:20px}}button{{padding:8px 15px;background:#216a8d;color:#fff;border:0;border-radius:5px;cursor:pointer}}@media print{{main{{padding:0}}body{{background:white}}section{{padding:12px;border-radius:0}}figure{{break-inside:avoid}}nav,.filters,button{{display:none}}.scroll{{overflow:visible}}table{{white-space:normal;font-size:9px}}}}</style></head>
<body><main><p class="muted">Ieum-care · 2026년 10월 14일 분석 정리 · 2025년 7~12월</p><h1>활동 위축이 지속되는 집단과<br>결과를 해석할 때 확인할 조건</h1>
<div class="intro">전체 72개 집단·월과 비교 가능한 전월비 60개를 분석했습니다. 계산·자료 검증은 완료했고, 시범 기준의 팀 합의와 공급기관 정의 확인은 남아 있습니다.<br>기본 단계: {' · '.join(f'{k}단계 {v}개' if k!='보류' else f'보류 {v}개' for k,v in stage_summary.items())}</div>
<nav><a href="#findings">핵심 결과</a><a href="#figures">전체 그래프</a><a href="#sensitivity">민감도</a><a href="#all">72개 결과</a><a href="#method">계산·근거</a></nav>
<section id="findings"><h2>핵심 결과</h2>{note_html}<h3>춘천 30·40대의 11~12월</h3>{html_table(focus_view)}</section>
<section id="figures"><h2>전체 범위의 변화와 구성</h2>{charts_html}<details><summary>지역 전체 카드 수치</summary>{html_table(regional_view)}</details></section>
<section id="sensitivity"><h2>가정을 바꾸면 결과는 어떻게 달라지는가</h2><h3>감소 기준 2%·3%·5%</h3>{html_table(threshold_view)}<h3>관측 조건</h3>{html_table(quality_view)}<p>강화 조건에서 새로 보류되는 {len(quality_held)}개 집단·월은 <a href="strict_quality_held.csv">별도 목록</a>으로 보존했습니다.</p><h3>지속 기간 2회·3회</h3>{html_table(persistence)}<h3>모든 월 동일 위치 비교</h3>{html_table(retention_view)}<p>기본 관측 조건을 유지하고 통신 변화율만 고정 위치 값으로 교체하면 단계 변경 {fixed_change}개입니다. 미래 월 정보를 쓴 사후 민감도이므로 기존 단계 입력은 변경하지 않았습니다.</p>{html_table(format_table(changes,ints=['활동위축단계','고정위치_단계']))}</section>
<section id="all"><h2>전체 72개 집단·월 결과</h2><p>지역·연령·월을 선택해 결과를 확인할 수 있습니다. <a href="all_72_results.csv">전체 수치 내려받기</a></p><div class="filters">{filters}<span id="visible-count">72개 표시</span></div>{table_html}</section>
<section id="method"><h2>계산·검증·근거</h2>{methods}<p>{escape(spatial_status)}. 대상 위치 {sum(spatial['target_location_status_counts'].values()):,}개 중 불일치 2개를 제외해도 2%·3%·5% 기준의 단계 변화는 0개입니다. 제외에 따른 최대 전월비 차이 {spatial_sensitivity['maximum_age_change_absolute_difference']*100:.8f}%p.</p><p>원본 카드 합계와 특징, 업종·시간대 합계, 통신 원본 중복·키·숫자 품질, 결합 특징 재계산을 확인했습니다. 독립 수치 대조 {len(audit['checks'])}개 항목 통과. 실행·입력·산출물 기록은 <a href="manifest.json">재현 기록</a>에 보존합니다.</p><h3>자료와 문헌</h3>{sources}<p>생성형 AI는 분석 코드 작성·실행, 문헌 검토, 설명 문서와 그래프 정리에 사용했습니다. 수치는 실제 제공자료에서 계산했으며 가상 관측·고립 정답·원인 설명을 생성하지 않았습니다.</p><h3>분석 이후 확인할 사항</h3><p>현지님과 지표 정의·시범 임계값·보류 및 업종 주의 표현을 검토하고, 공급기관에 좌표계 전체 정의·대표점 의미·금액 단위를 확인합니다. 2번 담당자에게는 <a href="../../agent_activity_evidence.json">기존 Agent 근거 입력</a>과 이 분석 결과를 함께 전달합니다. 자료를 자동으로 전송하거나 공개하지 않았습니다.</p><p><a href="../card/report.html">카드 업종·시간대·거주지 전체 상세</a> · <a href="../joint_review/report.html">공동 검토용 대표 사례</a> · <a href="summary.md">최종 설명문</a></p></section><button onclick="window.print()">보고서 인쇄</button></main>
<script>const filterKeys=['region','age','month'];function filterRows(){{let n=0;document.querySelectorAll('#all-results tbody tr').forEach(row=>{{const show=filterKeys.every(k=>!document.getElementById('filter-'+k).value||row.dataset[k]===document.getElementById('filter-'+k).value);row.hidden=!show;if(show)n++;}});document.getElementById('visible-count').textContent=n+'개 표시';}}filterKeys.forEach(k=>document.getElementById('filter-'+k).addEventListener('change',filterRows));</script></body></html>'''
    (OUT/'report.html').write_text(html,encoding='utf-8')
    markdown='# 데이터 분석 1번 최종 정리\n\n2026-10-14. 분석 산출물 완료, 시범 기준의 팀 검토는 별도.\n\n'
    markdown+='\n\n'.join(notes)+'\n\n'
    for title,frame in tables.items():markdown+=f'## {title}\n\n'+md_table(frame)+'\n\n'
    markdown+='## 계산과 해석\n\n소비는 일평균 결제건수, 통신은 인접 두 월 공통 위치의 연령유동량 전월비다. 지역은 가맹점·관측 활동 지역이며 같은 개인이나 거주민 집단을 연결하지 않았다. 통신 시간·요일은 지역×월 12개 조합의 맥락이다. 7월 보류는 6월 자료가 없기 때문이다. 3%·5%·2회·90%·75%는 시범 가정이며 독립 고립 검증은 없다.\n\n'
    markdown+='금액 정의서는 결제금액 합계라고 설명하나 배율을 명시하지 않았다. 금액 변화율·구성비는 보존하고 절대값을 원 단위 예산으로 전환하지 않았다. 통신 정의서는 일평균 유동인구와 UTM-K를 명시한다. EPSG:5179 및 대표점의 기관 확인은 남아 있다.\n\n'
    markdown+='## 오늘 완료한 결과와 남은 공동 확인\n\n전체 집단 분석·업종 기여·시간대·거주지 구성·관측 조건·공간 재현·민감도·72개 결과표·Agent 입력을 준비했다. 현지와 시범 기준 및 표현을 합의하고 2번 담당자가 입력 형식을 확인하면 팀 인계가 가능하다. 기관 정의 확인과 실제 고립 정답 검증은 별도 미확정 사항으로 명시한다.\n\n'
    markdown+='## 자료 위치\n\n이 폴더의 report.html에 모든 그래프와 필터 가능한 결과표, all_72_results.csv에 상세 수치, manifest.json에 입력·코드·출력 해시를 보존했다. 고정 위치는 fixed_location_comparison.csv 및 fixed_location_stage_comparison.csv, 지속 기간은 persistence_sensitivity.csv, 업종 기여는 focus_industry_drivers.csv를 확인한다.\n'
    (OUT/'summary.md').write_text(markdown,encoding='utf-8')
    (ROOT/'docs/data_analysis_final_20261014.md').write_text(markdown,encoding='utf-8')
    # 보고서 생성 중 다른 입력이 바뀌거나 원본 특징을 변경했으면 완료로 기록하지 않음.
    if initial_hashes!={n:digest(DATA/n) for n in names}:raise ValueError('분석 중 입력 파일 변경')
    raw_sources=sorted((ROOT/'data/raw').glob('flow_*_pop_*.csv'))+sorted((ROOT/'data/raw').glob('신한카드*.txt'))
    definitions=[p for p in (ROOT/'data/raw').glob('*.xlsx') if p.name.startswith('[별첨') or p.name.startswith('2026빅')]
    manifest={'status':summary['status'],'created_at_utc':summary['created_at_utc'],
        'python':sys.version.split()[0],'pandas':pd.__version__,'numpy':np.__version__,
        'source_sha256':{(DATA/n).relative_to(ROOT).as_posix():v for n,v in initial_hashes.items()},
        'raw_and_definition_sha256':{p.relative_to(ROOT).as_posix():digest(p) for p in raw_sources+definitions},
        'script_sha256':digest(Path(__file__)),
        'dependency_script_sha256':{p.relative_to(ROOT).as_posix():digest(p) for p in
            [ROOT/'ai/risk_model/build_activity_levels.py',ROOT/'scripts/data_processing/data_contract.py',
             ROOT/'scripts/data_processing/spatial_review_status.py']},
        'output_sha256':{p.name:digest(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='manifest.json'},
        'complete_scope':['card_all_groups','telecom_all_groups','industry_contributions','time_residence_context',
            'spatial_reproduction','threshold_quality_duration_fixed_location_sensitivity','all_72_results','agent_evidence_available'],
        'remaining':['team_rule_signoff','provider_full_CRS_point_definition_amount_unit','independent_isolation_validation'],
        'fixed_location_usage':'retrospective_sensitivity_only_not_live_model_input'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['rows','stage_counts','fixed_location_counts',
        'fixed_location_retention_min','fixed_location_max_change_difference','fixed_location_stage_changes',
        'fixed_location_stage_change_rows','persistence_sensitivity']},ensure_ascii=False,indent=2))
    print(OUT/'report.html')


def build_notes(summary,levels,evidence,regional,fixed,drivers,context,residence,raw_quality,changes,groups,times):
    notes=[]
    dec=regional.loc[regional['월'].eq('202512')].set_index('지역')
    notes.append(f"12월 지역 전체 일평균 결제건수는 춘천 {dec.loc['강원 춘천시',CHANGE]:+.2%}, 강남 {dec.loc['서울 강남구',CHANGE]:+.2%}다. 연령별 감소는 이 지역 전체 변화와 함께 해석한다.")
    focus=evidence.loc[evidence['월'].eq('202512')&evidence['지역'].eq('강원 춘천시')&evidence['연령대'].isin(['30대','40대'])].set_index('연령대')
    for age in ['30대','40대']:
        r=focus.loc[age]
        notes.append(f"12월 춘천 {age}는 소비 {r[SPEND]:+.2%}, 통신 {r[MOVE]:+.2%}, 동시 감소 {int(r['동시감소연속개월'])}회로 시범 4단계다. 지역 전체 소비 대비 차이는 {r['소비_지역전체대비차이']*100:+.2f}%p, 직전 3개월 평균 대비 소비는 {r['과거3개월대비변화율']:+.2%}다.")
    notes.append('골프장·놀이동산 제외 후 춘천 30대의 11~12월 소비 감소는 3% 기준을 유지한다. 40대는 11월 감소가 3% 미만이 되어 연속 조건이 끊긴다. 업종 선택에 대한 민감도를 함께 전달한다.')
    teen=levels.loc[levels['월'].eq('202509')&levels['지역'].eq('강원 춘천시')&levels['연령대'].eq('10대')].iloc[0]
    p=drivers.loc[drivers['월'].eq('202509')&drivers['연령대'].eq('10대')].head(3)
    description=', '.join(f"{r['업종']} {r['일평균_결제건수_전월차이']:+,.1f}건/일" for _,r in p.iterrows())
    notes.append(f"9월 춘천 10대 소비는 {teen[SPEND]:+.2%}, 통신은 {teen[MOVE]:+.2%}다. 소비 증가 기여 상위는 {description}이다. 학사 일정·관광·날씨 등 원인은 확인되지 않았다.")
    mismatch=levels.loc[levels['월'].eq('202508')&levels['지역'].eq('서울 강남구')&levels['연령대'].eq('20대')].iloc[0]
    notes.append(f"8월 강남 20대는 소비 {mismatch[SPEND]:+.2%}, 통신 {mismatch[MOVE]:+.2%}로 방향이 다르다. 두 자료의 지표 의미와 관측 대상을 각각 보존한다.")
    time_sum=times.groupby(['지역','TIME_GB'])['결제건수'].sum()
    for region in sorted(REGIONS.values()):
        midday=time_sum.loc[region,'12_17']/time_sum.loc[region].sum()
        notes.append(f"전체 6개월 {region}의 12~17시 결제건수 비중은 {midday:.2%}다.")
    notes.append('카드2 거주지는 시도 단위이므로 강원 고객을 춘천 주민, 서울 고객을 강남 주민으로 동일시하지 않는다. 전체 거주지 구성은 카드 상세표에 보존했다.')
    held_share=groups.loc[groups['업종그룹'].eq('해석보류'),'결제건수'].sum()/groups['결제건수'].sum()
    notes.append(f"전체 개인 결제건수 중 해석보류 업종 비중은 {held_share:.2%}다. 관측값 누락이 아니라 세부 업종 의미의 불확실성이므로 전체 소비 분모에 유지하고 사회활동 후보로 확대하지 않는다. 카드1·2는 중복 정보를 포함할 수 있어 합산하지 않고 카드2는 교차확인 자료로 남겼다.")
    notes.append(f"6개월 동일 위치 비교는 단계 {summary['fixed_location_stage_changes']}개를 바꾼다. 두 통신 계산의 전월비 최대 차이는 {summary['fixed_location_max_change_difference']*100:.2f}%p다. 대상 사례와 전체 변경 목록을 보존했다. 전체 기간을 사용한 사후 민감도이며 기본 단계 입력은 유지한다.")
    duration=summary['persistence_sensitivity'][-1]
    notes.append(f"지속 조건을 연속 전월비 2회에서 3회로 강화하면 4단계 {duration['4단계']}개, 5단계 {duration['5단계']}개이며 기본 대비 {duration['기본대비단계변경']}개가 달라진다. 3회 지속에는 최소 4개월 관측이 필요하다.")
    notes.append(f"관측 조건을 95%·80%로 강화하면 보류가 12개에서 24개로 늘고 기존 4단계 두 사례도 보류된다. 연령 관측률 범위는 {context['통신_연령관측률'].min():.2%}~{context['통신_연령관측률'].max():.2%}, 시간은 {context['통신_시간관측률'].min():.2%}~{context['통신_시간관측률'].max():.2%}다.")
    duplicates=raw_quality.loc[raw_quality['완전중복행수'].gt(0),['파일','완전중복행수']]
    notes.append('통신 원본 12월 시간 자료의 완전 중복 92,545행과 요일 자료의 완전 중복 121,267행은 정제에서 제거했다. 중복제거 후 키 충돌·키 결측·부분 결측·음수·무한대는 원본 감사에서 발견되지 않았다. 세 자료 간 관측 위치 차이는 결측으로 보존했다.' if len(duplicates)==2 else '통신 원본의 중복·키·숫자 품질 감사표를 보존했다.')
    notes.append('공간 검증은 대상 고유 위치 126,291개 중 2개 불일치를 기록했다. 이를 제외해도 2%·3%·5% 감소 기준 모두 단계 변화가 없다. 좌표계 해석은 조건부이며 기관 정의 확인은 남아 있다.')
    notes.append('모든 분석은 72개 집단·월의 관측 활동 변화다. 실제 고립 정답과 개인 연결키가 없으므로 고립 진단·개인 확률·지원 자격을 확정하지 않는다. 외부 생활·날씨 자료는 이번 점수에 추가하지 않았다.')
    return notes


if __name__=='__main__':main()
