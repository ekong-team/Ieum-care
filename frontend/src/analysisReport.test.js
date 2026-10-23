import { expect, test } from "vitest";
import { buildAnalysisReport } from "./analysisReport.js";

function fixture() {
  const cohort = {
    analysis_id: "female",
    profile: {
      target: { region: "춘천시", age_group: 30, sex: "female" },
      period: "2025-12",
      risk: { status: "complete", level: 4 },
      evidence: [
        {
          name: "카드 일평균 변화",
          value: -0.0662,
          unit: "ratio",
          description: "집단 관측",
        },
      ],
      limitations: ["개인 진단 불가"],
    },
    interpretation: {
      observed: "두 번 연속 동시 감소",
      hypotheses: [
        {
          label: "동반 위축",
          interpretation: "가설이며 원인 미확정",
          questions: ["계절 배경은?"],
        },
      ],
      contextual_observations: [],
      model_review: { status: "executed", questions: ["추가 확인?"] },
    },
  };
  const data = {
    cohorts: [cohort],
    method: { decline_ratio: 0.03, severe_ratio: 0.05 },
    priority: { ranked_cohorts: [{ analysis_id: "female", rank: 1 }] },
    total_records: 216,
    verification: { status: "passed" },
    batch_id: "same-batch",
  };
  return { cohort, data };
}

test("보고서가 한국어 대상·수치·판정 기준·순위·출처를 읽을 수 있는 형태로 담는다", () => {
  const { data, cohort } = fixture();
  const doc = new DOMParser().parseFromString(
    buildAnalysisReport(data, cohort, null),
    "text/html",
  );
  expect(doc.title).toContain("춘천시 · 30대 · 여성");
  expect(doc.querySelector("table").textContent).toContain("-6.62%");
  expect(doc.body.textContent).toContain("4단계");
  expect(doc.body.textContent).toContain("1순위");
  expect(doc.body.textContent).toContain(
    "이번 실행에서 외부 검색·AI 검토를 수행하지 않았습니다",
  );
  expect(doc.body.textContent).toContain(
    "최종 2차 순위는 이 보고서에서 확정하지 않습니다",
  );
});

test("자료 확보와 AI 인용 탈락을 구분하고 실제 인용0개를 보존한다", () => {
  const { data, cohort } = fixture();
  const receipt = {
    analysis_id: "female",
    research_findings: [],
    rejected_findings: [{ source_id: "S2", reason: "quote_not_in_excerpt" }],
    sources: [
      {
        id: "S2",
        url: "https://www.bok.or.kr/report.pdf",
        title: "공식 보고서",
        document: { status: "pdf_text", pages: [1, 3] },
        scope_check: {
          status: "reference_candidate",
          geographic_scope: "wider_region_context",
        },
        publication_after_target_period: true,
      },
    ],
  };
  const html = buildAnalysisReport(data, cohort, receipt);
  expect(html).toContain("최종 인용 후보 0개");
  expect(html).toContain("공식 참고 후보는 확보했지만");
  expect(html).toContain("AI 인용 문장이 제공된 발췌와 일치하지 않음");
  expect(html).toContain("광역 배경자료");
  expect(html).toContain("분석 기준월 이후 발표된 자료");
});

test("모델·출처에 HTML 지시가 있어도 실행 가능한 태그나 URL을 만들지 않는다", () => {
  const { data, cohort } = fixture();
  cohort.interpretation.observed = "<script>alert(1)</script>";
  const receipt = {
    analysis_id: "female",
    sources: [
      {
        id: "S1",
        title: "<img src=x onerror=alert(1)>",
        url: "javascript:alert(1)",
        snippet: "<iframe src=x>",
      },
    ],
  };
  const doc = new DOMParser().parseFromString(
    buildAnalysisReport(data, cohort, receipt),
    "text/html",
  );
  expect(doc.querySelectorAll("script,img,iframe").length).toBe(0);
  expect(doc.querySelectorAll("a").length).toBe(0);
  expect(doc.body.textContent).toContain("<script>alert(1)</script>");
  expect(
    doc.querySelector('meta[http-equiv="Content-Security-Policy"]').content,
  ).toContain("default-src 'none'");
});

test("다른 집단의 외부 검토는 섞지 않고 부분 판정을 완료 단계로 표시하지 않는다", () => {
  const { data, cohort } = fixture();
  expect(() =>
    buildAnalysisReport(data, cohort, { analysis_id: "male" }),
  ).toThrow();
  cohort.profile.risk.status = "partial";
  data.priority.ranked_cohorts = [];
  const html = buildAnalysisReport(data, cohort, null);
  expect(html).toContain("부분 판정 (4단계 하한)");
  expect(html).toContain("순위 산정 제외");
});
