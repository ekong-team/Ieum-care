let resources = [];
let purposes = {};
let recommendation = null;
let responseRouting = null;
let loading = false;
let errorMessage = '';
let requestedMode = 'live';
let retryAvailableAt = 0;
let retryTimer = null;
const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);

const $ = (selector) => document.querySelector(selector);
const pages = { dashboard: '대시보드', analysis: '분석', recommendations: '복지자원 추천', planning: '프로그램 기획', evaluation: '평가·예산' };
const selected = new Set();
let filters = { region: '춘천시', age: 60, purpose: 'all' };
const ageLabel = (age) => age === 60 ? '60대 이상' : age === 10 ? '20대 미만' : `${age}대`;

const relevanceLabels = { direct: '고립 예방과 직접 연관', indirect: '일반 생활 지원 · 간접 연관', uncertain: '고립 예방 연관성 확인 필요' };

function sourceInfo(item, detailed = false) {
  const source = item.source;
  const live = recommendation?.mode === 'live';
  const year = source.reference_year;
  const yearLabel = year ? `${year}년` : '미확인';
  const yearKindLabel = source.reference_year_kind === 'publication' ? '자료 발행·게시 연도' : source.reference_year_kind === 'applicable' ? '적용 기준 연도' : '자료 연도(의미 미확인)';
  const yearNote = source.reference_year_kind === 'publication' ? '발행·게시 연도만 확인 · 현행 적용 기준은 별도 확인' : source.reference_year_status === 'past_year' ? '과거 자료 · 현행 기준 재확인'
    : source.reference_year_status === 'future_year' ? '향후 기준 자료 · 적용 시점 확인'
    : year ? '현재 운영·모집 여부는 별도 확인' : '최신 자료인지 확인 필요';
  return `<div class="source-info"><a class="source-link" href="${escape(source.url)}" target="_blank" rel="noopener noreferrer">${escape(source.title)} ↗</a>
    <div class="source-dates"><span>${live ? '검색일' : '출처 확인일'}: ${escape(source.checked_at)}</span><span>${yearKindLabel}: ${escape(yearLabel)}</span>${recommendation?.search_cache_hit ? '<span>5분 이내 검색 결과 재사용 · 추가 검색 호출 없음</span>' : ''}</div>
    <p class="source-freshness ${source.reference_year_status === 'past_year' ? 'past-year' : ''}">${escape(yearNote)}</p>
    ${detailed ? `<p class="muted">${live ? '자료 연도는 검색 발췌문 대조 결과이며 원문 전체를 검증한 것은 아닙니다.' : '저장된 자료의 확인일이며 이번에 검색한 날짜가 아닙니다.'}<br>페이지 수정일: ${escape(source.page_updated_at || '미확인')}</p>${source.reference_year_evidence ? `<blockquote class="source-evidence">${escape(source.reference_year_evidence)}</blockquote>` : ''}<p class="muted">${escape(source.review_note)}</p>` : ''}</div>`;
}

