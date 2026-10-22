import React from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App.jsx";
import { STORAGE_KEY } from "./domain.js";

const entries = ["female", "male"].map((sex, index) => ({
  analysis_id: sex,
  rank: index + 1,
  request: {
    target: { region: "춘천시", age_group: 30, sex, purpose: "all" },
    confirmed_support_needs: [],
    risk_assessment: {
      schema_version: "risk-input-0.2",
      assessment_id: sex,
      region: "춘천시",
      age_group: 30,
      sex,
      period: "2025-12",
      status: "complete",
      level: 4,
      model_version: "test",
      is_example: false,
      signals: [],
      limitations: ["집단 관측"],
    },
    analysis_context: {
      profile: {
        target: { region: "춘천시", age_group: 30, sex },
        is_example: false,
      },
      causes: [],
    },
  },
}));
const batch = {
  schema_version: "analysis-welfare-inputs-0.1",
  batch_id: "batch-1",
  period: "2025-12",
  entries,
  priority: { partial_assessments: [], held_cohorts: [] },
};
const resource = {
  id: "R1",
  name: "관계 형성 모임",
  purpose: "connection",
  organization: "춘천시",
  age_match: "overlap",
  description: "주 1회 모임",
  region: "춘천시",
  format: "대면",
  reason: "사회 참여 기회",
  match_reasons: ["운영 확인"],
  isolation_relevance: "direct",
  source: {
    url: "https://www.chuncheon.go.kr/",
    title: "공식 안내",
    checked_at: "2026-10-22",
  },
};
const routing = (status) => ({
  schema_version: "response-routing-0.1",
  candidate_status: status,
  routes: [],
  notes: [],
});
const response = (data, ok = true) => ({
  ok,
  headers: new Headers({ "content-type": "application/json" }),
  json: async () => data,
});
const resultFor = (input, resources = []) => ({
  schema_version: "welfare-0.4",
  is_demo: false,
  mode: "live",
  target: input.target,
  risk_assessment: input.risk_assessment,
  analysis_context: input.analysis_context,
  resources,
  total: resources.length,
  review: {
    confirmed_support_needs: [],
    suggested_purposes: [],
    questions: [],
    summary: "근거 대조",
  },
  response_routing: routing(
    resources.length ? "candidates_found" : "no_candidates_found",
  ),
});

let posts, inbox, recommend;
beforeEach(() => {
  location.hash = "#recommendations";
  posts = [];
  inbox = [];
  recommend = (input) => response(resultFor(input));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path, options = {}) => {
      if (path === "/api/welfare/status")
        return response({ configured: true, model: "configured-model" });
      if (path === "/api/welfare/analysis-inputs") return response(batch);
      if (path === "/api/welfare/recommendations") {
        const input = JSON.parse(options.body);
        posts.push(input);
        return recommend(input);
      }
      if (path === "/api/planning/requests" && options.method === "POST") {
        const request = JSON.parse(options.body);
        const envelope = {
          schema_version: "planning-inbox-0.1",
          status: "awaiting_planning_agent",
          agent_connected: false,
          received_at: "2026-10-22",
          request,
        };
        inbox.push(envelope);
        return response(envelope);
      }
      if (path === "/api/planning/requests")
        return response({
          schema_version: "planning-inbox-0.1",
          agent_connected: false,
          requests: inbox,
        });
      throw new Error(`unexpected ${path}`);
    }),
  );
});

const load = async () => {
  const view = render(<App />);
  await screen.findAllByRole("button", { name: "분석 입력 보기" });
  return view;
};
const selectFirst = async (user) =>
  user.click(screen.getAllByRole("button", { name: "분석 입력 보기" })[0]);

test("초기 진입에는 외부 추천 호출이 없고 테스트용 조작은 제거되어 있다", async () => {
  await load();
  expect(posts).toHaveLength(0);
  expect(screen.queryByText("저장 자료 조회 · 테스트용")).toBeNull();
  expect(screen.queryByText("예시 입력 채우기")).toBeNull();
  expect(
    screen.queryByRole("textbox", { name: "위험도 결과 JSON (선택)" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "대시보드" }));
  await waitFor(() =>
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "대시보드",
    ),
  );
});

