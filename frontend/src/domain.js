// API로 전달하는 계약과 화면 표시 로직을 React 컴포넌트에서 분리한다.
export const pages = {
  dashboard: "대시보드",
  analysis: "분석",
  recommendations: "복지자원 추천",
  planning: "프로그램 기획",
  evaluation: "평가·예산",
};
export const ageLabel = (age) =>
  age === 60 ? "60대 이상" : age === 10 ? "10대 (10~19세)" : `${age}대`;
export const sexLabel = (sex) =>
  ({ all: "남녀 합산", male: "남성", female: "여성" })[sex || "all"];
export const purposeLabels = {
  all: "전체 목적",
  connection: "관계 형성·사회 참여",
  daily: "일상생활 지원",
  wellbeing: "정서·마음 돌봄",
  economic: "경제·생활 안정",
  other: "기타·통합 안내",
};
export const relevanceLabels = {
  direct: "고립 예방과 직접 연관",
  indirect: "일반 생활 지원 · 간접 연관",
  uncertain: "고립 예방 연관성 확인 필요",
};
export const targetLabel = (target) =>
  `${target.region} · ${ageLabel(target.age_group)} · ${sexLabel(target.sex)}`;
// 서버 기록 시각(UTC ISO)을 담당자 PC의 현지 시각 "YYYY-MM-DD HH:mm"으로 보여 준다. 읽지 못하면 원문 그대로.
export function localTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
export const STORAGE_KEY = "ieum-welfare-results-v1";

export function downloadJSON(data, filename) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function api(path, options = {}) {
  const response = await fetch(path, {
    signal: AbortSignal.timeout(150000),
    ...options,
  });
  if (!response.headers.get("content-type")?.includes("application/json"))
    throw new Error(
      "API 서버를 확인해주세요. 최신 backend/server.py를 실행해야 합니다.",
    );
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || "요청에 실패했습니다.");
    error.result = result;
    throw error;
  }
  return result;
}
export const post = (path, data) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export function saveResults(batch, records, storage = localStorage) {
  const entries = batch.entries.flatMap((entry) => {
    const record = records.get(`live:${entry.analysis_id}`);
    return record
      ? [
          {
            analysis_id: entry.analysis_id,
            mode: "live",
            request_signature: JSON.stringify(entry.request),
            record,
          },
        ]
      : [];
  });
  storage.setItem(
    STORAGE_KEY,
    JSON.stringify({ version: 1, batch_id: batch.batch_id, entries }),
  );
}

export function restoreResults(batch, storage = localStorage) {
  const records = new Map();
  const saved = JSON.parse(storage.getItem(STORAGE_KEY) || "null");
  if (
    saved?.version !== 1 ||
    saved.batch_id !== batch.batch_id ||
    !Array.isArray(saved.entries)
  )
    return records;
  for (const item of saved.entries) {
    const entry = batch.entries.find((e) => e.analysis_id === item.analysis_id);
    const record = item.record;
    if (
      !entry ||
      item.mode !== "live" ||
      item.request_signature !== JSON.stringify(entry.request) ||
      !record?.filters
    )
      continue;
    const target = entry.request.target;
    if (
      record.filters.region !== target.region ||
      record.filters.age !== target.age_group ||
      record.filters.sex !== target.sex ||
      record.filters.purpose !== target.purpose
    )
      continue;
    const result = record.recommendation;
    if (
      result &&
      (result.schema_version !== "welfare-0.4" ||
        result.is_demo !== false ||
        result.mode !== "live" ||
        !Array.isArray(result.resources) ||
        !result.review ||
        JSON.stringify(result.risk_assessment) !==
          JSON.stringify(entry.request.risk_assessment) ||
        JSON.stringify(result.analysis_context) !==
          JSON.stringify(entry.request.analysis_context))
    )
      continue;
    if (!result && typeof record.errorMessage !== "string") continue;
    if (
      record.planningContext &&
      (record.planningContext.mode !== "live" ||
        !record.planningContext.input ||
        ["region", "age_group", "sex", "purpose"].some(
          (key) => record.planningContext.input.target?.[key] !== target[key],
        ) ||
        ["risk_assessment", "analysis_context", "confirmed_support_needs"].some(
          (key) =>
            JSON.stringify(record.planningContext.input[key]) !==
            JSON.stringify(entry.request[key]),
        ))
    )
      continue;
    records.set(`live:${entry.analysis_id}`, record);
  }
  return records;
}

