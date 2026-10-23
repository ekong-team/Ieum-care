import React from "react";
import { downloadJSON } from "../domain.js";

const kinds = { web_page: "웹 안내", directory: "대표·목록 화면", reference_document: "참고 문서", background_news: "성과·배경 자료" };
const recency = { current_year_mentioned: "현재 연도 언급", older_years_only: "과거 연도만 확인", future_years_only: "향후 연도 언급", unspecified: "연도 단서 없음" };
const statuses = { candidate_considered: "AI 후보 검토에 사용", deferred: "AI 보류", not_recorded: "AI 설명 기록 없음", invalid_record: "AI 설명 확인 불가" };
const documentFailures = {
  redirect_blocked: "다른 주소로 이동 응답 · 자동 추적 중단",
  redirect_not_allowed: "같은 공식 안내의 정규 주소 이동 조건 미충족",
  redirect_limit: "주소 이동 횟수 제한 도달",
  redirect_missing_location: "이동 응답에 목적지 주소 없음",
  request_limit: "본문 GET 횟수 제한 도달",
  http_error: "서버 HTTP 오류",
  timeout: "응답 시간 초과",
  tls_error: "보안 연결·인증서 오류",
  connection_failed: "네트워크 연결 실패",
  page_size_limit: "본문 크기 제한 초과",
  non_html: "HTML이 아닌 응답",
  invalid_body: "본문 응답 형식 오류",
  decode_failed: "본문 문자 해독 실패",
  unsupported_encoding: "지원하지 않는 문자 인코딩",
  insufficient_text: "추출된 본문 텍스트 부족",
  url_not_allowed: "수집 허용 URL 조건 미충족",
  page_read_failed: "분류되지 않은 본문 읽기 오류",
};
const exclusions = { source_not_grounded: "검색 출처 미일치", source_not_detail: "상세 안내 부족", quote_not_grounded: "원문 인용 불일치", numeric_claim_not_grounded: "수치 근거 불일치", region_mismatch: "지역 불일치", age_mismatch: "연령 불일치", purpose_mismatch: "지원 목적 불일치", closed: "종료 확인", duplicate: "중복" };
exclusions.application_deadline_passed = "명시된 신청 마감일 경과";

function officialLink(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && /(^|\.)(chuncheon|gangnam|bokjiro|mohw)\.go\.kr$/.test(parsed.hostname);
  } catch { return false; }
}

export default function SearchDiagnostics({ result }) {
  const data = result.diagnostics;
  if (!data) return <p className="muted">이 결과에는 검색 검토 기록이 없습니다. 이전 결과의 보류 이유를 추정하지 않습니다. 새 조회부터 기록됩니다.</p>;
  const sources = data.sources || [];
  const exportData = () => downloadJSON({
    schema_version: "welfare-review-export-0.1", target: result.target,
    analysis_id: result.risk_assessment?.assessment_id || null,
    period: result.risk_assessment?.period || null,
    model: result.model, searched_at: result.searched_at,
    decision_date: result.decision_date,
    rules_version: result.review?.rules_version,
    search_stages: result.search_stages || [], diagnostics: data,
    resources: result.resources || [],
  }, "ieum-welfare-search-review.json");
  return <details className="search-diagnostics">
    <summary>검색 출처·추천 보류 이유 확인 ({sources.length}개 자료)</summary>
    <p>AI 제시 {data.model_candidate_count}개 · 서버 제외 {data.server_excluded_count}개 · 최종 후보 {data.final_candidate_count}개</p>
    {data.model_candidate_count === 0 && <p>AI가 처음부터 후보를 제시하지 않았습니다. 실제 복지자원 부재를 뜻하지 않습니다.</p>}
    <p className="muted">AI의 설명은 검토 기록이며 사실 판정이 아닙니다. 인용 일치도 의미·개인 자격·현재 모집을 보증하지 않습니다.</p>
    <button className="secondary" onClick={exportData}>검색 검토 기록 내려받기</button>
    {(result.search_stages || []).map((stage, index) => <p key={index}>
      {stage.stage === "local" ? "지역 검색" : "중앙 보완 검색"}: {stage.query}
      <br />검색일 {stage.searched_at} · 출처 {stage.source_count}개 · 상세 단서 {stage.detail_hint_count ?? "미기록"}개
      {stage.general_guidance_hint_count !== undefined && ` · 일반 안내 단서 ${stage.general_guidance_hint_count}개`}
      {stage.cache_hit ? " · 임시 검색 캐시 사용" : ""}
    </p>)}
    {sources.map((source) => <article className="search-review-source" key={source.url}>
      <h4>{officialLink(source.url) ? <a href={source.url} target="_blank" rel="noreferrer">{source.title || "공식 출처 열기"} ↗</a> : "출처 링크 확인 필요"}</h4>
      <p className="muted">{kinds[source.source_kind] || "자료 종류 미확인"} · {recency[source.recency_hint] || "연도 단서 미기록"} · 검색일 {source.searched_at}</p>
      {source.document && <p className="muted">공식 본문: {({ html_excerpt: "HTML 본문 일부 읽음", unavailable: "읽기 실패 · 검색 발췌만 사용", not_fetched: "미수집 · 검색 발췌만 사용" })[source.document.status] || "상태 확인 필요"}{source.document.fetched_at ? ` · 수집일 ${source.document.fetched_at}` : ""}{source.document.truncated ? " · 길이 제한으로 일부만 제공" : ""}</p>}
      {!!source.document?.redirects?.length && <p className="muted">같은 공식 안내의 정규 주소로 {source.document.redirects.length}회 이동 · 이동 기록은 다운로드에 포함됩니다.</p>}
      {source.document?.status === "unavailable" && <p className="muted">수집 실패 사유: {documentFailures[source.document.reason] || "기록되지 않은 오류"}{source.document.http_status ? ` (HTTP ${source.document.http_status})` : ""}. 검색 발췌는 별도로 남아 있습니다.</p>}
      {source.application_period && <p className="muted">신청·접수 기간: {source.application_period.status === "deadline_passed" ? "명시 마감일 경과" : source.application_period.status === "deadline_not_passed" ? "명시 마감일 미경과 · 현재 접수는 별도 확인" : "명확한 신청 날짜 확인 필요"}{source.application_period.deadline ? ` (${source.application_period.deadline})` : ""}</p>}
      {source.application_period?.evidence && <blockquote className="source-evidence">{source.application_period.evidence}</blockquote>}
      <p><strong>{statuses[source.model_review?.status] || "AI 설명 기록 없음"}</strong></p>
      {source.model_review?.reason && <p>{source.model_review.reason}</p>}
      {source.model_review?.warning === "fetch_failure_is_not_evidence_absence" && <p className="input-basis">이 보류 설명은 재검토가 필요합니다. 본문 수집 실패만으로 남아 있는 검색 근거까지 없다고 판단할 수 없습니다.</p>}
      {source.model_review?.evidence_quote && <blockquote className="source-evidence">{source.model_review.evidence_quote}</blockquote>}
      {source.model_review?.quote_status === "not_provided" && <p className="muted">이유에 대한 원문 인용 없음 · 설명의 사실성은 추가 확인이 필요합니다.</p>}
      {(source.server_exclusions || []).map((item, index) => <p key={index}>서버 제외: {item.name} · {exclusions[item.reason] || "검증 조건 미충족"}</p>)}
      <details><summary>검색·본문 근거 보기</summary><p className="search-excerpt">{source.content}</p></details>
    </article>)}
  </details>;
}
