import React, { useEffect, useRef, useState } from "react";
import { api, post, targetLabel } from "../domain.js";
import "./Planning.css";

// 설계 문서 7장 통합 실행 화면: 대상 입력 → 진행 타임라인 → 결과 탭 → 내보내기·다시 보기.
const NODE_LABELS = {
  cause_analysis: "원인 분석",
  welfare_recommend: "기존 자원 확인",
  trend_search: "참고 사례 검색",
  gap_analysis: "공백 분석",
  plan_generate: "기획안 생성",
  grounding_check: "근거 검증",
  evaluate: "평가",
  priority_report: "우선 지원 리포트",
};
const CAUSE_LABELS = {
  C0_unknown: "원인 미확정",
  C1_mobility: "외출·이동 위축",
  C2_social_consumption: "지역 소비 활동 위축",
  C3_overall_withdrawal: "생활 전반 위축",
  C4_prolonged: "위축 장기화",
  C5_weekend_gap: "주말 공백",
};
const AXIS_LABELS = {
  target_fit: "타깃 적합성",
  novelty: "신규성",
  grounding: "근거성",
  budget: "예산",
  measurability: "측정 가능성",
  feasibility: "실현 가능성",
};
const COVERAGE_LABELS = {
  covered: "기존 자원 있음",
  partial: "일부 공백",
  gap: "공백",
  unknown: "확인 안 됨",
};
const SIGNALS = {
  activity_decline: "소비·이동 동시 감소",
  consumption_decline: "소비 감소",
  movement_decline: "이동 감소",
};
const UNITS = { ratio: "비율", percent: "%", count: "건수", krw: "원", other: "기타" };
const SOURCES = { card: "카드", telecom: "통신", public: "공공", manual: "직접 확인", other: "기타" };
const TABS = [
  ["causes", "원인 분석"],
  ["existing", "기존 자원"],
  ["plans", "신규 기획안"],
  ["evaluation", "평가"],
  ["report", "우선 지원 리포트"],
];

const emptyEvidence = () => ({
  name: "",
  value: "",
  unit: "ratio",
  source: "card",
  related_signal: "",
  description: "",
});
const initialForm = () => ({
  region: "춘천시",
  age_group: 20,
  sex: "all",
  period: "2025-12",
  risk_status: "complete",
  risk_level: 3,
  signals: [],
  evidence: [emptyEvidence()],
  limitations: "집계 단위 신호로 개인의 고립을 뜻하지 않음",
  officer_request: "",
  is_example: false,
});
const exampleForm = () => ({
  ...initialForm(),
  signals: ["consumption_decline", "movement_decline"],
  evidence: [
    {
      name: "사회활동 관련 소비 건수 변화",
      value: "-0.083",
      unit: "ratio",
      source: "card",
      related_signal: "consumption_decline",
      description: "외식·카페·문화·운동 업종 결제 건수의 전월 대비 변화 (예시 값)",
    },
    {
      name: "연령 유동량 변화",
      value: "-0.041",
      unit: "ratio",
      source: "telecom",
      related_signal: "movement_decline",
      description: "공통 위치 기준 20대 유동량의 전월 대비 변화 (예시 값)",
    },
  ],
  limitations: "예시 입력이며 실제 분석 결과가 아님\n집계 단위 신호로 개인의 고립을 뜻하지 않음",
  is_example: true,
});

export function formToProfile(form) {
  const evidence = form.evidence
    .filter((item) => item.name.trim())
    .map((item, index) => {
      const value = Number(item.value);
      if (item.value === "" || !Number.isFinite(value))
        throw new Error(`근거 ${index + 1}의 값은 숫자여야 합니다.`);
      return {
        id: `E${index + 1}`,
        name: item.name.trim(),
        value,
        unit: item.unit,
        period: form.period,
        description: item.description.trim() || item.name.trim(),
        source: item.source,
        ...(item.related_signal ? { related_signal: item.related_signal } : {}),
      };
    });
  const risk =
    form.risk_status === "none"
      ? null
      : {
          status: form.risk_status,
          level: form.risk_status === "held" ? null : Number(form.risk_level),
          model_version: "manual-input",
        };
  return {
    schema_version: "target-profile-0.2",
    source: "manual",
    target: { region: form.region, age_group: Number(form.age_group), sex: form.sex },
    period: form.period,
    risk,
    evidence,
    signals: form.signals,
    limitations: form.limitations
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean),
    is_example: form.is_example,
  };
}

