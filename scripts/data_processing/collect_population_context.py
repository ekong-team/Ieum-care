"""Collect public MOIS monthly originals and validate target age/sex counts."""
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data/external/public_context/context_research_20261015'
OUT = ROOT / 'data/processed/external_context_20261015'
URL = 'https://jumin.mois.go.kr/downloadCsvAge.do?searchYearMonth=month&xlsStats=2'
TARGETS = {'1168000000': ('강남구', '11230'), '5111000000': ('춘천시', '32010')}


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest, normalized = [], []
    for month in range(6, 13):
        params = dict(sltOrgType='1', sltOrgLvl1='A', sltOrgLvl2='', gender='gender', sum='sum',
                      sltUndefType='', searchYearStart='2025', searchMonthStart=f'{month:02}',
                      searchYearEnd='2025', searchMonthEnd=f'{month:02}', sltOrderType='1',
                      sltOrderValue='ASC', sltArgTypes='10', sltArgTypeA='0', sltArgTypeB='100', category='month')
        path = RAW / f'mois_age_2025{month:02}.csv'
        cached = path.exists()
        if not cached:
            request = Request(URL, data=urlencode(params).encode(), headers={
                'Referer': 'https://jumin.mois.go.kr/ageStatMonth.do', 'User-Agent': 'Ieum-care public data research'})
            with urlopen(request, timeout=45) as response:
                path.write_bytes(response.read())
        raw = path.read_bytes()
        rows = list(csv.DictReader(io.StringIO(raw.decode('cp949'))))
        selected = []
        for code, (region, sgis) in TARGETS.items():
            matches = [r for r in rows if f'({code})' in r['행정구역']]
            assert len(matches) == 1, (month, code, len(matches))
            row = matches[0]
            selected.append(row['행정구역'])
            values = {}
            for sex, label in [('계', '전체'), ('남', '남성'), ('여', '여성')]:
                prefix = f'2025년{month:02}월_{sex}_'
                # The publisher uses zero-padded month labels in downloaded CSVs.
                if prefix + '총인구수' not in row:
                    prefix = f'2025년{month}월_{sex}_'
                get = lambda name: int(row[prefix + name].replace(',', ''))
                bands = [get(f'{a}~{a+9}세') for a in range(0, 100, 10)] + [get('100세 이상')]
                assert sum(bands) == get('총인구수'), (month, region, sex)
                values[sex] = bands
                for age in [10, 20, 30, 40, 50, 60]:
                    count = bands[age // 10] if age < 60 else sum(bands[6:])
                    normalized.append(dict(month=f'2025-{month:02}', region=region,
                                           mois_code=code, sgis_code=sgis, age_group=f'{age}대' if age < 60 else '60대 이상',
                                           sex=label, population=count, baseline_only=month == 6))
            assert all(a == b + c for a, b, c in zip(values['계'], values['남'], values['여']))
        manifest.append(dict(file=path.name, url=URL, method='POST', params=params,
                             sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), encoding='cp949',
                             checked_at_utc=datetime.now(timezone.utc).isoformat(), reused_existing_file=cached,
                             selected_regions=selected))
    with (OUT / 'population_age_sex.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(normalized[0]))
        writer.writeheader()
        writer.writerows(normalized)
    (RAW / 'population_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = dict(original_files=len(manifest), normalized_rows=len(normalized),
                   analysis_rows=sum(not r['baseline_only'] for r in normalized),
                   validations=['unique target region each month', 'all age bands sum to total', 'male + female = total by age'],
                   purpose='Resident population context; not a valid denominator for visitor activity or merchant card usage.')
    (OUT / 'population_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
