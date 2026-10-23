import React from "react";
import { expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "./Dashboard.jsx";
import {
  summarizeDashboard,
  formatEvidence,
  dashboardRows,
} from "../dashboard.js";

const complete = {
  analysis_id: "complete",
  target: { region: "춘천시", age_group: 30, sex: "female" },
  level: 4,
  rank: 1,
  assessment_status: "complete",
  quality_warnings: [],
};
const partial = {
  analysis_id: "partial",
  target: { region: "춘천시", age_group: 30, sex: "male" },
  level: 5,
  assessment_status: "partial",
  quality_warnings: ["비교 불완전"],
};
const held = {
  analysis_id: "held",
  target: { region: "강남구", age_group: 60, sex: "female" },
  level: null,
  assessment_status: "held",
  quality_warnings: [],
};
const batch = {
  period: "2025-12",
  entries: [
    {
      analysis_id: "complete",
      request: {
        target: complete.target,
        risk_assessment: { signals: [] },
        analysis_context: {
          profile: {
            evidence: [
              {
                id: "E1",
                name: "소비 전월 변화율",
                value: -0.0662,
                unit: "ratio",
              },
            ],
            limitations: [],
          },
          causes: [],
        },
      },
    },
  ],
  priority: {
    ranked_cohorts: [complete],
    partial_assessments: [partial],
    held_cohorts: [held],
    scope: {
      observed_cohorts: 3,
      expected_cohorts: 4,
      missing_targets: [{ region: "강남구", age_group: 60, sex: "male" }],
    },
  },
};
const model = {
  batch,
  analysisLoading: false,
  busy: false,
  running: false,
  analysisStatus: "완료",
  loadAnalysis: vi.fn(),
};

test("완료만 단계 분포·4~5단계 집단에 집계하고 부분·보류는 유지한다", () => {
  const rows = dashboardRows(batch);
  const summary = summarizeDashboard(rows);
  expect(summary).toMatchObject({
    total: 3,
    complete: 1,
    partial: 1,
    held: 1,
    upper: 1,
  });
  expect(summary.levels.map((item) => item.count)).toEqual([0, 0, 0, 1, 0]);
  expect(rows[1].level).toBe(5);
  expect(rows[2].level).toBeNull();
  expect(formatEvidence({ value: -0.0662, unit: "ratio" })).toBe("-6.62%");
  expect(formatEvidence({ value: -6.62, unit: "percent" })).toBe("-6.62%");
  expect(formatEvidence({ value: 2, unit: "count" })).toBe("2");
});

test("지역·성별 필터는 표시만 바꾸고 부분 판정을 낮은 단계로 바꾸지 않는다", async () => {
  const user = userEvent.setup();
  render(<Dashboard model={model} openRecommendations={vi.fn()} />);
  expect(screen.getByText("소비 전월 변화율")).toBeTruthy();
  expect(screen.getByText("-6.62%")).toBeTruthy();
  await user.selectOptions(screen.getByLabelText("분석 대상 성별"), "male");
  expect(
    screen.queryByRole("button", { name: "춘천시 · 30대 · 여성 · 4단계" }),
  ).toBeNull();
  expect(
    screen.getByRole("button", { name: "춘천시 · 30대 · 남성 · 부분 판정" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "이 집단 복지 추천으로 이동 →" })
      .disabled,
  ).toBe(true);
  expect(
    screen.getByText("선택 범위에 완료 판정 집단이 없습니다."),
  ).toBeTruthy();
});

test("완료 집단의 추천 연결에 원래 입력을 전달한다", async () => {
  const user = userEvent.setup();
  const open = vi.fn();
  render(<Dashboard model={model} openRecommendations={open} />);
  await user.click(
    screen.getByRole("button", { name: "이 집단 복지 추천으로 이동 →" }),
  );
  expect(open).toHaveBeenCalledWith(batch.entries[0]);
});

test("데이터가 없을 때 예시 수치나 위험 표를 표시하지 않는다", () => {
  render(
    <Dashboard
      model={{ ...model, batch: null, analysisStatus: "분석 파일 없음" }}
      openRecommendations={vi.fn()}
    />,
  );
  expect(screen.getByText("분석 결과를 연결하지 못했습니다.")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByText("관측 집단")).toBeNull();
});
