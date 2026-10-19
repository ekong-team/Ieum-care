"""분석 산출물과 Agent 근거의 일치를 확인하고 공동 검토 자료를 준비한다."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/processed'
FINAL = DATA / 'eda/final_analysis_20261014'
OUT = DATA / 'eda/team_review_20261015'
KEYS = ['월', '지역', '연령대']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((FINAL/'manifest.json').read_text(encoding='utf-8'))
    checks = {}
    for section in ['source_sha256', 'dependency_script_sha256']:
        for name, value in manifest[section].items():
            if sha(ROOT/name) != value:
                raise ValueError(f'최종 분석 이후 입력/코드 변경: {name}')
    if sha(ROOT/'scripts/data_processing/finish_analysis.py') != manifest['script_sha256']:
        raise ValueError('최종 분석 생성 코드 변경')
    for name,value in manifest['output_sha256'].items():
        if sha(FINAL/name) != value:
            raise ValueError(f'최종 분석 이후 산출물 변경: {name}')
    checks['최종보고서_입력코드산출물일치'] = True
    agent = json.loads((DATA/'agent_activity_evidence.json').read_text(encoding='utf-8'))
    evidence = pd.read_csv(DATA/'activity_evidence.csv',dtype={'월':str})
    require = KEYS + ['활동위축단계','단계설명','해석상태',
        '소비_일평균건수_전월변화율','통신_연령유동량_전월변화율',
        '동시감소연속개월','업종민감도주의','통신_연령관측률','통신_전월공통위치비율',
        '지역전체_소비전월변화율','소비_지역전체대비차이']
    records = agent['records']
    if len(records)!=72 or evidence.duplicated(KEYS).any():
        raise ValueError('Agent/근거의 72개 키 확인 필요')
    indexed = evidence.set_index(KEYS)
    record_keys = [tuple(r[k] for k in KEYS) for r in records]
    if len(set(record_keys))!=72 or set(record_keys)!=set(indexed.index):
        raise ValueError('Agent 입력과 근거의 키 불일치')
    for record in records:
        if not set(require).issubset(record):
            raise ValueError('Agent 입력 필수 항목 누락')
        expected = indexed.loc[tuple(record[k] for k in KEYS)]
        for column, actual in record.items():
            if column in KEYS:
                continue
            source = expected[column]
            if pd.isna(source):
                if actual is not None:
                    raise ValueError(f'결측이 다른 값으로 변환됨: {column}')
            elif isinstance(actual,bool):
                if actual!=bool(source):
                    raise ValueError(f'주의 표시 불일치: {column}')
            elif isinstance(actual,(float,int)):
                if not math.isfinite(actual) or not math.isclose(actual,float(source),rel_tol=1e-9,abs_tol=5e-10):
                    raise ValueError(f'수치 불일치: {column}')
            elif actual!=source:
                raise ValueError(f'설명 불일치: {column}')
    checks['Agent_72개키_근거수치설명일치'] = True
    held = [r for r in records if r['월']=='202507']
    if len(held)!=12 or any(r['활동위축단계'] is not None for r in held):
        raise ValueError('7월 보류 보존 실패')
    fragile = next(r for r in records if tuple(r[k] for k in KEYS)==('202512','강원 춘천시','40대'))
    if not fragile['업종민감도주의']:
        raise ValueError('40대 업종 주의 표시 누락')
    if not agent['limitations'] or not agent['agent_instructions']:
        raise ValueError('Agent 전달 해석 지침 누락')
    checks['7월보류_40대주의_해석지침보존'] = True
    OUT.mkdir(parents=True,exist_ok=True)
    summary = json.loads((FINAL/'summary.json').read_text(encoding='utf-8'))
    config = json.loads((DATA/'activity_review_manifest.json').read_text(encoding='utf-8'))['config']
    thresholds = pd.read_csv(DATA/'activity_review_sensitivity.csv').to_dict('records')
    quality = pd.read_csv(DATA/'activity_review_quality_sensitivity.csv').to_dict('records')
    packet = {
        'schema_version':'analysis-team-review-v1',
        'status':'ready_for_team_review_not_team_approved',
        'prepared_at_utc':datetime.now(timezone.utc).isoformat(),
        'local_checks':checks,
        'proposed_config':config,
        'team_signoff':{'status':'pending','reviewers':[],'agreed_at':None},
        'integration_status':'evidence_fields_checked_consumer_execution_unverified',
        'sensitivity':{'decline_threshold':thresholds,'observation_conditions':quality,
            'persistence':summary['persistence_sensitivity'],
            'fixed_location_stage_changes':summary['fixed_location_stage_changes'],
            'fixed_location_use':'retrospective_only_not_live_input'},
        'evidence':agent,
        'source_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in
            [DATA/'agent_activity_evidence.json',DATA/'activity_evidence.csv',FINAL/'manifest.json',FINAL/'report.html']},
        'script_sha256':sha(Path(__file__)),
    }
    (OUT/'analysis_review_packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'checks':checks,'records':len(records),'team_signoff':'pending',
                     'consumer_execution':'unverified','packet':str(OUT/'analysis_review_packet.json')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
