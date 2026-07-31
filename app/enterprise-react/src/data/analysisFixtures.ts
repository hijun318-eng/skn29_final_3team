import { OPENAPI_VERSION, type AnalysisRun, type AnalysisViewState } from "../contracts/analysis.ts";

export const FIXTURE_VERSION = "UI-FIXTURE-v1.0.0";

const baseRun: AnalysisRun = {
  conversationId: "conv-demo-001",
  requestId: "req-demo-001",
  traceId: "trace-demo-001",
  status: "success",
  question: "지난달 객실 매출 하락 원인을 알려줘.",
  sources: [
    {
      name: "PMS reservations",
      urn: "urn:answervice:dataset:pms.public.reservations",
      fqn: "pms.public.reservations",
      schemaVersion: "1.0.0",
      seedVersion: "20260729",
      status: "success",
    },
    {
      name: "CRM membership history",
      urn: "urn:answervice:dataset:crm.public.membership_history",
      fqn: "crm.public.membership_history",
      schemaVersion: "1.0.0",
      seedVersion: "20260729",
      status: "success",
    },
  ],
  artifact: {
    artifactId: "00000000-0000-0000-0000-0000000002f9",
    queryId: "fixture-query-success",
    contextHash: "fixture-context-success",
  },
  metrics: [
    { metricId: "recognized_room_revenue", label: "인식 객실 매출", value: 128400000, unit: "KRW" },
    { metricId: "occupancy_rate", label: "객실 점유율", value: 72.5, unit: "%" },
  ],
  table: {
    columns: ["business_date", "recognized_room_revenue", "occupancy_rate"],
    rows: [
      { business_date: "2026-07-28", recognized_room_revenue: 45200000, occupancy_rate: 76.1 },
      { business_date: "2026-07-29", recognized_room_revenue: 43100000, occupancy_rate: 72.8 },
      { business_date: "2026-07-30", recognized_room_revenue: 40100000, occupancy_rate: 68.6 },
    ],
  },
  chart: {
    chartType: "line",
    xField: "business_date",
    yFields: ["recognized_room_revenue"],
  },
  evidence: {
    artifactId: "00000000-0000-0000-0000-0000000002f9",
    queryId: "fixture-query-success",
    asOf: "2026-07-30",
    period: { start: "2026-07-01", endExclusive: "2026-08-01" },
    filters: { hotel: "synthetic", channel: "direct" },
    cached: false,
    sampling: { applied: false, returnedRows: 3, totalRows: 3 },
  },
  meta: {
    asOf: "2026-07-30",
    timezone: "Asia/Seoul",
    synthetic: true,
    seed: "20260729",
    schemaVersion: "1.0.0",
    contractVersion: OPENAPI_VERSION,
  },
};

function fixture(overrides: Partial<AnalysisRun>): AnalysisRun {
  return { ...baseRun, ...overrides, sources: overrides.sources ?? baseRun.sources };
}

export const analysisFixtures: Record<Lowercase<AnalysisViewState> | "clarification", AnalysisRun> = {
  loading: fixture({
    status: "queued", requestId: "req-loading-001", summary: "요청을 접수했습니다.",
    sources: [], artifact: undefined, metrics: [], table: null, chart: null, evidence: undefined,
  }),
  clarification: fixture({
    status: "blocked",
    requestId: "00000000-0000-0000-0000-000000000100",
    traceId: "fixture-g1-clarification",
    error: { code: "CONTEXT_INCOMPLETE", message: "분석 기간을 입력해 주세요.", retryable: false },
    sources: [], artifact: undefined, metrics: [], table: null, chart: null, evidence: undefined,
  }),
  empty: fixture({
    status: "success", requestId: "req-empty-001", rowCount: 0, evidenceReady: true,
    summary: "조건에 맞는 결과가 없습니다.", metrics: [], table: { columns: [], rows: [] }, chart: null,
    evidence: { ...baseRun.evidence!, sampling: { applied: false, returnedRows: 0, totalRows: 0 } },
  }),
  ready: fixture({
    status: "success", requestId: "req-ready-001", rowCount: 3, evidenceReady: true,
    summary: "주중 객실 점유율과 직접 예약 비중 감소가 함께 관측됐습니다.",
  }),
  delayed: fixture({
    status: "running", delayed: true, requestId: "req-delayed-001", summary: "일부 원천 응답이 지연되고 있습니다.",
    sources: [], artifact: undefined, metrics: [], table: null, chart: null, evidence: undefined,
  }),
  partial: fixture({
    status: "partial", requestId: "req-partial-001", rowCount: 1, evidenceReady: true,
    summary: "PMS 결과는 확인했지만 CRM 원천은 시간 초과로 제외됐습니다.",
    table: { columns: baseRun.table!.columns, rows: baseRun.table!.rows.slice(0, 1) },
    evidence: { ...baseRun.evidence!, sampling: { applied: false, returnedRows: 1, totalRows: null } },
    sources: [
      baseRun.sources[0],
      { ...baseRun.sources[1], status: "failed" },
    ],
  }),
  error: fixture({
    status: "failed", requestId: "req-error-001",
    error: { code: "QUERY_SOURCE_FAILED", message: "데이터 원천 조회에 실패했습니다.", retryable: true },
    sources: [], artifact: undefined, metrics: [], table: null, chart: null, evidence: undefined,
  }),
  forbidden: fixture({
    status: "blocked", requestId: "req-forbidden-001", sources: [],
    error: { code: "ACCESS_DENIED", message: "이 분석 범위에 접근할 권한이 없습니다.", retryable: false },
    artifact: undefined, metrics: [], table: null, chart: null, evidence: undefined,
  }),
  insufficient_evidence: fixture({
    status: "blocked", requestId: "req-evidence-001", evidenceReady: false,
    error: { code: "RESULT_EVIDENCE_MISSING", message: "결과 근거가 충분하지 않아 표시하지 않습니다.", retryable: true },
    sources: [], artifact: undefined, metrics: [], table: null, chart: null, evidence: undefined,
  }),
  cancelled: fixture({
    status: "cancelled", requestId: "req-cancelled-001", summary: "사용자가 분석을 취소했습니다.",
    sources: [], artifact: undefined, metrics: [], table: null, chart: null, evidence: undefined,
  }),
};

export type FixtureKey = keyof typeof analysisFixtures;
