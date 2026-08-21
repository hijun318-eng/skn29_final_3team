import assert from "node:assert/strict";

import {
  ENTERPRISE_SERIES_COLORS,
  analysisTitle,
  formatCompactNumber,
  formatMetricValue,
  isNumericValue,
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

assert.equal(new Set(ENTERPRISE_SERIES_COLORS).size, 8);
assert.equal(seriesColor(0), ENTERPRISE_SERIES_COLORS[0]);
assert.equal(seriesColor(7), ENTERPRISE_SERIES_COLORS[7]);
assert.equal(seriesColor(8), ENTERPRISE_SERIES_COLORS[0]);

console.log("frontend presentation tests passed");
