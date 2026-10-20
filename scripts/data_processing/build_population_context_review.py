"""Join resident context without changing the activity-stage evidence."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = ROOT / 'data/processed/agent_activity_evidence.json'
    population = ROOT / 'data/processed/external_context_20261015/population_age_sex.csv'
    evidence = json.loads(source.read_text(encoding='utf-8'))
    with population.open(encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['sex'] == '전체']
    counts = {}
    for r in rows:
        key = (r['month'].replace('-', ''), r['sgis_code'], r['age_group'].replace(' ', ''))
        assert key not in counts, key
        counts[key] = int(r['population'])
    joined = []
    for record in evidence['records']:
        month = str(record['월'])
        code = '32010' if '춘천' in record['지역'] else '11230' if '강남' in record['지역'] else None
        assert code is not None, record['지역']
        age = record['연령대'].replace(' ', '')
        prior_month = f'{int(month[:4]) - 1}12' if month[4:] == '01' else str(int(month) - 1)
        current = counts[(month, code, age)]
        prior = counts[(prior_month, code, age)]
        age_code = '60GU' if age == '60대이상' else age[:2] + 'G'
        joined.append(dict(analysis_id=f'{month}_{code}_{age_code}', analysis_evidence=record,
                           resident_population=current, prior_resident_population=prior,
                           population_mom_change=current / prior - 1 if prior else None))
    assert len(joined) == 72
    output = dict(schema_version='population-context-review-v1', records=joined,
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, population)},
                  limitations=['Resident context only; visitor activity is not divided by resident population.',
                               'Population changes do not establish causes or individual isolation.',
                               'Existing evidence and stages are preserved; retrospective context, not live features.'])
    out = ROOT / 'data/processed/external_context_20261015/population_activity_review.json'
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for r in joined:
        e = r['analysis_evidence']
        if str(e['월']) == '202512' and '춘천' in e['지역'] and e['연령대'] in ('30대', '40대'):
            print(e['연령대'], r['prior_resident_population'], r['resident_population'],
                  round(r['population_mom_change'] * 100, 4))
    print('Joined 72 records; original evidence preserved.')


if __name__ == '__main__':
    main()
