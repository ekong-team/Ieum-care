let resources = [];
let purposes = {};
let recommendation = null;
let loading = false;
let errorMessage = '';
let requestedMode = 'live';
const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);

const $ = (selector) => document.querySelector(selector);
const pages = { dashboard: '대시보드', analysis: '분석', recommendations: '복지자원 추천', planning: '프로그램 기획', evaluation: '평가·예산' };
const selected = new Set();
let filters = { region: '춘천시', age: 60, purpose: 'all' };
const ageLabel = (age) => age === 60 ? '60대 이상' : age === 10 ? '20대 미만' : `${age}대`;

function navigate() {
  const page = location.hash.slice(1) || 'dashboard';
  if (!Object.hasOwn(pages, page)) {
    location.replace('#dashboard');
    return;
  }
  $('#recommendation-page').hidden = page !== 'recommendations';
  $('#empty-page').hidden = page === 'recommendations';
  $('#empty-title').textContent = pages[page];
  document.title = `이음케어 · ${pages[page]}`;
  document.querySelectorAll('.navigation a').forEach((link) => {
    if (link.hash === `#${page}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}

function renderResults() {
  const matches = resources;
  $('#results-title').textContent = `${filters.region} · ${ageLabel(filters.age)}`;
  $('#result-count').textContent = loading ? '조회 중' : errorMessage ? '연결 확인 필요' : !recommendation ? '조회 전' : `확인 후보 ${matches.length}개`;
  $('#result-description').textContent = recommendation?.mode === 'offline' ? '저장된 자료 조회 테스트입니다. 외부 검색·LLM을 실행하지 않았습니다.' : 'AI가 분석 결과와 외부 검색 근거를 대조해 제안하는 검토 순서입니다. 개인 자격·지원 효과는 확정하지 않습니다.';
  $('#results').setAttribute('aria-busy', String(loading));
  $('#results').innerHTML = loading ? `<div class="no-results panel">${requestedMode === 'live' ? '공식 사이트를 검색하고 AI가 분석 결과와 자원을 대조하고 있습니다. 잠시 기다려주세요.' : '저장된 자료를 조회하고 있습니다.'}</div>` : errorMessage ? `<div class="no-results panel" role="alert"><strong>자원을 불러오지 못했습니다.</strong><p>${escape(errorMessage)}</p><button id="retry-request" class="secondary">다시 시도</button></div>` : !recommendation ? '<div class="no-results panel"><strong>대상을 선택하고 추천받기를 눌러주세요.</strong><p>실시간 모드는 외부 검색과 AI 판단을 실행합니다. 페이지를 열거나 새로고침하는 것만으로 API를 호출하지 않습니다.</p></div>' : matches.length ? matches.map((item) => `
    <article class="resource-card panel">
      <div class="card-top"><span class="category ${escape(item.purpose)}">${escape(purposes[item.purpose])}</span><span class="example-tag">운영 확인 필요</span></div>
      <h3>${escape(item.name)}</h3><p class="organization">${escape(item.organization)}</p><p class="muted">${escape(({overlap:"연령 범위 겹침",partial:"일부 연령만 해당 · 정확한 나이 확인",unknown:"연령 기준 미확정 · 기관 확인"})[item.age_match])}</p>
      <p class="resource-description">${escape(item.description)}</p>
      <div class="resource-meta"><span>⌖ ${escape(item.region)}</span><span>◷ ${escape(item.format)}</span></div>
      <p class="muted"><a class="source-link" href="${escape(item.source.url)}" target="_blank" rel="noopener noreferrer">${escape(item.source.title)} ↗</a> · ${escape(item.source.checked_at)}</p>
      <div class="recommendation-reason"><span aria-hidden="true">✧</span><p><strong>검토 포인트</strong>${escape(item.reason)}<br>${item.match_reasons.map(escape).join(' · ')}</p></div>
      <div class="card-bottom"><button class="text-button" data-details="${escape(item.id)}">상세 정보 <span aria-hidden="true">↗</span></button>
      <button class="select-button ${selected.has(item.id) ? 'is-selected' : ''}" data-select="${escape(item.id)}" aria-pressed="${selected.has(item.id)}">${selected.has(item.id) ? '✓ 선택됨' : '+ 기획 목록에 담기'}</button></div>
    </article>`).join('') : `<div class="no-results panel"><strong>근거를 갖춘 후보를 제시하지 못했습니다.</strong><p>${escape(recommendation.coverage?.message || '실제 서비스 부재를 뜻하지 않습니다. 추가 조사가 필요합니다.')}</p></div>`;
  renderSelection();
  renderReview();

}

function renderReview() {
  const panel = $('#review-context');
  const risk = recommendation?.risk_assessment;
  const review = recommendation?.review;
  panel.hidden = !review || (!risk && !review.confirmed_support_needs.length && !review.summary);
  if (panel.hidden) { panel.replaceChildren(); return; }
  const status = {browse:'일반 조회', needs_confirmation:'지원 필요 확인', ready_for_review:'확인한 필요로 후보 검토', risk_held:'위험 판정 보류 · 일반 조회', risk_partial:'불완전한 위험 판정 · 일반 조회'};
  panel.innerHTML = `<h3>${escape(status[review.status])}</h3>
    ${review.summary ? `<p><strong>AI 추천 판단</strong><br>${escape(review.summary)}</p>` : ''}
    ${risk ? `<p><strong>${risk.is_example ? '예시 위험도 입력 · 실제 분석 결과 아님' : '입력받은 위험도 결과 · 자동 수신 전'}</strong><br>${escape(risk.period)} · ${escape(risk.region)} · ${escape(ageLabel(risk.age_group))} · ${risk.level === null ? '단계 보류' : `${escape(risk.level)}단계`}<br>모델: ${escape(risk.model_version)}</p><ul>${risk.signals.map((signal) => `<li>${escape(signal.description)}</li>`).join('')}${risk.limitations.map((text) => `<li>관측 제한: ${escape(text)}</li>`).join('')}</ul>` : ''}
    ${review.confirmed_support_needs.length ? `<p>담당자가 확인한 필요: ${review.confirmed_support_needs.map((purpose) => escape(recommendation.purposes[purpose])).join(' · ')}</p>` : ''}
    ${review.suggested_purposes.map((item) => `<p><strong>확인해볼 목적: ${escape(recommendation.purposes[item.purpose])}</strong><br>${escape(item.reason)}</p>`).join('')}
    <ul>${review.questions.map((text) => `<li>${escape(text)}</li>`).join('')}</ul>`;
}

function renderSelection() {
  const items = resources.filter((item) => selected.has(item.id));
  $('#selected-resources').replaceChildren();
  if (!items.length) $('#selected-resources').textContent = '아직 선택한 자원이 없습니다.';
  items.forEach((item) => {
    const button = document.createElement('button');
    button.className = 'selection-chip';
    button.textContent = `${item.name} ×`;
    button.setAttribute('aria-label', `${item.name} 선택 해제`);
    button.addEventListener('click', () => { selected.delete(item.id); renderResults(); });
    $('#selected-resources').append(button);
  });
  $('#download-selection').disabled = loading || !items.length;
}

async function queryResources() {
  if (loading) return;
  filters = { region: $('#region').value, age: Number($('#age').value), purpose: $('#purpose').value };
  requestedMode = $('#search-mode').value;
  loading = true;
  recommendation = null;
  resources = [];
  errorMessage = '';
  selected.clear();
  $('#resource-dialog').close();
  $('#filter-form').querySelectorAll('select, button').forEach((el) => { el.disabled = true; });
  $('#filter-form').querySelectorAll('input').forEach((el) => { el.disabled = true; });
  $('#risk-input').disabled = true;
  $('#load-risk-example').disabled = true;
  $('#clear-risk-input').disabled = true;
  renderResults();
  try {
    let risk = null;
    try { risk = $('#risk-input').value.trim() ? JSON.parse($('#risk-input').value) : null; }
    catch { throw new Error('위험도 JSON 형식이 올바르지 않습니다. 예시 입력과 비교해주세요.'); }
    const response = await fetch('/api/welfare/recommendations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: requestedMode, target: { region: filters.region, age_group: filters.age, purpose: filters.purpose }, risk_assessment: risk,
        confirmed_support_needs: [...document.querySelectorAll('[name="support-need"]:checked')].map((input) => input.value) }),
      signal: AbortSignal.timeout(150000),
    });
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('추천 API 서버로 접속해주세요. 실행 방법은 frontend/README.md에 있습니다.');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '추천 조회에 실패했습니다.');
    if (result.schema_version !== 'welfare-0.4' || result.is_demo !== false || !result.review || !Array.isArray(result.resources)) throw new Error('지원하지 않는 추천 응답 형식입니다.');
    recommendation = result;
    resources = result.resources;
    purposes = result.purposes;
  } catch (error) {
    errorMessage = error.name === 'TimeoutError' ? '응답 시간이 초과되었습니다. 다시 시도해주세요.' : error.message;
  } finally {
    loading = false;
    $('#filter-form').querySelectorAll('select, button').forEach((el) => { el.disabled = false; });
    $('#filter-form').querySelectorAll('input').forEach((el) => { el.disabled = false; });
    $('#risk-input').disabled = false;
    $('#load-risk-example').disabled = false;
    $('#clear-risk-input').disabled = false;
    renderResults();
  }
}

$('#filter-form').addEventListener('submit', (event) => { event.preventDefault(); queryResources(); });

$('#results').addEventListener('click', (event) => {
  if (event.target.closest('#retry-request')) { queryResources(); return; }
  const selectButton = event.target.closest('[data-select]');
  if (selectButton) {
    const id = selectButton.dataset.select;
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    renderResults();
    // 목록을 다시 그려도 키보드 사용자의 위치가 유지되게 합니다.
    [...document.querySelectorAll('[data-select]')].find((button) => button.dataset.select === id)?.focus();
  }
  const detailsButton = event.target.closest('[data-details]');
  if (!detailsButton) return;
  const item = resources.find((resource) => resource.id === detailsButton.dataset.details);
  $('#dialog-content').innerHTML = `<span class="category ${escape(item.purpose)}">${escape(purposes[item.purpose])}</span>
    <h2 id="dialog-title">${escape(item.name)}</h2><p class="muted">${escape(item.organization)}</p>
    <dl><dt>지원 내용</dt><dd>${escape(item.description)}</dd><dt>대상·신청 조건</dt><dd>${escape(item.eligibility)}</dd>
    <dt>운영 기간</dt><dd>${escape(item.schedule)}</dd><dt>확인할 사항</dt><dd>${escape(item.check)}</dd>
    <dt>신청 방법</dt><dd>${escape(item.application_method)}</dd><dt>공식 출처</dt><dd><a class="source-link" href="${escape(item.source.url)}" target="_blank" rel="noopener noreferrer">${escape(item.source.title)} ↗</a><br>페이지 확인일: ${escape(item.source.checked_at)}<br>페이지 수정일: ${escape(item.source.page_updated_at || "미확인")}<br>${escape(item.source.review_note)}</dd><dt>운영 상태</dt><dd>현재 모집·예산·운영 여부는 기관 확인이 필요합니다. 페이지 확인일은 서비스 검증일이 아닙니다.</dd></dl>`;
  $('#resource-dialog').showModal();
});

$('#load-risk-example').addEventListener('click', () => {
  // 선택 집단에 맞춘 연결 검증용 예시이며 실제 분석 수치나 결과를 만들지 않는다.
  $('#risk-input').value = JSON.stringify({ schema_version: 'risk-input-0.1', assessment_id: 'example-only',
    region: $('#region').value, age_group: Number($('#age').value), period: '2025-12',
    status: 'complete', level: 3, model_version: 'example-model-not-production', is_example: true,
    signals: [{type:'movement_decline', description:'이동 감소 신호를 받았다고 가정한 연결 검증 예시입니다.'},
      {type:'consumption_decline', description:'소비 감소 신호를 받았다고 가정한 연결 검증 예시입니다.'}],
    limitations: ['화면 연결 확인용 가상 입력입니다. 실제 분석 결과가 아닙니다.'],
  }, null, 2);
});
$('#clear-risk-input').addEventListener('click', () => { $('#risk-input').value = ''; });
// 다른 집단으로 바꿀 때 이전 집단에서 확인한 지원 필요를 그대로 적용하지 않는다.
for (const selector of ['#region', '#age']) {
  $(selector).addEventListener('change', () => {
    document.querySelectorAll('[name="support-need"]').forEach((input) => { input.checked = false; });
  });
}

$('#download-selection').addEventListener('click', () => {
  if (!recommendation || loading || !selected.size) return;
  // 조건・버전・주의사항을 함께 보존하는 기획 Agent 연결용 임시 형식.
  const payload = { ...recommendation, exported_at: new Date().toISOString(),
    resources: resources.filter((item) => selected.has(item.id)), total: selected.size };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'ieum-welfare-selection.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

$('.skip-link').addEventListener('click', (event) => {
  event.preventDefault();
  $('#main').focus();
});
window.addEventListener('hashchange', navigate);
navigate();
renderResults();
fetch('/api/welfare/status').then((response) => response.ok ? response.json() : Promise.reject()).then((status) => {
  $('#agent-status').textContent = status.configured ? `Tavily 검색 + Gemini 추천 · ${status.model}. 두 서비스의 무료 등급·한도를 유지해주세요.` : `키 설정 필요: ${[!status.tavily_configured && 'TAVILY_API_KEY', !status.gemini_configured && 'GEMINI_API_KEY'].filter(Boolean).join(', ')}. .env를 확인해주세요. 저장 자료 테스트는 키 없이 사용할 수 있습니다.`;
}).catch(() => { $('#agent-status').textContent = 'API 서버 연결을 확인해주세요. python backend/server.py로 실행합니다.'; });
