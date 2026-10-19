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
      addEventListener() {}, setAttribute() {}, removeAttribute() {},
      replaceChildren() { this.innerHTML = ''; }, close() {}, querySelectorAll() { return []; },
    });
    return elements.get(selector);
  }
  const context = vm.createContext({
    document: { querySelector: element, querySelectorAll: () => [], title: '' },
    location: { hash: '#recommendations' }, window: { addEventListener() {} },
    AbortSignal, setInterval, clearInterval,
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
  element('#risk-input').value = '{';
  await vm.runInContext('queryResources()', context);
  assert.equal(element('#response-routes').hidden, true);
  assert.equal(element('#response-routes').innerHTML, '');
});
