import React, { useEffect, useState } from "react";
import { pages, targetLabel } from "./domain.js";
import useWelfare from "./useWelfare.js";
import Dashboard from "./components/Dashboard.jsx";
import Analysis from "./components/Analysis.jsx";
import Planning from "./components/Planning.jsx";
import {
  AnalysisPanels,
  Filters,
  Review,
  ResourceCard,
  ResourceDialog,
  PlanningHandoff,
} from "./components/RecommendationParts.jsx";

export default function App() {
  const getPage = () =>
    Object.hasOwn(pages, location.hash.slice(1))
      ? location.hash.slice(1)
      : "dashboard";
  const [page, setPage] = useState(getPage);
  const model = useWelfare();
  const [selected, setSelected] = useState(new Set());
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    const update = () => setPage(getPage());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    document.title = `이음케어 · ${pages[page]}`;
  }, [page]);
  useEffect(() => {
    setSelected(new Set());
    setDetail(null);
  }, [model.current]);
  const result = model.current?.recommendation;
  const shownFilters = model.current?.filters || model.filters;
  const title = targetLabel({
    region: shownFilters.region,
    age_group: shownFilters.age,
    sex: shownFilters.sex,
  });
  const toggle = (id) =>
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <>
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main").focus();
        }}
      >
        본문으로 이동
      </a>
      <header className="header">
        <div className="header-inner">
          <a className="brand" href="#dashboard" aria-label="이음케어 대시보드">
            <span className="brand-mark" aria-hidden="true">
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                focusable="false"
              >
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
              </svg>
            </span>
            <span>
              <strong>이음케어</strong>
              <small>지역과 사람을 잇는 복지</small>
            </span>
          </a>
          <span className="workspace">
            <span className="status-dot" />
            담당자 워크스페이스
          </span>
        </div>
        <nav className="navigation" aria-label="주요 메뉴">
          {Object.entries(pages).map(([key, label]) => (
            <a
              key={key}
              href={`#${key}`}
              aria-current={page === key ? "page" : undefined}
            >
              {label}
            </a>
          ))}
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <section
          hidden={["recommendations", "planning", "dashboard", "analysis"].includes(page)}
          aria-label={pages[page]}
        >
          <div className="page-heading">
            <div>
              <p className="eyebrow">IEUM CARE</p>
              <h1>{pages[page]}</h1>
            </div>
          </div>
          <div className="empty-canvas" aria-label="아직 콘텐츠가 없는 화면" />
        </section>
        <div hidden={page !== "dashboard"}>
          <Dashboard
            model={model}
            openRecommendations={(entry) => {
              model.selectEntry(entry);
              location.hash = "#recommendations";
            }}
          />
        </div>
        <Planning active={page === "planning"} />
        <Analysis active={page === 'analysis'} model={model} openRecommendations={(entry) => {
          model.selectEntry(entry);
          location.hash = '#recommendations';
        }} />
        <section
          hidden={page !== "recommendations"}
          aria-labelledby="recommendation-title"
        >
          <div className="page-heading">
            <div>
              <p className="eyebrow">WELFARE CONNECTION</p>
              <h1 id="recommendation-title">필요한 지원을, 알맞은 곳으로</h1>
              <p className="subtitle">
                지역과 연령, 지원 목적에 맞는 복지자원을 살펴보고 연결하세요.
              </p>
            </div>
            <span className="page-label">복지자원 추천</span>
          </div>
          <div className="service-notice">
            <span className="notice-icon" aria-hidden="true">
              i
            </span>
            <p>
              Tavily 검색과 Gemini 판단으로 추천합니다. 무료 등급·한도를
              유지해주세요. 페이지 진입에는 검색·LLM을 실행하지 않습니다. 실제
              자격·모집 여부는 기관 확인이 필요합니다.
            </p>
          </div>
          <AnalysisPanels model={model} />
          <div className="recommendation-layout">
            <Filters model={model} />
            <div className="results-area">
              <div className="results-header">
                <div>
                  <p className="eyebrow">맞춤 자원 탐색</p>
                  <h2>{title}</h2>
                </div>
                <span className="count-badge">
                  {model.busy
                    ? "조회 중"
                    : model.current?.errorMessage
                      ? "연결 확인 필요"
                      : result
                        ? `확인 후보 ${result.resources.length}개`
                        : "조회 전"}
                </span>
              </div>
              <p className="muted">
                분석 결과와 검색 근거를 대조한 검토 후보입니다. 개인 자격·지원
                효과는 확정하지 않습니다.
              </p>
              {!model.busy && <Review result={result} />}
              <div
                className="resource-list"
                aria-live="polite"
                aria-busy={model.busy}
              >
                {model.busy ? (
                  <div className="no-results panel">
                    공식 사이트를 검색하고 AI가 분석 결과와 자원을 대조하고
                    있습니다.
                  </div>
                ) : model.current?.errorMessage ? (
                  <div className="no-results panel" role="alert">
                    <strong>자원을 불러오지 못했습니다.</strong>
                    <p>{model.current.errorMessage}</p>
                    <button
                      className="secondary"
                      disabled={model.running || model.retrySeconds > 0}
                      onClick={model.queryCurrent}
                    >
                      {model.retrySeconds > 0
                        ? `${model.retrySeconds}초 후 다시 시도`
                        : "다시 시도"}
                    </button>
                  </div>
                ) : !result ? (
                  <div className="no-results panel">
                    <strong>대상을 선택하고 추천받기를 눌러주세요.</strong>
                    <p>집단 선택만으로 외부 API를 호출하지 않습니다.</p>
                  </div>
                ) : result.resources.length ? (
                  result.resources.map((item) => (
                    <ResourceCard
                      key={item.id}
                      item={item}
                      result={result}
                      selected={selected.has(item.id)}
                      onSelect={() => toggle(item.id)}
                      onDetails={() => setDetail(item)}
                    />
                  ))
                ) : (
                  <div className="no-results panel">
                    <strong>근거를 갖춘 후보를 제시하지 못했습니다.</strong>
                    <p>
                      {result.coverage?.message ||
                        "실제 서비스 부재를 뜻하지 않으며 추가 조사가 필요합니다."}
                    </p>
                  </div>
                )}
              </div>
              <PlanningHandoff
                record={model.current}
                selected={selected}
                setSelected={setSelected}
                busy={model.busy || model.running}
              />
            </div>
          </div>
          <footer className="page-footer">
            IEUM CARE <span>한 번의 추천이, 새로운 연결의 시작이 되도록.</span>
          </footer>
        </section>
      </main>
      <ResourceDialog item={detail} close={() => setDetail(null)} />
    </>
  );
}
