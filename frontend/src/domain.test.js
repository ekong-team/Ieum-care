import { expect, test } from "vitest";
import {
  buildSecondReview,
  buildPlanningRequest,
  saveResults,
  restoreResults,
  STORAGE_KEY,
} from "./domain.js";

const request = {
  target: { region: "춘천시", age_group: 30, sex: "female", purpose: "all" },
  risk_assessment: { level: 4 },
  confirmed_support_needs: [],
};
const batch = {
  batch_id: "a",
  period: "2025-12",
  entries: ["found", "empty", "failed", "pending"].map((id) => ({
    analysis_id: id,
    rank: 1,
    request,
  })),
};

test("2차 검토에서 후보 0·실패·미조회를 구분하고 위험 단계·1차 동률을 유지한다", () => {
  const records = new Map([
    [
      "live:found",
      {
        recommendation: {
          resources: [{ id: "r", name: "자원", isolation_relevance: "direct" }],
        },
      },
    ],
    ["live:empty", { recommendation: { resources: [] } }],
    ["live:failed", { errorMessage: "503" }],
  ]);
  const report = buildSecondReview(batch, records);
  expect(report.rows.map((r) => r.candidate_count)).toEqual([1, 0, null, null]);
  expect(report.comparison_complete).toBe(false);
  expect(
    report.rows.every(
      (r) =>
        r.first_priority_rank === 1 &&
        r.risk_assessment.level === 4 &&
        r.second_priority_rank === null,
    ),
  ).toBe(true);
});

test("기획 요청은 마지막 조회 입력을 복사하고 기존 자원 기획에는 선택을 요구한다", () => {
  const resource = {
    id: "r",
    name: "자원",
    source: { url: "https://www.chuncheon.go.kr" },
  };
  const record = {
    planningContext: { input: request, mode: "live", error: null },
    recommendation: { resources: [resource] },
    responseRouting: null,
  };
  expect(() =>
    buildPlanningRequest("existing_resource_based", record, new Set(), ""),
  ).toThrow();
  const draft = buildPlanningRequest(
    "existing_resource_based",
    record,
    new Set(["r"]),
    "  주 1회  ",
  );
  expect(draft.officer_prompt).toBe("주 1회");
  draft.target.sex = "male";
  expect(request.target.sex).toBe("female");
  const failed = buildPlanningRequest(
    "preventive_new",
    {
      planningContext: { input: request, mode: "live", error: "503" },
      recommendation: null,
      responseRouting: { candidate_status: "unavailable" },
    },
    new Set(),
    "",
  );
  expect(failed.welfare_lookup.total_candidates).toBeNull();
  expect(failed.welfare_lookup.status).toBe("unavailable");
});

test("브라우저 저장은 같은 배치·조건·실시간 결과만 복원하고 손상은 오류로 알린다", () => {
  const result = {
    schema_version: "welfare-0.4",
    is_demo: false,
    mode: "live",
    resources: [],
    review: {},
    risk_assessment: request.risk_assessment,
  };
  const record = {
    recommendation: result,
    filters: { region: "춘천시", age: 30, sex: "female", purpose: "all" },
  };
  saveResults(batch, new Map([["live:found", record]]));
  expect(restoreResults(batch).size).toBe(1);
  expect(restoreResults({ ...batch, batch_id: "b" }).size).toBe(0);
  expect(
    restoreResults({
      ...batch,
      entries: batch.entries.map((e) => ({
        ...e,
        request: { ...request, target: { ...request.target, sex: "male" } },
      })),
    }).size,
  ).toBe(0);
  const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
  stored.entries[0].mode = "offline";
  localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
  expect(restoreResults(batch).size).toBe(0);
  localStorage.setItem(STORAGE_KEY, "bad");
  expect(() => restoreResults(batch)).toThrow();
  expect(() =>
    saveResults(batch, new Map(), {
      setItem() {
        throw Error("quota");
      },
    }),
  ).toThrow("quota");
});
