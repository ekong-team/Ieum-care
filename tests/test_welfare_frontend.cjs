// 브라우저 없이 실제 app.js의 조회→표시 흐름을 검사한다. 외부 API는 호출하지 않는다.
// 실행: node --test tests/test_welfare_frontend.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');

function screen() {
  const elements = new Map();
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      value: '', innerHTML: '', textContent: '', hidden: false,
      handlers: {}, addEventListener(name, handler) { this.handlers[name] = handler; }, setAttribute() {}, removeAttribute() {},
      append() {}, click() {},
      replaceChildren() { this.innerHTML = ''; }, close() {}, querySelectorAll() { return []; },
    });
    return elements.get(selector);
  }
  const context = vm.createContext({
    document: { querySelector: element, querySelectorAll: () => [], title: '', createElement: () => element('created-element') },
    location: { hash: '#recommendations' }, window: { addEventListener() {} },
    AbortSignal, setInterval, clearInterval, crypto: require('node:crypto').webcrypto, Blob,
    setTimeout: () => {}, URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    fetch: async () => ({ ok: true, json: async () => ({ configured: false }) }),
  });
  vm.runInContext(readFileSync(require('node:path').join(__dirname, '../frontend/app.js'), 'utf8'), context);
  element('#region').value = '춘천시';
  element('#age').value = '60';
  element('#purpose').value = 'all';
  element('#search-mode').value = 'offline';
  return { element, context };
}

const route = (status) => ({ schema_version: 'response-routing-0.1', candidate_status: status,
  routes: [{ route: 'preventive_planning', title: '예방·신규 프로그램 기획 검토',
    reason: '예방 기획 <검토>', checks: ['참여 수요 확인'], resource_ids: [] }], notes: ['자동 실행 아님'] });

test('조회 전과 재조회 중에는 이전 대응 결과가 남지 않는다', async () => {
  const { element, context } = screen();
  assert.equal(element('#response-routes').hidden, true);
  context.routing = route('no_candidates_found');
  vm.runInContext('responseRouting = routing; renderResponseRoutes()', context);
  assert.equal(element('#response-routes').hidden, false);
  let finish;
  context.fetch = () => new Promise((resolve) => { finish = resolve; });
  const request = vm.runInContext('queryResources()', context);
  assert.equal(element('#response-routes').hidden, true);
  assert.equal(element('#response-routes').innerHTML, '');
  finish({ ok: false, headers: { get: () => 'application/json' }, json: async () => ({ error: '실패' }) });
  await request;
});

for (const [status, label] of [['candidates_found', '기존 자원 후보 확보'], ['no_candidates_found', '이번 조회에서 후보 미확보']]) {
  test(`${status}: 대응 경로를 표시하며 추가 요청하지 않는다`, async () => {
    const { element, context } = screen();
    let calls = 0;
    context.fetch = async () => {
      calls++;
      return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({
        schema_version: 'welfare-0.4', is_demo: false, mode: 'offline', resources: [], purposes: {},
        review: { confirmed_support_needs: [], summary: '' }, response_routing: route(status),
      }) };
    };
    await vm.runInContext('queryResources()', context);
    const panel = element('#response-routes');
    assert.equal(panel.hidden, false);
    assert.ok(panel.innerHTML.includes(label));
    assert.ok(panel.innerHTML.includes('예방·신규 프로그램 기획 검토'));
    assert.ok(panel.innerHTML.includes('예방 기획 &lt;검토&gt;'));
    assert.equal(calls, 1);
  });
}

test('HTTP 실패는 조회 미완료로 표시하고 잘못된 다음 요청에서는 이전 경로를 지운다', async () => {
  const { element, context } = screen();
  context.fetch = async () => ({ ok: false, headers: { get: () => 'application/json' },
    json: async () => ({ error: '일시 중단', response_routing: route('unavailable') }) });
  await vm.runInContext('queryResources()', context);
  assert.ok(element('#results').innerHTML.includes('일시 중단'));
  assert.ok(element('#response-routes').innerHTML.includes('조회 미완료'));
  assert.equal(element('#prepare-preventive').disabled, false);
  const draft = vm.runInContext("buildPlanningRequest('preventive_new')", context);
  assert.equal(draft.welfare_lookup.status, 'unavailable');
  assert.equal(draft.welfare_lookup.total_candidates, null);
  assert.equal(draft.welfare_lookup.error, '일시 중단');
  element('#risk-input').value = '{';
  await vm.runInContext('queryResources()', context);
  assert.equal(element('#response-routes').hidden, true);
  assert.equal(element('#response-routes').innerHTML, '');
  assert.equal(element('#prepare-preventive').disabled, true);
});

