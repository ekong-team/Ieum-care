import React from "react";
import { expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SearchDiagnostics from "./SearchDiagnostics.jsx";
import { downloadJSON } from "../domain.js";

vi.mock("../domain.js", () => ({ downloadJSON: vi.fn() }));

const result = {
  target: { region: "춘천시", age_group: 30, sex: "female" },
  risk_assessment: { assessment_id: "sample", period: "2025-12" },
  search_stages: [{ stage: "local", query: "춘천시 성인 복지서비스", source_count: 1, detail_hint_count: 0, searched_at: "2026-10-23" }],
  diagnostics: {
    schema_version: "welfare-diagnostics-0.1", model_candidate_count: 0, server_excluded_count: 0, final_candidate_count: 0,
    sources: [{ url: "https://www.chuncheon.go.kr/sample", title: "사업 안내", source_kind: "web_page", recency_hint: "unspecified", content: "검토용 검색 발췌문", searched_at: "2026-10-23", model_review: { status: "deferred", reason: "대상 조건 자료가 부족합니다.", quote_status: "not_provided" }, server_exclusions: [] }],
  },
};

test("추천 0개의 AI 보류 이유와 실제 발췌문을 보고 외부 호출 없이 기록을 내보낸다", async () => {
  const user = userEvent.setup();
  render(<SearchDiagnostics result={result} />);
  await user.click(screen.getByText(/검색 출처·추천 보류 이유 확인/));
  expect(screen.getByText(/AI가 처음부터 후보를 제시하지 않았습니다/)).toBeTruthy();
  expect(screen.getByText("대상 조건 자료가 부족합니다.")).toBeTruthy();
  expect(screen.getByRole("link", { name: /사업 안내/ }).getAttribute("href")).toBe(result.diagnostics.sources[0].url);
  await user.click(screen.getByText("검색·본문 근거 보기"));
  expect(screen.getByText("검토용 검색 발췌문")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "검색 검토 기록 내려받기" }));
  expect(downloadJSON).toHaveBeenCalledWith(expect.objectContaining({ analysis_id: "sample", diagnostics: result.diagnostics }), "ieum-welfare-search-review.json");
});

test("이전 결과에 진단 기록이 없으면 새 이유를 만들어 표시하지 않는다", () => {
  render(<SearchDiagnostics result={{ resources: [] }} />);
  expect(screen.getByText(/이 결과에는 검색 검토 기록이 없습니다/)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

test("서버 제외와 AI 검토 사용을 구분하고 허용하지 않은 링크를 숨긴다", async () => {
  const input = structuredClone(result);
  input.diagnostics.model_candidate_count = 1;
  input.diagnostics.server_excluded_count = 1;
  input.diagnostics.sources[0].url = "javascript:alert(1)";
  input.diagnostics.sources[0].model_review = { status: "candidate_considered", reason: "조건부 검토 후보" };
  input.diagnostics.sources[0].document = { status: "html_excerpt", fetched_at: "2026-10-23", truncated: true };
  input.diagnostics.sources[0].server_exclusions = [{ name: "검토 자원", reason: "numeric_claim_not_grounded" }];
  render(<SearchDiagnostics result={input} />);
  await userEvent.click(screen.getByText(/검색 출처·추천 보류 이유 확인/));
  expect(screen.getByText(/AI 제시 1개 · 서버 제외 1개 · 최종 후보 0개/)).toBeTruthy();
  expect(screen.getByText(/서버 제외: 검토 자원 · 수치 근거 불일치/)).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.getByText(/공식 본문: HTML 본문 일부 읽음 · 수집일 2026-10-23/)).toBeTruthy();
  expect(screen.queryByText(/AI가 처음부터 후보를 제시하지 않았습니다/)).toBeNull();
});
