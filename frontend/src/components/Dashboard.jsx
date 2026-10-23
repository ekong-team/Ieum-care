import React, { useState } from "react";
import { ageLabel, sexLabel, targetLabel } from "../domain.js";
import {
  dashboardRows,
  summarizeDashboard,
  formatEvidence,
} from "../dashboard.js";
import "./Dashboard.css";

const ages = [10, 20, 30, 40, 50, 60];
const statusLabel = {
  complete: "완료",
  partial: "부분 판정",
  held: "판정 보류",
};
const causeLabels = {
  C0_unknown: "원인 미확정",
  C1_mobility: "외출·이동 위축",
  C2_social_consumption: "관계형 활동 감소",
  C3_overall_withdrawal: "생활 전반 위축",
  C4_prolonged: "위축 장기화",
  C5_weekend_gap: "주말 공백",
};
const cellKey = (target) =>
  `${target.region}:${target.sex}:${target.age_group}`;

export default function Dashboard({ model, openRecommendations }) {
  const [region, setRegion] = useState("*");
  const [sex, setSex] = useState("*");
  const [selectedId, setSelectedId] = useState(null);
  const rows = dashboardRows(model.batch);
  const missing = model.batch?.priority.scope?.missing_targets || [];
  const targets = [...rows.map((row) => row.target), ...missing];
  const regions = [...new Set(targets.map((target) => target.region))];
  const sexes = [...new Set(targets.map((target) => target.sex))];
  // 새 분석에 이전 필터 값이 없으면 전체 범위로 돌아가 빈 화면으로 오해하지 않게 한다.
  const activeRegion = regions.includes(region) ? region : "*";
  const activeSex = sexes.includes(sex) ? sex : "*";
  const matches = (target) =>
    (activeRegion === "*" || target.region === activeRegion) &&
    (activeSex === "*" || target.sex === activeSex);
  const filtered = rows.filter((row) => matches(row.target));
  const stats = summarizeDashboard(filtered);
  const selected =
    filtered.find((row) => row.analysis_id === selectedId) || filtered[0];
  const entry = model.batch?.entries.find(
    (item) => item.analysis_id === selected?.analysis_id,
  );
  const profile = entry?.request.analysis_context?.profile;
  const causes = entry?.request.analysis_context?.causes || [];
  const axes = [
    ...new Map(
      targets
        .filter(matches)
        .map((target) => [
          `${target.region}:${target.sex}`,
          { region: target.region, sex: target.sex },
        ]),
    ).values(),
  ];
  const lookup = new Map(filtered.map((row) => [cellKey(row.target), row]));
  const disabled = model.busy || model.running || model.analysisLoading;
  return (
    <section aria-labelledby="dashboard-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">IEUM CARE · OVERVIEW</p>
          <h1 id="dashboard-title">대시보드</h1>
          <p className="subtitle">
            지역·연령·성별 활동 위축 신호와 1차 우선 대상을 확인하세요.
          </p>
        </div>
        <div className="dashboard-period">
          <span className="muted">분석 기준월</span>
          <strong>{model.batch?.period || "연결 대기"}</strong>
          <button
            className="secondary"
            disabled={disabled}
            onClick={model.loadAnalysis}
          >
            최신 분석 불러오기
          </button>
        </div>
      </div>
      {!model.batch ? (
        <div className="panel dashboard-empty" role="status">
          <h2>
            {model.analysisLoading
              ? "분석 결과를 불러오고 있습니다."
              : "분석 결과를 연결하지 못했습니다."}
          </h2>
          <p className="muted">{model.analysisStatus}</p>
          <p className="muted">
            완료된 분석 결과를 연결한 뒤 다시 불러와주세요. 데이터가 없으면
            수치나 예시 결과를 표시하지 않습니다.
          </p>
        </div>
      ) : (
        <>
          <div className="service-notice">
            <span className="notice-icon" aria-hidden="true">
              i
            </span>
            <p>
              연결된 최신 기준월의 집단 분석입니다. 아래 수치는{" "}
              <strong>집단 수</strong>이며 인구수·고립 확률이 아닙니다. 같은
              단계는 공동 순위이고 실제 지원 자격은 별도 확인이 필요합니다.
            </p>
          </div>
          <div className="dashboard-filters panel">
            <div>
              <label htmlFor="dashboard-region">지역</label>
              <select
                id="dashboard-region"
                value={activeRegion}
                onChange={(e) => {
                  setRegion(e.target.value);
                  setSelectedId(null);
                }}
              >
                <option value="*">전체 지역</option>
                {regions.map((value) => (
                  <option value={value} key={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="dashboard-sex">분석 대상 성별</label>
              <select
                id="dashboard-sex"
                value={activeSex}
                onChange={(e) => {
                  setSex(e.target.value);
                  setSelectedId(null);
                }}
              >
                <option value="*">전체 분석 집단</option>
                {sexes.map((value) => (
                  <option value={value} key={value}>
                    {sexLabel(value)}
                  </option>
                ))}
              </select>
            </div>
            <p className="muted">
              남녀 개별 집단을 유지하며 합산 집단과 중복 집계하지 않습니다.
              <br />
              필터는 표시 범위만 바꾸고 원래 순위는 유지합니다.
            </p>
          </div>
          <div className="dashboard-stats" aria-label="분석 집단 요약">
            {[
              ["관측 집단", stats.total],
              ["판정 완료", stats.complete],
              ["4·5단계 집단", stats.upper],
              ["부분 판정", stats.partial],
              ["판정 보류", stats.held],
            ].map(([label, count]) => (
              <div className="panel dashboard-stat" key={label}>
                <span>{label}</span>
                <strong>
                  {count}
                  <small>집단</small>
                </strong>
              </div>
            ))}
          </div>
          <div className="dashboard-grid">
            <div className="dashboard-main">
              <section
                className="panel dashboard-section"
                aria-labelledby="matrix-title"
              >
                <h2 id="matrix-title">지역 × 연령 위험 현황</h2>
                <p className="muted">
                  집단을 누르면 전달된 근거와 추천 연결을 확인할 수 있습니다.
                </p>
                <div className="review-table-wrap">
                  <table className="dashboard-matrix">
                    <caption className="sr-only">
                      지역·성별·연령별 분석 단계
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">지역 · 성별</th>
                        {ages.map((age) => (
                          <th scope="col" key={age}>
                            {ageLabel(age)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {axes.map((axis) => (
                        <tr key={`${axis.region}:${axis.sex}`}>
                          <th scope="row">
                            {axis.region}
                            <small>{sexLabel(axis.sex)}</small>
                          </th>
                          {ages.map((age) => {
                            const row = lookup.get(
                              cellKey({ ...axis, age_group: age }),
                            );
                            return (
                              <td key={age}>
                                {row ? (
                                  <button
                                    aria-pressed={
                                      selected?.analysis_id === row.analysis_id
                                    }
                                    className={`risk-cell ${row.assessment_status === "complete" ? `risk-level-${row.level}` : `risk-${row.assessment_status}`}`}
                                    onClick={() =>
                                      setSelectedId(row.analysis_id)
                                    }
                                    aria-label={`${targetLabel(row.target)} · ${row.assessment_status === "complete" ? `${row.level}단계` : statusLabel[row.assessment_status]}`}
                                  >
                                    <strong>
                                      {row.assessment_status === "complete"
                                        ? `${row.level}단계`
                                        : statusLabel[row.assessment_status]}
                                    </strong>
                                    <small>
                                      {row.rank
                                        ? `${row.rank}순위`
                                        : "별도 확인"}
                                    </small>
                                  </button>
                                ) : (
                                  <span className="dashboard-missing">
                                    자료 없음
                                  </span>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="dashboard-legend">
                  {[1, 2, 3, 4, 5].map((level) => (
                    <span className={`risk-level-${level}`} key={level}>
                      {level}단계
                    </span>
                  ))}
                  <span>부분 판정·보류·미관측은 별도 표시</span>
                </div>
              </section>
              <section className="panel dashboard-section">
                <h2>완료 판정의 단계별 분포</h2>
                <p className="muted">
                  선택 범위의 완료 {stats.complete}집단 기준 · 부분 판정·보류
                  제외
                </p>
                <div className="dashboard-distribution">
                  {stats.levels.map(({ level, count }) => (
                    <div key={level}>
                      <span>{level}단계</span>
                      <div className="dashboard-bar">
                        <span
                          className={`risk-level-${level}`}
                          style={{
                            width: `${stats.complete ? (count / stats.complete) * 100 : 0}%`,
                          }}
                        />
                      </div>
                      <strong>{count}집단</strong>
                    </div>
                  ))}
                </div>
              </section>
            </div>
            <aside
              className="panel dashboard-section dashboard-detail"
              aria-labelledby="selected-title"
            >
              <p className="eyebrow">선택 집단 상세</p>
              <h2 id="selected-title">
                {selected
                  ? targetLabel(selected.target)
                  : "선택할 집단이 없습니다."}
              </h2>
              {selected && (
                <>
                  <p>
                    <span
                      className={`risk-badge ${selected.assessment_status === "complete" ? `risk-level-${selected.level}` : "risk-held"}`}
                    >
                      {selected.assessment_status === "complete"
                        ? `${selected.level}단계 · ${selected.rank}순위`
                        : statusLabel[selected.assessment_status]}
                    </span>
                  </p>
                  <p className="muted">
                    {model.batch.period} ·{" "}
                    {selected.reason ||
                      "전달된 집단 분석 결과를 기준으로 표시합니다."}
                  </p>
                  {profile?.evidence?.length > 0 && (
                    <>
                      <h3>핵심 수치 근거</h3>
                      <dl className="dashboard-evidence">
                        {profile.evidence.map((item) => (
                          <div key={item.id}>
                            <dt>{item.name}</dt>
                            <dd>{formatEvidence(item)}</dd>
                          </div>
                        ))}
                      </dl>
                    </>
                  )}
                  {entry?.request.risk_assessment.signals?.length > 0 && (
                    <ul className="muted">
                      {entry.request.risk_assessment.signals.map(
                        (signal, index) => (
                          <li key={index}>{signal.description}</li>
                        ),
                      )}
                    </ul>
                  )}
                  {causes.length > 0 && (
                    <details>
                      <summary>전달된 원인 가설</summary>
                      <p className="muted">
                        집계 신호를 해석한 가설이며 개인의 상태를 확정하지
                        않습니다.
                      </p>
                      {causes.map((cause) => (
                        <div key={cause.code}>
                          <h3>{causeLabels[cause.code] || "원인 확인 필요"}</h3>
                          {cause.explanation && (
                            <p className="muted">{cause.explanation}</p>
                          )}
                          <ul className="muted">
                            {cause.questions.map((text, index) => (
                              <li key={index}>{text}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </details>
                  )}
                  {(selected.quality_warnings?.length > 0 ||
                    profile?.limitations?.length > 0) && (
                    <details>
                      <summary>관측 한계·품질 확인</summary>
                      <ul className="muted">
                        {[
                          ...(selected.quality_warnings || []),
                          ...(profile?.limitations || []),
                        ].map((text, index) => (
                          <li key={index}>{text}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  <button
                    className="primary full"
                    disabled={disabled || !entry}
                    onClick={() => openRecommendations(entry)}
                  >
                    이 집단 복지 추천으로 이동 →
                  </button>
                  <p className="muted">
                    {entry
                      ? "이동만으로 검색·Gemini를 호출하지 않습니다. 추천 화면에서 직접 실행하세요."
                      : "부분 판정·보류 집단은 완료 판정의 1차 추천 목록에서 제외되어 추가 확인이 필요합니다."}
                  </p>
                </>
              )}
            </aside>
          </div>
          <section className="panel dashboard-section dashboard-priority">
            <h2>1차 우선 대상 목록</h2>
            <p className="muted">
              완료 판정의 원래 공동 순위 유지 · 복지자원에 따른 2차 순위는 아직
              반영하지 않았습니다.
            </p>
            <div className="review-table-wrap">
              <table className="cohort-review-table">
                <caption className="sr-only">
                  현재 표시 범위의 1차 우선 대상
                </caption>
                <thead>
                  <tr>
                    <th scope="col">원래 순위</th>
                    <th scope="col">대상 집단</th>
                    <th scope="col">단계</th>
                    <th scope="col">확인</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered
                    .filter((row) => row.assessment_status === "complete")
                    .map((row) => (
                      <tr key={row.analysis_id}>
                        <td>{row.rank}순위</td>
                        <th scope="row">{targetLabel(row.target)}</th>
                        <td>{row.level}단계</td>
                        <td>
                          <button
                            className="text-button"
                            onClick={() => setSelectedId(row.analysis_id)}
                          >
                            근거 보기
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            {!stats.complete && (
              <p className="muted">선택 범위에 완료 판정 집단이 없습니다.</p>
            )}
          </section>
          <div className="dashboard-notes muted">
            <p>
              관측 범위:{" "}
              {model.batch.priority.scope?.observed_cohorts ?? rows.length}집단
              {model.batch.priority.scope?.expected_cohorts != null &&
                ` / 예상 ${model.batch.priority.scope.expected_cohorts}집단`}{" "}
              · 누락 대상 {missing.length}집단. 현재 화면은 {model.batch.period}{" "}
              결과만 제공합니다.
            </p>
            <ul>
              {(model.batch.priority.limitations || []).map((text, index) => (
                <li key={index}>{text}</li>
              ))}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}
