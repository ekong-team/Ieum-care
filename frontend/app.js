let resources = [];
let purposes = {};
let recommendation = null;
let loading = false;
let errorMessage = '';
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
  $('#result-count').textContent = loading ? '조회 중' : errorMessage ? '연결 확인 필요' : `확인 후보 ${matches.length}개`;
  $('#result-description').textContent = '지역·연령·목적을 기준으로 조회한 후보입니다. 정렬은 추천 순위가 아니며, 개인 자격은 미판정입니다.';
  $('#results').setAttribute('aria-busy', String(loading));
  $('#results').innerHTML = loading ? '<div class="no-results panel">공식 안내 자원을 조회하고 있습니다.</div>' : errorMessage ? `<div class="no-results panel" role="alert"><strong>자원을 불러오지 못했습니다.</strong><p>${escape(errorMessage)}</p><button id="retry-request" class="secondary">다시 시도</button></div>` : matches.length ? matches.map((item) => `
    <article class="resource-card panel">
      <div class="card-top"><span class="category ${escape(item.purpose)}">${escape(purposes[item.purpose])}</span><span class="example-tag">운영 확인 필요</span></div>
      <h3>${escape(item.name)}</h3><p class="organization">${escape(item.organization)}</p><p class="muted">${escape(({overlap:"연령 범위 겹침",partial:"일부 연령만 해당 · 정확한 나이 확인",unknown:"연령 기준 미확정 · 기관 확인"})[item.age_match])}</p>
      <p class="resource-description">${escape(item.description)}</p>
      <div class="resource-meta"><span>⌖ ${escape(item.region)}</span><span>◷ ${escape(item.format)}</span></div>
      <div class="recommendation-reason"><span aria-hidden="true">✧</span><p><strong>검토 포인트</strong>${escape(item.reason)}<br>${item.match_reasons.map(escape).join(' · ')}</p></div>
      <div class="card-bottom"><button class="text-button" data-details="${escape(item.id)}">상세 정보 <span aria-hidden="true">↗</span></button>
      <button class="select-button ${selected.has(item.id) ? 'is-selected' : ''}" data-select="${escape(item.id)}" aria-pressed="${selected.has(item.id)}">${selected.has(item.id) ? '✓ 선택됨' : '+ 기획 목록에 담기'}</button></div>
    </article>`).join('') : '<div class="no-results panel"><strong>등록 목록에서 조건에 맞는 후보를 찾지 못했습니다.</strong><p>아직 수집하지 않은 자원이 있을 수 있습니다. 목적을 바꾸거나 지역 기관에 문의하세요.</p></div>';
  renderSelection();
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
  loading = true;
  recommendation = null;
  resources = [];
  errorMessage = '';
  selected.clear();
  $('#resource-dialog').close();
  $('#filter-form').querySelectorAll('select, button').forEach((el) => { el.disabled = true; });
  renderResults();
  try {
    const response = await fetch('/api/welfare/recommendations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: { region: filters.region, age_group: filters.age, purpose: filters.purpose }, risk_assessment: null }),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('추천 API 서버로 접속해주세요. 실행 방법은 frontend/README.md에 있습니다.');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '추천 조회에 실패했습니다.');
    if (result.schema_version !== 'welfare-0.2' || result.is_demo !== false || !Array.isArray(result.resources)) throw new Error('지원하지 않는 추천 응답 형식입니다.');
    recommendation = result;
    resources = result.resources;
    purposes = result.purposes;
  } catch (error) {
    errorMessage = error.name === 'TimeoutError' ? '응답 시간이 초과되었습니다. 다시 시도해주세요.' : error.message;
  } finally {
    loading = false;
    $('#filter-form').querySelectorAll('select, button').forEach((el) => { el.disabled = false; });
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
queryResources();