const percent = (value, unit) =>
  unit === "ratio" ? `${(value * 100).toFixed(1)}%` : `${value}${unit === "percent" ? "%" : ""}`;

function ManualForm({ disabled, onRun }) {
  const [form, setForm] = useState(initialForm);
  const [error, setError] = useState("");
  const set = (key, value) => setForm((previous) => ({ ...previous, [key]: value }));
  const setEvidence = (index, key, value) =>
    setForm((previous) => ({
      ...previous,
      evidence: previous.evidence.map((item, i) => (i === index ? { ...item, [key]: value } : item)),
    }));
  function submit(event) {
    event.preventDefault();
    try {
      setError("");
      onRun({ profile: formToProfile(form), officer_request: form.officer_request.trim() });
    } catch (problem) {
      setError(problem.message);
    }
  }
  return (
    <form className="panel planning-form" onSubmit={submit} aria-label="대상 직접 입력">
      <div className="section-heading">
        <h2>대상 직접 입력</h2>
        <button type="button" className="text-button" onClick={() => setForm(exampleForm())}>
          예시 값 채우기
        </button>
      </div>
      <div className="planning-grid">
        <label>
          지역
          <select value={form.region} onChange={(e) => set("region", e.target.value)}>
            <option>춘천시</option>
            <option>강남구</option>
          </select>
        </label>
        <label>
          연령대
          <select value={form.age_group} onChange={(e) => set("age_group", Number(e.target.value))}>
            {[10, 20, 30, 40, 50, 60].map((age) => (
              <option key={age} value={age}>
                {age === 60 ? "60대 이상" : `${age}대`}
              </option>
            ))}
          </select>
        </label>
        <label>
          성별
          <select value={form.sex} onChange={(e) => set("sex", e.target.value)}>
            <option value="all">남녀 합산</option>
            <option value="female">여성</option>
            <option value="male">남성</option>
          </select>
        </label>
        <label>
          기준월
          <input
            type="month"
            value={form.period}
            required
            onChange={(e) => set("period", e.target.value)}
          />
        </label>
        <label>
          위험 판정
          <select value={form.risk_status} onChange={(e) => set("risk_status", e.target.value)}>
            <option value="complete">판정 완료</option>
            <option value="partial">부분 판정</option>
            <option value="held">판단 보류</option>
            <option value="none">위험도 없음</option>
          </select>
        </label>
        <label>
          위험 단계
          <select
            value={form.risk_level}
            disabled={["held", "none"].includes(form.risk_status)}
            onChange={(e) => set("risk_level", Number(e.target.value))}
          >
            {[1, 2, 3, 4, 5].map((level) => (
              <option key={level} value={level}>
                {level}단계
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset className="planning-signals">
        <legend>관측 신호</legend>
        {Object.entries(SIGNALS).map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={form.signals.includes(key)}
              onChange={(e) =>
                set(
                  "signals",
                  e.target.checked ? [...form.signals, key] : form.signals.filter((s) => s !== key),
                )
              }
            />
            {label}
          </label>
        ))}
      </fieldset>
      <fieldset className="planning-evidence">
        <legend>근거 수치 (기획안은 여기 있는 수치만 인용합니다)</legend>
        {form.evidence.map((item, index) => (
          <div className="evidence-row" key={index}>
            <span className="step-number">E{index + 1}</span>
            <input
              aria-label={`근거 ${index + 1} 이름`}
              placeholder="이름 (예: 연령 유동량 변화)"
              value={item.name}
              onChange={(e) => setEvidence(index, "name", e.target.value)}
            />
            <input
              aria-label={`근거 ${index + 1} 값`}
              placeholder="값 (예: -0.041)"
              inputMode="decimal"
              value={item.value}
              onChange={(e) => setEvidence(index, "value", e.target.value)}
            />
            <select
              aria-label={`근거 ${index + 1} 단위`}
              value={item.unit}
              onChange={(e) => setEvidence(index, "unit", e.target.value)}
            >
              {Object.entries(UNITS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <select
              aria-label={`근거 ${index + 1} 출처`}
              value={item.source}
              onChange={(e) => setEvidence(index, "source", e.target.value)}
            >
              {Object.entries(SOURCES).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <select
              aria-label={`근거 ${index + 1} 관련 신호`}
              value={item.related_signal}
              onChange={(e) => setEvidence(index, "related_signal", e.target.value)}
            >
              <option value="">관련 신호 없음</option>
              {Object.entries(SIGNALS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="text-button"
              aria-label={`근거 ${index + 1} 삭제`}
              onClick={() => set("evidence", form.evidence.filter((_, i) => i !== index))}
            >
              삭제
            </button>
          </div>
        ))}
        <button
          type="button"
          className="secondary"
          disabled={form.evidence.length >= 20}
          onClick={() => set("evidence", [...form.evidence, emptyEvidence()])}
        >
          근거 추가
        </button>
      </fieldset>
      <label className="full">
        관측 제한 (한 줄에 하나)
        <textarea rows={2} value={form.limitations} onChange={(e) => set("limitations", e.target.value)} />
      </label>
      <label className="full">
        담당자 추가 요청 (선택)
        <textarea
          rows={2}
          maxLength={2000}
          placeholder="예: 평일 저녁 직장인 대상으로 검토해주세요."
          value={form.officer_request}
          onChange={(e) => set("officer_request", e.target.value)}
        />
      </label>
      <label className="planning-check">
        <input type="checkbox" checked={form.is_example} onChange={(e) => set("is_example", e.target.checked)} />
        예시 입력 (실제 분석 결과가 아님)
      </label>
      {error && (
        <p className="planning-error" role="alert">
          {error}
        </p>
      )}
      <button className="primary" disabled={disabled}>
        이 대상으로 통합 실행
      </button>
    </form>
  );
}

function Inbox({ active, disabled, onRun }) {
  const [requests, setRequests] = useState([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true);
    setStatus("전달함을 불러오고 있습니다.");
    try {
      const result = await api("/api/planning/requests");
      if (result.schema_version !== "planning-inbox-0.1" || !Array.isArray(result.requests))
        throw new Error("전달함 응답 형식을 확인해주세요.");
      setRequests(result.requests);
      setStatus(`복지 추천 전달함 ${result.requests.length}건 저장됨`);
    } catch (error) {
      setRequests([]);
      setStatus(error.message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (active) load();
  }, [active]);
  return (
    <div className="panel planning-inbox">
      <div className="section-heading">
        <h2>복지 추천 전달함</h2>
        <button type="button" className="text-button" disabled={busy} onClick={load}>
          새로고침
        </button>
      </div>
      <p className="muted" role="status">
        {status}
      </p>
      <p className="muted">추천 화면의 조회 결과를 그대로 쓰므로 복지 검색을 다시 하지 않습니다.</p>
      <div id="planning-inbox-list">
        {requests.map((item) => (
          <article className="resource-card inbox-card" key={item.request.request_id}>
            <h3>{targetLabel(item.request.target)}</h3>
            <p>
              {item.request.planning_type === "existing_resource_based" ? "기존 자원 활용" : "예방·신규 기획"} ·
              선택 자원 {item.request.selected_resources.length}개 ·{" "}
              {item.request.welfare_lookup.mode === "live" ? "실시간 추천" : "저장 자료 조회"}
              {item.request.has_example_context ? " · 예시 분석 포함" : ""}
            </p>
            <p className="muted">{item.request.officer_prompt || "담당자 추가 요청 없음"}</p>
            <button
              type="button"
              className="secondary"
              disabled={disabled}
              onClick={() => onRun({ request_id: item.request.request_id })}
            >
              이 요청으로 통합 실행
            </button>
          </article>
        ))}
      </div>
      {!busy && !requests.length && (
        <p className="muted">복지 추천 화면에서 기획 요청을 준비하고 전달함에 저장하세요.</p>
      )}
    </div>
  );
}

function Timeline({ events, running }) {
  const finished = new Set(events.filter((e) => e.status !== "started").map((e) => e.node));
  const inProgress = events.filter((e) => e.status === "started" && !finished.has(e.node));
  const rows = events.filter((e) => e.status !== "started");
  let revisionSeen = false;
  return (
    <ol className="timeline" aria-live="polite">
      {rows.map((event) => {
        const revision = event.node === "plan_generate" && revisionSeen;
        if (event.node === "plan_generate") revisionSeen = true;
        return (
          <li key={event.seq} className={`timeline-item ${event.status}${revision ? " revision" : ""}`}>
            <span className="timeline-mark" aria-hidden="true">
              {event.status === "done" ? "✓" : event.status === "failed" ? "✗" : "-"}
            </span>
            <div>
              <strong>
                {NODE_LABELS[event.node] || event.node}
                {revision && <span className="example-tag">재기획</span>}
              </strong>
              <span className="muted">
                {" "}
                {(event.duration_ms / 1000).toFixed(1)}초
                {event.llm_called ? " · LLM 호출" : ""}
                {Object.entries(event.external_calls || {})
                  .map(([name, count]) => ` · ${name} ${count}회`)
                  .join("")}
              </span>
              <p>{event.decision}</p>
              {event.reasons.filter(Boolean).length > 0 && (
                <ul>
                  {event.reasons.filter(Boolean).slice(0, 4).map((reason, i) => (
                    <li key={i}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        );
      })}
      {running &&
        inProgress.map((event) => (
          <li key={`run-${event.seq}`} className="timeline-item running">
            <span className="timeline-mark" aria-hidden="true">
              …
            </span>
            <div>
              <strong>{NODE_LABELS[event.node] || event.node}</strong>
              <p className="muted">진행 중</p>
            </div>
          </li>
        ))}
    </ol>
  );
}

function PlanCard({ plan, evaluation, recommended, before }) {
  return (
    <article className="resource-card plan-card">
      <div className="card-top">
        <span className="category">{plan.plan_id}</span>
        {plan.revision > 0 && <span className="example-tag">재기획안</span>}
        {recommended && <span className="relevance-tag">추천</span>}
        {evaluation && (
          <span className="count-badge">
            {before !== undefined ? `${before} → ` : ""}
            {evaluation.total}점 {evaluation.passed ? "통과" : "기준 미달"}
          </span>
        )}
      </div>
      <h3>{plan.title}</h3>
      <p>{plan.one_liner}</p>
      <p className="muted">
        다루는 원인: {plan.risk_causes_addressed.map((code) => CAUSE_LABELS[code] || code).join(", ")} · 인용 근거:{" "}
        {plan.data_evidence.join(", ") || "없음"} · {plan.schedule.duration_weeks}주 {plan.schedule.sessions}회
      </p>
      <details>
        <summary>기획 상세</summary>
        <h4>문제 정의</h4>
        <p>{plan.problem_statement}</p>
        <h4>기존 자원과 다른 점</h4>
        <p>{plan.novelty.differs_from_existing}</p>
        <h4>활동</h4>
        <ul>
          {plan.activities.map((activity, i) => (
            <li key={i}>
              <strong>{activity.name}</strong> ({activity.frequency}, {activity.time_slot}) — {activity.description}
            </li>
          ))}
        </ul>
        <h4>예산</h4>
        <ul>
          {plan.budget_items.map((item, i) => (
            <li key={i}>
              {item.item}: {item.quantity} {item.unit} ×{" "}
              {item.unit_cost_krw === null ? "단가 확인 필요" : `${item.unit_cost_krw.toLocaleString()}원`} ({item.basis})
            </li>
          ))}
        </ul>
        <h4>성과지표</h4>
        <ul>
          {plan.kpis.map((kpi, i) => (
            <li key={i}>
              {kpi.name}: {kpi.definition} ({kpi.data_source}
              {kpi.measurable_by_data ? ", 제공 데이터로 측정" : ""})
            </li>
          ))}
        </ul>
        {plan.trend_references.length > 0 && (
          <>
            <h4>참고 사례</h4>
            <ul>
              {plan.trend_references.map((ref, i) => (
                <li key={i}>
                  <a href={ref.url} target="_blank" rel="noreferrer noopener">
                    {ref.title}
                  </a>{" "}
                  — {ref.how_applied}
                </li>
              ))}
            </ul>
          </>
        )}
        {plan.risks_and_mitigations.length > 0 && (
          <>
            <h4>운영 위험과 대응</h4>
            <ul>
              {plan.risks_and_mitigations.map((item, i) => (
                <li key={i}>
                  {item.risk} → {item.mitigation}
                </li>
              ))}
            </ul>
          </>
        )}
        {plan.assumptions.length > 0 && (
          <>
            <h4>가정·확인 필요</h4>
            <ul>
              {plan.assumptions.map((text, i) => (
                <li key={i}>{text}</li>
              ))}
            </ul>
          </>
        )}
      </details>
    </article>
  );
}

function Results({ run }) {
  const [tab, setTab] = useState("plans");
  const result = run.result;
  if (!result) return run.error ? <p className="planning-error">{run.error}</p> : null;
  const profile = result.profile;
  const evidence = Object.fromEntries((profile.evidence || []).map((e) => [e.id, e]));
  const evaluations = Object.fromEntries((result.evaluations || []).map((e) => [e.plan_id, e]));
  const before = Object.fromEntries((result.evaluations_original || []).map((e) => [e.plan_id, e.total]));
  const report = result.report || {};
  const recommended = new Set(report.recommended_plan_ids || []);
  const existing = result.existing_resources || {};
  return (
    <div className="panel planning-results">
      <div className="result-source">
        <span className="category">{run.mode === "live" ? "실제 실행 (Gemini·Tavily)" : "예시 실행 (외부 호출 없음)"}</span>
        <span className="category">
          {profile.source === "data" ? "데이터 분석 결과" : "담당자 직접 입력"}
          {run.source?.kind === "planning_request" ? " · 복지 추천 전달함" : ""}
        </span>
        {profile.is_example && <span className="example-tag">예시 입력 · 실제 분석 결과 아님</span>}
        <span className="muted">
          {targetLabel(profile.target)} · 기준월 {profile.period}
          {profile.risk ? ` · 위험 ${profile.risk.level ?? "-"}단계 (${profile.risk.status})` : " · 위험도 없음"}
        </span>
      </div>
      <h2>{report.summary}</h2>
      {run.officer_request && <p className="muted">담당자 요청: {run.officer_request}</p>}
      <div className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={tab === key}
            className={tab === key ? "tab active" : "tab"}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "causes" && (
          <ul className="plain-list">
            {(result.causes || []).map((cause) => (
              <li key={cause.code}>
                <strong>{CAUSE_LABELS[cause.code] || cause.code}</strong> (가설)
                {cause.evidence_ids.length > 0 &&
                  ` — 근거: ${cause.evidence_ids
                    .map((id) => (evidence[id] ? `${evidence[id].name} ${percent(evidence[id].value, evidence[id].unit)}` : id))
                    .join(", ")}`}
                {cause.explanation && <p>{cause.explanation}</p>}
                {cause.questions.length > 0 && (
                  <ul>
                    {cause.questions.map((q, i) => (
                      <li key={i}>확인: {q}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
            <li className="muted">
              공백 분석:{" "}
              {(result.gaps || [])
                .map((gap) => `${CAUSE_LABELS[gap.cause] || gap.cause} ${COVERAGE_LABELS[gap.coverage]}`)
                .join(" · ") || "없음"}
            </li>
          </ul>
        )}
        {tab === "existing" &&
          (existing.status === "available" ? (
            existing.resources.length ? (
              <ul className="plain-list">
                {existing.resources.map((resource) => (
                  <li key={resource.id}>
                    <strong>{resource.name}</strong> {resource.organization && `· ${resource.organization}`}
                    <p className="muted">{resource.purpose}</p>
                    {resource.source_url && (
                      <a href={resource.source_url} target="_blank" rel="noreferrer noopener">
                        출처
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p>이번 조회에서 기존 자원 후보를 확보하지 못했습니다. 실제 자원 부재를 뜻하지 않습니다.</p>
            )
          ) : (
            <p>기존 자원 확인 불가: {existing.reason}</p>
          ))}
        {tab === "plans" && (
          <div className="resource-list">
            {(result.plans || []).map((plan) => (
              <PlanCard
                key={plan.plan_id}
                plan={plan}
                evaluation={evaluations[plan.plan_id]}
                recommended={recommended.has(plan.plan_id)}
                before={plan.revision ? before[plan.plan_id] : undefined}
              />
            ))}
            {!(result.plans || []).length && <p>근거 검증을 통과한 기획안이 없습니다.</p>}
            {(result.grounding_report?.issues || []).length > 0 && (
              <details>
                <summary>근거 검증에서 걸러진 항목 {result.grounding_report.issues.length}건</summary>
                <ul>
                  {result.grounding_report.issues.map((issue, i) => (
                    <li key={i}>
                      {issue.plan_id}: {issue.detail} ({issue.action === "excluded" ? "기획안 제외" : issue.action === "removed_item" ? "항목 삭제" : "주의"})
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
        {tab === "evaluation" && (
          <div className="review-table-wrap">
            <table className="score-table">
              <thead>
                <tr>
                  <th>기획안</th>
                  {Object.values(AXIS_LABELS).map((label) => (
                    <th key={label}>{label}</th>
                  ))}
                  <th>총점</th>
                </tr>
              </thead>
              <tbody>
                {(result.evaluations || []).map((evaluation) => {
                  const axes = Object.fromEntries(evaluation.axes.map((a) => [a.axis, a]));
                  return (
                    <tr key={evaluation.plan_id}>
                      <th>{evaluation.plan_id}</th>
                      {Object.keys(AXIS_LABELS).map((axis) => (
                        <td key={axis} title={axes[axis]?.reasons.join("\n")}>
                          {axes[axis]?.available ? axes[axis].score : "평가 못함"}
                        </td>
                      ))}
                      <td>
                        {before[evaluation.plan_id] !== undefined && `${before[evaluation.plan_id]} → `}
                        <strong>{evaluation.total}</strong> {evaluation.passed ? "통과" : "미달"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {(result.evaluations || []).some((e) => e.revision_requests.length) && (
              <ul className="plain-list">
                {(result.evaluations || []).flatMap((e) =>
                  e.revision_requests.map((r, i) => (
                    <li key={`${e.plan_id}-${i}`}>
                      {e.plan_id} {AXIS_LABELS[r.axis]}: {r.request}
                    </li>
                  )),
                )}
              </ul>
            )}
          </div>
        )}
        {tab === "report" && (
          <ul className="plain-list">
            <li>
              <strong>추천 기획안:</strong> {[...recommended].join(", ") || "없음"}
            </li>
            {(report.notes || []).map((note, i) => (
              <li key={`n${i}`}>{note}</li>
            ))}
            {(run.notes || []).map((note, i) => (
              <li key={`r${i}`}>{note}</li>
            ))}
            {(result.warnings || []).map((text, i) => (
              <li key={`w${i}`} className="muted">
                주의: {text}
              </li>
            ))}
            {(profile.limitations || []).map((text, i) => (
              <li key={`l${i}`} className="muted">
                관측 제한: {text}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function Planning({ active }) {
  const [mode, setMode] = useState("offline");
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState([]);
  const [starting, setStarting] = useState(false);
  const lastSeq = useRef(-1);
  const running = starting || run?.status === "running";

  async function loadSaved() {
    try {
      const result = await api("/api/pipeline/saved");
      setSaved(Array.isArray(result.runs) ? result.runs : []);
    } catch {
      setSaved([]);
    }
  }
  useEffect(() => {
    if (active) loadSaved();
  }, [active]);

  useEffect(() => {
    if (run?.status !== "running") return undefined;
    let stopped = false;
    let pending = false;
    const timer = setInterval(async () => {
      if (pending || stopped) return; // 이전 조회가 끝나기 전에는 다시 묻지 않는다
      pending = true;
      try {
        const next = await api(`/api/pipeline/runs/${run.run_id}?after_seq=${lastSeq.current}`);
        if (stopped) return;
        if (next.events.length) {
          lastSeq.current = next.events[next.events.length - 1].seq;
          setEvents((previous) => [...previous, ...next.events]);
        }
        if (next.status !== "running") {
          setRun(next);
          setMessage(next.status === "completed" ? "통합 실행이 끝났습니다." : "통합 실행이 실패했습니다.");
          loadSaved();
        }
      } catch (error) {
        setMessage(error.message);
      } finally {
        pending = false;
      }
    }, 1000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [run?.run_id, run?.status]);

  async function start(input) {
    if (running) return;
    setStarting(true);
    setMessage("통합 실행을 시작합니다.");
    setEvents([]);
    lastSeq.current = -1;
    try {
      const started = await post("/api/pipeline/runs", { mode, ...input });
      setRun(started);
      setMessage(
        mode === "live"
          ? "실행 중입니다. Gemini·Tavily를 호출하므로 1~3분 걸릴 수 있습니다."
          : "예시 실행 중입니다. 외부 호출은 하지 않습니다.",
      );
    } catch (error) {
      setMessage(error.message);
    } finally {
      setStarting(false);
    }
  }

  async function openSaved(runId) {
    try {
      const result = await api(`/api/pipeline/runs/${runId}`);
      lastSeq.current = result.events.length ? result.events[result.events.length - 1].seq : -1;
      setEvents(result.events);
      setRun(result);
      setMessage("저장된 실행 결과를 불러왔습니다.");
    } catch (error) {
      setMessage(error.message);
    }
  }

  function download() {
    const blob = new Blob([JSON.stringify(run, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${run.run_id}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <section hidden={!active} aria-labelledby="planning-title" className="planning-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">PROGRAM PLANNING</p>
          <h1 id="planning-title">프로그램 기획 · 통합 실행</h1>
          <p className="subtitle">
            원인 분석부터 기존 자원 확인, 신규 기획, 근거 검증, 평가·재기획, 우선 지원 리포트까지 한 번에 실행합니다.
          </p>
        </div>
        <span className="page-label">기획 Agent</span>
      </div>
      <div className="service-notice">
        <span className="notice-icon" aria-hidden="true">
          i
        </span>
        <p>
          기획안은 담당자 검토용 초안입니다. 근거에 없는 수치·출처는 근거 검증에서 걸러지고, 60점 미만 기획안은 한 번
          재기획합니다. 개인 자격·효과는 확정하지 않습니다.
        </p>
      </div>
      <fieldset className="panel planning-mode">
        <legend>실행 방식</legend>
        <label>
          <input type="radio" name="planning-mode" checked={mode === "offline"} onChange={() => setMode("offline")} />
          예시 실행 (외부 호출 없음, 시연·리허설용)
        </label>
        <label>
          <input type="radio" name="planning-mode" checked={mode === "live"} onChange={() => setMode("live")} />
          실제 실행 (Gemini·Tavily, 무료 한도 사용)
        </label>
      </fieldset>
      <div className="planning-layout">
        <ManualForm disabled={running} onRun={start} />
        <div className="planning-side">
          <Inbox active={active} disabled={running} onRun={start} />
          <div className="panel planning-saved">
            <div className="section-heading">
              <h2>저장된 실행</h2>
              <button type="button" className="text-button" onClick={loadSaved}>
                새로고침
              </button>
            </div>
            {saved.length ? (
              <ul className="plain-list">
                {saved.slice(0, 10).map((item) => (
                  <li key={item.run_id}>
                    <button type="button" className="text-button" disabled={running} onClick={() => openSaved(item.run_id)}>
                      {targetLabel(item.target)} · {item.mode === "live" ? "실제" : "예시"} ·{" "}
                      {item.started_at.slice(0, 16).replace("T", " ")}
                    </button>
                    <span className="muted"> {item.summary}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">아직 저장된 실행이 없습니다.</p>
            )}
          </div>
        </div>
      </div>
      {(run || message) && (
        <div className="panel planning-run">
          <div className="section-heading">
            <h2>진행 타임라인</h2>
            {run && run.status !== "running" && (
              <span className="planning-actions">
                <button type="button" className="secondary" onClick={download}>
                  결과 JSON 내려받기
                </button>
                <button type="button" className="secondary" onClick={() => window.print()}>
                  인쇄
                </button>
              </span>
            )}
          </div>
          <p className="muted" role="status">
            {message}
          </p>
          <Timeline events={events} running={run?.status === "running"} />
        </div>
      )}
      {run && run.status !== "running" && <Results key={run.run_id} run={run} />}
    </section>
  );
}
