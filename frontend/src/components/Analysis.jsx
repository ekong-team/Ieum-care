import React, { useEffect, useState, useRef } from "react";
import { api, targetLabel, downloadJSON } from "../domain.js";
import { formatEvidence } from "../dashboard.js";
import {
  buildAnalysisReport,
  downloadAnalysisReport,
} from "../analysisReport.js";
import "./Analysis.css";

function ReportDialog({ html, filename, onClose }) {
  const dialog = useRef(null);
  const frame = useRef(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!dialog.current.open) dialog.current.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="analysis-report-dialog"
      onClose={onClose}
      aria-labelledby="analysis-report-title"
    >
      <div className="analysis-report-toolbar">
        <div>
          <h2 id="analysis-report-title">선택 집단 분석 보고서</h2>
          <p>
            읽기 쉬운 보고서입니다. 인쇄 창에서 ‘PDF로 저장’을 선택할 수
            있습니다.
          </p>
        </div>
        <div className="analysis-actions">
          <button
            disabled={!ready}
            onClick={() => {
              frame.current.contentWindow.focus();
              frame.current.contentWindow.print();
            }}
          >
            인쇄 / PDF 저장
          </button>
          <button
            className="secondary"
            onClick={() => downloadAnalysisReport(html, filename)}
          >
            보고서 내려받기 (HTML)
          </button>
          <button className="secondary" onClick={() => dialog.current.close()}>
            닫기
          </button>
        </div>
      </div>
      <iframe
        ref={frame}
        title="분석 보고서 미리보기"
        srcDoc={html}
        sandbox="allow-same-origin allow-modals"
        onLoad={() => setReady(true)}
      />
    </dialog>
  );
}

const reviewLabels = {
  not_run: "외부 검토 미실행",
  executed: "AI 검토 응답 확인",
  fixture_only: "시험용 응답",
  failed: "AI 검토 실패",
  rejected: "AI 응답 검증 실패",
};
const documentLabels = {
  pdf_text: "PDF 본문 추출",
  html_text: "페이지 본문 추출",
  image_only_requires_review: "이미지 PDF · 본문 미확인",
  unavailable: "본문 수집 실패 · 검색 발췌만 있음",
  deferred: "검색 발췌 · 등록된 공식 원문 수집을 우선하여 본문 미수집",
};
const stopLabels = {
  model_not_needed: "추가 검색 불필요",
  not_needed: "기존 자료로 검토",
  candidate_sources_available: "최소 출처 후보 확보",
  search_budget_exhausted: "검색 한도 도달",
  no_more_usable_sources: "추가 근거 미확보",
  auth_or_quota_limit: "인증·사용 한도로 중단",
  planning_failed: "검색 계획 검증 실패",
};

