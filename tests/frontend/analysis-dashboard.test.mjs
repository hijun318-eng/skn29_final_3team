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
  const { AgentCapabilityOverview, AgentExecutionBar, agentKindsForRun } = await server.ssrLoadModule("/src/components/agent/AgentIdentity.jsx");
  const { attachAgentResults, mlPredictionRun, ragRun } = await server.ssrLoadModule("/src/pages/agentResponseMappers.js");
  const { AnalysisStatePanel, analysisResultDensity } = await server.ssrLoadModule("/src/components/analysis/AnalysisStatePanel.tsx");
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
  assert.match(html, /analysis-summary-heading/);
  assert.doesNotMatch(html, /근거 검증 완료|analysis-summary-verified/);
  assert.doesNotMatch(html, />분석 결과</);
  assert.match(html, /analysis-summary-answer/);
  assert.doesNotMatch(html, /핵심 답변/);
  assert.match(html, /수치 근거/);
  assert.match(html, />핵심 지표</);
  assert.doesNotMatch(html, /주요 KPI|개 승인 지표/);
  assert.doesNotMatch(html, /상세 데이터 표/);
  assert.doesNotMatch(html, /취소·무료 제공을 제외한 객실 매출/);
  assert.doesNotMatch(html, /aria-label="차트 표현 방식"/);
  assert.equal(analysisResultDensity({ ...run, metrics: run.metrics.slice(0, 1) }, "SUMMARY"), "compact");
  assert.equal(analysisResultDensity({ ...run, metrics: run.metrics.slice(0, 3) }, "SUMMARY"), "regular");
  assert.equal(analysisResultDensity(run, "TABLE"), "wide");

  const localizedSummaryHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: {
      ...run,
      summary: "2026년 6월 1일 전부터 2026년 7월 1일 전까지의 Room Revenue 합계 계산 결과는 6,632,629,550 KRW입니다.",
      evidence: {
        ...run.evidence,
        period: { start: "2026-06-01", endExclusive: "2026-07-01" },
      },
      metrics: [{
        ...run.metrics[0],
        metricId: "room_revenue",
        label: "Room Revenue",
        displayLabel: "객실 매출",
        value: 6632629550,
        unit: "KRW",
        displayUnit: "원",
      }],
    },
  }));
  assert.match(localizedSummaryHtml, /2026년 6월 객실 매출 분석/);
  assert.match(localizedSummaryHtml, /2026년 6월 1일부터 30일까지의 객실 매출 합계는 66\.3억 원입니다/);
  assert.match(localizedSummaryHtml, /title="6,632,629,550 원"/);
  assert.match(localizedSummaryHtml, /data-result-density="compact"/);
  assert.match(localizedSummaryHtml, /analysis-state--compact-width/);
  assert.match(localizedSummaryHtml, /데이터 기준 <\/time>|데이터 기준 2026\./);
  assert.doesNotMatch(localizedSummaryHtml, /Room Revenue|KRW|ADR|RevPAR/);

  const singleMetricTrendHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: {
      ...run,
      metrics: [run.metrics[0]],
      chart: { chartType: "line", xField: "period", yFields: ["room_revenue"] },
      table: {
        columns: ["period", "room_revenue"],
        rows: [
          { period: "2026-05-01", room_revenue: 5200000000 },
          { period: "2026-06-01", room_revenue: 5480000000 },
          { period: "2026-07-01", room_revenue: 5842000000 },
        ],
      },
    },
  }));
  assert.match(singleMetricTrendHtml, /analysis-kpi-section is-single-metric/);
  assert.match(singleMetricTrendHtml, /analysis-metric-card--total is-hero-metric has-sparkline/);
  assert.match(singleMetricTrendHtml, /class="analysis-kpi-sparkline" role="img" aria-label="객실 매출 최근 3개 시점 추이"/);
  assert.match(singleMetricTrendHtml, /<polyline points=/);

  const twoTurnHtml = renderToStaticMarkup(createElement("div", null,
    createElement(AnalysisStatePanel, { run }),
    createElement(AnalysisStatePanel, { run }),
  ));
  const kpiHeadingIds = [...twoTurnHtml.matchAll(/class="analysis-kpi-section" aria-labelledby="([^"]+)"/g)]
    .map((match) => match[1]);
  assert.equal(kpiHeadingIds.length, 2);
  assert.equal(new Set(kpiHeadingIds).size, 2);

  const comparisonSummaryHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: {
      ...run,
      summary: "2026년 4월 기준 계산 결과는 Room Revenue 5,600,000,000 KRW. 2026년 6월 기준 계산 결과는 Room Revenue 6,632,629,550 KRW.",
      evidence: {
        ...run.evidence,
        period: { start: "2026-04-01", endExclusive: "2026-05-01" },
        comparisonPeriod: { start: "2026-06-01", endExclusive: "2026-07-01" },
      },
      metrics: [{
        ...run.metrics[0],
        metricId: "room_revenue",
        resultField: "room_revenue",
        label: "Room Revenue",
        displayLabel: "객실 매출",
        value: 5600000000,
        unit: "KRW",
        displayUnit: "원",
      }],
      table: {
        columns: ["period", "room_revenue"],
        rows: [
          { period: "2026-04-01", room_revenue: 5600000000 },
          { period: "2026-06-01", room_revenue: 6632629550 },
        ],
      },
    },
  }));
  assert.match(comparisonSummaryHtml, /객실 매출 56억 원/);
  assert.match(comparisonSummaryHtml, /객실 매출 66\.3억 원/);
  assert.doesNotMatch(comparisonSummaryHtml, /6,632,629,550 원|Room Revenue|KRW/);

  const analysisProcessHtml = renderToStaticMarkup(createElement(AnalysisProgress, { model: processViewModels.analysisActive }));
  assert.match(analysisProcessHtml, /data-process-kind="ANALYSIS"/);
  assert.match(analysisProcessHtml, /data-process-flow="vertical"/);
  assert.match(analysisProcessHtml, /class="active" data-state="active"/);
  assert.match(analysisProcessHtml, /class="done" data-state="complete"/);
  assert.match(analysisProcessHtml, /데이터 조회/);

  const runningPanelHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, status: "running" },
    processViewModel: processViewModels.analysisActive,
  }));
  assert.match(runningPanelHtml, /data-process-status="running"/);
  assert.match(runningPanelHtml, /analysis-state--regular-width/);
  assert.match(runningPanelHtml, /승인된 범위에서 분석하고 있습니다/);

  assert.match(html, /analysis-section-meta/);
  assert.match(html, /데이터 기준 2026\.08\.14\./);
  assert.doesNotMatch(html, /class="meta-strip"/);

  const completedAnalysisProcess = {
    ...processViewModels.analysisActive,
    status: "success",
    steps: processViewModels.analysisActive.steps.map((step) => ({ ...step, state: "complete" })),
  };
  const completedPanelHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run,
    processViewModel: completedAnalysisProcess,
  }));
  assert.match(completedPanelHtml, /AI 분석 요약/);
  assert.doesNotMatch(completedPanelHtml, /analysis-trace|분석 과정을 완료했습니다|단계 완료/);

  const presentationProcessHtml = renderToStaticMarkup(createElement(AnalysisProgress, { model: processViewModels.presentationActive }));
  assert.match(presentationProcessHtml, /data-process-kind="PRESENTATION"/);
  assert.match(presentationProcessHtml, /요청한 보기/);
  assert.doesNotMatch(presentationProcessHtml, /이전 분석 결과|재사용|재조회/);
  assert.doesNotMatch(presentationProcessHtml, /SQL|데이터 조회|재분석/);

  const completeProcessHtml = renderToStaticMarkup(createElement(AnalysisProgress, { model: processViewModels.complete }));
  assert.match(completeProcessHtml, /data-process-status="success"/);
  assert.match(completeProcessHtml, /analysis-trace--complete/);
  assert.match(completeProcessHtml, /단계 완료/);
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

  const capabilityHtml = renderToStaticMarkup(createElement(AgentCapabilityOverview, {
    ragEnabled: true,
    mlEnabled: true,
  }));
  assert.match(capabilityHtml, /Analysis Agent/);
  assert.match(capabilityHtml, /RAG Agent/);
  assert.match(capabilityHtml, /ML Agent/);
  assert.match(capabilityHtml, /HGBR 예측 Tool/);

  const ragResult = {
    status: "ANSWER",
    answer: { text: "승인 문서 답변" },
    evidence_bundle: [],
    citations: [],
  };
  const mlResult = {
    execution_id: "ml-run-1",
    property_id: "GRAND",
    as_of: "2026-09-01",
    daily_forecasts: [{ target_date: "2026-09-02" }],
  };
  const compositeRun = attachAgentResults(run, "복합 요청", {
    ragResult,
    mlPrediction: mlResult,
    supervisorComposition: {
      schema_version: "SupervisorCompositionReceipt.v1",
      plan_ref: `model-supervisor:sha256:${"a".repeat(64)}`,
      primary_agent: "ANALYSIS_WORKFLOW",
      agents: ["ANALYSIS_WORKFLOW", "INTERNAL_GUIDELINE", "ML_PREDICTION"],
      evidence_refs: [`model-supervisor:sha256:${"a".repeat(64)}`],
    },
  });
  assert.deepEqual(agentKindsForRun(compositeRun), ["ANALYSIS", "RAG", "ML"]);
  assert.equal(compositeRun.rag.answer_text, "승인 문서 답변");
  assert.equal(compositeRun.mlPrediction, mlResult);
  const executionHtml = renderToStaticMarkup(createElement(AgentExecutionBar, { run: compositeRun }));
  assert.match(executionHtml, /Supervisor/);
  assert.match(executionHtml, /3개 작업 완료/);
  assert.match(executionHtml, /Analysis Agent/);
  assert.match(executionHtml, /RAG Agent/);
  assert.match(executionHtml, /ML Agent/);
  assert.equal((executionHtml.match(/>완료</g) || []).length, 3);

  for (const invalidReceipt of [
    { ...compositeRun.supervisorComposition, schema_version: "invalid" },
    { ...compositeRun.supervisorComposition, agents: ["ANALYSIS_WORKFLOW", "UNKNOWN"] },
    { ...compositeRun.supervisorComposition, agents: ["ANALYSIS_WORKFLOW", "ANALYSIS_WORKFLOW"] },
  ]) {
    const fallbackHtml = renderToStaticMarkup(createElement(AgentExecutionBar, {
      run: { ...compositeRun, supervisorComposition: invalidReceipt },
    }));
    assert.doesNotMatch(fallbackHtml, /Supervisor/);
    assert.match(fallbackHtml, /전문 Agent 협업/);
  }
  assert.deepEqual(agentKindsForRun(ragRun("질문", ragResult)), ["RAG"]);
  assert.deepEqual(agentKindsForRun(mlPredictionRun("질문", mlResult)), ["ML"]);

  assert.doesNotMatch(agentSource, /내부 업무지침 찾아보기|rag-documents|RagEmptyState/);
  assert.match(agentSource, /enabledFeatures\.includes\(SERVICE_FEATURE\.mlPrediction\)/);
  assert.doesNotMatch(agentSource, /mlPredictionEnabled && <MLPredictionWorkspace/);
  assert.doesNotMatch(agentSource, /import MLPredictionWorkspace/);
  assert.match(agentSource, /AgentCapabilityOverview/);
  assert.match(agentSource, /AgentExecutionBar/);
  assert.match(agentSource, /attachAgentResults/);
  assert.doesNotMatch(agentSource, /추천 질문|저장 분석 바로 실행|exampleQuestions/);
  assert.match(agentSource, /이 저장 분석은 현재 데이터 릴리스와 맞지 않아 재실행할 수 없습니다/);

  // 차트 뷰(CHART)로 전환했을 때만 차트 표현 방식 세그먼트와 실제 차트 markup이 나온다.
  const chartHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, { run, viewType: "CHART" }));
  assert.match(chartHtml, /aria-label="차트 표현 방식"/);
  assert.match(chartHtml, /aria-pressed="true">가로 막대<\/button>/);
  assert.match(chartHtml, /enterprise-chart--horizontal-bar/);
  assert.doesNotMatch(chartHtml, /AI 분석 요약/);

  const tableWithPresentationActionHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run,
    viewType: "TABLE",
    onRequestBarPresentation: () => {},
  }));
  assert.match(tableWithPresentationActionHtml, /막대그래프로 보기/);

  const barPresentationHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run,
    viewType: "BAR",
    onRequestBarPresentation: () => {},
    artifactReuse: { viewSpecId: "view-spec-bar" },
  }));
  assert.doesNotMatch(barPresentationHtml, /막대그래프로 보기/);
  assert.match(barPresentationHtml, /기존 분석 재사용 · 새 분석 쿼리 없음/);

  const pendingPresentationHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run,
    viewType: "BAR",
    artifactReuse: { pending: true },
  }));
  assert.doesNotMatch(pendingPresentationHtml, /새 분석 쿼리 없음/);

  const fullHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, { run, viewType: "FULL" }));
  assert.doesNotMatch(fullHtml, /aria-label="차트 표현 방식"/);

  const unsupportedChartHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, chart: { ...run.chart, chartType: "internal_super_chart" } },
    viewType: "CHART",
  }));
  assert.match(unsupportedChartHtml, /현재 지원하지 않는 그래프 형식입니다/);
  assert.doesNotMatch(unsupportedChartHtml, /internal_super_chart|차트 메타데이터|DataHub|AST SQL/);

  const mismatchedChartHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, chart: { ...run.chart, yFields: ["field_not_in_table"] } },
    viewType: "CHART",
  }));
  assert.match(mismatchedChartHtml, /그래프 구성 정보를 확인할 수 없습니다/);
  assert.doesNotMatch(mismatchedChartHtml, /class="enterprise-chart/);

  const donutHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, chart: { ...run.chart, yFields: [run.chart.yFields[0]] } },
    viewType: "DONUT",
  }));
  assert.match(donutHtml, /enterprise-chart--donut/);
  assert.match(donutHtml, /aria-pressed="false">원형<\/button>/);
  assert.match(donutHtml, /aria-pressed="true">도넛<\/button>/);

  const emptyChartHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, table: { ...run.table, rows: [] } },
    viewType: "CHART",
  }));
  assert.match(emptyChartHtml, /그래프로 표시할 데이터가 없습니다/);
  assert.match(emptyChartHtml, /상세 데이터가 없어 값을 임의로 만들지 않았습니다/);
  assert.doesNotMatch(emptyChartHtml, /class="enterprise-chart/);

  const followupHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run,
    viewType: "TABLE",
    artifactReuse: { pending: false, viewSpecId: "view-table" },
    onOpenEvidence: () => {},
  }));
  assert.match(followupHtml, /상세 데이터 표/);
  assert.match(followupHtml, /analysis-data-meta/);
  assert.match(followupHtml, /열 제목을 눌러 정렬/);
  assert.match(followupHtml, /analysis-table-sort/);
  assert.match(followupHtml, /data-result-density="wide"/);
  assert.match(followupHtml, /data-table-density="wide"/);
  assert.match(followupHtml, /is-wide-result/);
  assert.match(followupHtml, /--analysis-table-min-width:1092px/);
  assert.doesNotMatch(followupHtml, /AI 분석 요약/);
  for (const label of ["요약으로 보기", "표로 보기", "그래프로 보기", "KPI만 보기"]) {
    assert.doesNotMatch(followupHtml, new RegExp(label));
  }
  assert.match(followupHtml, /기존 분석 재사용 · 새 분석 쿼리 없음/);
  assert.doesNotMatch(followupHtml, /결과 보기 전환|이전 분석 결과|재조회|연결 정보/);
  assert.doesNotMatch(followupHtml, /DataHub|AST SQL|거버넌스/);

  const regularTableHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: {
      ...run,
      table: {
        columns: run.table.columns.slice(0, 3),
        rows: run.table.rows.slice(0, 8).map((row) => Object.fromEntries(
          run.table.columns.slice(0, 3).map((column) => [column, row[column]]),
        )),
      },
    },
    viewType: "TABLE",
  }));
  assert.match(regularTableHtml, /data-result-density="regular"/);
  assert.match(regularTableHtml, /data-table-density="regular"/);
  assert.doesNotMatch(regularTableHtml, /is-wide-result|--analysis-table-min-width/);

  const manyRowNarrowTable = {
    ...run,
    table: {
      columns: run.table.columns.slice(0, 2),
      rows: Array.from({ length: 30 }, (_, index) => ({
        [run.table.columns[0]]: `2026-08-${String((index % 30) + 1).padStart(2, "0")}`,
        [run.table.columns[1]]: index + 1,
      })),
    },
  };
  assert.equal(analysisResultDensity(manyRowNarrowTable, "TABLE"), "regular");
  const manyRowNarrowTableHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: manyRowNarrowTable,
    viewType: "TABLE",
  }));
  assert.match(manyRowNarrowTableHtml, /data-table-density="regular"/);
  assert.doesNotMatch(manyRowNarrowTableHtml, /is-wide-result|--analysis-table-min-width/);

  const singleMetricField = run.metrics[0].resultField;
  const singleValueTableHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: {
      ...run,
      table: {
        columns: [singleMetricField],
        rows: [{ [singleMetricField]: run.metrics[0].value }],
      },
      rowCount: 1,
    },
    viewType: "TABLE",
  }));
  assert.match(singleValueTableHtml, /data-table-density="single"/);
  assert.match(singleValueTableHtml, /data-result-density="compact"/);
  assert.match(singleValueTableHtml, /is-compact-result is-single-value-result/);
  assert.match(singleValueTableHtml, /analysis-table-label/);
  assert.match(singleValueTableHtml, /단일 결과/);
  assert.doesNotMatch(singleValueTableHtml, /class="row-number"|analysis-table-sort|열 제목을 눌러 정렬/);

  const pendingFollowupHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, elapsedSeconds: 0 },
    viewType: "TABLE",
    artifactReuse: { pending: true },
  }));
  assert.match(pendingFollowupHtml, /data-process-kind="PRESENTATION"/);
  assert.match(pendingFollowupHtml, /요청한 형태로 답변을 구성하고 있습니다/);
  assert.doesNotMatch(pendingFollowupHtml, /이전 분석 결과|재사용|재조회/);
  assert.doesNotMatch(pendingFollowupHtml, /연결 정보/);
  assert.doesNotMatch(pendingFollowupHtml, /상세 데이터 표/);
  assert.doesNotMatch(pendingFollowupHtml, /SQL 실행 중|데이터 조회 중|재분석 중/);

  const unavailableHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, metrics: [], chart: null, table: { columns: [], rows: [] }, rowCount: 1 },
    viewType: "KPI",
    artifactReuse: { pending: false },
  }));
  assert.match(unavailableHtml, /현재 분석 결과로는 KPI 보기를 만들 수 없습니다/);
  assert.match(unavailableHtml, /값을 임의로 만들지 않았습니다/);
  assert.doesNotMatch(unavailableHtml, /Artifact/);
  assert.match(unavailableHtml, /data-view="kpi"/);

  const emptyTableHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, table: { columns: [], rows: [] }, rowCount: 0 },
    viewType: "TABLE",
    artifactReuse: { pending: false },
  }));
  assert.match(emptyTableHtml, /analysis-state--empty/);
  assert.match(emptyTableHtml, /결과 없음/);
  assert.doesNotMatch(emptyTableHtml, /<table/);

  // 실제 렌더 트리가 쓰는 KPI·차트·표 카드 선택자만 검증한다(죽은 ".analysis-dashboard" 조상 선택자는 삭제됨).
  assert.match(stylesSource, /\.analysis-metrics\{/);
  assert.match(stylesSource, /\.analysis-summary-stack\{gap:0;overflow:hidden;border:1px solid var\(--av-paper-line\)/);
  assert.match(stylesSource, /\.analysis-result-section \.analysis-table thead th\{/);
  assert.match(stylesSource, /\.analysis-data-section\.is-single-value-result\{width:min\(100%,460px\)\}/);
  assert.match(stylesSource, /\.analysis-trace\[data-process-flow="vertical"\] ol\{display:grid;grid-template-columns:minmax\(0,1fr\)/);
  assert.match(stylesSource, /\.analysis-summary-answer \.agent-narrative-text\{[^}]*font-size:16px/);
  assert.match(stylesSource, /\.message\.message--user\{[^}]*align-items:center[^}]*justify-content:flex-end/);
  assert.match(stylesSource, /\.message--user>\.turn-user-bubble\{[^}]*margin-left:auto/);
  assert.match(stylesSource, /\.message--user>\.user-icon\{[^}]*border-radius:50%/);
  assert.doesNotMatch(stylesSource, /\.turn-user-bubble \.user-icon|analysis-summary-verified/);
  assert.match(agentSource, /<div className="turn-user-bubble">\s*<div className="user-content">[\s\S]*?<\/div>\s*<\/div>\s*<span className="user-icon"/);
  assert.match(stylesSource, /\.message\.message--agent\{justify-content:flex-start\}/);
  assert.match(stylesSource, /\.chat-layout \.message\.message--agent>\.agent-response-container\{[^}]*padding:0[^}]*border:0[^}]*background:transparent/);
  assert.match(stylesSource, /\.chat-layout \.analysis-state--loading,\.chat-layout \.analysis-state--delayed\{[^}]*grid-template-columns:minmax\(0,1fr\) auto[^}]*border-radius:12px/);
  assert.doesNotMatch(stylesSource, /\.chat-layout \.run-history-panel\{/);
  assert.doesNotMatch(agentSource, /className="run-history-panel"/);
  assert.match(stylesSource, /\.chat-layout \.conversation\{width:min\(100%,var\(--analysis-thread-width\)\)/);
  assert.match(stylesSource, /\.chat-layout \.analysis-notice\{max-width:min\(100%,var\(--analysis-thread-width\)\)/);
  assert.doesNotMatch(stylesSource, /\.chat-layout \.meta-strip/);
  assert.doesNotMatch(agentSource, /verified=\{/);
  assert.doesNotMatch(agentSource, /question-help/);
  assert.doesNotMatch(agentSource, /호텔 운영 데이터 분석과 후속 질문을 한 대화에서 이어갈 수 있습니다/);
  assert.doesNotMatch(agentSource, /승인된 내부 업무지침 질문과 후속 질문을 한 대화에서 이어갈 수 있습니다/);
  assert.doesNotMatch(agentSource, /question\.length\.toLocaleString/);
  assert.match(agentSource, /maxLength=\{MAX_QUESTION_LENGTH\}/);
  assert.match(agentSource, /무엇을 도와드릴까요/);
  assert.match(agentSource, /className="scope-notice-response"/);
  assert.match(agentSource, /답변을 준비하고 있어요/);
  assert.doesNotMatch(agentSource, /onQuickView|quickViewAction/);
  assert.match(stylesSource, /\.theme-light \.analysis-result-section \.analysis-table-sort\{background:transparent\}/);
  assert.match(stylesSource, /\.analysis-data-section \.analysis-table\{[^}]*overflow-x:auto/);
  assert.match(stylesSource, /\.analysis-data-section\.is-compact-result \.analysis-table\{overflow-x:auto/);
  assert.match(stylesSource, /\.analysis-data-section\.is-single-value-result \.analysis-table\{overflow-x:hidden/);
  assert.match(stylesSource, /\.analysis-data-section\.is-wide-result \.analysis-table table\{width:100%;min-width:var\(--analysis-table-min-width,760px\)/);
  assert.match(stylesSource, /\.analysis-kpi-section header small,[^\n]*\.analysis-result-section \.analysis-table thead th,[^\n]*\{font-size:12px\}/);
  assert.match(stylesSource, /\.theme-light \.analysis-state\{--av-ink-3:#5f7085\}/);
  assert.match(stylesSource, /\.analysis-state button:focus-visible/);
  assert.match(stylesSource, /\.analysis-state\{[^}]*--av-paper:#0f1825[^}]*--av-ink:#e8edf5[^}]*--av-chart-grid:#223149/);
  assert.match(stylesSource, /\.theme-light \.analysis-state\{[^}]*--av-paper:#fff[^}]*--av-ink:#15253a[^}]*--av-chart-grid:#e3eaf3/);
  assert.match(stylesSource, /\.analysis-metric-card--total\{[^}]*var\(--av-paper-accent\)/);
  assert.doesNotMatch(stylesSource, /같은 흰 종이 표면|흰 종이 위/);
  assert.match(stylesSource, /\.app-shell\{--app-nav-height:64px;--app-context-height:74px;--app-header-height:calc\(var\(--app-nav-height\) \+ var\(--app-context-height\)\)/);
  assert.match(stylesSource, /\.topbar\{[^}]*grid-template-rows:var\(--app-nav-height\) var\(--app-context-height\)/);
  assert.match(appSource, /<AppHeader page=\{route\.page\}/);
  assert.match(stylesSource, /@media\(max-width:760px\)\{[^\n]*\.top-navigation\{[^}]*overflow-x:auto/);
  assert.match(stylesSource, /\.chat-layout\{[^}]*grid-template-columns:205px minmax\(400px,1fr\) 285px/);
  assert.match(stylesSource, /@media\(min-width:1201px\)\{\.chat-layout\.evidence-open\{grid-template-columns:205px minmax\(400px,1fr\) 340px\}/);
  assert.match(agentSource, /className="chat-scroll-region"/);
  assert.match(agentSource, /대화 결과를 덮지 않는 중앙 하단 입력 영역/);
  assert.match(stylesSource, /html:has\(\.chat-layout\),body:has\(\.chat-layout\)\{height:100%;overflow:hidden\}/);
  assert.match(stylesSource, /\.app-shell:has\(\.chat-layout\)\{height:100dvh;min-height:0;overflow:hidden\}/);
  assert.match(stylesSource, /\.app-shell:has\(\.chat-layout\)>\.workspace\{height:100%;min-height:0;display:grid;grid-template-rows:auto minmax\(0,1fr\);overflow:hidden\}/);
  assert.match(stylesSource, /\.app-shell:has\(\.chat-layout\)>\.workspace>\.page-stage\{min-height:0;overflow:hidden\}/);
  assert.match(stylesSource, /\.chat-main\{padding:0;display:grid;grid-template-rows:minmax\(0,1fr\) auto;overflow:hidden\}/);
  assert.match(stylesSource, /\.chat-scroll-region\{[^}]*overflow:auto[^}]*overscroll-behavior:contain\}/);
  assert.match(stylesSource, /\.chat-scroll-region\{scrollbar-gutter:stable both-edges\}/);
  assert.match(stylesSource, /@media\(max-width:650px\)\{[^\n]*\.chat-scroll-region\{scrollbar-gutter:auto;scrollbar-width:none\}/);
  assert.match(stylesSource, /\.chat-input\{position:static;min-width:0;width:100%;padding:10px 25px calc\(12px \+ env\(safe-area-inset-bottom\)\)\}/);
  assert.match(stylesSource, /\.chat-main>\.chat-input\{background:transparent\}/);
  assert.match(stylesSource, /\.question-field,\.analysis-input-error\{width:min\(100%,920px\);margin-inline:auto\}/);
  assert.match(stylesSource, /@media\(max-width:650px\)\{\.app-shell:has\(\.chat-layout\) \.chat-layout,\.chat-main\{height:100%;min-height:0\}\.chat-main\{padding:0\}\.chat-scroll-region\{padding:12px 12px 28px\}\.chat-input\{max-width:none;padding:10px 12px/);
  assert.doesNotMatch(agentSource, /AnalysisArtifactCollection|analysis-artifact-mobile|compactViewport/);
  assert.match(agentSource, /<span>\{d\.question\}<small>다시 분석하기<\/small><\/span>/);
  assert.doesNotMatch(agentSource, /<span>\{d\.title\}<small>다시 분석하기<\/small><\/span>/);
  assert.match(agentSource, /!turnItem\.isArtifactReuse \? \(\) => void saveAnalysis/);
  assert.match(agentSource, /analysis-notice--\$\{feedback\.tone\}/);
  assert.match(agentSource, /feedback\.tone === "error" \? "alert" : "status"/);
  assert.match(stylesSource, /\.analysis-notice--success/);
  assert.match(stylesSource, /\.analysis-notice--error/);
  assert.match(agentSource, /prefers-reduced-motion: reduce/);
  assert.match(agentSource, /scrollIntoView\(\{[\s\S]*?block: "end"/);
  assert.match(agentSource, /className="conversation-end"/);
  assert.doesNotMatch(appSource + stylesSource, /AppSidebar|\.mobile-menu\{|(?:^|\n)\.sidebar\{/);

  // 서버 unit이 "KRW"여도 화면 표기는 보고서와 같은 한국어 배율 라벨로 통일한다(KRW 노출 회귀 방지).
  const krwHtml = renderToStaticMarkup(createElement(AnalysisStatePanel, {
    run: { ...run, metrics: run.metrics.map((metric) => ({ ...metric, unit: "KRW", value: 33005912094 })) },
  }));
  assert.match(krwHtml, />330\.1<em>억 원<\/em>/);
  assert.match(krwHtml, /title="33,005,912,094 원"/);
  assert.doesNotMatch(krwHtml, /KRW/);

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
