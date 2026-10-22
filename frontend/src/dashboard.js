// 대시보드는 검증된 분석 결과를 요약할 뿐, 위험 단계나 원래 순위를 재계산하지 않는다.
export function dashboardRows(batch) {
  if (!batch) return [];
  const priority = batch.priority;
  const complete =
    priority.ranked_cohorts ||
    batch.entries.map((entry) => ({
      analysis_id: entry.analysis_id,
      target: entry.request.target,
      rank: entry.rank,
      level: entry.request.risk_assessment.level,
      assessment_status: "complete",
      quality_warnings: entry.quality_warnings || [],
      reason: "",
    }));
  return [
    ...complete,
    ...(priority.partial_assessments || []),
    ...(priority.held_cohorts || []),
  ];
}

export function summarizeDashboard(rows) {
  const complete = rows.filter((row) => row.assessment_status === "complete");
  return {
    total: rows.length,
    complete: complete.length,
    partial: rows.filter((row) => row.assessment_status === "partial").length,
    held: rows.filter((row) => row.assessment_status === "held").length,
    upper: complete.filter((row) => row.level >= 4).length,
    // 부분 판정에 임시 단계가 있어도 완료 판정의 단계 분포에 섞지 않는다.
    levels: [1, 2, 3, 4, 5].map((level) => ({
      level,
      count: complete.filter((row) => row.level === level).length,
    })),
  };
}

export function formatEvidence(item) {
  if (typeof item.value !== "number" || !Number.isFinite(item.value))
    return "미확인";
  const value = item.unit === "ratio" ? item.value * 100 : item.value;
  const number = value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  // count는 결제 건수·비교 횟수 등 의미가 다양하므로 항목 이름과 함께 숫자만 표시한다.
  const unit =
    { ratio: "%", percent: "%", count: "", krw: "원" }[item.unit] ?? "";
  return `${number}${unit}`;
}