function updateRetryControls() {
  const remaining = Math.max(0, Math.ceil((retryAvailableAt - Date.now()) / 1000));
  const retry = $('#retry-request');
  if (retry) {
    retry.disabled = loading || remaining > 0;
    retry.textContent = remaining ? `${remaining}초 후 다시 시도` : '다시 시도';
  }
  $('#filter-form button[type="submit"]').disabled = loading || remaining > 0;
  if (!remaining && retryTimer !== null) {
    clearInterval(retryTimer);
    retryTimer = null;
  }
}

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
  $('#result-description').textContent = !recommendation ? '지역·연령·지원 목적을 선택하고 복지자원을 추천받으세요.'
    : recommendation.mode === 'offline' ? '저장된 자료 조회 테스트입니다. 외부 검색·LLM을 실행하지 않았습니다.'
    : !recommendation.risk_assessment ? '지역·연령·지원 목적과 검색 자료를 바탕으로 찾은 검토 후보입니다. 위험도 분석 결과는 아직 연결되지 않았습니다.'
    : '전달받은 집단 분석 결과와 검색 근거를 대조한 검토 후보입니다. 개인 자격·지원 효과는 확정하지 않습니다.';
  $('#results').setAttribute('aria-busy', String(loading));
  $('#results').innerHTML = loading ? `<div class="no-results panel">${requestedMode === 'live' ? '공식 사이트를 검색하고 AI가 분석 결과와 자원을 대조하고 있습니다. 잠시 기다려주세요.' : '저장된 자료를 조회하고 있습니다.'}</div>` : errorMessage ? `<div class="no-results panel" role="alert"><strong>자원을 불러오지 못했습니다.</strong><p>${escape(errorMessage)}</p><button id="retry-request" class="secondary">다시 시도</button></div>` : !recommendation ? '<div class="no-results panel"><strong>대상을 선택하고 추천받기를 눌러주세요.</strong><p>실시간 모드는 외부 검색과 AI 판단을 실행합니다. 페이지를 열거나 새로고침하는 것만으로 API를 호출하지 않습니다.</p></div>' : matches.length ? matches.map((item) => `
    <article class="resource-card panel">
      <div class="card-top"><div class="resource-tags"><span class="category ${escape(item.purpose)}">${escape(purposes[item.purpose])}</span>${item.isolation_relevance ? `<span class="relevance-tag ${escape(item.isolation_relevance)}">${escape(relevanceLabels[item.isolation_relevance])} · AI 분류</span>` : ''}</div><span class="example-tag">운영 확인 필요</span></div>
      <h3>${escape(item.name)}</h3><p class="organization">${escape(item.organization)}</p><p class="muted">${escape(({overlap:"연령 범위 겹침",partial:"일부 연령만 해당 · 정확한 나이 확인",unknown:"연령 기준 미확정 · 기관 확인"})[item.age_match])}</p>
      <p class="resource-description">${escape(item.description)}</p>
      <div class="resource-meta"><span>⌖ ${escape(item.region)}</span><span>◷ ${escape(item.format)}</span></div>
      ${sourceInfo(item)}
      <div class="recommendation-reason"><span aria-hidden="true">✧</span><p><strong>추천 이유</strong>${escape(item.reason)}${item.relevance_reason ? `<br><strong>고립 예방과의 연결</strong>${escape(item.relevance_reason)}` : ''}<br><strong>신청 전 확인</strong>${item.match_reasons.map(escape).join(' · ')}</p></div>
      <div class="card-bottom"><button class="text-button" data-details="${escape(item.id)}">상세 정보 <span aria-hidden="true">↗</span></button>
      <button class="select-button ${selected.has(item.id) ? 'is-selected' : ''}" data-select="${escape(item.id)}" aria-pressed="${selected.has(item.id)}">${selected.has(item.id) ? '✓ 선택됨' : '+ 기획 목록에 담기'}</button></div>
    </article>`).join('') : `<div class="no-results panel"><strong>근거를 갖춘 후보를 제시하지 못했습니다.</strong><p>${escape(recommendation.coverage?.message || '실제 서비스 부재를 뜻하지 않습니다. 추가 조사가 필요합니다.')}</p></div>`;
  renderSelection();
  renderReview();
  renderResponseRoutes();
  updateRetryControls();

}

function renderResponseRoutes() {
  const panel = $('#response-routes');
  panel.hidden = loading || !responseRouting;
  if (panel.hidden) { panel.replaceChildren(); return; }
  const status = { candidates_found: '기존 자원 후보 확보', no_candidates_found: '이번 조회에서 후보 미확보', unavailable: '조회 미완료' };
  panel.innerHTML = `<h2>다음 대응 검토</h2><p class="muted">${escape(status[responseRouting.candidate_status])}${recommendation?.mode === 'offline' ? ' · 저장 자료 테스트 결과' : ''} · 여러 대응을 함께 검토할 수 있습니다.</p>
    <div class="route-options">${responseRouting.routes.map((route) => `<article><h3>${escape(route.title)}</h3><p>${escape(route.reason)}</p><ul>${route.checks.map((check) => `<li>${escape(check)}</li>`).join('')}</ul></article>`).join('')}</div>
    <ul class="route-notes">${responseRouting.notes.map((note) => `<li>${escape(note)}</li>`).join('')}</ul>
    <p class="muted">기획 Agent 연결 전입니다. 이 화면에서 기획서를 생성하거나 기관으로 전송하지 않습니다.</p>`;
}

