import React from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Planning, { formToProfile } from "./Planning.jsx";

const response = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const plan = {
  plan_id: "P-1",
  revision: 1,
  title: "주말 동네 산책 모임",
  one_liner: "주말 공백을 채우는 소규모 모임",
  risk_causes_addressed: ["C1_mobility"],
  data_evidence: ["E1"],
  schedule: { duration_weeks: 8, sessions: 8 },
  problem_statement: "문제",
  novelty: { differs_from_existing: "다름" },
  activities: [{ name: "산책", description: "함께 걷기", frequency: "주 1회", time_slot: "토 10시" }],
  budget_items: [{ item: "간식", unit: "1인 1회", quantity: 10, unit_cost_krw: null, basis: "단가 확인 필요" }],
  kpis: [{ name: "참여율", definition: "참여/모집", data_source: "운영 기록", measurable_by_data: false }],
  trend_references: [],
  risks_and_mitigations: [],
  assumptions: [],
};
const axes = ["target_fit", "novelty", "grounding", "budget", "measurability", "feasibility"].map((axis) => ({
  axis,
  score: 10,
  available: true,
  reasons: [],
}));
const event = (seq, node, status, decision = "") => ({
  seq,
  node,
  status,
  decision,
  reasons: [],
  llm_called: false,
  external_calls: {},
  duration_ms: 100,
});
const finished = {
  run_id: "run-000000000001",
  status: "completed",
  mode: "offline",
  source: { kind: "manual" },
  officer_request: "",
  notes: [],
  target: { region: "춘천시", age_group: 20, sex: "all" },
  is_example: true,
  started_at: "2026-10-24T12:00:00+00:00",
  events: [
    event(0, "cause_analysis", "started"),
    event(1, "cause_analysis", "done", "원인 가설: C1_mobility"),
    event(2, "plan_generate", "done", "기획안 1개 생성"),
    event(3, "plan_generate", "done", "기준 미달 1개 재기획"),
  ],
  result: {
    profile: {
      source: "manual",
      target: { region: "춘천시", age_group: 20, sex: "all" },
      period: "2025-12",
      risk: { level: 3, status: "complete" },
      evidence: [{ id: "E1", name: "연령 유동량 변화", value: -0.041, unit: "ratio" }],
      limitations: [],
      is_example: true,
    },
    causes: [{ code: "C1_mobility", evidence_ids: ["E1"], questions: [] }],
    gaps: [],
    existing_resources: { status: "available", resources: [] },
    plans: [plan],
    evaluations: [{ plan_id: "P-1", axes, total: 72, passed: true, revision_requests: [] }],
    evaluations_original: [{ plan_id: "P-1", axes, total: 55, passed: false, revision_requests: [] }],
    grounding_report: { issues: [] },
    report: { status: "completed", summary: "추천 기획안 1개", recommended_plan_ids: ["P-1"], notes: [] },
    warnings: [],
  },
};

let posts;
beforeEach(() => {
  posts = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path, options = {}) => {
      if (path === "/api/planning/requests")
        return response({ schema_version: "planning-inbox-0.1", requests: [] });
      if (path === "/api/pipeline/saved") return response({ runs: [] });
      if (path === "/api/pipeline/runs" && options.method === "POST") {
        posts.push(JSON.parse(options.body));
        return response({ ...finished, status: "running", events: [], result: null }, 202);
      }
      if (path.startsWith("/api/pipeline/runs/run-000000000001")) return response(finished);
      throw new Error(`unexpected ${path}`);
    }),
  );
});

test("직접 입력 → 타임라인 → 결과 탭이 끝까지 동작한다", async () => {
  const user = userEvent.setup();
  render(<Planning active />);
  await screen.findByText(/전달함 0건 저장됨/);
  await user.click(screen.getByRole("button", { name: "예시 값 채우기" }));
  await user.click(screen.getByRole("button", { name: "이 대상으로 통합 실행" }));
  expect(posts).toHaveLength(1);
  expect(posts[0].mode).toBe("offline");
  expect(posts[0].profile.evidence.map((e) => e.id)).toEqual(["E1", "E2"]);
  expect(posts[0].profile.is_example).toBe(true);

  await screen.findByText("추천 기획안 1개", {}, { timeout: 3000 });
  expect(screen.getByText("예시 입력 · 실제 분석 결과 아님")).toBeTruthy();
  // 두 번째 기획 생성은 재기획으로 강조한다.
  expect(screen.getAllByText("재기획").length).toBe(1);
  expect(screen.getByText(/55 → 72점 통과/)).toBeTruthy();
  await user.click(screen.getByRole("tab", { name: "평가" }));
  const table = screen.getByRole("table");
  expect(within(table).getByText("72")).toBeTruthy();
  await user.click(screen.getByRole("tab", { name: "원인 분석" }));
  expect(screen.getByText(/연령 유동량 변화 -4.1%/)).toBeTruthy();
});

test("근거 값이 숫자가 아니면 실행하지 않는다", () => {
  const form = {
    region: "춘천시",
    age_group: 20,
    sex: "all",
    period: "2025-12",
    risk_status: "held",
    risk_level: 3,
    signals: [],
    evidence: [{ name: "x", value: "-8%", unit: "ratio", source: "card", related_signal: "", description: "" }],
    limitations: "",
    is_example: false,
  };
  expect(() => formToProfile(form)).toThrow(/숫자/);
  form.evidence[0].value = "-0.08";
  const profile = formToProfile(form);
  expect(profile.risk).toEqual({ status: "held", level: null, model_version: "manual-input" });
  expect(profile.evidence[0].value).toBe(-0.08);
});
