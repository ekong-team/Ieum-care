import React, { useEffect, useRef, useState } from "react";
import {
  ageLabel,
  sexLabel,
  targetLabel,
  purposeLabels,
  relevanceLabels,
  buildPlanningRequest,
  buildSecondReview,
  downloadJSON,
  post,
} from "../domain.js";

export function AnalysisPanels({ model }) {
  const { batch, records, busy, running, retrySeconds } = model;
  const report = buildSecondReview(batch, records);
  const disabled = busy || running || model.analysisLoading;
  const statusLabels = {
    candidates_found: "후보 확보",
    no_candidates_found: "후보 미확보",
    unavailable: "조회 실패",
    pending: "미조회",
  };
  return (
    <>
      <section
        className="panel analysis-input-panel"
        aria-labelledby="analysis-title"
      >
        <div className="results-header">
          <h2 id="analysis-title">분석 결과 · 1차 우선 대상</h2>
          <button
            className="secondary"
            disabled={disabled}
            onClick={model.loadAnalysis}
          >
            최신 분석 불러오기
          </button>
        </div>
        <p className="muted" role="status">
          {model.analysisStatus}
        </p>
        <p className="muted" role="status">
          {model.storageStatus}
        </p>
        <button
          className="text-button"
          disabled={disabled}
          onClick={model.clearSaved}
        >
          이 브라우저의 추천 결과 지우기
        </button>
        <div className="analysis-targets">
          {batch?.entries.map((entry) => {
            const record = records.get(`live:${entry.analysis_id}`);
            return (
              <div className="analysis-target" key={entry.analysis_id}>
                <span>
                  <strong>{entry.rank}순위</strong> ·{" "}
                  {targetLabel(entry.request.target)} ·{" "}
                  {entry.request.risk_assessment.level}단계
                </span>
                <span>
                  {record
                    ? record.recommendation
                      ? `후보 ${record.recommendation.resources.length}개`
                      : "조회 실패"
                    : "추천 대기"}
                </span>
                <button
                  className="text-button"
                  disabled={disabled}
                  onClick={() => model.selectEntry(entry)}
                >
                  {record?.recommendation ? "결과 보기" : "분석 입력 보기"}
                </button>
              </div>
            );
          })}
        </div>
        <div className="planning-actions">
          <button
            className="primary"
            disabled={disabled || retrySeconds > 0 || !batch?.entries.length}
            onClick={model.runBatch}
          >
            1차 대상 순서대로 복지 추천
          </button>
          <button
            className="secondary"
            disabled={!running}
            onClick={model.stop}
          >
            현재 요청 후 중지
          </button>
        </div>
        <p className="muted">
          단계·순위는 분석 결과를 유지합니다. 전체 실행 시 집단당 검색 최대
          2회·Gemini 1회입니다. 첫 오류에서 중지하며 자동 재시도하지 않습니다.
        </p>
      </section>
      {report && (
        <section
          className="panel analysis-input-panel"
          aria-labelledby="second-title"
        >
          <div className="results-header">
            <h2 id="second-title">2차 대응 검토 · 집단별 추천 현황</h2>
            <button
              className="secondary"
              disabled={disabled}
              onClick={() =>
                downloadJSON(
                  report,
                  `ieum-cohort-review-${report.period}-live.json`,
                )
              }
            >
              검토표 JSON 내려받기
            </button>
          </div>
          <p className="muted">
            {report.completed_cohorts}/{report.total_cohorts}집단 조회 완료 ·{" "}
            {report.comparison_complete
              ? "전체 조회 완료 · 담당자 확인 필요"
              : "전체 집단 비교 미완성"}{" "}
            · 2차 순위 미확정
          </p>
          <p className="muted">
            후보 수는 실제 공급량·수용 인원·지원 효과가 아닙니다. 미조회·실패는
            후보 0개와 구분합니다.
          </p>
          <div className="review-table-wrap">
            <table className="cohort-review-table">
              <caption>1차 순위에 따른 복지 추천 결과와 다음 조치</caption>
              <thead>
                <tr>
                  <th scope="col">1차 순위·대상</th>
                  <th scope="col">추천 결과</th>
                  <th scope="col">다음 조치</th>
                  <th scope="col">상세</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row, index) => (
                  <tr key={row.analysis_id}>
                    <th scope="row">
                      {row.first_priority_rank}순위 · {targetLabel(row.target)}{" "}
                      · {row.risk_assessment.level}단계
                    </th>
                    <td>
                      {statusLabels[row.lookup_status]}
                      {row.candidate_count !== null &&
                        ` · ${row.candidate_count}개`}
                      {row.ai_direct_relevance_count !== null && (
                        <>
                          <br />
                          AI 직접 연관 {row.ai_direct_relevance_count}개
                        </>
                      )}
                    </td>
                    <td>{row.next_action}</td>
                    <td>
                      <button
                        className="text-button"
                        disabled={disabled}
                        onClick={() => model.selectEntry(batch.entries[index])}
                      >
                        보기
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

export function Filters({ model }) {
  const { filters, entry, busy, running, retrySeconds } = model;
  const disabled = busy || running || model.analysisLoading;
  return (
    <aside className="filters panel">
      <div className="section-heading">
        <span className="step-number">01</span>
        <h2>추천 대상 설정</h2>
      </div>
      <p className="muted">
        분석 집단을 선택하거나 지역·연령으로 직접 탐색하세요.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          model.queryCurrent();
        }}
      >
        <p className="muted">{model.agentStatus}</p>
        <label htmlFor="region">대상 지역</label>
        <select
          id="region"
          disabled={disabled}
          value={filters.region}
          onChange={(e) => model.changeFilter("region", e.target.value)}
        >
          <option value="춘천시">강원 춘천시</option>
          <option value="강남구">서울 강남구</option>
        </select>
        <label htmlFor="age">대상 연령</label>
        <select
          id="age"
          disabled={disabled}
          value={filters.age}
          onChange={(e) => model.changeFilter("age", Number(e.target.value))}
        >
          {[10, 20, 30, 40, 50, 60].map((age) => (
            <option key={age} value={age}>
              {ageLabel(age)}
            </option>
          ))}
        </select>
        <label htmlFor="sex">분석 대상 성별</label>
        <select
          id="sex"
          disabled={disabled}
          value={filters.sex}
          onChange={(e) => model.changeFilter("sex", e.target.value)}
        >
          {["all", "male", "female"].map((sex) => (
            <option value={sex} key={sex}>
              {sexLabel(sex)}
            </option>
          ))}
        </select>
        <label htmlFor="purpose">지원 목적</label>
        <select
          id="purpose"
          disabled={disabled}
          value={filters.purpose}
          onChange={(e) => model.changeFilter("purpose", e.target.value)}
        >
          {Object.entries(purposeLabels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <div className="context-note">
          <div>
            <strong>{entry ? "분석 결과 연결됨" : "일반 탐색"}</strong>
            <p>
              {entry
                ? `${entry.request.risk_assessment.period} · ${entry.request.risk_assessment.level}단계 · 수치·원인 맥락을 함께 전달합니다.`
                : "1차 대상에서 집단을 선택하면 분석 근거도 함께 반영합니다."}
            </p>
          </div>
        </div>
        <button
          type="submit"
          className="primary full"
          disabled={disabled || retrySeconds > 0}
        >
          {retrySeconds > 0
            ? `${retrySeconds}초 후 다시 시도`
            : "복지자원 추천받기 →"}
        </button>
      </form>
      <div className="filter-footer">
        추천은 지원 검토 자료입니다. 실제 신청 자격은 제공 기관에서 확인하세요.
      </div>
    </aside>
  );
}

function safeURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

export function SourceInfo({ item, detailed = false, cacheHit = false }) {
  const source = item.source || {};
  const note =
    source.reference_year_kind === "publication"
      ? "발행·게시 연도만 확인 · 현행 적용 기준은 별도 확인"
      : source.reference_year_status === "past_year"
        ? "과거 자료 · 현행 기준 재확인"
        : source.reference_year_status === "future_year"
          ? "향후 기준 자료 · 적용 시점 확인"
          : source.reference_year
            ? "현재 운영·모집 여부는 별도 확인"
            : "최신 자료인지 확인 필요";
  return (
    <div className="source-info">
      <a
        className="source-link"
        href={safeURL(source.url)}
        target="_blank"
        rel="noopener noreferrer"
      >
        {source.title || "공식 출처"} ↗
      </a>
      <div className="source-dates">
        <span>검색일: {source.checked_at || "미확인"}</span>
        <span>
          {source.reference_year_kind === "publication"
            ? "자료 발행·게시 연도"
            : source.reference_year_kind === "applicable"
              ? "적용 기준 연도"
              : "자료 연도(의미 미확인)"}
          : {source.reference_year || "미확인"}
        </span>
        {cacheHit && <span>검색 결과 임시 캐시 재사용</span>}
      </div>
      <p className="source-freshness">{note}</p>
      {detailed && (
        <>
          <p className="muted">
            검색 발췌문 대조 결과이며 원문 전체를 검증한 것은 아닙니다.
            <br />
            페이지 수정일: {source.page_updated_at || "미확인"}
          </p>
          {source.reference_year_evidence && (
            <blockquote className="source-evidence">
              {source.reference_year_evidence}
            </blockquote>
          )}
          {source.description_evidence && (
            <>
              <strong>지원 내용 근거</strong>
              <blockquote className="source-evidence">
                {source.description_evidence}
              </blockquote>
            </>
          )}
          {source.eligibility_evidence && (
            <>
              <strong>대상·신청 조건 근거</strong>
              <blockquote className="source-evidence">
                {source.eligibility_evidence}
              </blockquote>
            </>
          )}
          <p>{source.review_note}</p>
        </>
      )}
    </div>
  );
}

export function Review({ result }) {
  if (!result) return null;
  const risk = result.risk_assessment;
  const review = result.review;
  const exclusions = {
    source_not_grounded: "검색 출처 미일치",
    source_not_detail: "사업 상세 안내 부족",
    quote_not_grounded: "지원 내용·조건의 원문 근거 미일치",
    numeric_claim_not_grounded: "금액·조건 수치의 원문 근거 미일치",
    region_mismatch: "지역 불일치",
    closed: "종료 확인",
    purpose_mismatch: "지원 목적 불일치",
    age_mismatch: "연령 불일치",
    duplicate: "중복",
  };
  return (
    <section
      className="panel review-context"
      aria-label="추천 판단과 추가 확인 사항"
    >
      <h3>지원 필요 확인</h3>
      {!risk && (
        <p className="input-basis">
          분석 결과 없이 지역·연령·지원 목적을 기준으로 추천했습니다.
        </p>
      )}
      {review?.input_note && <p>{review.input_note}</p>}
      {review?.summary && (
        <p>
          <strong>AI 추천 판단</strong>
          <br />
          {review.summary}
        </p>
      )}
      {risk && (
        <>
          <p>
            <strong>
              {risk.is_example ? "예시 분석 포함" : "연결된 분석 결과"}
            </strong>
            <br />
            {risk.period} ·{" "}
            {targetLabel({
              region: risk.region,
              age_group: risk.age_group,
              sex: risk.sex,
            })}{" "}
            · {risk.level === null ? "단계 보류" : `${risk.level}단계`} ·{" "}
            {risk.status}
            <br />
            모델: {risk.model_version}
          </p>
          <ul>
            {risk.signals.map((signal, i) => (
              <li key={i}>{signal.description}</li>
            ))}
            {risk.limitations.map((text, i) => (
              <li key={`limit-${i}`}>관측 제한: {text}</li>
            ))}
          </ul>
        </>
      )}
      {!!review?.confirmed_support_needs?.length && (
        <p>
          담당자가 확인한 필요:{" "}
          {review.confirmed_support_needs
            .map((key) => purposeLabels[key])
            .join(" · ")}
        </p>
      )}
      {review?.suggested_purposes?.map((item, i) => (
        <p key={i}>
          <strong>확인해볼 목적: {purposeLabels[item.purpose]}</strong>
          <br />
          {item.reason}
        </p>
      ))}
      {Object.keys(result.exclusion_counts || {}).length > 0 && (
        <p>
          검토에서 제외:{" "}
          {Object.entries(result.exclusion_counts)
            .map(([key, count]) => `${exclusions[key] || key} ${count}개`)
            .join(" · ")}
        </p>
      )}
      <ul>
        {review?.questions?.map((text, i) => (
          <li key={i}>{text}</li>
        ))}
      </ul>
    </section>
  );
}

export function ResourceCard({ item, selected, onSelect, onDetails, result }) {
  return (
    <article className="resource-card panel">
      <div className="card-top">
        <div className="resource-tags">
          <span className={`category ${item.purpose}`}>
            {purposeLabels[item.purpose]}
          </span>
          {item.isolation_relevance && (
            <span className="relevance-tag">
              {relevanceLabels[item.isolation_relevance]} · AI 분류
            </span>
          )}
        </div>
        <span className="example-tag">운영 확인 필요</span>
      </div>
      <h3>{item.name}</h3>
      <p className="organization">{item.organization}</p>
      <p className="muted">
        {
          {
            overlap: "연령 범위 겹침",
            partial: "일부 연령만 해당 · 정확한 나이 확인",
            unknown: "연령 기준 미확정 · 기관 확인",
          }[item.age_match]
        }
      </p>
      <p className="resource-description">{item.description}</p>
      <div className="resource-meta">
        <span>⌖ {item.region}</span>
        <span>◷ {item.format}</span>
      </div>
      <SourceInfo item={item} cacheHit={result.search_cache_hit} />
      <div className="recommendation-reason">
        <span aria-hidden="true">✧</span>
        <p>
          <strong>추천 이유</strong>
          {item.reason}
          {item.relevance_reason && (
            <>
              <strong>고립 예방과의 연결</strong>
              {item.relevance_reason}
            </>
          )}
          <strong>신청 전 확인</strong>
          {item.match_reasons?.join(" · ")}
        </p>
      </div>
      <div className="card-bottom">
        <button className="text-button" onClick={onDetails}>
          상세 정보 ↗
        </button>
        <button
          className={`select-button ${selected ? "is-selected" : ""}`}
          aria-pressed={selected}
          onClick={onSelect}
        >
          {selected ? "✓ 선택됨" : "+ 기획 목록에 담기"}
        </button>
      </div>
    </article>
  );
}

export function ResourceDialog({ item, close }) {
  const ref = useRef(null);
  useEffect(() => {
    if (item) ref.current?.showModal();
  }, [item]);
  if (!item) return null;
  return (
    <dialog ref={ref} onClose={close} aria-labelledby="dialog-title">
      <h2 id="dialog-title">{item.name}</h2>
      <p>{item.organization}</p>
      <dl>
        {[
          ["지원 내용", item.description],
          ["대상·신청 조건", item.eligibility],
          ["운영 기간", item.schedule],
          ["확인할 사항", item.check],
          ["신청 방법", item.application_method],
        ].map(([label, text]) => (
          <React.Fragment key={label}>
            <dt>{label}</dt>
            <dd>{text}</dd>
          </React.Fragment>
        ))}
      </dl>
      <SourceInfo item={item} detailed />
      <p className="muted">
        현재 모집·예산·운영 여부는 기관 확인이 필요합니다. 검색일은 현행 요건
        검증일이 아닙니다. AI 연관성 분류는 실제 예방 효과가 검증됐다는 뜻이
        아닙니다.
      </p>
      <form method="dialog">
        <button className="secondary full">닫기</button>
      </form>
    </dialog>
  );
}

export function PlanningHandoff({ record, selected, setSelected, busy }) {
  const [prompt, setPrompt] = useState("");
  const [draft, setDraft] = useState(null);
  const [status, setStatus] = useState(
    "조회 후 기획 요청을 준비할 수 있습니다.",
  );
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setPrompt("");
    setDraft(null);
    setStatus("기획 요청을 준비해주세요.");
  }, [record]);
  useEffect(() => {
    setDraft(null);
  }, [selected, prompt]);
  const items =
    record?.recommendation?.resources.filter((item) => selected.has(item.id)) ||
    [];
  const ready = !busy && !!record?.planningContext;
  const routing = record?.responseRouting;
  function prepare(type) {
    try {
      setDraft(buildPlanningRequest(type, record, selected, prompt));
      setStatus("미리보기를 확인하고 전달함에 저장하거나 JSON을 내려받으세요.");
    } catch (error) {
      setStatus(error.message);
    }
  }
  async function send() {
    if (!draft || saving) return;
    setSaving(true);
    const sending = draft;
    try {
      const result = await post("/api/planning/requests", sending);
      if (
        result.schema_version !== "planning-inbox-0.1" ||
        result.request?.request_id !== sending.request_id ||
        result.agent_connected !== false ||
        result.status !== "awaiting_planning_agent"
      )
        throw new Error("전달함 응답을 확인해주세요.");
      setStatus(
        "기획 전달함에 저장했습니다. 실제 기획 Agent는 연결 대기 중입니다.",
      );
    } catch (error) {
      setStatus(`${error.message} 자동 재시도하지 않았습니다.`);
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="handoff panel" aria-labelledby="handoff-title">
      <h2 id="handoff-title">프로그램 기획 요청 준비</h2>
      <p className="muted">
        기존 자원 활용 또는 예방·신규 기획을 요청할 수 있습니다.
      </p>
      <p className="planning-target">
        {record?.planningContext
          ? `최근 조회 기준: ${targetLabel(record.planningContext.input.target)}`
          : "먼저 대상 집단의 복지자원을 조회해주세요."}
      </p>
      {routing && (
        <div className="planning-lookup">
          <p>
            {
              {
                candidates_found: "기존 자원 후보 확보",
                no_candidates_found: "이번 조회에서 후보 미확보",
                unavailable: "조회 미완료",
              }[routing.candidate_status]
            }
          </p>
          <p>
            후보 미확보·조회 실패는 실제 자원 부재를 뜻하지 않습니다. 예방
            기획은 자원 선택 없이 준비할 수 있습니다.
          </p>
          <details>
            <summary>기획 시 확인할 사항</summary>
            {routing.routes.map((route) => (
              <div key={route.route}>
                <strong>{route.title}</strong>
                <p>{route.reason}</p>
                <ul>
                  {route.checks.map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
                </ul>
              </div>
            ))}
            <ul>
              {routing.notes.map((text, i) => (
                <li key={i}>{text}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
      <div className="selected-resources">
        {items.length
          ? items.map((item) => (
              <button
                className="selection-chip"
                key={item.id}
                disabled={busy || saving}
                onClick={() =>
                  setSelected(
                    new Set([...selected].filter((id) => id !== item.id)),
                  )
                }
              >
                {item.name} ×
              </button>
            ))
          : "아직 선택한 자원이 없습니다."}
      </div>
      <label htmlFor="planning-prompt">
        기획 담당자에게 전달할 요청 (선택)
      </label>
      <textarea
        id="planning-prompt"
        rows={4}
        maxLength={2000}
        disabled={!ready || saving}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="예: 주 1회 소규모 모임을 기획해주세요. 이동 부담이 적으면 좋겠습니다."
      />
      <p className="muted">
        최대 2,000자. 전달함에 저장하면 담당자 요청과 분석·추천 자료가 로컬
        서버에 보관됩니다.
      </p>
      <div className="planning-actions">
        <button
          className="secondary"
          disabled={!ready || !items.length || saving}
          onClick={() => prepare("existing_resource_based")}
        >
          선택 자원 활용 기획 요청 만들기
        </button>
        <button
          className="primary"
          disabled={!ready || saving}
          onClick={() => prepare("preventive_new")}
        >
          예방·신규 기획 요청 만들기
        </button>
      </div>
      <p className="muted" role="status">
        {status}
      </p>
      {draft && (
        <div id="planning-preview">
          <p>
            {targetLabel(draft.target)} · 선택 자원{" "}
            {draft.selected_resources.length}개
          </p>
          <details>
            <summary>전달 데이터 보기</summary>
            <pre id="planning-json">{JSON.stringify(draft, null, 2)}</pre>
          </details>
        </div>
      )}
      <div className="planning-actions">
        <button
          className="primary"
          disabled={!draft || busy || saving}
          onClick={send}
        >
          {saving ? "저장 중" : "검토한 요청을 기획 전달함에 저장"}
        </button>
        <button
          className="secondary"
          disabled={!draft || busy || saving}
          onClick={() =>
            downloadJSON(
              draft,
              `ieum-planning-request-${draft.planning_type}.json`,
            )
          }
        >
          기획 요청 JSON 내려받기 ↓
        </button>
      </div>
      <p className="muted">
        실제 기획 Agent 연결 전이며 기획서는 생성하지 않습니다.{" "}
        <a className="source-link" href="#planning">
          기획 전달함 보기 →
        </a>
      </p>
    </section>
  );
}
