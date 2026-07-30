import type { AnalysisRun, AnalysisViewState } from "../contracts/analysis";

export const FIXTURE_VERSION = "DRAFT-UI-FIXTURE-v0.1";

const baseRun: AnalysisRun = {
  conversationId: "conv-demo-001",
  requestId: "req-demo-001",
  traceId: "trace-demo-001",
  status: "success",
  question: "지난달 객실 매출 하락 원인을 알려줘.",
  sources: [
    { name: "PMS 예약", urn: "urn:li:dataset:(trino,pms.reservation,PROD)", status: "success" },
    { name: "POS 주문", urn: "urn:li:dataset:(trino,pos.orders,PROD)", status: "success" },
  ],
  meta: {
    asOf: "2026-07-30",
    timezone: "Asia/Seoul",
    synthetic: true,
    seed: "20260729",
    schemaVersion: "1.0.0",
    contractVersion: "1.0.0-draft",
  },
};

function fixture(overrides: Partial<AnalysisRun>): AnalysisRun {
  return { ...baseRun, ...overrides, sources: overrides.sources ?? baseRun.sources };
}

export const analysisFixtures: Record<Lowercase<AnalysisViewState>, AnalysisRun> = {
  loading: fixture({ status: "queued", requestId: "req-loading-001", summary: "요청을 접수했습니다." }),
  empty: fixture({ status: "success", requestId: "req-empty-001", rowCount: 0, evidenceReady: true, summary: "조건에 맞는 결과가 없습니다." }),
  ready: fixture({ status: "success", requestId: "req-ready-001", rowCount: 24, evidenceReady: true, summary: "주중 객실 점유율과 직접 예약 비중 감소가 함께 관측됐습니다." }),
  delayed: fixture({ status: "running", delayed: true, requestId: "req-delayed-001", summary: "일부 원천 응답이 지연되고 있습니다." }),
  partial: fixture({ status: "partial", requestId: "req-partial-001", rowCount: 18, evidenceReady: true, summary: "PMS 결과는 확인했지만 POS 원천은 시간 초과로 제외됐습니다.", sources: [
    { name: "PMS 예약", urn: "urn:li:dataset:(trino,pms.reservation,PROD)", status: "success" },
    { name: "POS 주문", urn: "urn:li:dataset:(trino,pos.orders,PROD)", status: "failed" },
  ] }),
  error: fixture({ status: "failed", requestId: "req-error-001", error: { code: "QUERY_SOURCE_FAILED", message: "데이터 원천 조회에 실패했습니다.", retryable: true } }),
  forbidden: fixture({ status: "blocked", requestId: "req-forbidden-001", sources: [], error: { code: "ACCESS_DENIED", message: "이 분석 범위에 접근할 권한이 없습니다.", retryable: false } }),
  insufficient_evidence: fixture({ status: "blocked", requestId: "req-evidence-001", evidenceReady: false, error: { code: "RESULT_EVIDENCE_MISSING", message: "결과 근거가 충분하지 않아 표시하지 않습니다.", retryable: true } }),
  cancelled: fixture({ status: "cancelled", requestId: "req-cancelled-001", summary: "사용자가 분석을 취소했습니다." }),
};

export type FixtureKey = keyof typeof analysisFixtures;
