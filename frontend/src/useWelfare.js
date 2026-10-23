import { useEffect, useRef, useState } from "react";
import {
  api,
  post,
  restoreResults,
  saveResults,
  STORAGE_KEY,
} from "./domain.js";

const initialFilters = {
  region: "춘천시",
  age: 60,
  sex: "all",
  purpose: "all",
};
const filtersFor = (entry) => ({
  region: entry.request.target.region,
  age: entry.request.target.age_group,
  sex: entry.request.target.sex,
  purpose: entry.request.target.purpose,
});

export default function useWelfare() {
  const [batch, setBatch] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const analysisLoadingRef = useRef(false);
  const batchRef = useRef(null);
  const [records, setRecords] = useState(new Map());
  const recordsRef = useRef(new Map());
  const [filters, setFilters] = useState(initialFilters);
  const [entry, setEntry] = useState(null);
  const [current, setCurrent] = useState(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);
  const stopRef = useRef(false);
  const [analysisStatus, setAnalysisStatus] =
    useState("분석 결과를 확인하고 있습니다.");
  const [storageStatus, setStorageStatus] = useState(
    "추천 결과는 이 브라우저에 저장됩니다.",
  );
  const [agentStatus, setAgentStatus] =
    useState("API 연결을 확인하고 있습니다.");
  const [retryAt, setRetryAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const retryRef = useRef(0);

  useEffect(() => {
    if (!retryAt) return;
    const timer = setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= retryAt) {
        setRetryAt(0);
        retryRef.current = 0;
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [retryAt]);

  async function loadAnalysis() {
    if (busyRef.current || runningRef.current || analysisLoadingRef.current)
      return;
    analysisLoadingRef.current = true;
    setAnalysisLoading(true);
    setAnalysisStatus("분석 결과를 불러오고 있습니다.");
    try {
      const data = await api("/api/welfare/analysis-inputs");
      if (
        data.schema_version !== "analysis-welfare-inputs-0.1" ||
        !Array.isArray(data.entries)
      )
        throw new Error("분석 연결 형식을 확인해주세요.");
      if (batchRef.current?.batch_id !== data.batch_id) {
        let restored = new Map();
        try {
          restored = restoreResults(data);
          setStorageStatus(
            `${restored.size}건 복원 · 같은 브라우저·주소에서 유지됩니다. 최신 운영 여부는 다시 확인해주세요.`,
          );
        } catch {
          setStorageStatus(
            "저장 결과를 읽지 못했습니다. 새로 조회할 수 있습니다.",
          );
        }
        recordsRef.current = restored;
        setRecords(restored);
        setEntry(null);
        setCurrent(null);
      }
      batchRef.current = data;
      setBatch(data);
      setAnalysisStatus(
        `${data.period} · 완료 ${data.entries.length}집단 · 부분 판정 ${data.priority.partial_assessments.length}집단 · 보류 ${data.priority.held_cohorts.length}집단`,
      );
    } catch (error) {
      batchRef.current = null;
      setBatch(null);
      recordsRef.current = new Map();
      setRecords(new Map());
      setEntry(null);
      setCurrent(null);
      setAnalysisStatus(error.message);
    } finally {
      analysisLoadingRef.current = false;
      setAnalysisLoading(false);
    }
  }

  useEffect(() => {
    loadAnalysis();
    api("/api/welfare/status")
      .then((status) =>
        setAgentStatus(
          status.configured
            ? `Tavily 검색 + Gemini 추천 · ${status.model}`
            : "서버의 TAVILY_API_KEY·GEMINI_API_KEY 설정을 확인해주세요.",
        ),
      )
      .catch(() => setAgentStatus("API 서버 연결을 확인해주세요."));
  }, []);

  function selectEntry(next) {
    if (busyRef.current || runningRef.current) return;
    setEntry(next);
    setFilters(filtersFor(next));
    setCurrent(recordsRef.current.get(`live:${next.analysis_id}`) || null);
  }

  function changeFilter(key, value) {
    setFilters((previous) => ({ ...previous, [key]: value }));
    if (["region", "age", "sex"].includes(key)) {
      setEntry(null);
    }
  }

  async function query(input, nativeEntry = null) {
    if (
      busyRef.current ||
      analysisLoadingRef.current ||
      Date.now() < retryRef.current
    )
      return false;
    busyRef.current = true;
    setBusy(true);
    setCurrent(null);
    const usedFilters = {
      region: input.target.region,
      age: input.target.age_group,
      sex: input.target.sex,
      purpose: input.target.purpose,
    };
    let record = {
      recommendation: null,
      responseRouting: null,
      planningContext: null,
      errorMessage: "",
      filters: usedFilters,
    };
    try {
      const result = await post("/api/welfare/recommendations", {
        mode: "live",
        ...input,
      });
      if (
        result.schema_version !== "welfare-0.4" ||
        result.is_demo !== false ||
        result.mode !== "live" ||
        !result.review ||
        !Array.isArray(result.resources)
      )
        throw new Error("추천 응답 형식을 확인해주세요.");
      record = {
        ...record,
        recommendation: result,
        responseRouting: result.response_routing || null,
        planningContext: { input, mode: "live", error: null },
      };
    } catch (error) {
      const result = error.result || {};
      record.errorMessage =
        error.name === "TimeoutError"
          ? "응답 시간이 초과되었습니다. 직접 다시 시도해주세요."
          : error.message;
      record.responseRouting = result.response_routing || null;
      if (record.responseRouting?.candidate_status === "unavailable")
        record.planningContext = {
          input,
          mode: "live",
          error: record.errorMessage,
        };
      if (
        Number.isInteger(result.retry_after_seconds) &&
        result.retry_after_seconds > 0 &&
        result.retry_after_seconds <= 60
      ) {
        retryRef.current = Date.now() + result.retry_after_seconds * 1000;
        setRetryAt(retryRef.current);
        setNow(Date.now());
      }
    } finally {
      record.saved_at = new Date().toISOString();
      setCurrent(record);
      if (nativeEntry && batchRef.current) {
        const next = new Map(recordsRef.current);
        next.set(`live:${nativeEntry.analysis_id}`, record);
        recordsRef.current = next;
        setRecords(next);
        try {
          saveResults(batchRef.current, next);
          setStorageStatus(
            "이 브라우저에 저장됨 · 공유 PC에서는 사용 후 결과를 지워주세요.",
          );
        } catch {
          setStorageStatus(
            "브라우저 저장 실패 · 현재 결과는 유지되지만 새로고침하면 사라질 수 있습니다.",
          );
        }
      }
      busyRef.current = false;
      setBusy(false);
    }
    return Boolean(record.recommendation);
  }

  function queryCurrent() {
    if (runningRef.current) return;
    const input = {
      target: {
        region: filters.region,
        age_group: filters.age,
        sex: filters.sex,
        purpose: filters.purpose,
      },
      risk_assessment: entry?.request.risk_assessment || null,
      // 화면에서 중복 입력하지 않는다. 연결된 팀원 입력만 보존하고 일반 탐색은 비운다.
      confirmed_support_needs: entry?.request.confirmed_support_needs || [],
    };
    if (entry?.request.analysis_context)
      input.analysis_context = entry.request.analysis_context;
    const native =
      entry &&
      filters.purpose === entry.request.target.purpose
        ? entry
        : null;
    return query(input, native);
  }

  async function runBatch() {
    if (
      !batchRef.current ||
      runningRef.current ||
      busyRef.current ||
      Date.now() < retryRef.current
    )
      return;
    const source = batchRef.current;
    runningRef.current = true;
    stopRef.current = false;
    setRunning(true);
    try {
      for (const [index, next] of source.entries.entries()) {
        if (stopRef.current) break;
        if (recordsRef.current.get(`live:${next.analysis_id}`)?.recommendation)
          continue;
        setAnalysisStatus(
          `${index + 1}/${source.entries.length}집단 추천 중 · 현재 요청 후 중지할 수 있습니다.`,
        );
        setEntry(next);
        setFilters(filtersFor(next));
        if (!(await query(next.request, next))) {
          stopRef.current = true;
          break;
        }
      }
      const done = source.entries.filter(
        (item) =>
          recordsRef.current.get(`live:${item.analysis_id}`)?.recommendation,
      ).length;
      setAnalysisStatus(
        `${source.entries.length}집단 중 ${done}집단 완료${stopRef.current ? " · 중지됨" : ""} · 이어 실행하면 성공 집단은 건너뜁니다.`,
      );
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  }

  function clearSaved() {
    if (busyRef.current || runningRef.current) return;
    try {
      localStorage.removeItem(STORAGE_KEY);
      recordsRef.current = new Map();
      setRecords(new Map());
      setCurrent(null);
      setStorageStatus(
        "브라우저 추천 결과를 지웠습니다. 서버의 기획 전달함은 유지됩니다.",
      );
    } catch {
      setStorageStatus(
        "브라우저 저장 결과를 지우지 못했습니다. 사이트 데이터 설정을 확인해주세요.",
      );
    }
  }

  return {
    batch,
    records,
    filters,
    changeFilter,
    entry,
    current,
    busy,
    running,
    analysisLoading,
    analysisStatus,
    storageStatus,
    agentStatus,
    retrySeconds: Math.max(0, Math.ceil((retryAt - now) / 1000)),
    loadAnalysis,
    selectEntry,
    queryCurrent,
    runBatch,
    clearSaved,
    stop: () => {
      stopRef.current = true;
    },
  };
}
