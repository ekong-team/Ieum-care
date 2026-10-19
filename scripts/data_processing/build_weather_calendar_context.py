"""Collect public KMA HTML; retain originals and produce exploratory context JSON."""
import calendar
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data/external/public_context/weather_calendar_20261015'
OUT = ROOT / 'data/processed/external_context_20261015'
SOURCES = {
    'calendar_release': 'https://www.kasi.re.kr/kor/publication/post/newsMaterial/30071',
    'holiday_crosscheck': 'https://www.korea.kr/multi/visualNewsView.do?newsId=148936865',
    'late_2025_crosscheck': 'https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=120839',
    'kma_copyright': 'https://www.weather.go.kr/kma/guide/copyright.jsp',
    'election_notice': 'https://www.hs.ac.kr/kor/4956/subview.do?enc=Zm5jdDF8QEB8JTJGYmJzJTJGa29yJTJGMjc0JTJGMTQ4ODA5JTJGYXJ0Y2xWaWV3LmRvJTNG',
}
# Explicit transcription of named holidays; weekend days are computed separately.
HOLIDAYS = {'2025-06-03': '대통령선거일', '2025-06-06': '현충일', '2025-08-15': '광복절',
            '2025-10-03': '개천절', '2025-10-05': '추석연휴', '2025-10-06': '추석',
            '2025-10-07': '추석연휴', '2025-10-08': '추석 대체공휴일',
            '2025-10-09': '한글날', '2025-12-25': '기독탄신일'}


