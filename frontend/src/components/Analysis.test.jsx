import React from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Analysis from "./Analysis.jsx";

const target = { region: "춘천시", age_group: 30, sex: "female" };
const cohort = {
  analysis_id: "202512_female",
  profile: {
    target,
    period: "2025-12",
    risk: { status: "complete", level: 4 },
    evidence: [
      {
        id: "E1",
        name: "카드 일평균 변화",
        value: -0.0662,
        unit: "ratio",
        description: "관측 변화",
      },
    ],
    limitations: ["집단 관측"],
  },
  interpretation: {
    observed: "동시 감소",
    hypotheses: [
      {
        code: "C3",
        label: "동반 위축",
        interpretation: "가설",
        questions: ["계절 효과 확인?"],
      },
    ],
    contextual_observations: [],
    model_review: { status: "not_run", questions: [] },
  },
};
const data = {
  schema_version: "analysis-screen-0.1",
  batch_id: "batch",
  period: "2025-12",
  periods: ["2025-11", "2025-12"],
  total_records: 216,
  cohorts: [cohort],
  method: { decline_ratio: -0.03, severe_ratio: -0.2 },
  verification: { status: "passed" },
  configuration: { gemini_configured: true, tavily_configured: true },
  execution: { model_receipts: [] },
  trace: [],
  priority: { ranked_cohorts: [{ analysis_id: cohort.analysis_id, rank: 1 }] },
};
const model = {
  batch: {
    batch_id: "batch",
    entries: [{ analysis_id: cohort.analysis_id, request: { target } }],
  },
  loadAnalysis: vi.fn(),
};
let current, posts, job;
const response = (body, ok = true) => ({
  ok,
  headers: new Headers({ "content-type": "application/json" }),
  json: async () => body,
});
beforeEach(() => {
  current = structuredClone(data);
  posts = [];
  job = null;
  model.loadAnalysis.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path, options = {}) => {
      if (path === "/api/analysis/result") return response(current);
      if (path === "/api/analysis/job")
        return response({ schema_version: "analysis-job-0.1", job });
      if (path === "/api/analysis/runs") {
        posts.push(JSON.parse(options.body));
        expect(options.headers["Content-Type"]).toBe("application/json");
        job = { id: "job1", status: "running", message: "분석 중" };
        return response({ schema_version: "analysis-job-0.1", job });
      }
      throw new Error("Unexpected endpoint");
    }),
  );
});

test("조회와 집단 이동은 과금 호출 없이 수치와 성별 입력을 보존한다", async () => {
  const open = vi.fn();
  render(<Analysis active model={model} openRecommendations={open} />);
  expect(await screen.findByText("-6.62%")).toBeTruthy();
  expect(
    screen.queryByText(/새로 인용할 외부 근거가 없습니다/),
  ).not.toBeTruthy();
  expect(
    screen.getByText(/다른 집단의 검토 결과를 재사용하지 않습니다/),
  ).toBeTruthy();
  await userEvent.click(
    screen.getByRole("button", { name: "이 집단 복지추천으로 이동 →" }),
  );
  expect(open).toHaveBeenCalledWith(model.batch.entries[0]);
  expect(posts).toHaveLength(0);
});

test("외부 전송 확인 없이는 AI 실행이 차단되고 기본 분석은 offline만 보낸다", async () => {
  render(<Analysis active model={model} openRecommendations={() => {}} />);
  await screen.findByText("-6.62%");
  expect(
    screen.getByRole("button", { name: "선택 집단 검색·AI 검토 실행" })
      .disabled,
  ).toBe(true);
  await userEvent.click(
    screen.getByRole("button", { name: "데이터 분석 새로 실행" }),
  );
  expect(posts).toEqual([{ mode: "offline", period: "2025-12" }]);
  expect(
    screen.getByRole("button", { name: "데이터 분석 새로 실행" }).disabled,
  ).toBe(true);
});