function withPlanningData() {
  const result = screen();
  vm.runInContext(`
    planningContext = { input: { target: {region:'춘천시',age_group:60,purpose:'connection'},
      risk_assessment: {is_example:true,level:1,status:'complete',limitations:['예시']},
      confirmed_support_needs:['connection'] }, mode:'offline', error:null };
    resources = [{id:'R1', name:'참고 자원',source:{url:'https://example.test/detail',reference_year:2025}}, {id:'R2',name:'다른 후보'}];
    recommendation = { mode:'offline', resources, warnings:['저장 자료'], analysis_context:{profile:{is_example:true},causes:[]} };
    responseRouting = {schema_version:'response-routing-0.1',candidate_status:'candidates_found',routes:[],notes:[]};
  `, result.context);
  return result;
}

test('선택 자원 활용 요청은 대상·근거·출처를 보존하고 복사본을 만든다', () => {
  const { context, element } = withPlanningData();
  assert.throws(() => vm.runInContext("buildPlanningRequest('existing_resource_based')", context), /자원을 먼저 선택/);
  element('#planning-prompt').value = '  주 1회 만남, 예산 100만원  ';
  element('#region').value = '강남구'; // 조회 뒤 폼만 바꿔도 이전 조회 맥락과 섞지 않는다.
  const payload = vm.runInContext("selected.add('R1'); buildPlanningRequest('existing_resource_based')", context);
  assert.equal(payload.target.region, '춘천시');
  assert.equal(payload.officer_prompt, '주 1회 만남, 예산 100만원');
  assert.equal(payload.selected_resources.length, 1);
  assert.equal(payload.selected_resources[0].source.reference_year, 2025);
  assert.equal(payload.welfare_lookup.recommendation_snapshot.resources.length, 2);
  assert.equal(payload.has_example_context, true);
  assert.equal(payload.risk_assessment.level, 1);
  assert.equal(payload.analysis_context.profile.is_example, true);
  payload.selected_resources[0].name = '변경';
  assert.equal(vm.runInContext('resources[0].name', context), '참고 자원');
  assert.equal(vm.runInContext('planningContext.input.risk_assessment.level', context), 1);
});

test('정상 조회 0개에서도 위험도 없이 예방 요청을 만들 수 있다', () => {
  const { context } = withPlanningData();
  const payload = vm.runInContext(`resources=[]; recommendation.resources=[];
    planningContext.input.risk_assessment=null; recommendation.analysis_context=null;
    responseRouting.candidate_status='no_candidates_found'; buildPlanningRequest('preventive_new')`, context);
  assert.equal(payload.selected_resources.length, 0);
  assert.equal(payload.risk_assessment, null);
  assert.equal(payload.has_example_context, false);
  assert.equal(payload.welfare_lookup.status, 'completed');
  assert.equal(payload.welfare_lookup.total_candidates, 0);
  assert.equal(payload.welfare_lookup.mode, 'offline');
});

test('미리보기 JSON을 내려받고 요청 수정·선택 변경 시 이전 파일 준비를 취소한다', async () => {
  const { context, element } = withPlanningData();
  let saved;
  context.URL.createObjectURL = (blob) => { saved = blob; return 'blob:test'; };
  element('#planning-prompt').value = '소규모 모임';
  element('#prepare-preventive').handlers.click();
  assert.equal(element('#planning-preview').hidden, false);
  assert.equal(element('#download-planning').disabled, false);
  element('#download-planning').handlers.click();
  const data = JSON.parse(await saved.text());
  assert.equal(data.schema_version, 'planning-request-0.1');
  assert.equal(data.officer_prompt, '소규모 모임');
  assert.equal(data.planning_type, 'preventive_new');
  assert.equal(element('created-element').download, 'ieum-planning-request-preventive_new.json');
  element('#planning-prompt').value = '다른 요청';
  element('#planning-prompt').handlers.input();
  assert.equal(element('#planning-preview').hidden, true);
  assert.equal(element('#download-planning').disabled, true);
  element('#prepare-preventive').handlers.click();
  vm.runInContext("selected.add('R1'); renderSelection()", context);
  assert.equal(element('#download-planning').disabled, true);
  element('#planning-prompt').value = 'a'.repeat(2001);
  element('#prepare-preventive').handlers.click();
  assert.equal(element('#planning-preview').hidden, true);
  assert.ok(element('#planning-status').textContent.includes('2,000자'));
});
