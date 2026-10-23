// 화면과 같은 검증 결과로 독립 실행 가능한 보고서를 만든다. 외부 요청은 없다.
import { targetLabel } from "./domain.js";
import { formatEvidence } from "./dashboard.js";

const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const list = (values) =>
  `<ul>${values.map((value) => `<li>${escape(value)}</li>`).join("")}</ul>`;
const paragraph = (value) => `<p>${escape(value)}</p>`;
const reviewLabels = {
  not_run: "외부 검토 미실행",
  executed: "AI 응답 확인",
  fixture_only: "가상 응답 시험",
  failed: "AI 검토 실패",
};
const documentLabels = {
  pdf_text: "PDF 텍스트 추출",
  html_text: "페이지 본문 추출",
  image_only_requires_review: "이미지 PDF · 본문 미확인",
  unavailable: "본문 수집 실패",
  deferred: "본문 수집 보류 · 검색 발췌만 제공",
};
const rejectionLabels = {
  quote_not_in_excerpt: "AI 인용 문장이 제공된 발췌와 일치하지 않음",
  insufficient_source_scope: "지역·기준월·주제 조건 미충족",
  question_source_mismatch: "질문과 출처 주제 불일치",
};

export function buildAnalysisReport(data, cohort, receipt) {
  if (
    !data ||
    !cohort ||
    !data.cohorts.some((c) => c.analysis_id === cohort.analysis_id) ||
    (receipt && receipt.analysis_id !== cohort.analysis_id)
  )
    throw new Error("같은 실행·집단의 분석 결과가 필요합니다.");
  const profile = cohort.profile;
  const complete = profile.risk.status === "complete";
  const rank = data.priority.ranked_cohorts.find(
    (c) => c.analysis_id === cohort.analysis_id,
  )?.rank;
  const findings = receipt?.research_findings || [];
  const sources = receipt?.sources || [];
  const title = `${profile.period} ${targetLabel(profile.target)} 분석 보고서`;
  const evidence = profile.evidence
    .map(
      (e) =>
        `<tr><th>${escape(e.name)}</th><td class="number">${escape(formatEvidence(e))}</td><td>${escape(e.description)}</td></tr>`,
    )
    .join("");
  const hypotheses = cohort.interpretation.hypotheses
    .map(
      (h) =>
        `<article><h3>${escape(h.label)}</h3>${paragraph(h.interpretation)}${list(h.questions || [])}</article>`,
    )
    .join("");
  const sourceCards = sources
    .map((source) => {
      let url;
      try {
        const parsed = new URL(source.url);
        if (
          parsed.protocol === "https:" &&
          !parsed.username &&
          !parsed.password
        )
          url = parsed.href;
      } catch {}
      return `<article><h3>${escape(source.id)} · ${escape(source.title || "출처 제목 미확인")}</h3>
      ${paragraph(source.document ? documentLabels[source.document.status] || "수집 상태 확인 필요" : "검색 발췌만 제공")}
      ${source.document?.pages?.length ? paragraph(`PDF ${source.document.pages.join(", ")}쪽`) : ""}
      ${paragraph(source.scope_check?.status === "reference_candidate" ? "최소 범위 검사 통과 · 최종 사실 검증을 뜻하지 않음" : "해석 근거로 사용 보류")}
      ${source.scope_check?.geographic_scope === "wider_region_context" ? paragraph("광역 배경자료입니다. 선택한 지역·성별·연령의 수치가 아닙니다.") : ""}
      ${source.discovery === "previously_reviewed_official_reference" ? paragraph("앞서 검토해 등록한 공식 출처를 재확인했습니다. 이번 검색에서 새로 발견한 자료와 구분합니다.") : ""}
      ${source.publication_after_target_period ? paragraph("분석 기준월 이후 발표된 자료입니다. 과거 실시간 판단의 근거로 해석하지 마세요.") : ""}
      ${list(source.scope_check?.reasons || [])}
      ${url ? `<a href="${escape(url)}" rel="noreferrer">공식 출처 열기</a><p class="url">${escape(url)}</p>` : paragraph("사용할 수 있는 공식 출처 주소가 없습니다.")}
      <details><summary>제공된 발췌</summary>${paragraph(source.snippet || "읽을 수 있는 본문이 없습니다.")}</details></article>`;
    })
    .join("");
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
    <title>${escape(title)}</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f2f5f2;color:#243b30;font:15px/1.85 'Malgun Gothic','Apple SD Gothic Neo',sans-serif}
    main{max-width:960px;margin:32px auto;background:white;padding:44px;border:1px solid #dce5dd;border-radius:16px}
    header{border-bottom:3px solid #28634b;padding-bottom:24px}h1{font-size:28px;line-height:1.5;margin:8px 0}h2{font-size:21px;margin:32px 0 14px}h3{font-size:16px;margin:0 0 8px}
    p{margin:8px 0;overflow-wrap:anywhere}.eyebrow{letter-spacing:.12em;color:#537865;font-size:12px}.muted,small{color:#617468}section{margin-top:26px}
    .metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:24px}.metrics div,article{background:#f6f8f5;border:1px solid #dce5dd;border-radius:10px;padding:18px;margin:12px 0}
    .metrics strong{display:block;font-size:25px;color:#1e5a40}.notice{border-left:4px solid #719582;background:#f0f5f0;padding:16px;margin:20px 0}.warning{border-color:#aa694c;background:#fff7ef}
    table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:12px;text-align:left;border-bottom:1px solid #dce5dd;vertical-align:top;overflow-wrap:anywhere}th{width:30%}.number{font-weight:bold;font-size:19px;white-space:nowrap}
    a{color:#176442}.url,.metadata{font-size:11px;overflow-wrap:anywhere}details{margin-top:12px}details p{white-space:pre-wrap}summary{cursor:pointer}ul,ol{padding-left:24px}.print-tip{font-size:12px;color:#617468}
    @media(max-width:640px){main{margin:0;padding:24px 18px;border:0;border-radius:0}h1{font-size:23px}.metrics{grid-template-columns:1fr}table,tbody,tr,th,td{display:block}th{width:auto}td{border:0}tr{padding:10px 0;border-bottom:1px solid #dce5dd}}
    @page{size:A4;margin:16mm}@media print{body{background:white;font-size:11pt}main{border:0;margin:0;padding:0;max-width:none}.print-tip{display:none}.metrics{display:flex}.metrics div{flex:1}h2,h3{break-after:avoid}tr,.metrics,article{break-inside:avoid}a{color:inherit}details{display:none}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
    </style></head><body><main><header><p class="eyebrow">IEUM CARE · ANALYSIS REPORT</p><h1>${escape(title)}</h1>
    <p class="muted">통신·카드 집계에서 관측된 활동 위축 신호와 추가 확인 사항</p><p class="print-tip">브라우저에서 열어 읽을 수 있습니다. 인쇄 메뉴에서 PDF로 저장할 수 있습니다. 접힌 발췌는 화면에서 펼쳐 확인하세요.</p></header>
    <div class="metrics"><div>분석 기준월<strong>${escape(profile.period)}</strong></div><div>활동 위축 검토<strong>${escape(complete ? `${profile.risk.level}단계` : profile.risk.status === "held" ? "판정 보류" : `부분 판정 (${profile.risk.level}단계 하한)`)}</strong></div><div>1차 우선 검토<strong>${escape(complete && rank != null ? `${rank}순위` : "순위 산정 제외")}</strong></div></div>
    <div class="notice">사회적 고립 확정·개인의 고립 확률·지원 자격을 뜻하지 않습니다. 같은 단계는 공동 순위이며 외부 배경자료는 위험 단계와 1차 순위를 자동으로 바꾸지 않습니다.</div>
    <section><h2>1. 무엇이 관측됐나요?</h2>${paragraph(cohort.interpretation.observed)}<table><thead><tr><th>분석 지표</th><th>결과</th><th>의미와 한계</th></tr></thead><tbody>${evidence}</tbody></table></section>
    <section><h2>2. 왜 이 단계인가요?</h2><p>감소 기준은 ${escape(Math.abs(data.method.decline_ratio * 100))}% 이상, 큰 감소 기준은 ${escape(Math.abs(data.method.severe_ratio * 100))}% 이상입니다. 기준값은 설계 가정이며 실제 고립 정답으로 검증된 확률 기준이 아닙니다.</p><ol><li>두 지표 모두 기준 이상 감소하지 않음. 안전 확정은 아님.</li><li>카드 또는 유동량 한 지표만 기준 이상 감소.</li><li>두 지표가 함께 기준 이상 감소.</li><li>동시 감소가 두 번 연속 전월 비교에서 나타남. 원자료 세 달이 필요함.</li><li>4단계에 더해 현재 두 지표의 큰 감소와 해석이 불분명한 업종을 제외한 소비의 지속 감소까지 충족.</li></ol><p>필수 전월 비교가 없으면 보류하고, 상위 조건을 확인하지 못하면 부분 판정으로 남깁니다.</p></section>
    <section><h2>3. 어떤 원인 가설을 확인해야 하나요?</h2>${hypotheses || paragraph("확정할 수 있는 원인 가설이 없습니다.")}
    <h3>이미 확보한 배경</h3>${list(cohort.interpretation.contextual_observations || [])}</section>
    <section><h2>4. 외부 검색과 AI는 무엇을 했나요?</h2>${paragraph(reviewLabels[cohort.interpretation.model_review.status] || "검토 상태 확인 필요")}
    ${
      receipt
        ? `${paragraph(receipt.research_decision?.reason || "검색 판단 설명 미제공")}<p>이 집단의 검색 ${escape(receipt.search_attempts || 0)}회 · Gemini ${escape(receipt.gemini_attempts || 0)}회 · 문서 GET ${escape(receipt.document_requests || 0)}회 · 최종 인용 후보 ${findings.length}개</p>
    ${receipt.transport === "fixture" ? paragraph("가상 응답 시험입니다. 실제 API 성공이 아닙니다.") : ""}
    ${findings.map((f) => `<article><h3>참고 후보 · ${escape(f.source_id)}</h3>${paragraph(f.quote)}${paragraph(f.relevance)}<small>관련성 해석이며 인과관계 확정이 아닙니다.</small></article>`).join("")}
    ${!findings.length ? `<div class="notice warning">${sources.some((s) => s.scope_check?.status === "reference_candidate") ? "공식 참고 후보는 확보했지만 최종 인용 검증을 통과한 설명은 없습니다." : "새로 인용할 외부 근거를 확보하지 못했습니다."} 자료 부족을 원인 부재로 해석하지 않습니다.</div>` : ""}
    ${list((receipt.rejected_findings || []).map((f) => `${f.source_id}: ${rejectionLabels[f.reason] || "인용 조건 미충족"} · 설명에 반영하지 않음`))}
    ${receipt.error_code ? paragraph(`외부 검토 오류: ${receipt.error_code}`) : ""}${sourceCards}`
        : paragraph(
            "이 집단은 이번 실행에서 외부 검색·AI 검토를 수행하지 않았습니다. 다른 집단의 검토 결과를 가져오지 않습니다.",
          )
    }
    <h3>추가로 확인할 질문</h3>${list(cohort.interpretation.model_review.questions || [])}</section>
    <section><h2>5. 다음에 무엇을 해야 하나요?</h2>${paragraph(complete ? `같은 기준월의 1차 검토 ${rank}순위로 복지추천 입력에 연결합니다.` : "원본 관측과 비교 이력을 보완한 뒤 판정을 다시 확인해야 합니다.")}
    <p>복지추천에서는 실제 자격·운영 기간·신청 방법을 추가 확인해야 합니다. 추천 후 자원 부족을 고려한 최종 2차 순위는 이 보고서에서 확정하지 않습니다.</p></section>
    <section><h2>6. 해석할 때 지켜야 할 한계</h2>${list(profile.limitations)}<p>표 행·열 대응과 인과관계는 자동 검증한 것이 아닙니다. 광역 통계와 전월비·전년비, 금액·건수의 단위를 구분해야 합니다.</p></section>
    <footer class="metadata"><hr><p>출력 범위: 선택 집단 1개 · 전체 계산 ${escape(data.total_records)}집단 · 현재 기준월 남녀 ${escape(data.cohorts.length)}집단 · 원본 재계산 검증 ${data.verification.status === "passed" ? "통과" : "확인 필요"}</p><p>분석 결과 식별자: ${escape(data.batch_id)}<br>집단 식별자: ${escape(cohort.analysis_id)}</p></footer></main></body></html>`;
}

export function downloadAnalysisReport(html, filename) {
  const url = URL.createObjectURL(
    new Blob([html], { type: "text/html;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