def parse_temperatures(html, year, month):
    table = html.split('class="table-col table-cal"', 1)[1].split('</table>', 1)[0]
    day_labels = [int(v) for v in re.findall(r'<span>(\d+)일</span>', table)]
    assert day_labels == list(range(1, calendar.monthrange(year, month)[1] + 1)), day_labels
    rows = []
    for label in ('평균기온', '최고기온', '최저기온'):
        cells = re.findall(label + r':\s*([^<]*)', table)
        assert len(cells) == calendar.monthrange(year, month)[1], (label, len(cells), month)
        values = [float(v.replace('℃', '').strip()) if re.fullmatch(r'-?\d+(?:\.\d+)?℃', v.strip()) else None for v in cells]
        rows.append(values)
    for mean, high, low in zip(*rows):
        if None not in (mean, high, low):
            assert low <= mean <= high
    return rows


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []

    def fetch(name, url):
        path = RAW / name
        cached = path.exists()
        if not cached:
            with urlopen(url, timeout=40) as response:
                path.write_bytes(response.read())
        raw = path.read_bytes()
        manifest.append(dict(file=name, url=url, sha256=hashlib.sha256(raw).hexdigest(),
                             bytes=len(raw), reused=cached, checked_at_utc=datetime.now(timezone.utc).isoformat()))
        return raw.decode('utf-8')

    for name, url in SOURCES.items():
        fetch(name + '.html', url)
    weather, calendars = [], []
    for month in range(6, 13):
        n = calendar.monthrange(2025, month)[1]
        days = [date(2025, month, day) for day in range(1, n + 1)]
        weekend = {d for d in days if d.weekday() >= 5}
        holidays = {d for d in days if d.isoformat() in HOLIDAYS}
        calendars.append(dict(month=f'2025{month:02}', days=n, weekend_days=len(weekend),
                              named_holiday_days=len(holidays), overlap_days=len(weekend & holidays),
                              weekend_or_holiday_days=len(weekend | holidays),
                              weekday_nonholiday_days=n - len(weekend | holidays),
                              named_holidays={d.isoformat(): HOLIDAYS[d.isoformat()] for d in sorted(holidays)}))
        for station, region, name in [(101, '32010', '춘천'), (108, '11230', '서울(강남 참고값)')]:
            url = f'https://www.weather.go.kr/w/weather/land/past-obs/obs-by-day.do?stn={station}&yy=2025&mm={month}&obs=1'
            html = fetch(f'kma_{station}_2025{month:02}.html', url)
            assert f'value="{station}" selected=' in html
            assert f'value="2025" selected=' in html and f'value="{month}" selected=' in html
            mean, high, low = parse_temperatures(html, 2025, month)
            valid = [v for v in mean if v is not None]
            weather.append(dict(month=f'2025{month:02}', region_code=region, station_id=station,
                                station_label=name, expected_days=n, observed_mean_temp_days=len(valid),
                                mean_temp_c=round(sum(valid) / n, 4) if len(valid) == n else None,
                                below_zero_min_days=sum(v < 0 for v in low) if all(v is not None for v in low) else None,
                                min_temp_c=min(v for v in low if v is not None),
                                daily=[dict(date=d.isoformat(), mean_temp_c=a, max_temp_c=b, min_temp_c=c)
                                       for d, a, b, c in zip(days, mean, high, low)]))
    analysis = json.loads((OUT / 'population_activity_review.json').read_text(encoding='utf-8'))
    for record in analysis['records']:
        month, code, _ = record['analysis_id'].split('_')
        w = next(r for r in weather if r['month'] == month and r['region_code'] == code)
        prior = next((r for r in weather if r['month'] == str(int(month) - 1) and r['region_code'] == code), None)
        record['weather_context'] = {k: v for k, v in w.items() if k != 'daily'}
        record['weather_context']['mean_temp_change_c'] = round(w['mean_temp_c'] - prior['mean_temp_c'], 4) if prior and w['mean_temp_c'] is not None and prior['mean_temp_c'] is not None else None
        record['calendar_context'] = next(r for r in calendars if r['month'] == month)
    analysis['schema_version'] = 'external-context-exploratory-v1'
    analysis['context_status'] = 'exploratory_not_seasonally_adjusted'
    analysis['limitations'] += ['KMA website source-route reuse confirmation pending; do not label competition-ready weather yet.',
                                 'Seoul ASOS108 is a regional proxy, not a Gangnam station.',
                                 'Daily temperatures read in calendar order; missing values preserved. Rain/snow not extracted.',
                                 'Named holidays manually transcribed from official references; no personal work schedule implied.']
    for filename, obj in [('weather_calendar_manifest.json', manifest), ('weather_monthly_and_daily.json', weather),
                          ('calendar_monthly.json', calendars), ('activity_external_context.json', analysis)]:
        folder = RAW if 'manifest' in filename else OUT
        (folder / filename).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    report = ['# 날씨·달력 배경 비교 — 2026-10-15', '',
              '기존 인구 배경 분석 72건에 기상청 기온과 공식 발표 기반 달력을 추가한 탐색 결과다. 기존 단계는 바꾸지 않았다.', '',
              '## 확보·검증', '',
              '- 기상청 서울108·춘천101의 2025년 6~12월 원본 HTML 14개, 일별 기온 428일분을 보존했다.',
              '- 날짜 순서·월 길이·조회 선택값·최저≤평균≤최고를 검사했다. 기온 결측은 그대로 남겼다.',
              '- 월평균은 일평균 기온의 산술평균이며 하루라도 빠지면 null이다. 공식 월통계값과 같다고 보증하지 않는다.',
              '- 달력은 공식 발표에서 명시된 날짜를 수동 전사하고 주말과의 합집합을 계산했다. 개인의 실제 휴무일은 아니다.',
              '- 서울108은 강남 관측소가 아닌 지역 참고값이다. 강수·적설은 아직 추출하지 않았다.',
              '- **기상청 웹 화면 수집 경로의 재이용 조건은 추가 확인이 필요하다. 무료·공공누리1형 API가 존재한다는 사실만으로 웹 수집 경로의 조건까지 확인됐다고 하지 않는다. 기상은 탐색용이며 대회 최종 사용 확정 전이다.**', '',
              '## 월별 비교', '',
              '|월|주말·공휴일 합계|평일 비공휴일|춘천 평균기온 ℃|서울 참고 평균기온 ℃|',
              '|---|---:|---:|---:|---:|']
    for c in calendars:
        if c['month'] == '202506':
            continue
        values = [next(w['mean_temp_c'] for w in weather if w['month'] == c['month'] and w['station_id'] == s) for s in (101, 108)]
        report.append(f"|{c['month']}|{c['weekend_or_holiday_days']}|{c['weekday_nonholiday_days']}|{values[0]}|{values[1]}|")
    report += ['', '## 해석', '',
               '춘천의 11→12월 평균기온은 약 6.32→-0.86℃로 낮아졌고, 최저기온이 0℃ 미만인 날은 16→29일로 늘었다. 활동 감소와 추운 날씨가 겹친다는 배경 설명은 가능하지만, 날씨 때문에 감소했다고 확정하지 않는다. 이 일수는 공식 한파일수가 아니다.',
               '같은 기간 주말·공휴일 합계는 10→9일, 평일 비공휴일은 20→22일이다. 월 길이와 휴일 구성의 차이를 함께 봐야 한다. 기존 카드 건수는 이미 일평균으로 계산했으므로 월 길이를 다시 나눠 보정하지 않는다.',
               '기온은 같은 지역 모든 연령에 동일하므로 72개 행을 독립적인 기상 표본으로 회귀 분석하지 않는다. 6개월만으로 계절 조정·기상 인과효과·고립 확정은 할 수 없다.', '',
               '춘천 6월 일평균 기온은 27/30일만 파싱되어 6월 평균과 7월 전월 기온 차이는 null이다. 미관측인지 원문 표기 차이인지는 추가 점검 대상이며 임의 보간하지 않았다.', '',
               '## 파일·재현', '',
               '- 재현: `scripts/data_processing/build_weather_calendar_context.py` (캐시 재사용).',
               '- 원본·출처·SHA-256: `data/external/public_context/weather_calendar_20261015/` 및 manifest.',
               '- 결과: `data/processed/external_context_20261015/activity_external_context.json`.',
               '- 수집·연결 검증과 원인 검증은 다르다. 인구는 기존 이용조건 확인 완료, 날씨는 위 경로 조건 확인 대기, 경제 지표는 미반영이다.']
    (ROOT / 'docs/weather_calendar_context_review_20261015.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(json.dumps(dict(weather_months=len(weather), daily_rows=sum(len(w['daily']) for w in weather),
                          joined_records=len(analysis['records']), calendar=calendars,
                          chuncheon=[{k: v for k, v in w.items() if k != 'daily'} for w in weather if w['station_id'] == 101]), ensure_ascii=False))


if __name__ == '__main__':
    main()
