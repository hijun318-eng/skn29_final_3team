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

  const emptyHtml = render({ ...baseRun, status: "success", rowCount: 0, error: undefined }, "EMPTY");
  assert.match(emptyHtml, /조건에 맞는 결과가 없습니다/);
  assert.doesNotMatch(emptyHtml, /analysis-diagnostic__action/);

  assert.match(styles, /grid-template-columns:minmax\(0,1\.4fr\) minmax\(220px,\.8fr\)/);
  assert.match(styles, /@media\(max-width:720px\)/);
  assert.match(styles, /@media\(prefers-reduced-motion:reduce\)/);
} finally {
  await server.close();
}

console.log("frontend analysis failure state tests passed");
