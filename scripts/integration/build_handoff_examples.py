"""실제 분석으로 연결 예시 생성. 2·3번 예시는 자료 부족 상태이며 실제 실행 결과가 아님."""
from datetime import date, datetime, timezone
from pathlib import Path
import copy
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'data/processed'
OUT = DATA/'integration_handoff'
SCHEMA = ROOT/'docs/contracts/integration_v1.schema.json'
REGIONS = {'서울 강남구':'11230','강원 춘천시':'32010'}
AGES = {'10대':'10G','20대':'20G','30대':'30G','40대':'40G','50대':'50G','60대이상':'60GU'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_example(value, rule, definitions, path='$'):
    """이 계약의 예시 검사용. 전체 JSON Schema 엔진이나 운영 입력 검증기는 아님."""
    if '$ref' in rule:
        return check_example(value,definitions[rule['$ref'].split('/')[-1]],definitions,path)
    if 'anyOf' in rule:
        errors=[]
        for option in rule['anyOf']:
            try:
                check_example(value,option,definitions,path)
                return
            except ValueError as exc:errors.append(str(exc))
        raise ValueError(path+': anyOf 불일치 '+str(errors))
    kinds={'null':value is None,'object':isinstance(value,dict),'array':isinstance(value,list),
           'string':isinstance(value,str),'boolean':isinstance(value,bool),
           'number':isinstance(value,(int,float)) and not isinstance(value,bool),
           'integer':isinstance(value,(int,float)) and not isinstance(value,bool)
               and math.isfinite(value) and float(value).is_integer()}
    allowed=rule.get('type',[])
    allowed=[allowed] if isinstance(allowed,str) else allowed
    if allowed and not any(kinds[k] for k in allowed):raise ValueError(path+': 타입 불일치')
    if 'enum' in rule and value not in rule['enum']:raise ValueError(path+': enum 불일치')
    if kinds['number']:
        if not math.isfinite(value):raise ValueError(path+': 유한 숫자 필요')
        if 'minimum' in rule and value<rule['minimum']:raise ValueError(path+': 최솟값 미달')
        if 'maximum' in rule and value>rule['maximum']:raise ValueError(path+': 최댓값 초과')
    if kinds['object']:
        missing=set(rule.get('required',[]))-set(value)
        if missing:raise ValueError(path+': 항목 누락 '+str(missing))
        properties=rule.get('properties',{})
        if rule.get('additionalProperties') is False and set(value)-set(properties):
            raise ValueError(path+': 추가 항목')
        for name,item in value.items():
            if name in properties:check_example(item,properties[name],definitions,path+'.'+name)
    if kinds['array'] and 'items' in rule:
        for i,item in enumerate(value):check_example(item,rule['items'],definitions,f'{path}[{i}]')
    if kinds['string'] and rule.get('format')=='date':date.fromisoformat(value)


def main():
    source=DATA/'agent_activity_evidence.json'
    evidence=json.loads(source.read_text(encoding='utf-8'))
    final=DATA/'eda/final_analysis_20261014'
    manifest=json.loads((final/'manifest.json').read_text(encoding='utf-8'))
    if manifest['source_sha256'][source.relative_to(ROOT).as_posix()]!=digest(source):
        raise ValueError('최종 분석과 현재 근거 입력 불일치')
    packet=json.loads((DATA/'eda/team_review_20261015/analysis_review_packet.json').read_text(encoding='utf-8'))
    if packet['source_sha256'][source.relative_to(ROOT).as_posix()]!=digest(source):
        raise ValueError('공동 검토와 현재 근거 입력 불일치')
    created=datetime.now(timezone.utc).isoformat()

    def analysis(month,region,age):
        found=[r for r in evidence['records'] if (r['월'],r['지역'],r['연령대'])==(month,region,age)]
        if len(found)!=1:raise ValueError('분석 키 확인 필요')
        record=copy.deepcopy(found[0])
        return {'schema_version':'integration-v1','analysis_version':'activity-review-v1',
            'analysis_id':f'{month}_{REGIONS[region]}_{AGES[age]}',
            'selection':{'month':month,'region_code':REGIONS[region],'region_name':region,
                         'age_code':AGES[age],'age_name':age},
            'analysis_status':'held' if record['활동위축단계'] is None else 'provisional',
            'analysis_evidence':record,'rules':copy.deepcopy(packet['proposed_config']),
            'sensitivity':copy.deepcopy(packet['sensitivity']),
            'limitations':copy.deepcopy(evidence['limitations']),
            'spatial_status':next(v for v in evidence['limitations'] if v.startswith('공간 대조')),
            'approval_status':'pending_team_review',
            'provenance':{'source_file':source.relative_to(ROOT).as_posix(),
                'source_sha256':digest(source),'generated_at_utc':created,
                'analysis_report_created_at_utc':manifest['created_at_utc'],
                'adapter_script_sha256':digest(Path(__file__))}}

    a30=analysis('202512','강원 춘천시','30대')
    a40=analysis('202512','강원 춘천시','40대')
    held=analysis('202507','강원 춘천시','30대')
    catalog={'schema_version':'welfare-resources-v1','status':'not_collected','resources':[],
             'missing_regions':['11230','32010'],
             'notes':['입력 템플릿. 실제 자원 이름·조건·운영·출처는 현지가 확인한 자료로 채운다.']}
    constraints={'usage_mode':'activity_group_planning','objective':None,'planned_participants':None,
        'duration_weeks':None,'budget_limit_krw':None,'venue':None,'access_support':[]}
    request={'schema_version':'integration-v1','request_id':'example-recommendation-001',
        'planning_as_of':'2026-10-15','analysis':a30,'resource_catalog':catalog,'constraints':constraints}
    response={'schema_version':'integration-v1','request_id':request['request_id'],
        'analysis_id':a30['analysis_id'],'status':'resource_data_required','recommendations':[],
        'excluded_resources':[],'questions':['강남·춘천의 공식 자원 목록과 운영·대상 조건을 입력해 주세요.'],
        'program_plan':None,'warnings':['자료 부족 상태의 연결 예시. 실제 추천 실행 결과가 아님.',
                                      '집단 활동 신호로 개인 자격을 확정하지 않음.']}
    missing=['title','objective','target.planned_participants','target.eligibility_text',
             'activities','schedule','performance_measures','budget_items']
    plan={'schema_version':'integration-v1','plan_id':'example-draft-plan-001','version':1,
        'status':'draft','origin':'user_input','mode':'new','base_resource_id':None,
        'analysis_id':a30['analysis_id'],'title':None,'objective':None,
        'target':{'region_code':'32010','age_code':'30G','planned_participants':None,
                  'eligibility_text':None,'residency_confirmation':'unknown'},
        'activities':[],'schedule':{'start_date':None,'end_date':None,'sessions':None,'venue':None},
        'performance_measures':[],'budget_items':[],'assumptions':[],
        'source_refs':[],'missing_fields':missing}
    evaluation_request={'schema_version':'integration-v1','request_id':'example-evaluation-001',
        'planning_as_of':'2026-10-15','analysis':a30,'program_plan':plan,
        'criteria_version':'planning-review-v1','budget_limit_krw':None,'baseline_plan':None}
    evaluation_response={'schema_version':'integration-v1','request_id':evaluation_request['request_id'],
        'evaluation_id':'example-evaluation-result-001','analysis_id':a30['analysis_id'],
        'plan_id':plan['plan_id'],'criteria_version':'planning-review-v1','status':'needs_input',
        'criteria_results':[{'criterion_id':key,'status':'insufficient_data',
            'evidence':[],'improvements':['기획안의 실제 내용과 항목별 근거를 입력해 주세요.']}
            for key in ['target_fit','activity_rationale','feasibility','accessibility','measurement']],
        'performance_plan':[],
        'budget':{'currency':'KRW','status':'incomplete','items':[],
            'documented_subtotal_krw':0,'available_subtotal_krw':0,'total_krw':None,
            'per_participant_krw':None,'over_budget':None,'missing_fields':['budget_items']},
        'comparison':None,'questions':['프로그램 목적·활동·대상 확인·인원·일정·성과 측정 계획을 입력해 주세요.',
                                      '예산 항목별 단가·수량·횟수와 출처 또는 가정 여부를 입력해 주세요.'],
        'missing_fields':missing,
        'provenance':{'example_kind':'missing_data_ui_contract_only',
                      'actual_agent_execution':False,'generated_at_utc':created}}
    samples={
        'analysis_chuncheon_30.json':('AnalysisResponse',a30),
        'analysis_chuncheon_40.json':('AnalysisResponse',a40),
        'analysis_held.json':('AnalysisResponse',held),
        'welfare_resource_catalog_template.json':('ResourceCatalog',catalog),
        'recommendation_request.json':('RecommendationRequest',request),
        'recommendation_missing_data_response.json':('RecommendationResponse',response),
        'program_plan_manual_template.json':('ProgramPlan',plan),
        'evaluation_request.json':('EvaluationRequest',evaluation_request),
        'evaluation_missing_data_response.json':('EvaluationResponse',evaluation_response)}
    schema=json.loads(SCHEMA.read_text(encoding='utf-8'))
    OUT.mkdir(parents=True,exist_ok=True)
    for name,(kind,value) in samples.items():
        check_example(value,schema['$defs'][kind],schema['$defs'])
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    assert held['analysis_evidence']['활동위축단계'] is None
    assert a40['analysis_evidence']['업종민감도주의'] is True
    assert response['recommendations']==[] and evaluation_response['budget']['total_krw'] is None
    record={'status':'contract_examples_checked_not_connected_services','created_at_utc':created,
        'schema_sha256':digest(SCHEMA),'script_sha256':digest(Path(__file__)),
        'evidence_sha256':digest(source),'example_count':len(samples),
        'checks':['계약 필수 항목·타입·상태 확인','실제 분석 record 보존',
                  '7월 null 보류 보존','40대 업종 주의 보존','자원 빈 목록과 예산 미완성을 실제 0원으로 대체하지 않음'],
        'examples':{name:{'schema_definition':kind,'sha256':digest(OUT/name)} for name,(kind,_) in samples.items()},
        'remaining':['team_signoff','verified_resource_catalog','program_and_cost_inputs',
                     'frontend_backend_2_3_integration_execution'],
        'validation_scope':'이 문서에 사용한 JSON Schema 기능의 예시 검사. 일반 운영 검증기 아님.'}
    (OUT/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'examples':len(samples),'status':record['status'],'output':str(OUT)},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
