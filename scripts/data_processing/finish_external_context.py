"""Collect official regional CPI and assemble the supplementary analysis report."""
import hashlib
from html import escape
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/processed/external_context_20261015'
RAW = ROOT / 'data/external/public_context/cpi_20261015'


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    cpi, manifest = {}, []
    url = 'https://mods.go.kr/cpidtvalregionAjax.es'
    for month in range(6, 13):
        key = f'2025{month:02}'
        params = dict(selectDate=key, selectArea='T10', selectYear='2025', selectMonth=f'{month:02}', selectItem='rdo01')
        path = RAW / f'cpi_{key}.json'
        if not path.exists():
            req = Request(url, data=json.dumps(params).encode(), headers={'Content-Type': 'application/json',
                          'Referer': 'https://mods.go.kr/cpidtvalregion.es?mid=b70201040000'})
            with urlopen(req, timeout=40) as response:
                path.write_bytes(response.read())
        raw = path.read_bytes()
        data = json.loads(raw)
        for area, region in [('T11', '11230'), ('T31', '32010')]:
            matches = [r for r in data['cpiTrdViewVORegionList'] if r['ov_l1_id'] == area]
            assert len(matches) == 1
            r = matches[0]
            assert r['prd_ym'] == key
            value, previous = float(r['dtval_co']), float(r['dtval_co2'])
            assert value > 0 and previous > 0
            cpi[(key, region)] = dict(month=key, region_code=region,
                                      geography='서울' if area == 'T11' else '강원',
                                      cpi_2020_100=value, prior_cpi=previous, mom_change=value / previous - 1,
                                      usage_status='exploratory_reuse_conditions_pending')
        manifest.append(dict(file=path.name, url=url, method='POST', params=params,
                             sha256=hashlib.sha256(raw).hexdigest()))
    for (month, region), r in cpi.items():
        if month != '202506':
            assert abs(cpi[(str(int(month)-1), region)]['cpi_2020_100'] - r['prior_cpi']) < 1e-8
    data = json.loads((OUT / 'activity_external_context.json').read_text(encoding='utf-8'))
    for r in data['records']:
        month, region, _ = r['analysis_id'].split('_')
        r['economic_context'] = cpi[(month, region)]
    data['limitations'].append('CPI is provincial price context, not a local business-cycle measure; reuse terms pending; counts/flow not deflated.')
    original = json.loads((ROOT / 'data/processed/agent_activity_evidence.json').read_text(encoding='utf-8'))
    assert [r['analysis_evidence'] for r in data['records']] == original['records']
    assert len(data['records']) == len({r['analysis_id'] for r in data['records']}) == 72
    (RAW / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'activity_context_complete.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (OUT / 'cpi_monthly.json').write_text(json.dumps(list(cpi.values()), ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 데이터 분석 1번: 외부 배경 검토 결과', '', '2026-10-15. 기존 카드·통신 전체 분석의 보완 보고서. 남녀 합산 분석이며 성별 모델 완성을 뜻하지 않는다.', '',
             '## 완료 범위와 채택 상태', '',
             '- 기존 72건의 카드·통신 근거, 단계, 업종·관측·공간 민감도를 보존하고 인구·달력·기온·물가를 연결했다.',
             '- 인구: 공식 원본 7개월, 연령·성별 합계 검증 완료. 기존 분석에서는 전체 인구 맥락만 사용한다.',
             '- 달력: 공식 발표 기반 날짜 전사, 월별 합집합·중복 검증 완료. 주말·공휴일을 개인 휴무일과 동일시하지 않는다.',
             '- 기온: 공개 원본 14개·428개 일자, 6월 춘천 3일 결측 원문 확인. 강남은 서울 관측소 참고값이다. **웹 경로 이용조건 확인 전 탐색용**이다.',
             '- 물가: 공식 조회 원본 7개, 서울·강원 14행. 당월과 다음달 응답의 전월 지수 일치 확인. **이용조건 확인 전 탐색용**이다.',
             '- 최종 제출용 기본 판정에는 기온·물가 가중치를 추가하지 않았다. 확인 전 자료의 원본을 제출·공개 묶음에 포함하지 않는다.', '',
             '## 대표 사례: 12월 춘천', '',
             '|연령|카드 건수 전월비|통신 전월비|주민등록 인구 전월비|기존 단계|',
             '|---|---:|---:|---:|---:|']
    pct = lambda v: '보류' if v is None else f'{v*100:+.2f}%'
    for r in data['records']:
        e = r['analysis_evidence']
        if r['analysis_id'] in ('202512_32010_30G', '202512_32010_40G'):
            lines.append(f"|{e['연령대']}|{pct(e['소비_일평균건수_전월변화율'])}|{pct(e['통신_연령유동량_전월변화율'])}|{pct(r['population_mom_change'])}|{e['활동위축단계']}|")
    lines += ['', '30대 인구는 증가했으므로 주민 수 감소만으로 활동 감소를 설명하기 어렵다. 40대 인구 감소도 활동 감소보다 훨씬 작다. 그러나 거주인구와 방문 활동의 모집단이 달라 이를 보정 효과나 인과관계로 해석하지 않는다.',
              '춘천 평균기온은 11월 6.32℃→12월 -0.86℃, 영하 최저기온 일수는 16→29일이다. 계절·추위라는 공통 배경을 검토해야 하며, 30·40대만의 고립 신호로 확정하지 않는다. 춘천 전체 카드 감소 -6.56%도 함께 제시한다.',
              '40대는 골프·놀이동산 제외 시 11월 3% 감소 기준을 충족하지 못한다. 기존 시범 4단계와 이 민감도는 함께 전달한다.', '',
              '## 전체 지역·월 배경', '',
              '|월|지역|평균기온 ℃|주말·공휴일|시도 CPI(2020=100)|CPI 전월비|',
              '|---|---|---:|---:|---:|---:|']
    for month in [f'2025{m:02}' for m in range(7, 13)]:
        for region, name in [('11230', '강남(서울 참고)'), ('32010', '춘천(강원 물가 참고)')]:
            r = next(r for r in data['records'] if r['analysis_id'].startswith(f'{month}_{region}_'))
            w, c, p = r['weather_context'], r['calendar_context'], r['economic_context']
            lines.append(f"|{month}|{name}|{w['mean_temp_c']}|{c['weekend_or_holiday_days']}|{p['cpi_2020_100']}|{pct(p['mom_change'])}|")
    lines += ['', '## 해석과 남은 조건', '',
              '이 자료로 활동 감소가 인구·기온·휴일·물가 변화와 동반됐는지 확인할 수 있다. 원인이 무엇인지 분리하거나 날씨 보정 고립 점수를 계산한 것은 아니다. 두 지역×6개월이라 외부 변수를 많이 넣은 회귀·가중치 학습은 진행하지 않았다. 같은 지역의 여섯 연령을 독립 기상·물가 표본으로 세지 않는다.',
              '물가는 카드 금액 설명의 배경이다. 카드 건수·통신량을 CPI로 나누지 않고, 카드 금액 단위·업종 바스켓 문제도 해결됐다고 보지 않는다. CPI는 경기 전체를 대변하지 않는다.',
              '기존 분석은 완료된 기본 산출물로 유지한다. 외부 보완은 위 범위에서 완료했으며 기상·물가 최종 채택, 강남 AWS, 강수·적설, 장기 계절성, 성별 카드·통신 분리는 미완료/추가 범위다. 고립 정답 검증·팀 기준 합의·기관 좌표 정의 확인도 남아 있다.', '',
              '## 공식 출처·재현', '',
              '- 인구: https://jumin.mois.go.kr/ageStatMonth.do',
              '- 날씨: https://www.weather.go.kr/w/weather/land/past-obs/obs-by-day.do',
              '- 기상 이용정책: https://www.weather.go.kr/kma/guide/copyright.jsp',
              '- 달력: https://www.kasi.re.kr/kor/publication/post/newsMaterial/30071',
              '- CPI: https://mods.go.kr/cpidtvalregion.es?mid=b70201040000',
              '- 수집 순서: collect_population_context.py → build_population_context_review.py → build_weather_calendar_context.py → finish_external_context.py (모두 scripts/data_processing 아래).',
              '- 산출물: data/processed/external_context_20261015/activity_context_complete.json. 기존 record와 완전 일치 및 72개 ID 유일성을 검사했다.',
              '- 원본·수집조건·해시는 data/external/public_context 아래 보존한다. 자료를 공개 저장소로 전송하지 않았다.']
    text = '\n'.join(lines) + '\n'
    (ROOT / 'docs/analysis_context_final_20261015.md').write_text(text, encoding='utf-8')
    # Plain standalone review page; source report is escaped, never interpreted as HTML.
    html = '<!doctype html><meta charset="utf-8"><title>분석 1번 추가 검토</title><style>body{max-width:1100px;margin:40px auto;padding:0 24px;font:17px/1.7 sans-serif;background:#fafafa;color:#17212b}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><pre>' + escape(text) + '</pre>'
    (OUT / 'context_report.html').write_text(html, encoding='utf-8')
    print('PASS: 7 CPI originals, 14 regional CPI values, adjacent-month consistency, 72 evidence records unchanged.')
    print(json.dumps([r for r in cpi.values() if r['month'] == '202512'], ensure_ascii=False))


if __name__ == '__main__':
    main()