test("선택한 집단만 외부 검토하며 완료 후 추천 배치를 새로 읽는다", async () => {
  render(<Analysis active model={model} openRecommendations={() => {}} />);
  await screen.findByText("-6.62%");
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(
    screen.getByRole("button", { name: "선택 집단 검색·AI 검토 실행" }),
  );
  expect(posts[0]).toEqual({
    mode: "gemini",
    period: "2025-12",
    analysis_id: cohort.analysis_id,
    allow_external: true,
  });
  job = { ...job, status: "completed", message: "검증 완료" };
  await waitFor(() => expect(model.loadAnalysis).toHaveBeenCalledOnce(), {
    timeout: 3500,
  });
  expect(screen.getByRole("checkbox").checked).toBe(false);
});

test("실패와 이미지 PDF를 확보한 근거로 표시하지 않는다", async () => {
  current.cohorts[0].interpretation.model_review.status = "failed";
  current.execution.model_receipts = [
    {
      analysis_id: cohort.analysis_id,
      error_code: "http_429",
      search_stop_reason: "auth_or_quota_limit",
      sources: [
        {
          id: "S1",
          title: "기상 자료",
          url: "https://www.kma.go.kr/report.pdf",
          snippet: "",
          document: { status: "image_only_requires_review" },
          scope_check: { status: "discovery_only", reasons: ["본문 미확인"] },
        },
      ],
    },
  ];
  render(<Analysis active model={model} openRecommendations={() => {}} />);
  expect(await screen.findByText("AI 검토 실패")).toBeTruthy();
  expect(screen.getByText("이미지 PDF · 본문 미확인")).toBeTruthy();
  expect(screen.getByText(/새로 인용할 외부 근거가 없습니다/)).toBeTruthy();
  expect(screen.getByText(/http_429/)).toBeTruthy();
});

test("추천 배치가 다른 실행이면 이전 입력으로 이동하지 않는다", async () => {
  render(
    <Analysis
      active
      model={{ ...model, batch: { ...model.batch, batch_id: "old" } }}
      openRecommendations={() => {}}
    />,
  );
  await screen.findByText("-6.62%");
  expect(
    screen.getByRole("button", { name: "이 집단 복지추천으로 이동 →" })
      .disabled,
  ).toBe(true);
});

test("원문 확보와 AI 인용 검증 탈락을 구분해 표시한다", async () => {
  current.execution.model_receipts = [
    {
      analysis_id: cohort.analysis_id,
      selected_source_ids: ["S2"],
      research_findings: [],
      rejected_findings: [{ source_id: "S2", reason: "quote_not_in_excerpt" }],
      sources: [
        {
          id: "S2",
          title: "공식 경기 보고서",
          url: "https://www.bok.or.kr/report.pdf",
          snippet: "공식 발췌",
          discovery: "previously_reviewed_official_reference",
          document: { status: "pdf_text", pages: [1, 3] },
          scope_check: {
            status: "reference_candidate",
            geographic_scope: "wider_region_context",
          },
        },
      ],
    },
  ];
  render(<Analysis active model={model} openRecommendations={() => {}} />);
  expect(await screen.findByText(/공식 참고 후보는 확보했지만/)).toBeTruthy();
  expect(
    screen.getByText(/AI의 인용 문장이 제공된 발췌와 일치하지 않음/),
  ).toBeTruthy();
  expect(
    screen.getByText(/이번 검색에서 새로 발견한 자료와 구분합니다/),
  ).toBeTruthy();
});

test("사용자 보고서는 미리보기로 열고 JSON은 개발용 접힌 항목에 둔다", async () => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function () {
      this.setAttribute("open", "");
    },
  });
  render(<Analysis active model={model} openRecommendations={() => {}} />);
  await screen.findByText("-6.62%");
  const jsonButton = screen.getByText("분석 결과 내려받기 (JSON)");
  expect(jsonButton.closest("details").open).toBe(false);
  await userEvent.click(
    screen.getByRole("button", { name: "분석 보고서 보기" }),
  );
  expect(screen.getByRole("dialog").getAttribute("open")).not.toBe(null);
  const frame = screen.getByTitle("분석 보고서 미리보기");
  expect(frame.getAttribute("srcdoc")).toContain("춘천시 · 30대 · 여성");
  expect(frame.getAttribute("srcdoc")).toContain("-6.62%");
  expect(frame.getAttribute("sandbox")).not.toContain("allow-scripts");
  expect(posts).toHaveLength(0);
});
