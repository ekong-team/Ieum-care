let resources = [];
let purposes = {};
let recommendation = null;
let responseRouting = null;
// 폼을 바꿔도 마지막 조회에 사용한 대상·분석 맥락으로 기획 요청을 만든다.
let planningContext = null;
let preparedPlanningRequest = null;
let planningSendRunning = false;
let analysisInputs = null;
let connectedAnalysisEntry = null;
let analysisBatchRunning = false;
let analysisStopRequested = false;
const analysisResults = new Map(); // 같은 배치의 브라우저 저장 결과와 현재 조회를 재사용한다.
const ANALYSIS_STORAGE_KEY = 'ieum-welfare-results-v1';

function persistAnalysisResults() {
  if (!analysisInputs) return;
  try {
    // 현재 배치만 보관한다. API 키·담당자 기획 프롬프트·선택 목록은 저장하지 않는다.
    const entries = analysisInputs.entries.flatMap((entry) => ['live', 'offline'].flatMap((mode) => {
      const record = analysisResults.get(`${mode}:${entry.analysis_id}`);
      return record ? [{analysis_id: entry.analysis_id, mode, request_signature: JSON.stringify(entry.request), record}] : [];
    }));
    localStorage.setItem(ANALYSIS_STORAGE_KEY, JSON.stringify({version: 1, batch_id: analysisInputs.batch_id, entries}));
    $('#analysis-storage-status').textContent = '이 브라우저에 추천 결과 저장됨 · 새로고침 후 같은 분석 배치에서 복원합니다. 최신 운영 여부는 다시 확인해주세요.';
  } catch {
    $('#analysis-storage-status').textContent = '브라우저에 저장하지 못했습니다. 현재 화면에서는 계속 확인할 수 있지만 새로고침하면 결과가 사라질 수 있습니다.';
  }
}

function restoreAnalysisResults() {
  try {
    const stored = JSON.parse(localStorage.getItem(ANALYSIS_STORAGE_KEY) || 'null');
    if (!stored || stored.version !== 1 || stored.batch_id !== analysisInputs.batch_id || !Array.isArray(stored.entries)) return;
    let restored = 0;
    for (const saved of stored.entries) {
      const entry = analysisInputs.entries.find((item) => item.analysis_id === saved.analysis_id);
      const record = saved.record;
      if (!entry || !['live', 'offline'].includes(saved.mode) || saved.request_signature !== JSON.stringify(entry.request)
          || !record || typeof record !== 'object') continue;
      const result = record.recommendation;
      // 로컬 저장소의 오래된 형식·손상 자료를 정상 응답으로 재사용하지 않는다.
      if (result && (result.schema_version !== 'welfare-0.4' || result.is_demo !== false || result.mode !== saved.mode
          || !Array.isArray(result.resources) || !result.review
          || JSON.stringify(result.risk_assessment) !== JSON.stringify(entry.request.risk_assessment)
          || JSON.stringify(result.analysis_context) !== JSON.stringify(entry.request.analysis_context))) continue;
      if (!result && typeof record.errorMessage !== 'string') continue;
      if (!record.filters || record.filters.region !== entry.request.target.region
          || record.filters.age !== entry.request.target.age_group || record.filters.sex !== entry.request.target.sex
          || record.filters.purpose !== entry.request.target.purpose) continue;
      if (record.planningContext && (record.planningContext.mode !== saved.mode
          || !record.planningContext.input
          || ['region', 'age_group', 'sex', 'purpose'].some((key) => record.planningContext.input.target?.[key] !== entry.request.target[key])
          || ['risk_assessment', 'analysis_context', 'confirmed_support_needs'].some((key) =>
            JSON.stringify(record.planningContext.input[key]) !== JSON.stringify(entry.request[key])))) continue;
      const key = `${saved.mode}:${entry.analysis_id}`;
      if (!analysisResults.has(key)) { analysisResults.set(key, record); restored++; }
    }
    $('#analysis-storage-status').textContent = `${restored}건의 브라우저 저장 결과를 복원했습니다. 추가 검색·AI 호출은 하지 않았습니다. 최신 운영 여부는 다시 확인해주세요.`;
  } catch {
    $('#analysis-storage-status').textContent = '브라우저 저장 결과를 읽지 못했습니다. 현재 분석 입력으로 새로 조회할 수 있습니다.';
  }
}
let loading = false;
let errorMessage = '';
let requestedMode = 'live';
let retryAvailableAt = 0;
let retryTimer = null;
const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);

