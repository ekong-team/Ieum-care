import React from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Evaluation from "./Evaluation.jsx";

const response = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const target = { region: "춘천시", age_group: 60, sex: "male" };
const plan = { plan_id: "P-1", source: "generated", title: "주말 산책 모임", target };
const evaluation = (total, measurability) => ({
  plan_id: "P-1",
  total,
  passed: total >= 60,
  llm_axis_available: false,
  revision_requests: measurability < 5 ? [{ axis: "measurability", request: "과정 지표를 추가하세요." }] : [],
  axes: ["target_fit", "novelty", "grounding", "budget", "measurability", "feasibility"].map((axis) => ({
    axis,
    score: axis === "measurability" ? measurability : axis === "feasibility" ? 0 : 10,
    available: axis !== "feasibility",
    reasons: axis === "measurability" ? ["과정 KPI 0개"] : [],
  })),
});
const saved = {
  runs: [{ run_id: "run-aaaaaaaaaaaa", status: "completed", mode: "offline", target, started_at: "2026-10-26T10:00:00" }],
};
const run = { run_id: "run-aaaaaaaaaaaa", status: "completed", result: { plans: [plan], evaluations: [evaluation(70, 10)] } };

beforeEach(() => {
  vi.restoreAllMocks();
});

test("저장된 실행의 기획안을 manual로 불러와 평가하고 원안과 축별로 비교한다", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (path, options) => {
    if (path === "/api/pipeline/saved") return response(saved);
    if (path === "/api/pipeline/runs/run-aaaaaaaaaaaa") return response(run);
    if (path === "/api/program/evaluate") {
      const body = JSON.parse(options.body);
      expect(body).toMatchObject({ mode: "offline", run_id: "run-aaaaaaaaaaaa", plan: { plan_id: "P-1", source: "manual" } });
      return response({
        run_id: body.run_id,
        mode: "offline",
        plan: body.plan,
        evaluation: evaluation(58.8, 0),
        original_evaluation: evaluation(70, 10),
        external_calls: {},
        warnings: [],
      });
    }
    throw new Error(`unexpected ${path}`);
  });
  const user = userEvent.setup();
  render(<Evaluation active />);

  await user.click(await screen.findByRole("button", { name: /춘천시/ }));
  const editor = await screen.findByRole("textbox", { name: /기획안 JSON/ });
  expect(JSON.parse(editor.value).source).toBe("manual");

  await user.click(screen.getByRole("button", { name: "평가하기" }));
  expect(await screen.findByText("평가가 끝났습니다.")).toBeTruthy();
  expect(screen.getByText("70 통과")).toBeTruthy();
  expect(screen.getByText("58.8")).toBeTruthy();
  expect(screen.getByText("측정 가능성: 과정 지표를 추가하세요.")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

test("JSON 문법이 틀리면 서버에 보내지 않는다", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (path) =>
    path === "/api/pipeline/saved" ? response(saved) : response(run),
  );
  const user = userEvent.setup();
  render(<Evaluation active />);
  await user.click(await screen.findByRole("button", { name: /춘천시/ }));
  const editor = await screen.findByRole("textbox", { name: /기획안 JSON/ });
  await user.clear(editor);
  await user.type(editor, "{{");
  await user.click(screen.getByRole("button", { name: "평가하기" }));
  expect(await screen.findByText("기획안 JSON 문법을 확인해주세요.")).toBeTruthy();
  expect(fetchMock.mock.calls.some(([path]) => path === "/api/program/evaluate")).toBe(false);
});
