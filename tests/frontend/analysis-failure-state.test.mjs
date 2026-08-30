import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const styles = readFileSync(new URL("../../app/frontend/src/components/analysis/analysis-failure-state.css", import.meta.url), "utf8");
const server = await createServer({
  appType: "custom",
  cacheDir: "node_modules/.vite-analysis-failure-state-test",
  logLevel: "error",
  root: frontendRoot,
  server: { middlewareMode: true, hmr: false },
});

const baseRun = {
  requestId: "internal-request-id",
  traceId: "internal-trace-id",
  status: "blocked",
  question: "분석해줘",
  metrics: [],
  sources: [],
  meta: {
    asOf: "2026-08-20",
    timezone: "Asia/Seoul",
    seed: "",
    schemaVersion: "",
    contractVersion: "OPENAPI-v1.0.0",
  },
};

try {
  const { AnalysisFailureState } = await server.ssrLoadModule("/src/components/analysis/AnalysisFailureState.tsx");
  const render = (run, viewState) => renderToStaticMarkup(createElement(AnalysisFailureState, {
    run,
    viewState,
    onSuggestion: () => {},
    onRetry: () => {},
  }));

  const periodHtml = render({
    ...baseRun,
    disambiguationOptions: [
      { label: "2026년 7월", clarification_type: "period", description: "2026-07-01부터 2026-08-01 미만" },
      { label: "2026년 6월", clarification_type: "period", description: "2026-06-01부터 2026-07-01 미만" },
    ],
    error: {
      code: "CONTEXT_INCOMPLETE",
      message: "질문에 분석 기간이 없습니다.",
      clarification_type: "period",
      disambiguation_options: [],
      suggestions: [],
      required_action: "PROVIDE_CONTEXT",
    },
  }, "EMPTY");
  assert.match(periodHtml, /data-tone="clarification"/);
  assert.match(periodHtml, /분석 기간을 선택해 주세요/);
  assert.match(periodHtml, /멈춘 이유/);
  assert.match(periodHtml, /다음 단계/);
  assert.match(periodHtml, /조회 가능한 기간/);
  assert.equal((periodHtml.match(/2026년 7월/g) ?? []).length, 1);

  const metricHtml = render({
    ...baseRun,
    error: {
      code: "CONTEXT_INCOMPLETE",
      message: "객실 매출은 두 지표로 해석될 수 있습니다.",
      clarification_type: "metric",
      suggestions: ["인식 객실 매출", "숙박일 배분 객실 매출"],
      required_action: "PROVIDE_CONTEXT",
    },
  }, "EMPTY");
  assert.match(metricHtml, /분석 지표를 선택해 주세요/);
  assert.match(metricHtml, /승인된 지표/);
  assert.match(metricHtml, /인식 객실 매출/);
  assert.doesNotMatch(metricHtml, /추천 질문/);

  const unavailableMetricHtml = render({
    ...baseRun,
    error: {
      code: "METRIC_NOT_AVAILABLE",
      message: "요청한 '예약된 객실 수' 지표는 다른 지표 계산을 위한 내부 값이므로 직접 분석할 수 없습니다.",
      required_action: "MODIFY_REQUEST",
    },
  }, "EMPTY");
  assert.match(unavailableMetricHtml, /이 지표는 아직 직접 분석할 수 없습니다/);
  assert.match(unavailableMetricHtml, /예약된 객실 수/);
  assert.doesNotMatch(unavailableMetricHtml, /internal-request-id|internal-trace-id|승인된 지표.*승인된 지표/);

  const deniedHtml = render({
    ...baseRun,
    error: {
      code: "ACCESS_DENIED",
      message: "denied serving.secret.customer_email internal-request-id",
      required_action: "REQUEST_ACCESS",
    },
  }, "FORBIDDEN");
  assert.match(deniedHtml, /data-tone="restricted"/);
  assert.match(deniedHtml, /이 분석에 접근할 수 없습니다/);
  assert.doesNotMatch(deniedHtml, /serving\.secret|customer_email|internal-request-id|internal-trace-id/);

  const timeoutHtml = render({
    ...baseRun,
    status: "failed",
    error: {
      code: "QUERY_TIMEOUT",
      message: "query timeout: internal detail",
      retryable: true,
      required_action: "RETRY",
    },
  }, "ERROR");
  assert.match(timeoutHtml, /제한 시간 안에 분석을 마치지 못했습니다/);
  assert.equal((timeoutHtml.match(/같은 질문 다시 분석/g) ?? []).length, 1);
  assert.doesNotMatch(timeoutHtml, /internal detail/);

  const internalGuidelineUnavailableHtml = render({
    ...baseRun,
    status: "failed",
    error: {
      code: "DEPENDENCY_UNAVAILABLE",
      message: "필수 서비스가 준비되지 않았습니다.",
      retryable: true,
      required_action: "RETRY",
      service_context: "INTERNAL_GUIDELINE",
    },
  }, "ERROR");
  assert.match(internalGuidelineUnavailableHtml, /현재 내부 업무지침 서비스를 사용할 수 없습니다/);
  assert.match(internalGuidelineUnavailableHtml, /승인된 내부 문서 검색 서비스/);
  assert.equal((internalGuidelineUnavailableHtml.match(/같은 질문 다시 요청/g) ?? []).length, 1);
  assert.doesNotMatch(internalGuidelineUnavailableHtml, /다시 분석|분석에 필요한 데이터 서비스/);

  const policyHtml = render({
    ...baseRun,
    error: {
      code: "SQL_POLICY_BLOCKED",
      message: "선택한 지표와 분류 기준으로 안전한 집계 계획을 만들 수 없습니다.",
      retryable: false,
      required_action: "MODIFY_REQUEST",
    },
  }, "ERROR");
  assert.match(policyHtml, /선택한 지표와 분류 기준으로 안전한 집계 계획을 만들 수 없습니다/);
  assert.match(policyHtml, /질문의 범위나 조건을 수정해 다시 전송해 주세요/);
  assert.doesNotMatch(policyHtml, /데이터 변경 지시를 제외/);

  const semanticContractHtml = render({
    ...baseRun,
    error: {
      code: "SEMANTIC_CONTRACT_INVALID",
      message: "선택한 지표와 분해 기준을 함께 실행할 수 있는 승인 관계·분석 단위 계약이 없습니다.",
      retryable: false,
      required_action: "MODIFY_REQUEST",
    },
  }, "ERROR");
  assert.match(semanticContractHtml, /data-tone="restricted"/);
  assert.match(semanticContractHtml, /이 지표 조합을 안전하게 분석할 수 없습니다/);
  assert.match(semanticContractHtml, /승인 관계·분석 단위 계약/);
  assert.doesNotMatch(semanticContractHtml, /internal-request-id|internal-trace-id/);

  const presentationUnsupportedHtml = render({
    ...baseRun,
    error: {
      code: "PRESENTATION_NOT_SUPPORTED",
      message: "현재 결과에는 그래프 비교에 필요한 기간 또는 분류 축이 없습니다.",
      retryable: false,
      required_action: "MODIFY_REQUEST",
    },
  }, "ERROR");
  assert.match(presentationUnsupportedHtml, /data-tone="clarification"/);
  assert.match(presentationUnsupportedHtml, /현재 결과를 요청한 방식으로 표시하기 어렵습니다/);
  assert.match(presentationUnsupportedHtml, /그래프 비교에 필요한 기간 또는 분류 축/);
  assert.match(presentationUnsupportedHtml, /기간별 추이나 항목별 비교/);
  assert.doesNotMatch(presentationUnsupportedHtml, /검증 근거나 계약이 완전하지 않아/);

  const emptyHtml = render({ ...baseRun, status: "success", rowCount: 0, error: undefined }, "EMPTY");
  assert.match(emptyHtml, /조건에 맞는 결과가 없습니다/);
  assert.doesNotMatch(emptyHtml, /analysis-diagnostic__action/);

  const blockedEmptyHtml = render({
    ...baseRun,
    status: "blocked",
    evidence: {
      asOf: "2026-08-18",
      timezone: "Asia/Seoul",
      period: { start: "2025-08-01", endExclusive: "2025-09-01" },
      filters: { "analytics.room_daily.hotel_name": "비스타 호텔" },
    },
    sources: [{
      name: "객실 일별 실적",
      urn: "urn:li:dataset:room_daily",
      status: "success",
    }],
    error: {
      code: "EMPTY_RESULT",
      message: "요청한 기간과 조건에 해당하는 결과가 없습니다.",
      retryable: false,
      required_action: "MODIFY_REQUEST",
    },
  }, "EMPTY");
  assert.match(blockedEmptyHtml, /data-tone="empty"/);
  assert.match(blockedEmptyHtml, /조건에 맞는 결과가 없습니다/);
  assert.match(blockedEmptyHtml, /2025-08-01 ~ 2025-09-01 미포함/);
  assert.match(blockedEmptyHtml, /hotel name: 비스타 호텔/);
  assert.match(blockedEmptyHtml, /객실 일별 실적/);

  assert.match(styles, /grid-template-columns:minmax\(0,1\.4fr\) minmax\(220px,\.8fr\)/);
  assert.match(styles, /\.analysis-diagnostic__options button:disabled\{[^}]*opacity:1[^}]*background:#0b121d/);
  assert.match(styles, /\.theme-light \.analysis-diagnostic\{[^}]*background:#fff/);
  assert.match(styles, /\.theme-light \.analysis-diagnostic\[data-tone="service"\]\{[^}]*--diagnostic-accent:#155fbe/);
  assert.match(styles, /@media\(max-width:900px\)/);
  assert.match(styles, /@media\(prefers-reduced-motion:reduce\)/);
} finally {
  await server.close();
}

console.log("frontend analysis failure state tests passed");
