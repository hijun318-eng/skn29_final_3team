/** 로그인 없이 보고서 UX만 검토하는 임시 LAN review adapter다. 병합 전 제거한다. */
export const REPORT_REVIEW_MODE = import.meta.env.VITE_REPORT_REVIEW_MODE === "true";

const ARTIFACT_ID = "review-monthly-revenue";
const QUERY_ID = "review-query-monthly-revenue";

const reviewArtifact = {
  contract_version: "REPORT-v1.0.0",
  artifact_id: ARTIFACT_ID,
  query_id: QUERY_ID,
  artifact_checksum: "review-only",
  summary: "8월 전체 매출은 전월 대비 8.2% 증가했습니다. 객실 매출과 VIP 고객 객단가 상승이 성장을 주도했습니다.",
  metrics: [
    { metric_id: "total_revenue", result_field: "total_revenue", label: "총 매출", definition: "월간 총 매출", value: 1824000000, unit: "원" },
    { metric_id: "room_revenue", result_field: "room_revenue", label: "객실 매출", definition: "취소 제외 객실 매출", value: 1140000000, unit: "원" },
    { metric_id: "fb_revenue", result_field: "fb_revenue", label: "F&B 매출", definition: "식음 업장 매출", value: 420000000, unit: "원" },
  ],
  table: {
    columns: ["month", "total_revenue", "room_revenue", "fb_revenue"],
    rows: [
      ["3월", 1480000000, 910000000, 360000000],
      ["4월", 1530000000, 950000000, 370000000],
      ["5월", 1610000000, 1010000000, 380000000],
      ["6월", 1680000000, 1050000000, 400000000],
      ["7월", 1686000000, 1060000000, 398000000],
      ["8월", 1824000000, 1140000000, 420000000],
    ].map(([month, total_revenue, room_revenue, fb_revenue]) => ({ month, total_revenue, room_revenue, fb_revenue })),
  },
  chart: { type: "line", chart_type: "line", x_field: "month", y_fields: ["total_revenue", "room_revenue", "fb_revenue"] },
  evidence: {
    artifact_id: ARTIFACT_ID,
    query_id: QUERY_ID,
    as_of: "2026-08-01",
    timezone: "Asia/Seoul",
    period: { start: "2026-03-01", end_exclusive: "2026-09-01" },
    filters: { property: "전체 호텔" },
    metrics: [
      { metric_id: "total_revenue", result_field: "total_revenue", label: "총 매출", definition: "월간 총 매출", unit: "원" },
      { metric_id: "room_revenue", result_field: "room_revenue", label: "객실 매출", definition: "취소 제외 객실 매출", unit: "원" },
      { metric_id: "fb_revenue", result_field: "fb_revenue", label: "F&B 매출", definition: "식음 업장 매출", unit: "원" },
    ],
    sources: [{ name: "검토용 호텔 경영 데이터", urn: "urn:answervice:review:hotel", fqn: "review.hotel_revenue", schema_version: "1", seed_version: "2026-08", synthetic: true }],
    gates: { g1: "PASSED", g2: "PASSED", g3: "PASSED" },
  },
};

let reviewDefinition = {
  definitionId: "report-review",
  version: 1,
  status: "draft",
  title: "2026년 8월 월간 경영 보고서",
  orientation: "landscape",
  currencyDisplayUnit: "hundredMillion",
  blocks: [
    { id: "review-intro", title: "월간 경영 보고서", type: "text", content: "## 2026년 8월\n\n전사 경영 성과와 주요 변동 요인을 요약합니다.", columns: 12, x: 0, y: 0, w: 12, h: 4 },
    { id: "review-chart", title: "월별 매출 추이", type: "chart", artifactId: ARTIFACT_ID, queryId: QUERY_ID, content: JSON.stringify({ chartType: "line", showLegend: true, sizeMode: "manual" }), columns: 12, x: 0, y: 4, w: 12, h: 7 },
    { id: "review-table", title: "월별 상세 실적", type: "table", artifactId: ARTIFACT_ID, queryId: QUERY_ID, content: JSON.stringify({ density: "comfortable", showRowNumbers: true, sizeMode: "manual" }), columns: 12, x: 0, y: 11, w: 12, h: 7 },
    { id: "review-summary", title: "AI 경영 요약", type: "text", content: "8월 전체 매출은 전월 대비 **8.2% 증가**했습니다.\n\n객실 매출 증가가 전체 실적 상승을 주도했고 F&B 부문도 성장했습니다. VIP 고객의 평균 객단가 상승이 주요 요인으로 보입니다.", columns: 12, x: 0, y: 18, w: 12, h: 5 },
  ],
};

function fromRequestBlock(block) {
  return {
    id: block.block_id,
    title: block.title,
    artifactId: block.artifact_id,
    queryId: block.query_id,
    columns: block.columns,
    type: block.type,
    content: block.content,
    x: block.x,
    y: block.y,
    w: block.w,
    h: block.h,
  };
}

const reportClient = {
  async listDefinitions() { return [reviewDefinition]; },
  async getDefinition() { return reviewDefinition; },
  async getArtifact() { return reviewArtifact; },
  async listRuns() { return []; },
  async listSchedules() { return []; },
  async replaceDraftBlocks(_definitionId, _version, blocks, options = {}) {
    reviewDefinition = {
      ...reviewDefinition,
      blocks: blocks.map(fromRequestBlock),
      orientation: options.orientation ?? reviewDefinition.orientation,
      currencyDisplayUnit: options.currencyDisplayUnit ?? reviewDefinition.currencyDisplayUnit,
    };
    return reviewDefinition;
  },
};

const analysisClient = {
  async listDefinitions() { return []; },
  async listRuns() { return []; },
};

/** 검토 빌드가 실제 인증·API를 건드리지 않고 보고서 편집 흐름만 여는 임시 client 경계다. */
export const REPORT_REVIEW_LIFECYCLE_OPTIONS = { analysisClient, reportClient };
