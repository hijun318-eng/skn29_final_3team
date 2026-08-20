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
  const { commandClarificationMessage, commandClarificationType, savedRunStatus } = await server.ssrLoadModule("/src/pages/agentPageHelpers.js");
  const { AnalysisStatePanel } = await server.ssrLoadModule("/src/components/analysis/AnalysisStatePanel.tsx");
  const { normalizeApiResponse } = await server.ssrLoadModule("/src/contracts/analysis.ts");
  const run = normalizeApiResponse(response, "7월 PLATINUM 장기 투숙 우수 고객 객실 유형별 매출을 분석해줘");
  const html = renderToStaticMarkup(createElement(AnalysisStatePanel, { run }));

  // 금액은 지표별로 확정한 배율 하나만 쓰고, 손실 없는 원값은 title로 남는다.
  assert.match(html, />58\.4<em>억 원<\/em>/);
  assert.match(html, /title="5,842,000,000 원"/);
  // 규모가 다른 지표까지 한 배율로 묶으면 안 된다: 평균 객실 단가 284,730원이 "0억 원"이 되면 회귀다.
  assert.match(html, />284,730<em>원<\/em>/);
  assert.doesNotMatch(html, />0<em>억 원<\/em>/);
  assert.doesNotMatch(html, /고객 고객/);
  assert.match(agentSource, /turnItem\.run\.artifact && \(turnItem\.run\.rowCount \?\? 0\) > 0/);
  assert.equal(commandClarificationType({ clarification_type: "period" }, null), "period");
  assert.equal(
    commandClarificationType({}, { resolved_slots: { clarification_type: "metric" } }),
    "metric",
  );
  assert.equal(
    commandClarificationMessage({ message: "분석 기간을 입력해 주세요." }, "period"),
    "분석 기간을 입력해 주세요.",
  );
  assert.match(commandClarificationMessage({}, "metric"), /분석할 지표/);
  assert.equal(savedRunStatus("CLARIFYING"), "입력 필요");

  // 차트 뷰(CHART)로 전환했을 때만 차트 표현 방식 세그먼트와 실제 차트 markup이 나온다.
  const chartHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, { run, viewType: "CHART" }));
  assert.match(chartHtml, /aria-label="차트 표현 방식"/);
  assert.match(chartHtml, /aria-pressed="true">가로 막대<\/button>/);
  assert.match(chartHtml, /enterprise-chart--horizontal-bar/);

  // 실제 렌더 트리가 쓰는 KPI·차트·표 카드 선택자만 검증한다(죽은 ".analysis-dashboard" 조상 선택자는 삭제됨).
  assert.match(stylesSource, /\.analysis-metrics\{/);
  assert.match(stylesSource, /\.analysis-result-section \.analysis-table thead th\{/);

  // 서버 unit이 "KRW"여도 화면 표기는 보고서와 같은 한국어 배율 라벨로 통일한다(KRW 노출 회귀 방지).
  const krwHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, metrics: run.metrics.map((metric) => ({ ...metric, unit: "KRW", value: 33005912094 })) },
  }));
  assert.match(krwHtml, />330\.1<em>억 원<\/em>/);
  assert.match(krwHtml, /title="33,005,912,094 KRW"/);
  assert.doesNotMatch(krwHtml, /<em>KRW<\/em>/);

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
  // PARTIAL 상태도 showResult 대상이므로 성공 상태와 동일한 결과 뷰가 렌더링된다.
  assert.match(partialHtml, /analysis-state--partial/);
  assert.match(partialHtml, />58\.4<em>억 원<\/em>/);
} finally {
  await server.close();
}

console.log("frontend analysis dashboard tests passed");
