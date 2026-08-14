import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const response = JSON.parse(readFileSync(new URL("./fixtures/analysis-rich-success.json", import.meta.url), "utf8"));
const stylesSource = readFileSync(new URL("../../app/frontend/src/styles.css", import.meta.url), "utf8");
const agentSource = readFileSync(new URL("../../app/frontend/src/pages/AgentPage.jsx", import.meta.url), "utf8");
const server = await createServer({
  appType: "custom",
  cacheDir: "node_modules/.vite-analysis-dashboard-test",
  logLevel: "error",
  root: frontendRoot,
  server: { middlewareMode: true, hmr: false },
});

try {
  const { AnalysisStatePanel } = await server.ssrLoadModule("/src/components/analysis/AnalysisStatePanel.tsx");
  const { normalizeApiResponse } = await server.ssrLoadModule("/src/contracts/analysis.ts");
  const run = normalizeApiResponse(response, "7월 PLATINUM 장기 투숙 우수 고객 객실 유형별 매출을 분석해줘");
  const html = renderToStaticMarkup(createElement(AnalysisStatePanel, { run }));

  assert.match(html, />58\.4억<em>원<\/em>/);
  assert.match(html, /title="5,842,000,000 원"/);
  assert.doesNotMatch(html, /고객 고객/);
  assert.match(html, /aria-label="차트 표현 방식"/);
  assert.match(html, /aria-pressed="true">가로<\/button>/);
  assert.match(html, /enterprise-chart--horizontal-bar/);
  assert.match(stylesSource, /analysis-context-card \.analysis-filter-list b/);
  assert.match(stylesSource, /analysis-dashboard \.analysis-table thead th:nth-child\(2\)/);
  assert.match(stylesSource, /analysis-partial-notice--sources/);
  assert.match(agentSource, /run\.artifact && \(run\.rowCount \?\? 0\) > 0/);

  const partialHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    onRetry: () => {},
    run: {
      ...run,
      status: "partial",
      error: {
        code: "PARTIAL_FAILURE",
        message: "일부 데이터 소스를 조회하지 못했습니다.",
        retryable: true,
        required_action: "RETRY",
        suggestions: [],
      },
      sources: run.sources.map((source) => ({ ...source, status: "unknown" })),
    },
  }));
  assert.match(partialHtml, /analysis-partial-notice--summary/);
  assert.match(partialHtml, />다시 분석<\/button>/);
  assert.doesNotMatch(partialHtml, /같은 질문 다시 분석/);
} finally {
  await server.close();
}

console.log("frontend analysis dashboard tests passed");
