import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  normalizeApiResponse,
  OPENAPI_VERSION,
  resolveViewState,
  UI_CONTRACT_VERSION,
} from "../../app/enterprise-react/src/contracts/analysis.ts";
import {
  approveDraft,
  createDraft,
  createReportRun,
  normalizeDraftLayout,
  REPORT_CONTRACT_VERSION,
  REPORT_RUN_STATUSES,
  serializeDraftLayout,
} from "../../app/enterprise-react/src/contracts/report.ts";
import {
  analysisFixtures,
  FIXTURE_VERSION,
} from "../../app/enterprise-react/src/data/analysisFixtures.ts";
import { resolveRoute } from "../../app/enterprise-react/src/routing.js";
import { catalogSources, I3_DATA_CONTRACT_VERSION } from "../../app/enterprise-react/src/data/catalogFixtures.ts";
import { createHttpAnalysisClient, usesMockAnalysisClient } from "../../app/enterprise-react/src/api/analysisClient.ts";
import { createReportClient, ReportApiError, usesFixtureReportClient } from "../../app/enterprise-react/src/api/reportClient.ts";

const packageJson = JSON.parse(readFileSync(new URL("../../app/enterprise-react/package.json", import.meta.url)));
const g1ClarificationFixture = JSON.parse(
  readFileSync(new URL("../backend/fixtures/api/v0.1/g1_clarification.json", import.meta.url)),
);
const timeoutFixture = JSON.parse(
  readFileSync(new URL("../backend/fixtures/api/v0.1/timeout.json", import.meta.url)),
);
const reportsPageSource = readFileSync(
  new URL("../../app/enterprise-react/src/pages/ReportsPage.jsx", import.meta.url),
  "utf8",
);
const agentPageSource = readFileSync(
  new URL("../../app/enterprise-react/src/pages/AgentPage.jsx", import.meta.url),
  "utf8",
);
const stylesSource = readFileSync(
  new URL("../../app/enterprise-react/src/styles.css", import.meta.url),
  "utf8",
);
const sidebarSource = readFileSync(
  new URL("../../app/enterprise-react/src/components/layout/AppSidebar.jsx", import.meta.url),
  "utf8",
);
const appSource = readFileSync(
  new URL("../../app/enterprise-react/src/App.jsx", import.meta.url),
  "utf8",
);
const analysisStatePanelSource = readFileSync(
  new URL("../../app/enterprise-react/src/components/analysis/AnalysisStatePanel.tsx", import.meta.url),
  "utf8",
);
assert.equal(UI_CONTRACT_VERSION, "UI-v1.0.0");
assert.equal(REPORT_CONTRACT_VERSION, "REPORT-v1.0.0");
assert.deepEqual(REPORT_RUN_STATUSES, ["queued", "running", "success", "partial", "failed", "cancelled"]);
assert.equal(FIXTURE_VERSION, "UI-FIXTURE-v1.0.0");
assert.equal(OPENAPI_VERSION, "OPENAPI-v1.0.0");
assert.ok(Object.values({ ...packageJson.dependencies, ...packageJson.devDependencies }).every((version) => version !== "latest"));
assert.equal(resolveRoute("/customers").page, "notFound");
assert.equal(resolveRoute("/catalog/tools").page, "notFound");
assert.match(sidebarSource, /const SHOW_ADMIN_NAV = true/);
assert.match(sidebarSource, /SHOW_ADMIN_NAV && renderGroup\("admin", "ADMINISTRATION"\)/);
assert.match(appSource, /const \[menuOpen, setMenuOpen\] = useState\(true\)/);
assert.match(appSource, /window\.history\.pushState[\s\S]*setMenuOpen\(false\)/);
assert.match(appSource, /new CustomEvent\("answervice:navigate", \{ detail: nextRoute\.path \}\)/);
assert.match(appSource, /sidebar-collapsed/);
assert.match(appSource, /const USE_PPT_THEME = true/);
assert.match(appSource, /USE_PPT_THEME \? "ppt-theme"/);
assert.match(stylesSource, /\.ppt-theme\{[^}]*--blue:#1c69d4/);
assert.match(stylesSource, /\.ppt-theme\{[^}]*--coral:#e22718/);
assert.match(stylesSource, /PPT theme preview: keep the original theme above intact for one-flag rollback/);
assert.match(stylesSource, /Presentation visual system: black canvas, technical rules, white type, blue\/red signals/);
assert.match(stylesSource, /\.ppt-theme\{--ivory:#000;--ivory-2:#030509;--surface:#05070b;--border:#2a3443;--radius:2px;background:#000\}/);
assert.match(stylesSource, /\.ppt-theme \.section-title:after\{[^}]*linear-gradient\(90deg,#1c69d4 0 68%,#e22718 68% 100%\)/);
assert.match(stylesSource, /\.ppt-theme \.message b em\{color:#fff!important;border:1px solid #1c69d4;border-radius:2px;background:#102a4d!important\}/);
assert.match(stylesSource, /\.ppt-theme \.message b em,\.ppt-theme \.analysis-state>header span\{color:#fff!important;border:1px solid #1c69d4!important;border-radius:2px;background:#102a4d!important/);
assert.match(stylesSource, /\.ppt-theme \.analysis-state>footer code\{[^}]*color:#fff!important[^}]*background:#102a4d!important/);
assert.match(stylesSource, /\.ppt-theme \.editor-topbar>div:first-child>button,\.ppt-theme \.legacy-document-actions>button\{[^}]*border:1px solid #1c69d4!important[^}]*background:#102a4d!important/);
assert.match(stylesSource, /\.ppt-theme \.report-preview-summary dl div\{[^}]*border-color:#26344a[^}]*background:#101725\}/);
assert.match(stylesSource, /\.ppt-theme \.report-preview-summary dd\{color:#fff\}/);
assert.match(reportsPageSource, /const \[chartPrompt, setChartPrompt\] = useState\("객실 매출과 점유율 변화를 비교해줘"\)/);
assert.match(reportsPageSource, /const generateChart = \(\) => \{/);
assert.match(reportsPageSource, /prompt\.includes\("연회"\)/);
assert.match(reportsPageSource, /prompt\.includes\("예약"\)/);
assert.match(reportsPageSource, /onClick=\{generateChart\}/);
assert.match(reportsPageSource, /addBlock\(\{ \.\.\.chart, type: "chart"[^;]+\}, true\)/);
assert.match(reportsPageSource, /\.editor-canvas \.editor-block\.selected/);
assert.match(reportsPageSource, /scrollIntoView\(\{ behavior: "smooth", block: "center" \}\)/);
assert.match(stylesSource, /\.enterprise-report-editor\{height:100vh;min-height:0;overflow:hidden\}/);
assert.match(stylesSource, /\.editor-workspace\{height:100vh;display:flex;flex-direction:column;overflow:hidden\}/);
assert.match(stylesSource, /\.editor-topbar,\.editor-selection-toolbar\{flex:none\}/);
assert.match(stylesSource, /\.editor-canvas\{min-height:0;flex:1;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable\}/);
assert.match(reportsPageSource, /const insertBlock = \(current, block, targetId, position = "after"\)/);
assert.match(reportsPageSource, /const isBasicDocumentBlock = \(block\) => block\.origin === "basic"/);
assert.match(reportsPageSource, /const hasReportNumber = \(block\) => block\.type !== "divider" && !isBasicDocumentBlock\(block\)/);
assert.match(reportsPageSource, /\{number && <span>\{String\(number\)\.padStart\(2, "0"\)\}<\/span>\}/);
assert.match(reportsPageSource, /updateDropTarget\(event, block\.id\)/);
assert.match(reportsPageSource, /className="editor-drag-handle"[^>]*draggable/);
assert.match(reportsPageSource, /여기에 블록을 놓으세요/);
assert.match(stylesSource, /\.editor-block\.drop-before:before,\.editor-block\.drop-after:after/);
assert.match(stylesSource, /\.ppt-theme \.brand-mark\{[^}]*background:#1c69d4/);
assert.match(stylesSource, /\.ppt-theme \.brand>button\{position:absolute;top:8px;right:8px/);
assert.match(stylesSource, /\.ppt-theme \.brand b:after\{width:112px;height:3px[^}]*linear-gradient\(90deg,#1c69d4 0 18%,#e22718 18% 28%,#fff 28% 100%\)/);
assert.match(stylesSource, /\.ppt-theme \.section-title:after\{width:112px;height:3px;background:linear-gradient\(90deg,#1c69d4 0 18%,#e22718 18% 28%,#fff 28% 100%\)\}/);
assert.match(stylesSource, /\.ppt-theme,\.ppt-theme button,\.ppt-theme input,[^}]*\.ppt-theme label\{font-weight:700\}/);
assert.doesNotMatch(stylesSource, /linear-gradient\(135deg,#1c69d4 0 64%,#e22718 64% 100%\)/);
assert.match(stylesSource, /\.ppt-theme \.analysis-chart \.recharts-line-curve\{stroke:#1c69d4;stroke-width:3\}/);
assert.match(stylesSource, /\.ppt-theme \.analysis-chart \.recharts-dot\{fill:#e22718;stroke:#fff\}/);
assert.match(stylesSource, /\.ppt-theme \.analysis-state--ready,\.ppt-theme \.analysis-state--partial\{border-color:#26344a;background:#0f1522\}/);
assert.match(stylesSource, /\.bar-fill\{color:#fff\}/);
assert.match(stylesSource, /\.ppt-theme \.demo-steps\{[^}]*color:#fff!important[^}]*background:transparent!important/);
assert.match(stylesSource, /\.ppt-theme \.demo-steps b,\.ppt-theme \.demo-steps b\.done,\.ppt-theme \.demo-steps b\.active,\.ppt-theme \.demo-steps>span\{color:#fff!important;background:transparent!important\}/);
assert.match(stylesSource, /\.sidebar-collapsed \.sidebar\{transform:translateX\(-100%\)\}/);
assert.match(stylesSource, /\.sidebar-collapsed \.workspace\{margin-left:0\}/);

for (const [expected, run] of Object.entries(analysisFixtures)) {
  assert.equal(resolveViewState(run).toLowerCase(), expected === "clarification" ? "empty" : expected);
}

const clarification = normalizeApiResponse(
  g1ClarificationFixture,
  "지난달 객실 매출을 알려줘.",
  "conv-clarification-001",
);
assert.equal(clarification.status, "blocked");
assert.equal(resolveViewState(clarification), "EMPTY");
assert.equal(clarification.error.code, "CONTEXT_INCOMPLETE");
assert.equal(clarification.error.message, "분석 기간을 입력해 주세요.");
assert.equal(clarification.requestId, "00000000-0000-0000-0000-000000000100");
assert.equal(clarification.traceId, "fixture-g1-clarification");
assert.equal(clarification.artifact, undefined);

const timeout = normalizeApiResponse(timeoutFixture, "객실 분석", "conv-timeout-001");
assert.equal(timeout.status, "failed");
assert.equal(resolveViewState(timeout), "ERROR");
assert.equal(timeout.error.code, "QUERY_SOURCE_FAILED");
assert.equal(timeout.error.message, "조회 시간이 초과되었습니다.");
assert.equal(timeout.error.retryable, true);
assert.equal(timeout.artifact, undefined);
assert.equal(timeout.traceId, "fixture-timeout");
assert.deepEqual(analysisFixtures.error.error, timeout.error);
assert.equal(analysisFixtures.error.traceId, timeout.traceId);
assert.match(analysisStatePanelSource, /<dd>{run\.error\.code}<\/dd>/);
assert.match(analysisStatePanelSource, /<dd>{String\(run\.error\.retryable\)}<\/dd>/);

const normalized = normalizeApiResponse({
  data: {
    status: "SUCCEEDED",
    transitions: ["RECEIVED", "ROUTED", "SUCCEEDED"],
    artifact: {
      artifact_id: "artifact-api-001",
      query_id: "query-api-001",
      context_hash: "context-api-001",
    },
    result: {
      summary: "Fake 분석 결과입니다.",
      metrics: [{ metric_id: "recognized_room_revenue", label: "인식 객실 매출", value: 128400000, unit: "KRW" }],
      table: { columns: ["business_date", "recognized_room_revenue"], rows: [{ business_date: "2026-07-30", recognized_room_revenue: 128400000 }] },
      chart: { chart_type: "line", x_field: "business_date", y_fields: ["recognized_room_revenue"] },
      evidence: {
        artifact_id: "artifact-api-001",
        query_id: "query-api-001",
        as_of: "2026-07-30",
        period: { start: "2026-07-01", end_exclusive: "2026-08-01" },
        filters: { hotel: "synthetic" },
        cached: false,
        sampling: { applied: false, returned_rows: 1, total_rows: 1 },
        sources: [{
          name: "PMS guest fixture",
          urn: "urn:answervice:dataset:pms.public.pms_guests",
          fqn: "pms.public.pms_guests",
          schema_version: "1.0.0",
          seed_version: "20260729",
        }],
      },
    },
  },
  meta: { request_id: "req-api-001", trace_id: "trace-api-001", as_of: "2026-07-30", contract_version: OPENAPI_VERSION, timestamp: "2026-07-30T03:00:00Z" },
  error: null,
}, "객실 분석", "conv-api-001");
assert.equal(normalized.status, "success");
assert.equal(normalized.requestId, "req-api-001");
assert.equal(normalized.traceId, "trace-api-001");
assert.equal(normalized.artifact.artifactId, "artifact-api-001");
assert.equal(normalized.artifact.queryId, "query-api-001");
assert.deepEqual(normalized.metrics[0], {
  metricId: "recognized_room_revenue",
  label: "인식 객실 매출",
  value: 128400000,
  unit: "KRW",
});
assert.equal(normalized.table.rows[0].recognized_room_revenue, 128400000);
assert.equal(normalized.chart.xField, "business_date");
assert.deepEqual(normalized.evidence.filters, { hotel: "synthetic" });
assert.deepEqual(normalized.evidence.period, { start: "2026-07-01", endExclusive: "2026-08-01" });
assert.equal(normalized.sources[0].urn, "urn:answervice:dataset:pms.public.pms_guests");
assert.equal(normalized.sources[0].schemaVersion, "1.0.0");
assert.equal(normalized.meta.seed, "20260729");
assert.equal(normalized.rowCount, 1);
assert.equal(analysisFixtures.ready.artifact.artifactId, analysisFixtures.ready.evidence.artifactId);
assert.equal(analysisFixtures.ready.metrics[0].unit, "KRW");
assert.ok(analysisFixtures.ready.table.rows.length > 0);
for (const source of analysisFixtures.ready.sources) {
  const catalogSource = catalogSources.find((candidate) => candidate.fqn === source.fqn);
  assert.ok(catalogSource, `analysis source must exist in catalog: ${source.fqn}`);
  assert.equal(source.urn, catalogSource.datasetUrn);
}
assert.equal(usesMockAnalysisClient, false);
assert.equal(usesFixtureReportClient, false);
assert.match(reportsPageSource, /usesFixtureReportClient \? <FixtureReportsPage \/> : <ReportApiPage \/>/);
assert.match(reportsPageSource, /오류 시 fixture로 전환하지 않습니다/);
assert.match(reportsPageSource, /401 · 로그인이 필요합니다/);
assert.match(reportsPageSource, /403 · REPORT_ADMIN 권한이 필요합니다/);
assert.match(reportsPageSource, /candidate\.artifactId/);
assert.match(reportsPageSource, /artifactId: candidate\.artifactId/);
assert.match(reportsPageSource, /LOCAL SYNTHETIC FIXTURE/);
assert.match(reportsPageSource, /aria-label={`\$\{block\.title} 앞으로 이동`}/);
assert.match(reportsPageSource, /aria-label={`\$\{block\.title} 너비 늘리기`}/);
assert.match(reportsPageSource, /aria-label={`\$\{block\.title} 높이 늘리기`}/);
assert.match(reportsPageSource, /aria-label={`\$\{block\.title} 삭제`}/);
assert.doesNotMatch(reportsPageSource, /targetView === "editor" && report\.status !== "초안"/);
assert.doesNotMatch(reportsPageSource, /report\.status === "초안" && <button className="edit"/);
assert.match(reportsPageSource, /className="edit".*openReport\(report, "editor"\).*편집/);
assert.match(reportsPageSource, /초안과 확정 보고서 모두 편집할 수 있으며/);
assert.match(reportsPageSource, /<button className="view"/);
assert.match(stylesSource, /\.legacy-report-actions\{[^}]*display:flex/);
assert.match(agentPageSource, /보고서 초안에 추가/);
assert.match(agentPageSource, /선택한 내용으로 초안 만들기/);
assert.doesNotMatch(agentPageSource, /answervice\.report\.openEditor/);
assert.match(reportsPageSource, /const \[view, setView\] = useState\("list"\)/);
assert.match(reportsPageSource, /id: importedId, type: "주간".*status: "초안"/);
assert.match(reportsPageSource, /candidate\.blocks\?\.length/);
assert.match(reportsPageSource, /artifact\.title \|\| artifact\.blocks/);
assert.match(reportsPageSource, /window\.localStorage\.setItem\("answervice\.reports"/);
assert.match(reportsPageSource, /확정 보고서의 변경사항을 저장했습니다/);
assert.match(reportsPageSource, /block\.type === "kpi" \? block\.content\.replaceAll\(" · ", "\\n"\)/);
assert.match(reportsPageSource, /여름 성수기 객실 운영 주간 보고/);
assert.match(reportsPageSource, /회원 예약 전환 및 객실 운영 보고/);
assert.match(reportsPageSource, /const mockReportBlocks =/);
assert.match(reportsPageSource, /report\.title \? mockReportBlocks\(report\) : initialEditorBlocks\(\)/);
assert.match(reportsPageSource, /window\.addEventListener\("answervice:navigate", showReportList\)/);
assert.match(reportsPageSource, /event\.detail === "\/reports"[\s\S]*setView\("list"\)/);
assert.match(agentPageSource, /4,520 → 4,010만원/);
assert.match(agentPageSource, /객실 매출\(만원\) 4,520→4,010/);
assert.match(reportsPageSource, /block\.labels\?\.\[index\] \?\? value/);
for (const status of REPORT_RUN_STATUSES) assert.match(reportsPageSource, new RegExp(`status: "${status}"`));
assert.match(reportsPageSource, /Run History 상태·접근성 점검/);
assert.match(reportsPageSource, /성공·부분 성공·실패 블록/);
assert.match(reportsPageSource, /aria-live="polite"/);
assert.match(reportsPageSource, /aria-pressed=\{selectedRunId === run\.id\}/);
assert.match(reportsPageSource, /detailRef\.current\?\.focus\(\)/);
assert.match(reportsPageSource, /REPORT_ADMIN 권한이 없는 사용자/);
assert.match(reportsPageSource, /로컬 실행 이력을 불러오는 중/);
assert.match(reportsPageSource, /표시할 실행 이력이 없습니다/);
assert.match(reportsPageSource, /실행 이력을 불러오지 못했습니다/);
assert.match(reportsPageSource, /return usesFixtureReportClient \? <FixtureReportsPage \/> : <ReportApiPage \/>/);
assert.match(stylesSource, /\.ppt-theme \.legacy-report-row>b small\{[^}]*color:#fff!important[^}]*font-size:14px[^}]*font-weight:800/);
assert.match(stylesSource, /grid-template-columns:repeat\(12,minmax\(0,1fr\)\)/);
assert.match(stylesSource, /grid-column:var\(--block-x\)\/span var\(--block-w\)/);
assert.match(stylesSource, /\.editor-block\{[^}]*grid-row:auto;[^}]*overflow:visible/);
assert.match(stylesSource, /\.editor-block textarea\{[^}]*field-sizing:content/);
assert.match(reportsPageSource, /origin: "basic"/);
assert.match(reportsPageSource, /block\.origin !== "basic" && <div>/);
assert.match(stylesSource, /\.editor-block--basic\{[^}]*border:0;[^}]*background:transparent/);
assert.match(stylesSource, /\.editor-block--divider hr\{[^}]*border-top-color/);
assert.match(reportsPageSource, /const \[selectedBlockId, setSelectedBlockId\] = useState\(null\)/);
assert.match(reportsPageSource, /className="card editor-selection-toolbar"/);
assert.match(reportsPageSource, /setBlockWidth\(selectedBlock\.id, 6\)/);
assert.match(reportsPageSource, /duplicateBlock\(selectedBlock\.id\)/);
assert.match(reportsPageSource, /event\.key\.toLowerCase\(\) === "s"/);
assert.match(reportsPageSource, /saveState === "saving"/);
assert.match(reportsPageSource, /const withReportTitle =/);
assert.match(reportsPageSource, /function GeneratedReportBlock/);
assert.match(reportsPageSource, /reportTitleBlock\?\.content/);
assert.match(reportsPageSource, /className="generated-report-grid"/);
assert.match(reportsPageSource, /function buildGeneratedReportLayout/);
assert.match(reportsPageSource, /reportNumber: hasReportNumber\(block\) \? sectionNumber\+\+ : null/);
assert.match(reportsPageSource, /isBasicDocumentBlock\(block\) && block\.type === "heading"[\s\S]*generated-report-heading/);
assert.match(reportsPageSource, /isBasicDocumentBlock\(block\) && block\.type === "text"[\s\S]*generated-report-text/);
assert.match(stylesSource, /\.generated-report-basic\{grid-column:span var\(--report-block-width\)/);
assert.match(stylesSource, /\.generated-report-grid\{[^}]*repeat\(12,minmax\(0,1fr\)\)/);
assert.match(stylesSource, /\.generated-report-block\{[^}]*grid-column:span var\(--report-block-width\)/);
assert.match(stylesSource, /\.generated-report-copy,.generated-report-block blockquote\{font-size:17px;line-height:1\.85\}/);
assert.match(stylesSource, /\.generated-report-kpi\{font-size:clamp\(26px,2vw,30px\)/);
assert.match(stylesSource, /button:focus-visible/);
assert.match(stylesSource, /@media\(max-width:900px\)/);
assert.match(stylesSource, /@media\(max-width:650px\).*\.editor-block\{grid-column:1\/-1;grid-row:auto/s);
assert.match(stylesSource, /\.report-run-fixture button:focus-visible/);
assert.match(stylesSource, /@media\(max-width:480px\).*\.report-run-list,\.report-view-states\{grid-template-columns:1fr\}/s);

let httpRequest;
const httpClient = createHttpAnalysisClient("http://backend.test/", async (url, init) => {
  httpRequest = { url, init };
  return new Response(JSON.stringify(g1ClarificationFixture), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
const httpRun = await httpClient.analyze("기간 없는 질문", "conv-http-001", "ready");
assert.equal(httpRequest.url, "http://backend.test/analysis");
assert.equal(httpRequest.init.method, "POST");
assert.equal(httpRequest.init.headers["X-Contract-Version"], OPENAPI_VERSION);
assert.equal(JSON.parse(httpRequest.init.body).template_id, "weekly-room-operations");
assert.equal(httpRun.requestId, g1ClarificationFixture.meta.request_id);
assert.equal(httpRun.traceId, g1ClarificationFixture.meta.trace_id);
assert.equal(httpRun.error.retryable, false);

const reportDefinitionResponse = {
  contract_version: REPORT_CONTRACT_VERSION,
  definition_id: "00000000-0000-0000-0000-000000000101",
  version: 1,
  status: "draft",
  title: "주간 운영 보고서",
  blocks: [{
    block_id: "00000000-0000-0000-0000-000000000102",
    title: "관리자 메모",
    artifact_id: null,
    query_id: null,
    columns: 12,
    type: "text",
    x: 0,
    y: 0,
    w: 12,
    h: 2,
    content: "검토 내용",
  }],
  approved_at: null,
};
const reportRunResponse = {
  contract_version: REPORT_CONTRACT_VERSION,
  run_id: "00000000-0000-0000-0000-000000000103",
  definition_id: reportDefinitionResponse.definition_id,
  definition_version: 1,
  as_of: "2026-08-04T00:00:00Z",
  policy_version: "policy-v1",
  context_hash: "sha256-context",
  watermark: { pms: "2026-08-04T00:00:00Z" },
  status: "success",
  blocks: [{
    block_id: reportDefinitionResponse.blocks[0].block_id,
    artifact_id: "00000000-0000-0000-0000-000000000104",
    query_id: "00000000-0000-0000-0000-000000000105",
    snapshot_checksum: "sha256-snapshot",
    status: "success",
  }],
};
const manualCommandResponse = {
  contract_version: REPORT_CONTRACT_VERSION,
  command_id: "00000000-0000-0000-0000-000000000106",
  definition_id: reportDefinitionResponse.definition_id,
  version: 1,
  as_of: "2026-08-04T00:00:00Z",
  idempotency_key: "00000000-0000-0000-0000-000000000107",
  status: "queued",
};
const reportResponses = [
  reportDefinitionResponse,
  { contract_version: REPORT_CONTRACT_VERSION, items: [reportDefinitionResponse] },
  reportDefinitionResponse,
  { ...reportDefinitionResponse, status: "approved", approved_at: "2026-08-04T00:00:00Z" },
  { ...reportDefinitionResponse, version: 2 },
  reportDefinitionResponse,
  { contract_version: REPORT_CONTRACT_VERSION, items: [reportRunResponse] },
  reportRunResponse,
  manualCommandResponse,
];
const reportRequests = [];
const reportClient = createReportClient("http://backend.test/", async (url, init) => {
  reportRequests.push({ url, init });
  return new Response(JSON.stringify(reportResponses.shift()), { status: 200, headers: { "Content-Type": "application/json" } });
});
const blockRequest = {
  block_id: reportDefinitionResponse.blocks[0].block_id,
  title: "관리자 메모",
  columns: 12,
  type: "text",
  x: 0,
  y: 0,
  w: 12,
  h: 2,
  content: "검토 내용",
};
await reportClient.createDefinition({ definition_id: reportDefinitionResponse.definition_id, title: "주간 운영 보고서", blocks: [blockRequest] });
await reportClient.listDefinitions();
await reportClient.getDefinition(reportDefinitionResponse.definition_id, 1);
await reportClient.approveDefinition(reportDefinitionResponse.definition_id, 1, "2026-08-04T00:00:00Z");
await reportClient.createNextDraft(reportDefinitionResponse.definition_id, 1);
await reportClient.replaceDraftBlocks(reportDefinitionResponse.definition_id, 1, [blockRequest]);
await reportClient.listRuns(reportDefinitionResponse.definition_id);
await reportClient.getRun(reportRunResponse.run_id);
const manualReceipt = await reportClient.createManualRun({
  definition_id: reportDefinitionResponse.definition_id,
  version: 1,
  as_of: manualCommandResponse.as_of,
  idempotency_key: manualCommandResponse.idempotency_key,
});
assert.equal(reportRequests.length, 9);
assert.deepEqual(reportRequests.map(({ init }) => init.method), ["POST", "GET", "GET", "POST", "POST", "PUT", "GET", "GET", "POST"]);
for (const { init } of reportRequests) {
  assert.equal(init.headers.Authorization, "Bearer synthetic-local");
  assert.equal(init.headers["X-Contract-Version"], "OPENAPI-v1.0.0");
  assert.equal(init.headers["X-Role"], "report_admin");
  assert.equal(init.headers["X-Timezone"], "Asia/Seoul");
  assert.match(init.headers["X-Trace-Id"], /^[0-9a-f-]{36}$/);
}
assert.deepEqual(Object.keys(JSON.parse(reportRequests[8].init.body)).sort(), ["as_of", "definition_id", "idempotency_key", "version"]);
assert.equal(manualReceipt.status, "queued");
assert.equal("run_id" in manualReceipt, false);

let failedRequestCount = 0;
const failingReportClient = createReportClient("http://backend.test", async () => {
  failedRequestCount += 1;
  return new Response(JSON.stringify({ error: { code: "REPORT_FORBIDDEN", message: "권한이 없습니다." } }), { status: 403 });
});
await assert.rejects(() => failingReportClient.listDefinitions(), (error) => error instanceof ReportApiError && error.status === 403 && error.code === "REPORT_FORBIDDEN");
assert.equal(failedRequestCount, 1);

const wrongVersionClient = createReportClient("http://backend.test", async () => new Response(JSON.stringify({ contract_version: "REPORT-v2.0.0", items: [] }), { status: 200 }));
await assert.rejects(() => wrongVersionClient.listDefinitions(), /지원하지 않는 Report 계약/);

const approved = Object.freeze({
  definitionId: "report-001",
  version: 1,
  status: "approved",
  title: "주간 운영 보고서",
  blocks: Object.freeze([{ id: "block-001", title: "객실 매출", artifactId: "artifact-001", columns: 6 }]),
});
const draft = createDraft(approved);
const next = approveDraft(draft, "2026-07-30T12:00:00+09:00");

assert.equal(approved.version, 1);
assert.equal(draft.version, 2);
assert.equal(next.version, 2);
assert.equal(next.status, "approved");
assert.ok(Object.isFrozen(next));
assert.ok(Object.isFrozen(next.blocks));
assert.throws(() => approveDraft(approved, "2026-07-30T12:00:00+09:00"), /draft Report version/);

const layout = normalizeDraftLayout([
  { id: "a", title: "A", artifactId: "artifact-a", columns: 8, w: 8, h: 3 },
  { id: "b", title: "B", artifactId: "artifact-b", columns: 6, w: 6, h: 4 },
]);
assert.deepEqual(layout.map(({ x, y, w, h }) => ({ x, y, w, h })), [
  { x: 0, y: 0, w: 8, h: 3 },
  { x: 0, y: 3, w: 6, h: 4 },
]);
const serializedLayout = JSON.parse(serializeDraftLayout(layout));
assert.equal(serializedLayout[0].artifactId, "artifact-a");
assert.deepEqual(
  Object.fromEntries(["x", "y", "w", "h"].map((key) => [key, serializedLayout[0][key]])),
  { x: 0, y: 0, w: 8, h: 3 },
);
assert.throws(() => approveDraft({ ...draft, blocks: [{ ...draft.blocks[0], x: 8, w: 5 }] }, "2026-07-30T12:00:00+09:00"), /1~12 범위/);

const reportRun = createReportRun({
  runId: "run-001",
  definitionId: next.definitionId,
  definitionVersion: next.version,
  asOf: "2026-07-30T12:00:00+09:00",
  policyVersion: "policy-v1",
  contextHash: "context-001",
  watermark: { pms: "2026-07-28T05:00:00.000Z" },
  status: "partial",
  blocks: [{ blockId: "block-001", artifactId: "artifact-001", queryId: "query-001", snapshotChecksum: "sha256-001", status: "partial" }],
});
assert.ok(Object.isFrozen(reportRun));
assert.ok(Object.isFrozen(reportRun.watermark));
assert.ok(Object.isFrozen(reportRun.blocks));
assert.equal(reportRun.definitionVersion, 2);

const i3Contract = JSON.parse(readFileSync(new URL("../../src/data/i3_contract.v1.json", import.meta.url)));
assert.equal(I3_DATA_CONTRACT_VERSION, i3Contract.contract_version);
assert.equal(catalogSources.length, 5);
for (const source of catalogSources) {
  const recipe = i3Contract.metadata.recipes.find((item) => item.source_id === source.sourceId);
  const check = i3Contract.catalog_checks.find((item) => item.source_id === source.sourceId);
  assert.ok(recipe, source.sourceId);
  assert.ok(check, source.sourceId);
  assert.equal(source.ingestionStatus, recipe.status);
  assert.equal(source.ingestionId, recipe.ingestion_id);
  assert.equal(source.datasetUrn, recipe.dataset_urn);
  assert.equal(source.fqn, recipe.fqn);
  assert.equal(source.catalogCheckFqn, check.fqn);
  assert.equal(source.sha256, check.sha256);
}

const apiCases = [
  ["g1_clarification", "EMPTY"],
  ["g2_blocked", "ERROR"],
  ["g3_failed", "INSUFFICIENT_EVIDENCE"],
  ["timeout", "ERROR"],
  ["partial", "PARTIAL"],
  ["cancelled", "CANCELLED"],
];
for (const [name, expectedView] of apiCases) {
  const fixtureResponse = JSON.parse(readFileSync(new URL(`../backend/fixtures/api/v0.1/${name}.json`, import.meta.url)));
  const fixtureRun = normalizeApiResponse(fixtureResponse, name, `conv-${name}`);
  assert.equal(resolveViewState(fixtureRun), expectedView);
  assert.equal(fixtureRun.error.code, fixtureResponse.error.code);
  assert.equal(fixtureRun.error.message, fixtureResponse.error.message);
  assert.equal(fixtureRun.error.retryable, fixtureResponse.error.retryable);
}

console.log("R5 contract checks passed");
