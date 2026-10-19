"""현재 활동 분석 산출물을 공동 검토용 HTML·SVG·CSV로 묶는다."""
from pathlib import Path
from html import escape
import hashlib
import json
import pandas as pd
from analyze_risk_features import heatmap
from spatial_review_status import current_spatial_status

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/processed'
OUT = DATA / 'eda/joint_review'
KEYS = ['월', '지역', '연령대']
CARD = '소비_일평균건수_전월변화율'
FLOW = '통신_연령유동량_전월변화율'
AGES = ['10대', '20대', '30대', '40대', '50대', '60대이상']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    names = ['activity_review_levels.csv', 'activity_evidence.csv',
             'activity_review_sensitivity.csv', 'activity_review_quality_sensitivity.csv',
             'eda/card/top_industry_drivers.csv']
    sources = [DATA / n for n in names]
    levels, evidence, sensitivity, quality, drivers = [
        pd.read_csv(p, dtype={'월': str}) for p in sources]
    assert len(levels) == 72 and not levels.duplicated(KEYS).any()
    assert len(evidence) == 72 and not evidence.duplicated(KEYS).any()
    assert set(map(tuple, levels[KEYS].values)) == set(map(tuple, evidence[KEYS].values))
    regions = sorted(levels['지역'].unique())
    order = pd.MultiIndex.from_product([regions, AGES], names=['지역', '연령대'])
    charts = []
    for filename, column, title, ratio in [
        ('01_card_change', CARD, '카드 · 일평균 결제건수 전월 변화', False),
        ('02_telecom_change', FLOW, '통신 · 전월 공통 위치의 연령유동량 변화', False),
        ('03_age_coverage', '통신_연령관측률', '통신 · 연령자료 관측률 (인구 대표성 아님)', True),
        ('04_common_locations', '통신_전월공통위치비율', '통신 · 전월 공통 위치 비율', True),
    ]:
        matrix = levels.pivot(index=['지역', '연령대'], columns='월', values=column).reindex(order)
        svg = heatmap(matrix, title, diverging=not ratio)
        svg = svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" font-family="Malgun Gothic, sans-serif" ', 1)
        (OUT / f'{filename}.svg').write_text(svg, encoding='utf-8')
        charts.append(f'<figure>{svg}</figure>')

    selections = [
        ('지속 감소', '202512', '강원 춘천시', '30대', '11~12월 이동·소비 동시 감소. 업종 제외 조건에서도 연속 감소가 유지된다.'),
        ('업종 민감도 주의', '202512', '강원 춘천시', '40대', '전체 소비로는 연속 감소지만, 11월 골프·놀이동산 제외 시 3% 감소 조건이 끊긴다.'),
        ('방향 불일치', '202508', '서울 강남구', '20대', '통신은 감소하고 소비는 증가한다. 같은 개인의 행동 불일치라고 해석하지 않는다.'),
        ('첫 달 판정 보류', '202507', '강원 춘천시', '30대', '6월 자료가 없어 전월 비교 불가. 낮은 위험으로 분류하지 않는다.'),
        ('카드 급증 점검', '202509', '강원 춘천시', '10대', '카드 급증의 업종 기여를 확인한다. 학교 일정 등 원인은 검증 전 가설이다.'),
    ]
    records = []
    for label, month, region, age, explanation in selections:
        found = evidence.loc[(evidence['월'] == month) & (evidence['지역'] == region) & (evidence['연령대'] == age)]
        assert len(found) == 1
        row = found.iloc[0]
        records.append({'사례': label, **{k: row[k] for k in KEYS},
            '단계': row['활동위축단계'], '소비변화율': row[CARD], '통신변화율': row[FLOW],
            '연속개월': row['동시감소연속개월'], '과거3개월대비소비': row['과거3개월대비변화율'],
            '지역전체소비변화': row['지역전체_소비전월변화율'], '해석': explanation})
    cases = pd.DataFrame(records)
    cases.to_csv(OUT / 'representative_cases.csv', index=False, encoding='utf-8-sig')
    table = cases.copy()
    for col in ['소비변화율', '통신변화율', '과거3개월대비소비', '지역전체소비변화']:
        table[col] = table[col].map(lambda v: '비교 불가' if pd.isna(v) else f'{v:+.2%}')
    table['단계'] = table['단계'].map(lambda v: '보류' if pd.isna(v) else str(int(v)))
    focus = levels.loc[(levels['월'].isin(['202511','202512'])) &
        levels['지역'].eq('강원 춘천시') & levels['연령대'].isin(['30대','40대']),
        KEYS + [CARD, FLOW, '소비_골프레저제외_전월변화율', '동시감소연속개월', '업종민감도주의']].copy()
    focus.to_csv(OUT / 'chuncheon_persistence.csv', index=False, encoding='utf-8-sig')
    for col in [CARD, FLOW, '소비_골프레저제외_전월변화율']:
        focus[col] = focus[col].map(lambda v: f'{v:+.2%}')
    teen = drivers.loc[drivers['월'].eq('202509') & drivers['지역'].eq('강원 춘천시') & drivers['연령대'].eq('10대'),
        ['업종', '일평균_결제건수_전월차이', '변화방향']].sort_values('일평균_결제건수_전월차이', ascending=False)
    counts = levels['활동위축단계'].value_counts().reindex(range(1,6), fill_value=0)
    summary = ' / '.join(f'{i}단계 {int(counts[i])}개' for i in range(1,6)) + f" / 보류 {levels['활동위축단계'].isna().sum()}개"
    html_table = lambda d: d.to_html(index=False, border=0, escape=True, na_rep='—', float_format=lambda v: f'{v:,.2f}')
    body = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>1번 데이터 분석 공동 검토</title>