function renderReview() {
  const panel = $('#review-context');
  const risk = recommendation?.risk_assessment;
  const review = recommendation?.review;
  panel.hidden = !review || (!risk && !review.confirmed_support_needs.length && !review.summary);
  if (panel.hidden) { panel.replaceChildren(); return; }
  const status = {browse:'일반 조회', needs_confirmation:'지원 필요 확인', ready_for_review:'확인한 필요로 후보 검토', risk_held:'위험 판정 보류 · 일반 조회', risk_partial:'불완전한 위험 판정 · 일반 조회'};
  panel.innerHTML = `<h3>${escape(status[review.status])}</h3>
    ${review.input_note || !risk ? `<p class="input-basis">${escape(review.input_note || '위험도 분석 결과가 연결되지 않아 지역·연령·지원 목적을 기준으로 조회했습니다.')}</p>` : ''}
    ${review.summary ? `<p><strong>AI 추천 판단</strong><br>${escape(review.summary)}</p>` : ''}
    ${risk ? `<p><strong>${risk.is_example ? '예시 위험도 입력 · 실제 분석 결과 아님' : '입력받은 위험도 결과 · 자동 수신 전'}</strong><br>${escape(risk.period)} · ${escape(risk.region)} · ${escape(ageLabel(risk.age_group))} · ${risk.level === null ? '단계 보류' : `${escape(risk.level)}단계`}<br>모델: ${escape(risk.model_version)}</p><ul>${risk.signals.map((signal) => `<li>${escape(signal.description)}</li>`).join('')}${risk.limitations.map((text) => `<li>관측 제한: ${escape(text)}</li>`).join('')}</ul>` : ''}
    ${review.confirmed_support_needs.length ? `<p>담당자가 확인한 필요: ${review.confirmed_support_needs.map((purpose) => escape(recommendation.purposes[purpose])).join(' · ')}</p>` : ''}
    ${review.suggested_purposes.map((item) => `<p><strong>확인해볼 목적: ${escape(recommendation.purposes[item.purpose])}</strong><br>${escape(item.reason)}</p>`).join('')}
    ${recommendation.exclusion_counts && Object.keys(recommendation.exclusion_counts).length ? `<p class="muted">검토에서 제외된 후보: ${Object.entries(recommendation.exclusion_counts).map(([key, count]) => `${escape(({source_not_grounded:'검색 출처 미일치',region_mismatch:'지역 불일치',closed:'종료 확인',purpose_mismatch:'지원 목적 불일치',age_mismatch:'연령 불일치',duplicate:'중복'})[key] || '기타 사유')} ${escape(count)}개`).join(' · ')}</p>` : ''}
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
  if (loading || Date.now() < retryAvailableAt) return;
  filters = { region: $('#region').value, age: Number($('#age').value), purpose: $('#purpose').value };
  requestedMode = $('#search-mode').value;
  loading = true;
  recommendation = null;
  responseRouting = null;
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
    if (!response.ok) {
      responseRouting = result.response_routing || null;
      if (Number.isInteger(result.retry_after_seconds) && result.retry_after_seconds > 0 && result.retry_after_seconds <= 60) {
        retryAvailableAt = Date.now() + result.retry_after_seconds * 1000;
        if (retryTimer !== null) clearInterval(retryTimer);
        retryTimer = setInterval(updateRetryControls, 1000);
      }
      throw new Error(result.error || '추천 조회에 실패했습니다.');
    }
    if (result.schema_version !== 'welfare-0.4' || result.is_demo !== false || !result.review || !Array.isArray(result.resources)) throw new Error('지원하지 않는 추천 응답 형식입니다.');
    recommendation = result;
    responseRouting = result.response_routing || null;
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
    <dt>신청 방법</dt><dd>${escape(item.application_method)}</dd><dt>공식 출처와 자료 시점</dt><dd>${sourceInfo(item, true)}</dd>${item.isolation_relevance ? `<dt>고립 예방 연관성 · AI 분류</dt><dd>${escape(relevanceLabels[item.isolation_relevance])}<br>${escape(item.relevance_reason)}<br>연관성 분류는 실제 예방 효과가 검증됐다는 뜻이 아닙니다.</dd>` : ''}<dt>운영 상태</dt><dd>현재 모집·예산·운영 여부는 기관 확인이 필요합니다. 검색일·출처 확인일은 서비스의 현행 요건 검증일이 아닙니다.</dd></dl>`;
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
  if (responseRouting) payload.response_routing = { ...responseRouting,
    routes: responseRouting.routes.map((route) => ({ ...route, resource_ids: route.resource_ids.filter((id) => selected.has(id)) })) };
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