const $ = (selector) => document.querySelector(selector);
const pages = { dashboard: '대시보드', analysis: '분석', recommendations: '복지자원 추천', planning: '프로그램 기획', evaluation: '평가·예산' };
const selected = new Set();
let filters = { region: '춘천시', age: 60, sex: 'all', purpose: 'all' };
const ageLabel = (age) => age === 60 ? '60대 이상' : age === 10 ? '10대 (10~19세)' : `${age}대`;
const sexLabel = (sex) => ({all:'남녀 합산',male:'남성',female:'여성'})[sex || 'all'];
const purposeLabels = { all: '전체 목적', connection: '관계 형성·사회 참여', daily: '일상생활 지원', wellbeing: '정서·마음 돌봄', economic: '경제·생활 안정', other: '기타·통합 안내' };

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
  $('#run-analysis-recommendations').disabled = loading || analysisBatchRunning || remaining > 0 || !analysisInputs?.entries.length;
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
  $('#planning-page').hidden = page !== 'planning';
  $('#empty-page').hidden = ['recommendations', 'planning'].includes(page);
  if (page === 'planning') loadPlanningInbox();
  $('#empty-title').textContent = pages[page];
  document.title = `이음케어 · ${pages[page]}`;
  document.querySelectorAll('.navigation a').forEach((link) => {
    if (link.hash === `#${page}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}

function renderResults() {
  const matches = resources;
  $('#results-title').textContent = `${filters.region} · ${ageLabel(filters.age)} · ${sexLabel(filters.sex)}`;
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
  panel.innerHTML = `<p><strong>${escape(status[responseRouting.candidate_status])}</strong>${requestedMode === 'offline' ? ' · 저장 자료 테스트 결과' : ''}</p>
    <p>${responseRouting.candidate_status === 'unavailable' ? '기존 자원 확인이 끝나지 않았습니다. 예방 기획 초안용 요청은 준비할 수 있으며, 조회 실패 사실도 함께 전달합니다.' : responseRouting.candidate_status === 'no_candidates_found' ? '이번 조회의 후보가 없어도 예방·신규 기획을 요청할 수 있습니다. 지역에 자원이 없다고 확정하는 것은 아닙니다.' : '선택 자원을 활용하거나, 기존 서비스와 별도로 예방·신규 기획을 요청하세요.'}</p>
    <details><summary>기획 시 확인할 사항</summary>${responseRouting.routes.map((route) => `<p><strong>${escape(route.title)}</strong><br>${escape(route.reason)}</p><ul>${route.checks.map((check) => `<li>${escape(check)}</li>`).join('')}</ul>`).join('')}<ul>${responseRouting.notes.map((note) => `<li>${escape(note)}</li>`).join('')}</ul></details>`;
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
    ${risk ? `<p><strong>${risk.is_example ? '예시 위험도 입력 · 실제 분석 결과 아님' : recommendation.analysis_context ? '연결된 분석 결과' : '직접 입력한 위험도 결과'}</strong><br>${escape(risk.period)} · ${escape(risk.region)} · ${escape(ageLabel(risk.age_group))} · ${escape(sexLabel(risk.sex))} · ${risk.level === null ? '단계 보류' : `${escape(risk.level)}단계`}<br>모델: ${escape(risk.model_version)}</p><ul>${risk.signals.map((signal) => `<li>${escape(signal.description)}</li>`).join('')}${risk.limitations.map((text) => `<li>관측 제한: ${escape(text)}</li>`).join('')}</ul>` : ''}
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
  updatePlanningControls();
}

function clearPlanningPreview() {
  preparedPlanningRequest = null;
  $('#planning-preview').hidden = true;
  $('#planning-json').textContent = '';
  $('#planning-summary').textContent = '';
  $('#download-planning').disabled = true;
  $('#send-planning').disabled = true;
}

function updatePlanningControls() {
  clearPlanningPreview();
  const ready = !loading && planningContext !== null;
  const count = resources.filter((item) => selected.has(item.id)).length;
  $('#planning-prompt').disabled = !ready;
  $('#prepare-existing').disabled = !ready || !count || !recommendation;
  $('#prepare-preventive').disabled = !ready;
  $('#planning-target').textContent = planningContext
    ? `최근 조회 기준: ${planningContext.input.target.region} · ${ageLabel(planningContext.input.target.age_group)} · ${sexLabel(planningContext.input.target.sex)} · ${purposeLabels[planningContext.input.target.purpose]}`
    : '먼저 대상 집단의 복지자원을 조회해주세요.';
  $('#planning-status').textContent = !ready ? '조회 후 요청을 준비할 수 있습니다.'
    : count ? `${count}개 자원이 선택되어 있습니다. 기획 방식을 선택해주세요.`
    : '자원을 선택하면 기존 자원 활용 기획을, 선택하지 않아도 예방·신규 기획을 요청할 수 있습니다.';
}

function buildPlanningRequest(planningType) {
  if (loading || !planningContext) throw new Error('먼저 올바른 조건으로 복지자원을 조회해주세요.');
  if (!['existing_resource_based', 'preventive_new'].includes(planningType)) throw new Error('기획 방식을 확인해주세요.');
  const items = resources.filter((item) => selected.has(item.id));
  if (planningType === 'existing_resource_based' && (!recommendation || !items.length)) throw new Error('활용할 기존 자원을 먼저 선택해주세요.');
  const prompt = $('#planning-prompt').value.trim();
  if (prompt.length > 2000) throw new Error('담당자 요청은 2,000자 이내로 작성해주세요.');
  const input = planningContext.input;
  // 완성 기획안과 구별되는 전달용 초안. 조회 실패는 후보 0개로 바꾸지 않는다.
  return JSON.parse(JSON.stringify({
    schema_version: 'planning-request-0.1', request_id: crypto.randomUUID(), created_at: new Date().toISOString(),
    planning_type: planningType, target: input.target, officer_prompt: prompt,
    confirmed_support_needs: input.confirmed_support_needs || [], risk_assessment: input.risk_assessment || null,
    analysis_context: recommendation?.analysis_context || input.analysis_context || null,
    has_example_context: Boolean(recommendation?.has_example_context || input.risk_assessment?.is_example || recommendation?.analysis_context?.profile?.is_example),
    selected_resources: items,
    welfare_lookup: { mode: planningContext.mode, status: recommendation ? 'completed' : 'unavailable',
      candidate_status: responseRouting?.candidate_status || (recommendation ? (resources.length ? 'candidates_found' : 'no_candidates_found') : 'unavailable'),
      total_candidates: recommendation ? resources.length : null, error: planningContext.error,
      response_routing: responseRouting, recommendation_snapshot: recommendation },
    notes: ['기획 Agent 연결 전 전달용 요청이며 완성 기획안이 아닙니다.',
      '후보 0개·조회 실패는 실제 자원 부재를 증명하지 않습니다.',
      '추천 건수로 위험 단계를 변경하지 않으며 예방 효과·개인 자격은 확정하지 않습니다.'],
  }));
}

function preparePlanningRequest(planningType) {
  clearPlanningPreview();
  try {
    preparedPlanningRequest = buildPlanningRequest(planningType);
    $('#planning-summary').textContent = `${preparedPlanningRequest.target.region} · ${ageLabel(preparedPlanningRequest.target.age_group)} · ${sexLabel(preparedPlanningRequest.target.sex)} / ${planningType === 'existing_resource_based' ? '기존 자원 활용' : '예방·신규 기획'} / 선택 자원 ${preparedPlanningRequest.selected_resources.length}개`;
    $('#planning-json').textContent = JSON.stringify(preparedPlanningRequest, null, 2);
    $('#planning-preview').hidden = false;
    $('#download-planning').disabled = false;
    $('#send-planning').disabled = planningSendRunning;
    $('#planning-send-status').textContent = '미리보기 내용을 확인한 뒤 기획 전달함에 저장하세요. 기획서 생성은 실행하지 않습니다.';
    $('#planning-status').textContent = '기획 요청을 준비했습니다. 내용을 확인하고 전달함에 저장하거나 JSON 파일을 내려받으세요.';
  } catch (error) { $('#planning-status').textContent = error.message; }
}

async function sendPlanningRequest() {
  if (!preparedPlanningRequest || planningSendRunning || loading) return;
  const request = preparedPlanningRequest; // 저장 도중 새 미리보기가 생겨도 이전 요청과 섞지 않는다.
  planningSendRunning = true;
  $('#send-planning').disabled = true;
  $('#planning-send-status').textContent = '기획 요청을 검증하고 로컬 전달함에 저장하고 있습니다.';
  try {
    const response = await fetch('/api/planning/requests', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(request), signal:AbortSignal.timeout(15000)});
    if (!response.headers?.get('content-type')?.includes('application/json')) throw new Error('최신 코드로 추천 서버를 다시 실행해주세요.');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '기획 요청 저장에 실패했습니다.');
    if (result.schema_version !== 'planning-inbox-0.1' || result.request?.request_id !== request.request_id
        || result.status !== 'awaiting_planning_agent' || result.agent_connected !== false) throw new Error('기획 전달함 응답을 확인해주세요.');
    $('#planning-send-status').textContent = '기획 전달함에 저장했습니다. 프로그램 기획 탭에서 확인하세요. 실제 기획 Agent는 연결 대기 중입니다.';
  } catch (error) {
    $('#planning-send-status').textContent = `${error.name === 'TimeoutError' ? '저장 응답 시간이 초과되었습니다. 같은 요청으로 다시 시도할 수 있습니다.' : error.message} 자동 재시도하지 않았습니다.`;
  } finally {
    planningSendRunning = false;
    $('#send-planning').disabled = !preparedPlanningRequest;
  }
}

async function loadPlanningInbox() {
  $('#load-planning-inbox').disabled = true;
  $('#planning-inbox-status').textContent = '전달함을 불러오고 있습니다.';
  $('#planning-inbox-list').replaceChildren();
  try {
    const response = await fetch('/api/planning/requests', {signal:AbortSignal.timeout(15000)});
    if (!response.headers?.get('content-type')?.includes('application/json')) throw new Error('최신 코드로 추천 서버를 다시 실행해주세요.');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '전달함을 불러오지 못했습니다.');
    if (result.schema_version !== 'planning-inbox-0.1' || !Array.isArray(result.requests)) throw new Error('전달함 응답 형식을 확인해주세요.');
    $('#planning-inbox-status').textContent = `${result.requests.length}건 저장됨 · 실제 기획 Agent 연결 대기 · 기획서 생성·검색·LLM 실행 없음`;
    $('#planning-inbox-list').innerHTML = result.requests.length ? result.requests.map((item) => {
      const request = item.request;
      return `<article class="resource-card"><h2>${escape(request.target.region)} · ${escape(ageLabel(request.target.age_group))} · ${escape(sexLabel(request.target.sex))}</h2><p>${request.planning_type === 'existing_resource_based' ? '기존 자원 활용' : '예방·신규 기획'} · 선택 자원 ${request.selected_resources.length}개 · ${request.welfare_lookup.mode === 'live' ? '실시간 추천' : '저장 자료 테스트'}</p><p class="muted">접수: ${escape(item.received_at)} · 기획 Agent 연결 대기${request.has_example_context ? ' · 예시 분석 포함' : ''}</p><p>${escape(request.officer_prompt || '담당자 추가 요청 없음')}</p><details><summary>팀원에게 전달할 요청 원문</summary><pre>${escape(JSON.stringify(request, null, 2))}</pre></details></article>`;
    }).join('') : '<p>아직 저장한 요청이 없습니다. 복지 추천 화면에서 기획 요청을 준비하고 전달함에 저장하세요.</p>';
  } catch (error) { $('#planning-inbox-status').textContent = error.message; }
  finally { $('#load-planning-inbox').disabled = false; }
}

async function queryResources() {
  if (loading || Date.now() < retryAvailableAt) return;
  let analysisResultKey = null;
  filters = { region: $('#region').value, age: Number($('#age').value), sex: $('#sex').value, purpose: $('#purpose').value };
  requestedMode = $('#search-mode').value;
  loading = true;
  recommendation = null;
  responseRouting = null;
  planningContext = null;
  $('#planning-prompt').value = '';
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
    const input = { target: { region: filters.region, age_group: filters.age, sex: filters.sex, purpose: filters.purpose }, risk_assessment: risk,
      confirmed_support_needs: [...document.querySelectorAll('[name="support-need"]:checked')].map((input) => input.value) };
    if (connectedAnalysisEntry && JSON.stringify(risk) === JSON.stringify(connectedAnalysisEntry.request.risk_assessment)
        && ['region', 'age_group', 'sex'].every((key) => input.target[key] === connectedAnalysisEntry.request.target[key])) {
      input.analysis_context = connectedAnalysisEntry.request.analysis_context;
      // 원래 1차 대상 요청과 조건이 같은 단건 실시간 조회도 일괄 결과에 보존한다.
      // 담당자가 목적·지원 필요를 바꾼 별도 조회를 전체 목적의 결과로 재사용하지 않는다.
      if (input.target.purpose === connectedAnalysisEntry.request.target.purpose
          && JSON.stringify(input.confirmed_support_needs) === JSON.stringify(connectedAnalysisEntry.request.confirmed_support_needs)) {
        analysisResultKey = `${requestedMode}:${connectedAnalysisEntry.analysis_id}`;
      }
    }
    const response = await fetch('/api/welfare/recommendations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: requestedMode, ...input }),
      signal: AbortSignal.timeout(150000),
    });
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('추천 API 서버로 접속해주세요. 실행 방법은 frontend/README.md에 있습니다.');
    const result = await response.json();
    if (!response.ok) {
      responseRouting = result.response_routing || null;
      // 서버가 입력 검증을 통과한 실행 실패에만 대응 경로를 제공한다.
      if (responseRouting?.candidate_status === 'unavailable') planningContext = { input, mode: requestedMode, error: result.error || '추천 조회 실패' };
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
    planningContext = { input, mode: requestedMode, error: null };
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
    if (analysisResultKey) {
      analysisResults.set(analysisResultKey, {recommendation, responseRouting, planningContext, errorMessage, filters: {...filters}, saved_at: new Date().toISOString()});
      persistAnalysisResults();
      renderAnalysisInputs();
      if (!analysisBatchRunning && analysisInputs) {
        const done = analysisInputs.entries.filter((entry) => analysisResults.get(`${requestedMode}:${entry.analysis_id}`)?.recommendation).length;
        $('#analysis-input-status').textContent = `${analysisInputs.entries.length}집단 중 ${done}집단 추천 완료 · 단건 결과도 목록에서 다시 볼 수 있습니다. 같은 방식의 일괄 실행은 성공 집단을 건너뜁니다.`;
      }
    }
  }
  return Boolean(recommendation);
}

function renderAnalysisInputs() {
  renderSecondReview();
  const panel = $('#analysis-targets');
  panel.replaceChildren();
  if (!analysisInputs) return;
  const mode = $('#search-mode').value;
  panel.innerHTML = analysisInputs.entries.map((entry, index) => {
    const target = entry.request.target;
    const saved = analysisResults.get(`${mode}:${entry.analysis_id}`);
    return `<div class="analysis-target"><span><strong>${escape(entry.rank)}순위</strong> · ${escape(target.region)} · ${escape(ageLabel(target.age_group))} · ${escape(sexLabel(target.sex))} · ${escape(entry.request.risk_assessment.level)}단계</span><span>${saved ? (saved.recommendation ? `후보 ${saved.recommendation.total}개` : '조회 실패') : '추천 대기'}</span><button type="button" class="text-button" data-analysis-index="${index}" ${analysisBatchRunning ? 'disabled' : ''}>${saved?.recommendation ? '결과 보기' : '분석 입력 보기'}</button></div>`;
  }).join('');
  $('#load-analysis').disabled = analysisBatchRunning || loading;
  $('#stop-analysis-recommendations').disabled = !analysisBatchRunning;
  updateRetryControls();
}

// 추천의 개수로 위험도나 지원 순위를 재계산하지 않는다. 같은 배치·방식만 비교한다.
function buildSecondReview() {
  if (!analysisInputs) return null;
  const mode = $('#search-mode').value;
  const rows = analysisInputs.entries.map((entry) => {
    const saved = analysisResults.get(`${mode}:${entry.analysis_id}`);
    const result = saved?.recommendation;
    const candidates = result?.resources || [];
    const status = result ? (candidates.length ? 'candidates_found' : 'no_candidates_found')
      : saved ? 'unavailable' : 'pending';
    return {
      analysis_id: entry.analysis_id, first_priority_rank: entry.rank,
      target: entry.request.target, risk_assessment: entry.request.risk_assessment,
      lookup_status: status, candidate_count: result ? candidates.length : null,
      saved_at: saved?.saved_at || null,
      // AI의 연관성 분류이며 효과 검증이나 담당자 확인을 대신하지 않는다.
      ai_direct_relevance_count: result && mode === 'live'
        ? candidates.filter((item) => item.isolation_relevance === 'direct').length : null,
      candidates: candidates.map((item) => ({id: item.id, name: item.name,
        source_url: item.source?.url || null, age_match: item.age_match || 'unknown',
        isolation_relevance: item.isolation_relevance || null,
        eligibility_status: item.eligibility_status || 'needs_confirmation',
        availability_status: item.availability_status || 'needs_confirmation',
        reference_year: item.source?.reference_year || null})),
      next_action: status === 'candidates_found' ? '기관에 실제 대상·운영·참여 가능 여부 확인 후 기존 자원 활용 또는 보완 기획'
        : status === 'no_candidates_found' ? '검색 범위·대상 조건을 추가 조사하고 예방·신규 기획 검토'
        : status === 'unavailable' ? '오류 확인 후 담당자가 조회 재실행 · 자원 부족 판단 보류'
        : '복지 추천 조회 필요 · 자원 부족 판단 보류',
      error: saved?.errorMessage || null,
      second_priority_rank: null,
    };
  });
  const completed = rows.filter((row) => ['candidates_found', 'no_candidates_found'].includes(row.lookup_status)).length;
  return {schema_version: 'welfare-cohort-review-0.1', batch_id: analysisInputs.batch_id,
    period: analysisInputs.period, mode, status: 'needs_human_review',
    comparison_complete: rows.length > 0 && completed === rows.length,
    completed_cohorts: completed, total_cohorts: rows.length,
    policy: 'preserve-first-priority-no-automatic-reranking-v1',
    limitations: ['화면 세션에 남은 같은 방식의 추천 결과만 비교합니다.',
      '후보 미확보·조회 실패는 지역의 실제 자원 부재를 의미하지 않습니다.',
      '자격·운영·수용 인원 및 미충족 수요 확인과 팀의 순위 기준 합의가 필요합니다.',
      '부분 판정·보류 집단은 1차 추천 입력에서 제외되어 이 표에도 포함되지 않습니다.'], rows};
}

function renderSecondReview() {
  const report = buildSecondReview();
  $('#second-review').hidden = !report;
  $('#download-second-review').disabled = !report || loading || analysisBatchRunning;
  if (!report) { $('#second-review-table').replaceChildren(); return; }
  $('#second-review-status').textContent = `${report.mode === 'live' ? '실시간 검색·AI 추천' : '저장 자료 테스트'} · ${report.completed_cohorts}/${report.total_cohorts}집단 조회 완료 · ${report.comparison_complete ? '전체 조회 완료 · 담당자 확인 필요' : '일부 미완료 · 전체 집단 비교 미완성'} · 2차 순위 미확정`;
  const labels = {candidates_found:'후보 확보',no_candidates_found:'후보 미확보',unavailable:'조회 실패',pending:'미조회'};
  $('#second-review-table').innerHTML = `<table class="cohort-review-table"><caption>1차 순위에 따른 복지 추천 결과와 다음 조치</caption><thead><tr><th scope="col">1차 순위·대상</th><th scope="col">추천 결과</th><th scope="col">다음 조치</th><th scope="col">상세</th></tr></thead><tbody>${report.rows.map((row, index) => `<tr><th scope="row">${escape(row.first_priority_rank)}순위 · ${escape(row.target.region)}<br>${escape(ageLabel(row.target.age_group))} · ${escape(sexLabel(row.target.sex))} · ${escape(row.risk_assessment.level)}단계</th><td>${labels[row.lookup_status]}${row.candidate_count === null ? '' : ` · ${row.candidate_count}개`}${row.ai_direct_relevance_count === null ? '' : `<br>AI 직접 연관 ${row.ai_direct_relevance_count}개`}</td><td>${escape(row.next_action)}</td><td><button type="button" class="text-button" data-analysis-index="${index}" ${loading || analysisBatchRunning ? 'disabled' : ''}>보기</button></td></tr>`).join('')}</tbody></table>`;
}

async function loadAnalysisInputs() {
  if (analysisBatchRunning || loading) return;
  $('#load-analysis').disabled = true;
  try {
    const response = await fetch('/api/welfare/analysis-inputs');
    if (!response.headers?.get('content-type')?.includes('application/json')) throw new Error('분석 결과 수신 API가 없습니다. 최신 코드로 서버를 다시 실행해주세요.');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '분석 결과를 불러오지 못했습니다.');
    if (data.schema_version !== 'analysis-welfare-inputs-0.1' || !Array.isArray(data.entries)) throw new Error('분석 연결 응답 형식을 확인해주세요.');
    if (analysisInputs?.batch_id !== data.batch_id) { analysisResults.clear(); connectedAnalysisEntry = null; }
    analysisInputs = data;
    restoreAnalysisResults();
    $('#analysis-input-status').textContent = `${data.period} · 완료 판정 ${data.entries.length}집단 · 부분판정 ${data.priority.partial_assessments.length}집단 · 보류 ${data.priority.held_cohorts.length}집단. 전체 실시간 실행은 최대 검색 ${data.entries.length * 2}회·Gemini ${data.entries.length}회입니다. 버튼을 눌러 순서대로 실행하세요.`;
  } catch (error) {
    analysisInputs = null;
    analysisResults.clear();
    connectedAnalysisEntry = null;
    $('#analysis-input-status').textContent = error.message;
  } finally { $('#load-analysis').disabled = false; renderAnalysisInputs(); updateRetryControls(); }
}

function useAnalysisEntry(entry) {
  connectedAnalysisEntry = entry;
  const target = entry.request.target;
  $('#region').value = target.region;
  $('#age').value = String(target.age_group);
  $('#sex').value = target.sex;
  $('#purpose').value = target.purpose;
  $('#risk-input').value = JSON.stringify(entry.request.risk_assessment, null, 2);
  document.querySelectorAll('[name="support-need"]').forEach((input) => { input.checked = entry.request.confirmed_support_needs.includes(input.value); });
  filters = {region: target.region, age: target.age_group, sex: target.sex, purpose: target.purpose};
}

async function runAnalysisRecommendations() {
  if (!analysisInputs || analysisBatchRunning || loading || Date.now() < retryAvailableAt) return;
  analysisBatchRunning = true;
  analysisStopRequested = false;
  const mode = $('#search-mode').value;
  const entries = analysisInputs.entries;
  renderAnalysisInputs();
  try {
    for (let index = 0; index < entries.length; index++) {
      if (analysisStopRequested) break;
      const entry = entries[index];
      const key = `${mode}:${entry.analysis_id}`;
      if (analysisResults.get(key)?.recommendation) continue;
      $('#analysis-input-status').textContent = `${index + 1}/${entries.length}집단 추천 중 · ${entry.request.target.region} · ${sexLabel(entry.request.target.sex)}. 현재 요청 후 중지할 수 있습니다.`;
      useAnalysisEntry(entry);
      $('#search-mode').value = mode;
      const success = await queryResources();
      renderAnalysisInputs();
      if (!success) { analysisStopRequested = true; break; } // 오류·한도 초과 시 자동 재시도하지 않는다.
    }
    const done = entries.filter((entry) => analysisResults.get(`${mode}:${entry.analysis_id}`)?.recommendation).length;
    $('#analysis-input-status').textContent = `${entries.length}집단 중 ${done}집단 추천 완료${analysisStopRequested ? ' · 중지됨. 실행 버튼으로 미완료 집단만 다시 처리할 수 있습니다.' : ''} · 브라우저 저장 상태는 위 안내를 확인해주세요.`;
  } finally {
    analysisBatchRunning = false;
    renderAnalysisInputs();
  }
}

$('#load-analysis').addEventListener('click', loadAnalysisInputs);
$('#clear-analysis-storage').addEventListener('click', () => {
  if (loading || analysisBatchRunning) return;
  try {
    localStorage.removeItem(ANALYSIS_STORAGE_KEY);
    analysisResults.clear();
    recommendation = null; responseRouting = null; planningContext = null;
    resources = []; selected.clear(); errorMessage = '';
    $('#planning-prompt').value = '';
    renderResults(); renderAnalysisInputs();
    $('#analysis-storage-status').textContent = '이 브라우저의 추천 결과를 지웠습니다. 다시 실시간 조회하면 API를 호출합니다.';
  } catch {
    $('#analysis-storage-status').textContent = '저장 결과를 지우지 못했습니다. 브라우저의 사이트 데이터 설정을 확인해주세요.';
  }
});
$('#run-analysis-recommendations').addEventListener('click', runAnalysisRecommendations);
$('#stop-analysis-recommendations').addEventListener('click', () => { analysisStopRequested = true; });
function showAnalysisResult(event) {
  const button = event.target.closest('[data-analysis-index]');
  if (!button || loading || analysisBatchRunning) return;
  const entry = analysisInputs.entries[Number(button.dataset.analysisIndex)];
  useAnalysisEntry(entry);
  requestedMode = $('#search-mode').value;
  const saved = analysisResults.get(`${requestedMode}:${entry.analysis_id}`);
  recommendation = saved?.recommendation || null;
  responseRouting = saved?.responseRouting || null;
  planningContext = saved?.planningContext || null;
  errorMessage = saved?.errorMessage || '';
  resources = recommendation?.resources || [];
  purposes = recommendation?.purposes || {};
  selected.clear();
  $('#planning-prompt').value = '';
  renderResults();
}
$('#analysis-targets').addEventListener('click', showAnalysisResult);
$('#second-review-table').addEventListener('click', showAnalysisResult);
$('#download-second-review').addEventListener('click', () => {
  if (loading || analysisBatchRunning) return;
  const report = buildSecondReview();
  if (!report) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type:'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = `ieum-cohort-review-${report.period}-${report.mode}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('#search-mode').addEventListener('change', renderAnalysisInputs);
$('#filter-form').addEventListener('submit', (event) => { event.preventDefault(); if (!analysisBatchRunning) queryResources(); });

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
  $('#risk-input').value = JSON.stringify({ schema_version: 'risk-input-0.2', assessment_id: 'example-only',
    region: $('#region').value, age_group: Number($('#age').value), sex: $('#sex').value, period: '2025-12',
    status: 'complete', level: 3, model_version: 'example-model-not-production', is_example: true,
    signals: [{type:'movement_decline', description:'이동 감소 신호를 받았다고 가정한 연결 검증 예시입니다.'},
      {type:'consumption_decline', description:'소비 감소 신호를 받았다고 가정한 연결 검증 예시입니다.'}],
    limitations: ['화면 연결 확인용 가상 입력입니다. 실제 분석 결과가 아닙니다.'],
  }, null, 2);
});
$('#clear-risk-input').addEventListener('click', () => { $('#risk-input').value = ''; });
// 다른 집단으로 바꿀 때 이전 집단에서 확인한 지원 필요를 그대로 적용하지 않는다.
for (const selector of ['#region', '#age', '#sex']) {
  $(selector).addEventListener('change', () => {
    document.querySelectorAll('[name="support-need"]').forEach((input) => { input.checked = false; });
  });
}

$('#prepare-existing').addEventListener('click', () => preparePlanningRequest('existing_resource_based'));
$('#send-planning').addEventListener('click', sendPlanningRequest);
$('#load-planning-inbox').addEventListener('click', loadPlanningInbox);
$('#prepare-preventive').addEventListener('click', () => preparePlanningRequest('preventive_new'));
$('#planning-prompt').addEventListener('input', updatePlanningControls);
$('#download-planning').addEventListener('click', () => {
  if (loading || !preparedPlanningRequest) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(preparedPlanningRequest, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `ieum-planning-request-${preparedPlanningRequest.planning_type}.json`;
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
loadAnalysisInputs();
fetch('/api/welfare/status').then((response) => response.ok ? response.json() : Promise.reject()).then((status) => {
  $('#agent-status').textContent = status.configured ? `Tavily 검색 + Gemini 추천 · ${status.model}. 두 서비스의 무료 등급·한도를 유지해주세요.` : `키 설정 필요: ${[!status.tavily_configured && 'TAVILY_API_KEY', !status.gemini_configured && 'GEMINI_API_KEY'].filter(Boolean).join(', ')}. .env를 확인해주세요. 저장 자료 테스트는 키 없이 사용할 수 있습니다.`;
}).catch(() => { $('#agent-status').textContent = 'API 서버 연결을 확인해주세요. python backend/server.py로 실행합니다.'; });