<style>body{{font-family:'Malgun Gothic',sans-serif;margin:0;background:#f2f5f8;color:#172838;line-height:1.7}}main{{max-width:1150px;margin:32px auto;background:white;padding:38px;border-radius:16px}}h1{{font-size:30px}}h2{{margin-top:42px}}.lead{{background:#eaf3fa;padding:20px;border-radius:12px}}.note{{color:#586675}}figure{{margin:24px 0}}svg{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border-bottom:1px solid #dce4eb;padding:10px;text-align:left}}th{{background:#edf3f7}}.scroll{{overflow:auto}}a{{color:#12659a}}@media print{{body{{background:white}}main{{margin:0;padding:10px}}figure{{break-inside:avoid}}}}</style>
<main><p class="note">2026년 10월 14일 갱신 · 한수·현지 공동 검토용</p>
<h1>활동 위축 분석: 결과와 확인할 사항</h1>
<div class="lead"><b>전체 72개 집단-월의 분석 결과를 준비했습니다. 공동 검토·공간 재현 확인은 남아 있습니다.</b><br>
2025년 7~12월 × 강남·춘천 × 6연령. 개인 고립 진단·확률이 아닌 활동 변화의 검토 자료입니다.<br>{escape(summary)}</div>
<h2>1. 전체 지역·연령의 변화</h2><p>카드는 월 일수로 보정한 일평균 건수, 통신은 인접 월 공통 위치의 변화입니다. 두 지표는 같은 개인을 추적한 값이 아닙니다. 색상은 변화 방향이며 위험 등급이 아닙니다. 7월은 이전 월이 없어 비교 불가입니다.</p>
{charts[0]}{charts[1]}
<h2>2. 공동으로 설명할 대표 사례</h2><div class="scroll">{html_table(table)}</div>
<p>30·40대 감소는 춘천 지역 전체 소비 감소와 함께 나타납니다. 지역 전체보다 특별히 큰 소비 감소인지도 함께 확인해야 합니다. 3개월 기준 비교는 계절 보정이 아닙니다.</p>
<h3>춘천 30·40대: 11월과 12월을 함께 확인</h3><div class="scroll">{html_table(focus)}</div>
<h3>춘천 10대 9월: 카드 일평균 건수 변화의 주요 업종</h3>{html_table(teen)}<p class="note">단위: 전월 대비 하루 평균 결제건수 차이. 주요 업종 목록이며 전체 업종 합계가 아닙니다. 결제건수는 사람 수가 아닙니다.</p>
<h2>3. 기준을 바꾸면 결과가 얼마나 달라지는가</h2>{html_table(sensitivity)}
<p>감소기준 0.02/0.03/0.05는 2%/3%/5%입니다. 기준을 5%로 높이면 4단계가 사라집니다. 단계 경계는 논문에서 검증된 수치가 아닌 팀의 시범 가정입니다.</p>
{html_table(quality)}<p>관측 기준을 95%·80%로 강화하면 보류가 24개로 늘고 기존 4단계 사례도 보류됩니다. 낮은 관측 품질을 낮은 위험으로 처리하지 않습니다.</p>
<h2>4. 통신 관측 범위</h2>{charts[2]}{charts[3]}
<p>지역 공통 관측률은 연령별로 반복될 수 있습니다. 72개의 독립 표본이나 인구 대표성을 뜻하지 않습니다.</p>
<h2>5. 현지님과 확인할 항목</h2><ul>
<li>동일한 입력·버전에서 통신 전월비와 공통 위치 비율이 일치하는가?</li>
<li>SGIS 경계 원본으로 공간 결과를 로컬 재현했다. 현지의 입력·버전 및 기관 정의 확인 상태와 함께 검토한다.</li>
<li>통신 좌표계의 전체 정의·대표점 의미·BLOCK_CD 기준일은 어디까지 확인됐는가?</li>
<li>3%/5%·2개월 지속·90%/75% 관측 조건을 시범 기준으로 채택할 것인가? 민감도를 함께 전달할 것인가?</li>
<li>대표 사례의 설명과 판정 보류를 2번 Agent 입력에 그대로 보존할 것인가?</li></ul>
<h2>6. 오늘 마무리할 공동 검토</h2><p>전체 분석·수치 대조·공간 재현·민감도 결과를 확인하고 시범 기준과 표현을 검토합니다. 분석 요약·기준표·입력 JSON을 2번 담당자에게 전달할 자료를 준비했습니다. 실제 전송은 팀원이 직접 하거나 별도 요청에 따라 진행합니다.</p>
<p><a href="../final_analysis_20261014/report.html">최종 전체 분석·고정 위치·지속 기간 민감도 보기</a></p>
<p><a href="../card/report.html">전체 카드 분석 보기</a> · <a href="../../../agent_activity_evidence.json">Agent 근거 입력</a></p>
<p class="note">외부 데이터 추가 없이 기존 결과를 정리했습니다. 실제 고립 정답·연간 계절성 검증은 없으며, 이 보고서는 공간 검증의 완료를 선언하지 않습니다.</p></main></html>'''
    # 보고서는 data/processed/eda/joint_review 아래이므로 processed는 두 단계 위.
    body = body.replace('../../../agent_activity_evidence.json', '../../agent_activity_evidence.json')
    spatial = current_spatial_status()
    body = body.replace('공동 검토·공간 재현 확인은 남아 있습니다.', '공동 검토는 남아 있습니다.')
    body = body.replace('이 보고서는 공간 검증의 완료를 선언하지 않습니다.', escape(spatial))
    body = body.replace('문서상 조건부 완료와 로컬 미재현 상태를 구분한다.', escape(spatial))
    (OUT / 'report.html').write_text(body, encoding='utf-8')
    manifest = {'scope': 'joint_review_not_final_signoff', 'rows': len(levels), 'case_count': len(cases),
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'spatial_status': spatial}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(summary)
    print(table.to_string(index=False))
    print(OUT / 'report.html')


if __name__ == '__main__':
    main()