export default function Analysis({ active, model, openRecommendations }) {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState("");
  const [period, setPeriod] = useState("");
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [consent, setConsent] = useState(false);
  const [report, setReport] = useState(null);
  const busy = starting || job?.status === "running";
  const blocked = busy || model.busy || model.running;
  async function load() {
    setLoading(true);
    try {
      const result = await api("/api/analysis/result");
      if (
        result.schema_version !== "analysis-screen-0.1" ||
        !Array.isArray(result.cohorts)
      )
        throw new Error("분석 결과 형식을 확인해주세요.");
      setData(result);
      setPeriod(result.period);
      setError("");
    } catch (failure) {
      setError(failure.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    if (!active) return;
    load();
    api("/api/analysis/job")
      .then((result) => setJob(result.job))
      .catch((failure) => setError(failure.message));
  }, [active]);
  useEffect(() => {
    if (job?.status !== "running") return;
    let alive = true;
    let timer;
    const poll = async () => {
      try {
        const result = await api("/api/analysis/job");
        if (!alive) return;
        setJob(result.job);
        setError("");
        if (result.job?.status === "completed") {
          await load();
          await model.loadAnalysis();
          setConsent(false);
        } else if (result.job?.status === "running")
          timer = setTimeout(poll, 1500);
      } catch (failure) {
        if (alive) {
          setError(
            `실행 상태를 확인하지 못했습니다. 실행을 반복하지 말고 연결 상태를 확인해주세요. ${failure.message}`,
          );
          timer = setTimeout(poll, 5000);
        }
      }
    };
    timer = setTimeout(poll, 1000);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [job?.id, job?.status]);
  const cohort =
    data?.cohorts.find((c) => c.analysis_id === selected) || data?.cohorts[0];
  const receipt = data?.execution.model_receipts.find(
    (r) => r.analysis_id === cohort?.analysis_id,
  );
  const profile = cohort?.profile;
  const rank = data?.priority.ranked_cohorts.find(
    (c) => c.analysis_id === cohort?.analysis_id,
  )?.rank;
  const entry =
    model.batch?.batch_id === data?.batch_id
      ? model.batch?.entries.find((c) => c.analysis_id === cohort?.analysis_id)
      : null;
  const completed = profile?.risk.status === "complete";
  const configurationReady =
    data?.configuration.gemini_configured &&
    data?.configuration.tavily_configured;
  const reportHTML = () => buildAnalysisReport(data, cohort, receipt);
  async function start(mode) {
    if (blocked) return;
    setStarting(true);
    setError("");
    try {
      const request =
        mode === "gemini"
          ? {
              mode,
              period: data.period,
              analysis_id: cohort.analysis_id,
              allow_external: consent,
            }
          : { mode, period };
      const result = await api("/api/analysis/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      if (result.schema_version !== "analysis-job-0.1" || !result.job?.id)
        throw new Error(
          "분석 접수 응답을 확인해주세요. 실행 상태를 새로 확인하세요.",
        );
      setJob(result.job);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setStarting(false);
    }
  }
  return (
    <section
      hidden={!active}
      aria-labelledby="analysis-heading"
      className="analysis-page"
    >
      <div className="page-heading">
        <div>
          <p className="eyebrow">DATA & EVIDENCE</p>
          <h1 id="analysis-heading">데이터 분석 · 근거 검토</h1>
          <p className="subtitle">
            활동 변화의 수치 근거를 확인하고, 필요한 배경만 추가로 찾아봅니다.
          </p>
        </div>
        <button className="secondary" disabled={loading || busy} onClick={load}>
          저장된 결과 새로고침
        </button>
      </div>
      <ol className="analysis-flow" aria-label="분석에서 추천까지">
        <li>데이터 계산·검증</li>
        <li>집단별 근거 확인</li>
        <li>선택 집단 외부 검토</li>
        <li>1차 대상·복지추천</li>
      </ol>
      {error && (
        <p className="analysis-error" role="alert">
          {error}
        </p>
      )}
      {job && (
        <div
          className={`analysis-job ${job.status}`}
          role="status"
          aria-live="polite"
        >
          <strong>
            {job.status === "running"
              ? "분석 실행 중"
              : job.status === "failed"
                ? "분석 실행 실패"
                : "분석 실행 완료"}
          </strong>
          <p>{job.message}</p>
          {job.status === "running" && (
            <p>
              최대 수 분 걸릴 수 있습니다. 다른 탭으로 이동해도 서버에서 계속
              처리하며, 화면 조회는 외부 API를 추가 호출하지 않습니다.
            </p>
          )}
        </div>
      )}
      {!data ? (
        <div className="panel">
          <p>
            {loading
              ? "검증된 분석을 불러오고 있습니다."
              : "분석 결과를 불러오지 못했습니다. 입력 데이터를 준비하고 다시 확인해주세요."}
          </p>
        </div>
      ) : (
        <>
          <div className="analysis-summary" aria-label="분석 연결 상태">
            <article>
              <span>표시 기준월</span>
              <strong>{data.period}</strong>
              <small>남녀 개별 {data.cohorts.length}집단</small>
            </article>
            <article>
              <span>전체 계산 범위</span>
              <strong>{data.total_records}집단</strong>
              <small>여러 기준월·합산 비교 포함</small>
            </article>
            <article>
              <span>원본 재계산 검증</span>
              <strong>
                {data.verification.status === "passed" ? "통과" : "확인 필요"}
              </strong>
              <small>수치·집단·1차 순위 대조</small>
            </article>
          </div>
          <div className="service-notice">
            <p>
              이 단계는 <strong>활동 위축 신호의 검토 단계</strong>입니다. 고립
              확률·확정 원인·지원 자격을 뜻하지 않습니다. 외부 자료는 배경
              설명이며 단계와 1차 순위를 자동으로 바꾸지 않습니다.
            </p>
          </div>
          <div className="analysis-columns">
            <article className="panel analysis-control">
              <h2>1. 데이터 분석 실행</h2>
              <p>
                준비된 통신·카드 집계와 배경 자료로 전체 집단을 재계산합니다.
                외부 검색·AI 호출은 없습니다.
              </p>
              <label htmlFor="analysis-period">분석 기준월</label>
              <select
                id="analysis-period"
                value={period}
                disabled={blocked}
                onChange={(e) => setPeriod(e.target.value)}
              >
                {data.periods.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
              <button
                disabled={blocked || !period}
                onClick={() => start("offline")}
              >
                데이터 분석 새로 실행
              </button>
              <p className="muted">
                검증에 통과한 결과만 대시보드와 추천 입력에 반영합니다. 새
                실행은 기존 외부 검토를 덮어 합치지 않고 별도 실행으로
                기록합니다.
              </p>
            </article>
            <article className="panel analysis-control">
              <h2>2. 검토할 집단 선택</h2>
              <label htmlFor="analysis-cohort">지역 · 연령 · 성별</label>
              <select
                id="analysis-cohort"
                disabled={blocked}
                value={cohort?.analysis_id || ""}
                onChange={(e) => {
                  setSelected(e.target.value);
                  setConsent(false);
                }}
              >
                {data.cohorts.map((c) => (
                  <option value={c.analysis_id} key={c.analysis_id}>
                    {targetLabel(c.profile.target)} ·{" "}
                    {c.profile.risk.level
                      ? `${c.profile.risk.level}단계`
                      : "판정 보류"}
                  </option>
                ))}
              </select>
              {profile && (
                <p className="analysis-selected">
                  <strong>{targetLabel(profile.target)}</strong>
                  <br />
                  {completed
                    ? `${profile.risk.level}단계 · ${rank}순위`
                    : profile.risk.status === "held"
                      ? "판정 보류"
                      : "부분 판정"}{" "}
                  · {cohort.interpretation.observed}
                </p>
              )}
              <button
                className="secondary"
                disabled={!entry || blocked}
                onClick={() => openRecommendations(entry)}
              >
                이 집단 복지추천으로 이동 →
              </button>
              <p className="muted">
                1차 순위는 같은 달의 완료 집단에서 단계가 같으면 공동
                순위입니다. 이동만으로 추천을 실행하지 않습니다.
              </p>
            </article>
          </div>
          {cohort && (
            <>
              <article className="panel analysis-detail">
                <h2>관측된 변화와 원인 가설</h2>
                <dl className="analysis-evidence">
                  {profile.evidence.map((e) => (
                    <div key={e.id}>
                      <dt>{e.name}</dt>
                      <dd>{formatEvidence(e)}</dd>
                      <p>{e.description}</p>
                    </div>
                  ))}
                </dl>
                <h3>이 수치에서 생각할 수 있는 가설</h3>
                <ul>
                  {cohort.interpretation.hypotheses.map((h) => (
                    <li key={h.code}>
                      <strong>{h.label}</strong> — {h.interpretation}
                      <p>{h.questions.join(" ")}</p>
                    </li>
                  ))}
                </ul>
                {!!cohort.interpretation.contextual_observations.length && (
                  <>
                    <h3>이미 확보한 배경</h3>
                    <ul>
                      {cohort.interpretation.contextual_observations.map(
                        (t) => (
                          <li key={t}>{t}</li>
                        ),
                      )}
                    </ul>
                  </>
                )}
                <details>
                  <summary>1~5단계 기준과 관측 한계</summary>
                  <p>
                    카드 결제건수의 일평균 변화, 공통 관측 위치 유동량 변화,
                    동시 감소의 연속 비교를 사용합니다. 감소 기준{" "}
                    {Math.abs(data.method.decline_ratio * 100)}% 이상, 큰 감소
                    기준 {Math.abs(data.method.severe_ratio * 100)}% 이상입니다.
                    고립 정답으로 학습한 확률 모델이 아닙니다.
                  </p>
                  <ol>
                    <li>
                      두 지표 모두 기준 이상 감소하지 않음. 안전 확정은 아님.
                    </li>
                    <li>카드 또는 유동량 한 지표만 기준 이상 감소.</li>
                    <li>두 지표가 함께 기준 이상 감소.</li>
                    <li>
                      동시 감소가 두 번 연속 전월 비교에서 나타남. 원자료 세
                      달이 필요함.
                    </li>
                    <li>
                      4단계 조건에 더해 현재 두 지표의 큰 감소, 해석이 불분명한
                      업종을 제외한 소비의 지속 감소까지 충족.
                    </li>
                  </ol>
                  <p>
                    필수 전월 비교가 없으면 보류합니다. 상위 조건을 확인하지
                    못하면 부분 판정으로 남기고 완료된 단계와 구분합니다.
                  </p>
                  <ul>
                    {profile.limitations.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                </details>
              </article>
              <article className="panel analysis-detail">
                <h2>3. 필요한 외부 근거 검토</h2>
                <p>
                  Gemini가 추가 검색 필요성을 판단하고 Tavily로 공식 자료를
                  찾습니다. 본문을 확보한 뒤 설명에 쓸 수 있는지 검토합니다.
                </p>
                <p className="muted">
                  선택 집단 1개만 실행합니다. Gemini 최대2회·Tavily 최대3회·공식
                  문서 GET 최대4회. 원본·좌표·개인정보를 보내지 않고 집단 요약과
                  공식 발췌를 전송합니다. 무료 API의 데이터 이용 조건과 실제
                  과금 등급은 계정에서 확인해야 합니다.
                </p>
                <label className="analysis-consent">
                  <input
                    type="checkbox"
                    checked={consent}
                    disabled={blocked}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  위에 선택한 집단 요약을 Gemini·Tavily 검토에 사용하는 것을
                  확인했습니다.
                </label>
                <button
                  disabled={
                    blocked || !completed || !consent || !configurationReady
                  }
                  onClick={() => start("gemini")}
                >
                  선택 집단 검색·AI 검토 실행
                </button>
                {!configurationReady && (
                  <p role="status">
                    서버의 Gemini·Tavily 키 설정이 필요합니다. 키를 화면에
                    입력하지 마세요.
                  </p>
                )}
                {!completed && (
                  <p>
                    관측이 부족한 집단은 원본 데이터 보완이 먼저입니다. 검색으로
                    판정을 대체하지 않습니다.
                  </p>
                )}
                <div className="analysis-review">
                  <h3>
                    {reviewLabels[cohort.interpretation.model_review.status] ||
                      "검토 상태 확인 필요"}
                  </h3>
                  {!receipt ? (
                    <p>
                      이 집단은 이번 분석에서 검색·AI 검토를 실행하지
                      않았습니다. 다른 집단의 검토 결과를 재사용하지 않습니다.
                    </p>
                  ) : (
                    <>
                      <p>{receipt.research_decision?.reason}</p>
                      <p>
                        검색 {receipt.search_attempts || 0}회 · Gemini{" "}
                        {receipt.gemini_attempts || 0}회 · 문서 GET{" "}
                        {receipt.document_requests || 0}회
                      </p>
                      <p>
                        검색 종료:{" "}
                        {stopLabels[receipt.search_stop_reason] ||
                          "실행 기록 확인"}{" "}
                        · 인용 후보 {(receipt.research_findings || []).length}개
                      </p>
                      {receipt.transport === "fixture" && (
                        <p>
                          가상 응답으로 검사한 결과입니다. 실제 API 성공이
                          아닙니다.
                        </p>
                      )}
                      {!!receipt.error_code && (
                        <p className="analysis-error">
                          외부 검토 오류: {receipt.error_code}. 미실행·실패를
                          근거 확보로 해석하지 마세요.
                        </p>
                      )}
                      {!(receipt.research_findings || []).length && (
                        <p>
                          {receipt.sources.some(
                            (s) =>
                              s.scope_check?.status === "reference_candidate",
                          )
                            ? "공식 참고 후보는 확보했지만 최종 인용 검증을 통과한 설명은 없습니다. 출처 후보와 AI가 채택한 근거를 구분해주세요."
                            : "새로 인용할 외부 근거가 없습니다. 자료 부족을 원인 부재로 해석하지 않습니다."}
                        </p>
                      )}
                      {!!receipt.rejected_findings?.length && (
                        <p className="analysis-error">
                          인용 검토에서 제외:{" "}
                          {receipt.rejected_findings
                            .map(
                              (f) =>
                                `${f.source_id} · ${{ quote_not_in_excerpt: "AI의 인용 문장이 제공된 발췌와 일치하지 않음", insufficient_source_scope: "지역·기준월·주제 조건 미충족", question_source_mismatch: "질문과 출처 주제 불일치" }[f.reason] || "인용 조건 미충족"}`,
                            )
                            .join(" / ")}
                          . 해당 문장을 원인 설명에 반영하지 않았습니다.
                        </p>
                      )}
                      {(receipt.research_findings || []).map((f, i) => (
                        <blockquote key={i}>
                          <p>{f.quote}</p>
                          <footer>
                            {f.relevance} · 출처 {f.source_id} · 참고 후보이며
                            원인 확정 아님
                          </footer>
                        </blockquote>
                      ))}
                      <p>
                        AI는 기존 근거·가설을 검토하고 추가 질문을 선택합니다.
                        새로운 위험점수를 만들지 않습니다.
                      </p>
                      {!!cohort.interpretation.model_review
                        .selected_observation_ids?.length && (
                        <p>
                          AI가 선택한 수치 근거:{" "}
                          {profile.evidence
                            .filter((e) =>
                              cohort.interpretation.model_review.selected_observation_ids.includes(
                                e.id,
                              ),
                            )
                            .map((e) => e.name)
                            .join(" · ")}
                        </p>
                      )}
                      {!!cohort.interpretation.model_review
                        .selected_hypothesis_codes?.length && (
                        <p>
                          AI가 추가 확인 대상으로 선택한 가설:{" "}
                          {cohort.interpretation.hypotheses
                            .filter((h) =>
                              cohort.interpretation.model_review.selected_hypothesis_codes.includes(
                                h.code,
                              ),
                            )
                            .map((h) => h.label)
                            .join(" · ")}
                        </p>
                      )}
                      {!!cohort.interpretation.model_review.questions
                        .length && (
                        <>
                          <h4>추가로 확인할 질문</h4>
                          <ul>
                            {cohort.interpretation.model_review.questions.map(
                              (q) => (
                                <li key={q}>{q}</li>
                              ),
                            )}
                          </ul>
                        </>
                      )}
                      <div className="analysis-sources">
                        {receipt.sources.map((source) => (
                          <article key={source.id}>
                            <h4>
                              <a
                                href={source.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {source.title || "공식 출처"} ↗
                              </a>
                            </h4>
                            {source.discovery ===
                              "previously_reviewed_official_reference" && (
                              <p>
                                앞서 원문을 검토해 등록한 공식 출처를
                                재확인했습니다. 이번 검색에서 새로 발견한 자료와
                                구분합니다.
                              </p>
                            )}
                            <p>
                              {source.document
                                ? documentLabels[source.document.status]
                                : "검색 발췌"}
                              {source.document?.pages?.length
                                ? ` · PDF ${source.document.pages.join(", ")}쪽`
                                : ""}
                            </p>
                            <p>
                              {source.scope_check?.geographic_scope ===
                              "wider_region_context"
                                ? "광역 배경 · 선택 집단 수치 아님"
                                : "지역·대상 범위 별도 확인"}{" "}
                              ·{" "}
                              {source.scope_check?.status ===
                              "reference_candidate"
                                ? "최소 범위 검사 통과 · 사실 확정 아님"
                                : "해석 근거로 사용 보류"}
                            </p>
                            {!!source.scope_check?.reasons?.length && (
                              <p>{source.scope_check.reasons.join(" · ")}</p>
                            )}
                            {source.publication_after_target_period && (
                              <p>
                                기준월 이후 발표된 자료입니다. 과거 시점의
                                실시간 예측 성능 근거로 사용할 수 없습니다.
                              </p>
                            )}
                            <details>
                              <summary>제공된 발췌 보기</summary>
                              <p className="analysis-excerpt">
                                {source.snippet ||
                                  "읽을 수 있는 본문이 없습니다."}
                              </p>
                              <p>
                                표 행·열 대응은 미검증입니다. 인과관계를
                                확정하지 않습니다.
                              </p>
                            </details>
                          </article>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </article>
              <article className="panel analysis-detail">
                <h2>4. 1차 대상과 다음 단계</h2>
                <p>
                  현재 집단: {targetLabel(profile.target)} ·{" "}
                  {completed ? `${rank}순위` : "원본 관측 보완 필요"}. 복지추천
                  결과에 따른 2차 순위는 여기서 확정하지 않습니다.
                </p>
                <div className="analysis-actions">
                  <button
                    disabled={!entry || blocked}
                    onClick={() => openRecommendations(entry)}
                  >
                    복지추천에서 이어서 확인 →
                  </button>
                  <button
                    className="secondary"
                    onClick={() => setReport(reportHTML())}
                  >
                    분석 보고서 보기
                  </button>
                  <button
                    className="secondary"
                    onClick={() =>
                      downloadAnalysisReport(
                        reportHTML(),
                        `이음케어_분석보고서_${cohort.analysis_id}.html`,
                      )
                    }
                  >
                    보고서 내려받기 (HTML)
                  </button>
                </div>
                <p className="muted">
                  보고서에는 수치·단계 판단 기준·원인 가설·공식 출처·검토 한계를
                  담습니다. 내려받은 HTML 파일은 브라우저에서 열어 읽을 수
                  있습니다.
                </p>
                <details>
                  <summary>개발·연동용 데이터</summary>
                  <p className="muted">
                    다른 프로그램에 분석 결과를 전달할 때 사용하는 JSON
                    형식입니다.
                  </p>
                  <button
                    className="secondary"
                    onClick={() =>
                      downloadJSON(
                        {
                          schema_version: "analysis-review-export-0.1",
                          batch_id: data.batch_id,
                          cohort,
                          external_research: receipt || null,
                        },
                        `ieum-analysis-${cohort.analysis_id}.json`,
                      )
                    }
                  >
                    분석 결과 내려받기 (JSON)
                  </button>
                </details>
                <details>
                  <summary>실행 과정 확인</summary>
                  <ol>
                    {data.trace.map((step, i) => (
                      <li key={i}>
                        {{
                          calculate: "수치 계산",
                          describe: "관측·가설 정리",
                          research_decide: "검색 필요 판단",
                          research_search: "공식 자료 검색",
                          research_check: "출처 범위 검사",
                          interpret: "근거 해석",
                          first_priority: "1차 우선순위",
                        }[step.node] || step.node}{" "}
                        · {step.status}
                        {step.reason ? ` · ${step.reason}` : ""}
                      </li>
                    ))}
                  </ol>
                </details>
              </article>
            </>
          )}
        </>
      )}
      {report && (
        <ReportDialog
          html={report}
          filename={`이음케어_분석보고서_${cohort.analysis_id}.html`}
          onClose={() => setReport(null)}
        />
      )}
    </section>
  );
}
