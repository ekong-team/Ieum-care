import React, { useEffect, useState } from "react";
import { api, localTime, post, targetLabel } from "../domain.js";
import "./Planning.css";

// 설계 문서 7장 평가·예산 화면: 저장된 실행의 기획안을 불러와 담당자가 고치고, 같은 기준으로 다시 채점해 원안과 비교한다.
const AXIS_LABELS = {
  target_fit: "타깃 적합성",
  novelty: "신규성",
  grounding: "근거성",
  budget: "예산",
  measurability: "측정 가능성",
  feasibility: "실현 가능성",
};
const AXIS_MAX = { target_fit: 25, novelty: 20, grounding: 15, budget: 15, measurability: 10, feasibility: 15 };

const byAxis = (evaluation) => Object.fromEntries((evaluation?.axes || []).map((a) => [a.axis, a]));
const shown = (axis) => (axis ? (axis.available ? axis.score : "평가 못함") : "-");

function Comparison({ result }) {
  const after = byAxis(result.evaluation);
  const before = byAxis(result.original_evaluation);
  const original = result.original_evaluation;
  return (
    <div className="panel planning-results">
      <div className="section-heading">
        <h2>평가 결과</h2>
        <span className="muted">
          {result.mode === "live" ? "실제 평가" : "예시 평가 (실현 가능성 축 없이 100점 환산)"} · 기준 실행 {result.run_id}
        </span>
      </div>
      <div className="review-table-wrap evaluation-compare">
        <table className="score-table">
          <thead>
            <tr>
              <th>평가 축 (만점)</th>
              <th>원안</th>
              <th>담당자 기획안</th>
              <th>이유</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys(AXIS_LABELS).map((axis) => (
              <tr key={axis}>
                <th>
                  {AXIS_LABELS[axis]} ({AXIS_MAX[axis]})
                </th>
                <td>{shown(before[axis])}</td>
                <td>
                  <strong>{shown(after[axis])}</strong>
                </td>
                <td>
                  <ul className="plain-list">
                    {(after[axis]?.reasons || []).map((reason, i) => (
                      <li key={i}>{reason}</li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
            <tr>
              <th>총점</th>
              <td>{original ? `${original.total} ${original.passed ? "통과" : "미달"}` : "원안 없음"}</td>
              <td>
                <strong>{result.evaluation.total}</strong> {result.evaluation.passed ? "통과" : "미달"}
              </td>
              <td className="muted">60점 이상 통과</td>
            </tr>
          </tbody>
        </table>
      </div>
      {result.evaluation.revision_requests.length > 0 && (
        <>
          <h4>개선 요청</h4>
          <ul className="plain-list">
            {result.evaluation.revision_requests.map((request, i) => (
              <li key={i}>
                {AXIS_LABELS[request.axis]}: {request.request}
              </li>
            ))}
          </ul>
        </>
      )}
      {result.warnings.map((text, i) => (
        <p key={i} className="muted">
          주의: {text}
        </p>
      ))}
    </div>
  );
}

export default function Evaluation({ active }) {
  const [mode, setMode] = useState("offline");
  const [saved, setSaved] = useState([]);
  const [run, setRun] = useState(null);
  const [planId, setPlanId] = useState("");
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadSaved() {
    try {
      const body = await api("/api/pipeline/saved");
      setSaved((body.runs || []).filter((item) => item.status === "completed"));
    } catch {
      setSaved([]);
    }
  }
  useEffect(() => {
    if (active) loadSaved();
  }, [active]);

  function choosePlan(plans, id) {
    const plan = plans.find((item) => item.plan_id === id);
    setPlanId(id);
    setText(plan ? JSON.stringify({ ...plan, source: "manual" }, null, 2) : "");
    setResult(null);
  }

  async function openRun(runId) {
    setMessage("");
    setResult(null);
    try {
      const body = await api(`/api/pipeline/runs/${runId}`);
      setRun(body);
      const plans = body.result?.plans || [];
      choosePlan(plans, plans[0]?.plan_id || "");
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function evaluate() {
    let plan;
    try {
      plan = JSON.parse(text);
    } catch {
      setMessage("기획안 JSON 문법을 확인해주세요.");
      return;
    }
    setBusy(true);
    setMessage(mode === "live" ? "실현 가능성 축을 Gemini로 평가하는 중입니다." : "규칙 축으로 평가하는 중입니다.");
    try {
      setResult(await post("/api/program/evaluate", { mode, run_id: run.run_id, plan }));
      setMessage("평가가 끝났습니다.");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  const plans = run?.result?.plans || [];
  return (
    <section hidden={!active} aria-labelledby="evaluation-title" className="planning-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">PLAN EVALUATION</p>
          <h1 id="evaluation-title">평가 · 예산</h1>
          <p className="subtitle">
            저장된 실행의 기획안을 불러와 고친 뒤, 같은 원인·기존 자원·공백·사례 기준으로 다시 채점해 원안과 비교합니다.
          </p>
        </div>
        <span className="page-label">평가 Agent</span>
      </div>
      <div className="service-notice">
        <span className="notice-icon" aria-hidden="true">
          i
        </span>
        <p>
          점수의 85%는 공개된 규칙으로, 15%(실현 가능성)만 AI로 매깁니다. 담당자 기획안은 근거 검증 없이 형식만
          확인하므로 인용한 수치·출처는 직접 확인해주세요.
        </p>
      </div>
      <div className="planning-layout">
        <div className="panel planning-form">
          <div className="section-heading">
            <h2>1. 기준 실행 고르기</h2>
            <button type="button" className="text-button" onClick={loadSaved}>
              새로고침
            </button>
          </div>
          {saved.length ? (
            <ul className="plain-list">
              {saved.slice(0, 10).map((item) => (
                <li key={item.run_id}>
                  <button type="button" className="text-button" disabled={busy} onClick={() => openRun(item.run_id)}>
                    {targetLabel(item.target)} · {item.mode === "live" ? "실제" : "예시"} ·{" "}
                    {localTime(item.started_at)}
                  </button>
                  {run?.run_id === item.run_id && <strong> 선택됨</strong>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">완료된 실행이 없습니다. 프로그램 기획 화면에서 먼저 실행해주세요.</p>
          )}
        </div>
        <div className="panel planning-form">
          <h2>2. 기획안 고치기</h2>
          {run ? (
            <>
              <label>
                <span>불러올 기획안</span>
                <select value={planId} disabled={busy} onChange={(e) => choosePlan(plans, e.target.value)}>
                  {plans.map((plan) => (
                    <option key={plan.plan_id} value={plan.plan_id}>
                      {plan.plan_id} · {plan.title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>기획안 JSON (활동 시간대·예산 항목·KPI 등을 고친 뒤 평가합니다)</span>
                <textarea
                  className="evaluation-json"
                  rows={18}
                  spellCheck={false}
                  value={text}
                  disabled={busy}
                  onChange={(e) => setText(e.target.value)}
                />
              </label>
              <fieldset className="planning-mode">
                <legend>평가 방식</legend>
                <label>
                  <input type="radio" name="evaluation-mode" checked={mode === "offline"} onChange={() => setMode("offline")} />
                  <span>
                    <strong>규칙만</strong>
                    <small>외부 호출 없이 규칙 5축을 100점으로 환산합니다.</small>
                  </span>
                </label>
                <label>
                  <input type="radio" name="evaluation-mode" checked={mode === "live"} onChange={() => setMode("live")} />
                  <span>
                    <strong>실현 가능성 포함</strong>
                    <small>Gemini를 1회 호출합니다.</small>
                  </span>
                </label>
              </fieldset>
              <button type="button" disabled={busy || !text.trim()} onClick={evaluate}>
                {busy ? "평가 중" : "평가하기"}
              </button>
            </>
          ) : (
            <p className="muted">1번에서 기준 실행을 고르면 그 실행의 기획안을 불러옵니다.</p>
          )}
          <p className="muted" role="status">
            {message}
          </p>
        </div>
      </div>
      {result && <Comparison result={result} />}
    </section>
  );
}
