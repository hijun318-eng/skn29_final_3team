import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const response = JSON.parse(readFileSync(new URL("./fixtures/analysis-rich-success.json", import.meta.url), "utf8"));
const processViewModels = JSON.parse(readFileSync(new URL("./fixtures/analysis-process-view-models.json", import.meta.url), "utf8"));
const stylesSource = readFileSync(new URL("../../app/frontend/src/styles.css", import.meta.url), "utf8");
const agentSource = readFileSync(new URL("../../app/frontend/src/pages/AgentPage.jsx", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../../app/frontend/src/App.jsx", import.meta.url), "utf8");
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
  const { AnalysisProgress, createAnalysisProcessViewModel } = await server.ssrLoadModule("/src/components/analysis/AnalysisStatePanelParts.tsx");
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
  assert.match(html, /AI 분석 요약/);
  assert.doesNotMatch(html, /상세 데이터 표/);
  assert.doesNotMatch(html, /aria-label="차트 표현 방식"/);

  const analysisProcessHtml = renderToStaticMarkup(createElement(AnalysisProgress, { model: processViewModels.analysisActive }));
  assert.match(analysisProcessHtml, /data-process-kind="ANALYSIS"/);
  assert.match(analysisProcessHtml, /class="active" data-state="active"/);
  assert.match(analysisProcessHtml, /class="done" data-state="complete"/);
  assert.match(analysisProcessHtml, /데이터 조회/);

  const presentationProcessHtml = renderToStaticMarkup(createElement(AnalysisProgress, { model: processViewModels.presentationActive }));
  assert.match(presentationProcessHtml, /data-process-kind="PRESENTATION"/);
  assert.match(presentationProcessHtml, /이전 분석 결과 확인/);
  assert.match(presentationProcessHtml, /요청한 보기 구성/);
  assert.doesNotMatch(presentationProcessHtml, /SQL|데이터 조회|재분석/);

  const completeProcessHtml = renderToStaticMarkup(createElement(AnalysisProgress, { model: processViewModels.complete }));
  assert.match(completeProcessHtml, /data-process-status="success"/);
  assert.match(completeProcessHtml, /class="done" data-state="complete"/);

  const failedProcessHtml = renderToStaticMarkup(createElement(AnalysisProgress, { model: processViewModels.failed }));
  assert.match(failedProcessHtml, /data-process-status="failed"/);
  assert.match(failedProcessHtml, /class="failed" data-state="failed"/);

  const cancelledProcessHtml = renderToStaticMarkup(createElement(AnalysisProgress, { model: processViewModels.cancelled }));
  assert.match(cancelledProcessHtml, /data-process-status="cancelled"/);
  assert.match(cancelledProcessHtml, /class="failed" data-state="cancelled"/);
  assert.match(cancelledProcessHtml, /취소 요청됨/);

  const analysisWithoutProgress = createAnalysisProcessViewModel({
    kind: "ANALYSIS",
    status: "running",
    elapsedSeconds: 31,
    cancelRequested: false,
  });
  assert.equal(analysisWithoutProgress.steps.length, 1);
  assert.equal(analysisWithoutProgress.steps[0].state, "active");
  assert.doesNotMatch(analysisWithoutProgress.steps[0].label, /SQL|데이터 조회|결과 검증/);

  const presentationWithoutProgress = createAnalysisProcessViewModel({
    kind: "PRESENTATION",
    status: "running",
    elapsedSeconds: 2,
    cancelRequested: false,
  });
  assert.equal(presentationWithoutProgress.steps.length, 1);
  assert.doesNotMatch(presentationWithoutProgress.steps[0].label, /SQL|데이터 조회|재분석/);
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
  assert.doesNotMatch(chartHtml, /AI 분석 요약/);

  const followupHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run,
    viewType: "TABLE",
    artifactReuse: { pending: false, viewSpecId: "view-table" },
    onQuickView: () => {},
    onOpenEvidence: () => {},
  }));
  assert.match(followupHtml, /기존 분석 결과 재사용/);
  assert.match(followupHtml, /추가 데이터 조회 없이 같은 Artifact와 근거를 사용합니다/);
  assert.match(followupHtml, /상세 데이터 표/);
  assert.doesNotMatch(followupHtml, /AI 분석 요약/);
  for (const label of ["요약으로 보기", "표로 보기", "그래프로 보기", "KPI만 보기"]) {
    assert.match(followupHtml, new RegExp(label));
  }
  assert.doesNotMatch(followupHtml, /전체 보기/);

  const pendingFollowupHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, elapsedSeconds: 0 },
    viewType: "TABLE",
    artifactReuse: { pending: true },
  }));
  assert.match(pendingFollowupHtml, /data-process-kind="PRESENTATION"/);
  assert.match(pendingFollowupHtml, /기존 분석 결과로 보기를 준비합니다/);
  assert.doesNotMatch(pendingFollowupHtml, /추가 데이터 조회 없이 같은 Artifact와 근거를 사용합니다/);
  assert.doesNotMatch(pendingFollowupHtml, /상세 데이터 표/);
  assert.doesNotMatch(pendingFollowupHtml, /SQL 실행 중|데이터 조회 중|재분석 중/);

  const unavailableHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, metrics: [], chart: null, table: { columns: [], rows: [] }, rowCount: 1 },
    viewType: "KPI",
    artifactReuse: { pending: false },
  }));
  assert.match(unavailableHtml, /현재 분석 결과로는 KPI 보기를 만들 수 없습니다/);
  assert.match(unavailableHtml, /값을 임의로 생성하지 않았습니다/);
  assert.match(unavailableHtml, /data-view="kpi"/);

  const emptyTableHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, table: { columns: [], rows: [] }, rowCount: 0 },
    viewType: "TABLE",
    artifactReuse: { pending: false },
  }));
  assert.match(emptyTableHtml, /analysis-state--empty/);
  assert.match(emptyTableHtml, /결과 없음/);
  assert.doesNotMatch(emptyTableHtml, /<table/);

  const networkFailureHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: {
      ...run,
      status: "failed",
      artifact: undefined,
      error: {
        code: "NETWORK_UNAVAILABLE",
        message: "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.",
        retryable: true,
        required_action: "RETRY",
      },
    },
  }));
  assert.match(networkFailureHtml, /현재 분석 서비스를 사용할 수 없습니다/);
  assert.match(networkFailureHtml, /데이터 서비스가 준비되지 않았거나 연결되지 않았습니다/);
  assert.match(networkFailureHtml, /data-tone="service"/);
  assert.doesNotMatch(networkFailureHtml, /현재 분석 결과로는 KPI 보기를 만들 수 없습니다/);

  const chartMismatchHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, chart: { ...run.chart, xField: "missing_dimension" } },
    viewType: "CHART",
  }));
  assert.match(chartMismatchHtml, /enterprise-chart-fallback/);
  assert.match(chartMismatchHtml, /원본 필드 이름을 임의로 해석하지 않고 데이터 표를 유지합니다/);
  assert.doesNotMatch(chartMismatchHtml, /recharts-wrapper|enterprise-chart--horizontal-bar/);

  const actionHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run,
    onSave: () => {},
    onCreateReportDraft: () => {},
    onOpenEvidence: () => {},
  }));
  for (const label of ["분석 저장", "보고서에 담기", "분석 근거"]) {
    assert.match(actionHtml, new RegExp(label));
  }

  const cancelledHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: {
      ...run,
      status: "cancelled",
      artifact: undefined,
      error: { code: "REQUEST_CANCELLED", message: "사용자가 분석을 취소했습니다.", retryable: false },
    },
  }));
  assert.match(cancelledHtml, /data-tone="cancelled"/);
  assert.match(cancelledHtml, /분석을 취소했습니다/);

  // 실제 렌더 트리가 쓰는 KPI·차트·표 카드 선택자만 검증한다(죽은 ".analysis-dashboard" 조상 선택자는 삭제됨).
  assert.match(stylesSource, /\.analysis-metrics\{/);
  assert.match(stylesSource, /\.analysis-result-section \.analysis-table thead th\{/);
  assert.match(stylesSource, /\.app-shell\{--workspace-inline-offset:var\(--sidebar\);/);
  assert.match(stylesSource, /\.sidebar-collapsed\{--workspace-inline-offset:0px\}/);
  assert.match(appSource, /\$\{menuOpen \? "" : "sidebar-collapsed"\}/);
  assert.match(stylesSource, /@media\(max-width:900px\)\{[^\n]*\.topbar>div>span\{overflow:hidden;text-overflow:ellipsis;white-space:nowrap\}/);
  // 데스크톱에서는 좌측 이력과 우측 근거 패널 사이에, 768px에서는 180px 이력 옆에 입력창을 맞춘다.
  assert.match(stylesSource, /\.chat-layout\{[^}]*grid-template-columns:205px minmax\(400px,1fr\) 285px/);
  assert.match(stylesSource, /\.chat-input\{[^}]*left:calc\(var\(--workspace-inline-offset\) \+ 205px\)[^}]*transition:left \.2s,right \.2s/);
  assert.match(stylesSource, /@media\(max-width:1200px\)\{[^\n]*\.chat-layout\{grid-template-columns:180px 1fr\}[^\n]*\.chat-input\{left:calc\(var\(--workspace-inline-offset\) \+ 180px\);right:0\}/);
  // 390px 모바일에서는 이력 패널을 접고 composer를 viewport 양쪽에 맞춘다.
  assert.match(stylesSource, /@media\(max-width:650px\)\{[^\n]*\.chat-layout\{height:auto;display:block\}[^\n]*\.chat-history\{display:none\}[^\n]*\.chat-input\{left:0;padding-inline:12px\}/);
  assert.match(stylesSource, /@media\(max-width:650px\)\{\.chat-main\{[^}]*padding-bottom:calc\(110px \+ env\(safe-area-inset-bottom\)\)[^}]*\}\.chat-input\{right:0;max-width:100vw\}/);
  assert.match(stylesSource, /\.chat-main\{padding-bottom:calc\(118px \+ env\(safe-area-inset-bottom\)\)/);
  assert.match(stylesSource, /\.conversation-end\{height:1px;scroll-margin-block-end:/);
  assert.match(stylesSource, /\.turn-user-bubble \.user-text,[^\n]*overflow-wrap:anywhere/);
  assert.match(stylesSource, /@media\(prefers-reduced-motion:reduce\)\{[^\n]*\.sidebar,\.workspace,\.chat-input\{transition:none\}/);
  assert.match(agentSource, /prefers-reduced-motion: reduce/);
  assert.match(agentSource, /scrollIntoView\(\{[\s\S]*?block: "end"/);
  assert.match(agentSource, /className="conversation-end"/);
  assert.match(agentSource, /<form className="chat-input" onSubmit=\{submitQuestion\}>/);
  assert.match(agentSource, /<input[\s\S]*?aria-describedby="question-help"[\s\S]*?required/);
  assert.match(agentSource, /<button aria-label="질문 전송"/);
  assert.match(stylesSource, /:where\(button,input,textarea,select,summary,\[tabindex\]\):focus-visible/);
  assert.match(stylesSource, /\.question-field input::placeholder,[^{]*\{color:#91a4ba;opacity:1\}/);
  assert.match(stylesSource, /\.theme-light \.question-field input::placeholder,[^{]*\{color:#5f7288;opacity:1\}/);
  assert.match(stylesSource, /\.unified-action-btn:disabled\{[^}]*opacity:1[^}]*background:#0b121d/);
  assert.match(stylesSource, /\.analysis-artifact-reuse code\{[^}]*max-width:28ch[^}]*overflow-wrap:anywhere/);

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