test("집단 선택은 조회하지 않으며 실제 추천 요청에 대상·수치·원인 맥락을 보존한다", async () => {
  const user = userEvent.setup();
  const view = await load();
  await selectFirst(user);
  expect(posts).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "복지자원 추천받기 →" }));
  await screen.findByText("근거를 갖춘 후보를 제시하지 못했습니다.");
  expect(posts[0]).toEqual({ mode: "live", ...entries[0].request });
  const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
  expect(stored.entries).toHaveLength(1);
  view.unmount();
  await load();
  await screen.findByRole("button", { name: "결과 보기" });
  expect(posts).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "결과 보기" }));
  expect(
    screen.getByText("근거를 갖춘 후보를 제시하지 못했습니다."),
  ).toBeTruthy();
});

test("일괄 추천은 첫 실패에서 멈추고 재실행 시 완료 0개도 건너뛴다", async () => {
  const user = userEvent.setup();
  await load();
  let fail = true;
  recommend = (input) =>
    input.target.sex === "male" && fail
      ? response(
          { error: "HTTP 503", response_routing: routing("unavailable") },
          false,
        )
      : response(resultFor(input));
  await user.click(
    screen.getByRole("button", { name: "1차 대상 순서대로 복지 추천" }),
  );
  await screen.findByText(/2집단 중 1집단 완료 · 중지됨/);
  expect(posts.map((p) => p.target.sex)).toEqual(["female", "male"]);
  expect(screen.getAllByText("조회 실패").length).toBeGreaterThan(0);
  fail = false;
  await user.click(
    screen.getByRole("button", { name: "1차 대상 순서대로 복지 추천" }),
  );
  await screen.findByText(/2집단 중 2집단 완료/);
  expect(posts.map((p) => p.target.sex)).toEqual(["female", "male", "male"]);
});

test("선택 자원·담당자 프롬프트를 검토한 뒤 서버 전달함에 저장한다", async () => {
  const user = userEvent.setup();
  await load();
  recommend = (input) => response(resultFor(input, [resource]));
  await selectFirst(user);
  await user.click(screen.getByRole("button", { name: "복지자원 추천받기 →" }));
  await screen.findByRole("heading", { name: resource.name });
  await user.click(screen.getByRole("button", { name: "+ 기획 목록에 담기" }));
  await user.type(
    screen.getByRole("textbox", { name: "기획 담당자에게 전달할 요청 (선택)" }),
    "주 1회 소규모 모임",
  );
  // 조회 뒤 폼을 바꾸어도 기획은 마지막 조회 대상을 사용한다.
  await user.selectOptions(screen.getByLabelText("대상 지역"), "강남구");
  await user.click(
    screen.getByRole("button", { name: "선택 자원 활용 기획 요청 만들기" }),
  );
  await user.click(
    screen.getByRole("button", { name: "검토한 요청을 기획 전달함에 저장" }),
  );
  await screen.findByText(/기획 전달함에 저장했습니다/);
  expect(inbox[0].request.target).toEqual(entries[0].request.target);
  expect(inbox[0].request.officer_prompt).toBe("주 1회 소규모 모임");
  expect(inbox[0].request.selected_resources).toEqual([resource]);
  await user.click(screen.getByRole("link", { name: "프로그램 기획" }));
  await screen.findByText(/1건 저장됨/);
  expect(inbox[0].agent_connected).toBe(false);
});

test("잘못된 요청 실패에는 기획을 허용하지 않고 UI에서 입력 문자열을 실행하지 않는다", async () => {
  const user = userEvent.setup();
  await load();
  recommend = () => response({ error: "<script>bad()</script>" }, false);
  await user.click(screen.getByRole("button", { name: "복지자원 추천받기 →" }));
  await screen.findByText("<script>bad()</script>");
  expect(document.querySelector("script")).toBeNull();
  expect(
    screen.getByRole("button", { name: "예방·신규 기획 요청 만들기" }).disabled,
  ).toBe(true);
});