export function buildSecondReview(analysisInputs, analysisResults) {
  if (!analysisInputs) return null;
  const mode = "live";
  const rows = analysisInputs.entries.map((entry) => {
    const saved = analysisResults.get(`${mode}:${entry.analysis_id}`);
    const result = saved?.recommendation;
    const candidates = result?.resources || [];
    const status = result
      ? candidates.length
        ? "candidates_found"
        : "no_candidates_found"
      : saved
        ? "unavailable"
        : "pending";
    return {
      analysis_id: entry.analysis_id,
      first_priority_rank: entry.rank,
      target: entry.request.target,
      risk_assessment: entry.request.risk_assessment,
      lookup_status: status,
      candidate_count: result ? candidates.length : null,
      saved_at: saved?.saved_at || null,
      // AI의 연관성 분류이며 효과 검증이나 담당자 확인을 대신하지 않는다.
      ai_direct_relevance_count:
        result && mode === "live"
          ? candidates.filter((item) => item.isolation_relevance === "direct")
              .length
          : null,
      candidates: candidates.map((item) => ({
        id: item.id,
        name: item.name,
        source_url: item.source?.url || null,
        age_match: item.age_match || "unknown",
        isolation_relevance: item.isolation_relevance || null,
        eligibility_status: item.eligibility_status || "needs_confirmation",
        availability_status: item.availability_status || "needs_confirmation",
        reference_year: item.source?.reference_year || null,
      })),
      next_action:
        status === "candidates_found"
          ? "기관에 실제 대상·운영·참여 가능 여부 확인 후 기존 자원 활용 또는 보완 기획"
          : status === "no_candidates_found"
            ? "검색 범위·대상 조건을 추가 조사하고 예방·신규 기획 검토"
            : status === "unavailable"
              ? "오류 확인 후 담당자가 조회 재실행 · 자원 부족 판단 보류"
              : "복지 추천 조회 필요 · 자원 부족 판단 보류",
      error: saved?.errorMessage || null,
      second_priority_rank: null,
    };
  });
  const completed = rows.filter((row) =>
    ["candidates_found", "no_candidates_found"].includes(row.lookup_status),
  ).length;
  return {
    schema_version: "welfare-cohort-review-0.1",
    batch_id: analysisInputs.batch_id,
    period: analysisInputs.period,
    mode,
    status: "needs_human_review",
    comparison_complete: rows.length > 0 && completed === rows.length,
    completed_cohorts: completed,
    total_cohorts: rows.length,
    policy: "preserve-first-priority-no-automatic-reranking-v1",
    limitations: [
      "현재 배치의 실시간 추천 결과만 비교합니다.",
      "후보 미확보·조회 실패는 지역의 실제 자원 부재를 의미하지 않습니다.",
      "자격·운영·수용 인원 및 미충족 수요 확인과 팀의 순위 기준 합의가 필요합니다.",
      "부분 판정·보류 집단은 1차 추천 입력에서 제외되어 이 표에도 포함되지 않습니다.",
    ],
    rows,
  };
}

export function buildPlanningRequest(
  planningType,
  record,
  selected,
  officerPrompt,
) {
  const { planningContext, recommendation, responseRouting } = record || {};
  const resources = recommendation?.resources || [];
  if (!planningContext)
    throw new Error("먼저 올바른 조건으로 복지자원을 조회해주세요.");
  if (!["existing_resource_based", "preventive_new"].includes(planningType))
    throw new Error("기획 방식을 확인해주세요.");
  const items = resources.filter((item) => selected.has(item.id));
  if (
    planningType === "existing_resource_based" &&
    (!recommendation || !items.length)
  )
    throw new Error("활용할 기존 자원을 먼저 선택해주세요.");
  const prompt = officerPrompt.trim();
  if (prompt.length > 2000)
    throw new Error("담당자 요청은 2,000자 이내로 작성해주세요.");
  const input = planningContext.input;
  // 완성 기획안과 구별되는 전달용 초안. 조회 실패는 후보 0개로 바꾸지 않는다.
  return JSON.parse(
    JSON.stringify({
      schema_version: "planning-request-0.1",
      request_id: crypto.randomUUID(),
      created_at: new Date().toISOString(),
      planning_type: planningType,
      target: input.target,
      officer_prompt: prompt,
      confirmed_support_needs: input.confirmed_support_needs || [],
      risk_assessment: input.risk_assessment || null,
      analysis_context:
        recommendation?.analysis_context || input.analysis_context || null,
      has_example_context: Boolean(
        recommendation?.has_example_context ||
        input.risk_assessment?.is_example ||
        recommendation?.analysis_context?.profile?.is_example,
      ),
      selected_resources: items,
      welfare_lookup: {
        mode: planningContext.mode,
        status: recommendation ? "completed" : "unavailable",
        candidate_status:
          responseRouting?.candidate_status ||
          (recommendation
            ? resources.length
              ? "candidates_found"
              : "no_candidates_found"
            : "unavailable"),
        total_candidates: recommendation ? resources.length : null,
        error: planningContext.error,
        response_routing: responseRouting,
        recommendation_snapshot: recommendation,
      },
      notes: [
        "기획 Agent 연결 전 전달용 요청이며 완성 기획안이 아닙니다.",
        "후보 0개·조회 실패는 실제 자원 부재를 증명하지 않습니다.",
        "추천 건수로 위험 단계를 변경하지 않으며 예방 효과·개인 자격은 확정하지 않습니다.",
      ],
    }),
  );
}
