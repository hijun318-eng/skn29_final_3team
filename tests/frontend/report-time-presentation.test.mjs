import assert from "node:assert/strict";

import {
  normalizeGeneratedArtifactViewTitle,
  normalizeGeneratedReportTitle,
  reportArtifactDefaultTitle,
  reportTimeCategoryPresentation,
  reportTimeColumnLabel,
  reportTimeRangeLabel,
} from "../../app/frontend/src/features/reports/reportTimePresentation.js";

function monthlyArtifact(start, endExclusive, periods) {
  return {
    table: {
      columns: ["period", "room_revenue"],
      rows: periods.map((period, index) => ({ period, room_revenue: 100 + index })),
    },
    chart: { x_field: "period", y_fields: ["room_revenue"] },
    evidence: {
      time_granularity: "month",
      time_field: "period",
      period: { start, end_exclusive: endExclusive },
      metrics: [{ result_field: "room_revenue", label: "객실 매출" }],
    },
  };
}

const sameYear = monthlyArtifact(
  "2026-05-01",
  "2026-09-01",
  ["2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01"],
);
const sameYearPresentation = reportTimeCategoryPresentation(sameYear, "period");
assert.equal(reportTimeRangeLabel(sameYear), "2026년 5월~8월");
assert.equal(reportArtifactDefaultTitle(sameYear, "chart"), "2026년 5월~8월 객실 매출 비교");
assert.deepEqual(
  sameYear.table.rows.map((row) => sameYearPresentation.axis(row.period)),
  ["5월", "6월", "7월", "8월"],
);
assert.equal(sameYearPresentation.detail("2026-05-01"), "2026년 5월");
assert.equal(reportTimeColumnLabel(sameYear, "period"), "월");

const crossYear = monthlyArtifact(
  "2025-11-01",
  "2026-03-01",
  ["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01"],
);
const crossYearPresentation = reportTimeCategoryPresentation(crossYear, "period");
assert.equal(reportTimeRangeLabel(crossYear), "2025년 11월~2026년 2월");
assert.deepEqual(
  crossYear.table.rows.map((row) => crossYearPresentation.axis(row.period)),
  ["2025년 11월", "2025년 12월", "2026년 1월", "2026년 2월"],
);

const missingContract = structuredClone(sameYear);
delete missingContract.evidence.time_granularity;
const inferredPresentation = reportTimeCategoryPresentation(missingContract, "period");
assert.equal(inferredPresentation.granularity, "month");
assert.deepEqual(
  missingContract.table.rows.map((row) => inferredPresentation.axis(row.period)),
  ["5월", "6월", "7월", "8월"],
);
assert.equal(reportTimeRangeLabel(missingContract), "2026년 5월~8월");
assert.equal(reportArtifactDefaultTitle(missingContract, "chart"), "2026년 5월~8월 객실 매출 비교");

const tableOnly = structuredClone(missingContract);
delete tableOnly.chart;
delete tableOnly.evidence.time_field;
assert.equal(reportTimeRangeLabel(tableOnly), "2026년 5월~8월");
assert.equal(reportArtifactDefaultTitle(tableOnly, "table"), "2026년 5월~8월 객실 매출 상세");
assert.equal(
  normalizeGeneratedArtifactViewTitle(
    "2026년 5월 1일부터 8월 31일까지 객실 매출 분석 · 차트",
    sameYear,
    "chart",
  ),
  "2026년 5월~8월 객실 매출 비교",
);
assert.equal(
  normalizeGeneratedArtifactViewTitle("경영진이 정한 월별 매출 차트", sameYear, "chart"),
  "경영진이 정한 월별 매출 차트",
);
assert.equal(
  normalizeGeneratedArtifactViewTitle("Analysis result · 차트", sameYear, "chart"),
  "2026년 5월~8월 객실 매출 비교",
);
assert.equal(
  normalizeGeneratedArtifactViewTitle("Analysis result · 핵심 지표", sameYear, "artifact"),
  "2026년 5월~8월 객실 매출 핵심 지표",
);
assert.equal(
  normalizeGeneratedReportTitle(
    "2026.05.01–2026.08.30 객실 매출 분석 보고서",
    sameYear,
  ),
  "2026년 5월~8월 객실 매출 비교 보고서",
);
assert.equal(
  normalizeGeneratedReportTitle("2026년 상반기 식음료 운영 보고서", sameYear),
  "2026년 상반기 식음료 운영 보고서",
);

const nonDateCategory = structuredClone(missingContract);
nonDateCategory.chart.x_field = "hotel";
nonDateCategory.evidence.time_field = "hotel";
nonDateCategory.table.columns = ["hotel", "room_revenue"];
nonDateCategory.table.rows = [{ hotel: "SEOUL", room_revenue: 100 }];
assert.equal(reportTimeCategoryPresentation(nonDateCategory, "hotel"), null);

const wrongField = structuredClone(sameYear);
wrongField.evidence.time_field = "business_date";
assert.equal(reportTimeCategoryPresentation(wrongField, "period"), null);

console.log("frontend report time presentation tests passed");
