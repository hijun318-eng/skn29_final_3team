import assert from "node:assert/strict";

import {
  ENTERPRISE_SERIES_COLORS,
  analysisTitle,
  formatCompactNumber,
  formatMetricValue,
  isNumericValue,
  localizeAnalysisSummary,
  localizeMetricDefinition,
  metricDisplayLabel,
  metricDisplayUnit,
  metricUnitLabel,
  reportTitleForAnalysis,
  seriesColor,
} from "../../app/frontend/src/utils/presentation.ts";

const structuredRun = {
  question: "이 문장을 제목으로 쓰지 마세요?",
  metrics: [{ label: "객실 매출", resultField: "revenue", unit: "원" }],
  chart: { xField: "month" },
  table: { columns: ["month", "revenue"] },
  evidence: {
    period: { start: "2026-07-01", endExclusive: "2026-08-01" },
    filters: { "customer.membership_grade_code": "GOLD" },
    metrics: [],
  },
};

assert.equal(analysisTitle(structuredRun), "2026년 7월 객실 매출 분석");
assert.equal(analysisTitle({
  ...structuredRun,
  evidence: {
    ...structuredRun.evidence,
    comparisonPeriod: { start: "2026-08-01", endExclusive: "2026-09-01" },
  },
}), "2026년 7월·2026년 8월 객실 매출 분석");
assert.equal(reportTitleForAnalysis(structuredRun), "2026년 7월 객실 매출 분석 보고서");
assert.doesNotMatch(reportTitleForAnalysis(structuredRun), /이 문장을 제목으로 쓰지 마세요/);
assert.equal(reportTitleForAnalysis({ question: "원문 질문" }), "분석 결과 보고서");

assert.equal(formatMetricValue(0), "0");
assert.equal(formatMetricValue(null, { unit: "원" }), "—");
assert.equal(formatMetricValue("1250000", { unit: "원" }), "1,250,000 원");
assert.equal(formatMetricValue(0.652306318, { unit: "ratio" }), "65.23%");
assert.equal(formatMetricValue(0.652306318, { unit: "ratio", includeUnit: false }), "65.23");
assert.equal(formatMetricValue(-12.345, { maximumFractionDigits: 1 }), "-12.3");
assert.equal(formatMetricValue("계산 불가", { unit: "원" }), "계산 불가");
assert.equal(formatCompactNumber(125000000), "1.3억");
assert.equal(isNumericValue("0"), true);
assert.equal(isNumericValue(""), false);
assert.equal(isNumericValue(null), false);
assert.equal(metricUnitLabel("객실 매출", "원"), "객실 매출 (원)");
assert.equal(metricDisplayLabel({ label: "Any Metric", displayLabel: "승인 지표" }), "승인 지표");
assert.equal(metricDisplayLabel({ label: "원본 지표" }), "원본 지표");
assert.equal(metricDisplayUnit("KRW"), "원");
assert.equal(metricDisplayUnit("KRW_per_available_room_night"), "원");
assert.equal(localizeAnalysisSummary(
  "2026년 6월의 Room Revenue 합계 계산 결과는 6,632,629,550 KRW입니다.",
  [{ label: "Room Revenue", displayLabel: "객실 매출", unit: "KRW", displayUnit: "원" }],
), "2026년 6월 객실 매출 합계는 6,632,629,550 원입니다.");
assert.equal(localizeAnalysisSummary(
  "Room Revenue는 요청 기간에 계산됩니다.",
  [{ label: "Room Revenue", displayLabel: "객실 매출", unit: "KRW", displayUnit: "원" }],
), "객실 매출은 요청 기간에 계산됩니다.");
assert.equal(
  localizeMetricDefinition("승인된 금액은 KRW 단위다."),
  "승인된 금액은 원 단위다.",
);

assert.equal(new Set(ENTERPRISE_SERIES_COLORS).size, 8);
assert.equal(seriesColor(0), ENTERPRISE_SERIES_COLORS[0]);
assert.equal(seriesColor(7), ENTERPRISE_SERIES_COLORS[7]);
assert.equal(seriesColor(8), ENTERPRISE_SERIES_COLORS[0]);

console.log("frontend presentation tests passed");
