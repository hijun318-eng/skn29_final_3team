import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normalizeApiResponse, OPENAPI_VERSION, resolveViewState, UI_CONTRACT_VERSION } from "../../app/frontend/src/contracts/analysis.ts";
import { compactDraftLayout, placeDraftBlock, REPORT_CONTRACT_VERSION, REPORT_RUN_STATUSES, reorderDraftBlocks, seoulWallClockToIso } from "../../app/frontend/src/contracts/report.ts";
import { AnalysisApiError, createAnalysisClient, createHttpAnalysisClient } from "../../app/frontend/src/api/analysisClient.ts";
import { createReportClient, ReportApiError } from "../../app/frontend/src/api/reportClient.ts";
import { resolveRoute } from "../../app/frontend/src/routing.js";
import { dataProvenanceLabel } from "../../app/frontend/src/utils/presentation.ts";

const source = (path) => readFileSync(new URL(`../../app/frontend/src/${path}`, import.meta.url), "utf8");
const nginx = readFileSync(new URL("../../app/frontend/nginx.conf", import.meta.url), "utf8");
const productSources = [
  "App.jsx", "routing.js", "api/analysisClient.ts", "api/reportClient.ts",
  "pages/AgentPage.jsx", "pages/ReportsPage.jsx",
  "components/analysis/AnalysisStatePanel.tsx", "components/layout/AppHeader.jsx", "components/layout/AppSidebar.jsx",
].map(source).join("\n");

assert.equal(UI_CONTRACT_VERSION, "UI-v1.0.0");
assert.equal(OPENAPI_VERSION, "OPENAPI-v1.0.0");
assert.equal(REPORT_CONTRACT_VERSION, "REPORT-v1.0.0");
assert.match(nginx, /location \/assets\/ \{[\s\S]*try_files \$uri =404/);
assert.match(nginx, /Cache-Control "no-cache, no-store, must-revalidate"/);
assert.deepEqual(REPORT_RUN_STATUSES, ["queued", "running", "success", "partial", "failed", "cancelled"]);
assert.equal(resolveRoute("/").path, "/agent");
assert.equal(resolveRoute("/agent").page, "chat");
assert.equal(resolveRoute("/reports").page, "reports");
assert.equal(resolveRoute("/catalog").page, "notFound");
assert.equal(resolveRoute("/connections").page, "notFound");

for (const forbidden of [
  /analysisFixtures|catalogFixtures|enterpriseDemoData/,
  /usesMockAnalysisClient|usesFixtureReportClient/,
  /localStorage/,
  /RECENT_ANALYSES|TRACE_STEPS|SYNTHETIC EXECUTION TRACE/,
  /CatalogPage|ConnectionsPage|Customer360Page/,
  /VITE_ANALYSIS_MODE|VITE_REPORT_MODE/,
  /2026-06-01|2026-07-01/,
]) assert.doesNotMatch(productSources, forbidden);

assert.doesNotMatch([
  source("components/auth/SessionLogin.jsx"), source("api/analysisClient.ts"), source("api/reportClient.ts"),
].join("\n"), /localStorage|sessionStorage/);
assert.match(source("pages/AgentPage.jsx"), /QUESTION_DRAFT_KEY/);
assert.match(source("App.jsx"), /answervice:clear-drafts/);

assert.doesNotMatch(source("pages/AgentPage.jsx"), /type="date"|periodStart|periodEnd/);
assert.match(source("pages/AgentPage.jsx"), /analysisClient\.analyze\(normalizedQuestion, \{\}, \{/);
assert.doesNotMatch([source("pages/AgentPage.jsx"), source("api/analysisClient.ts"), source("contracts/analysis.ts")].join("\n"), /conversationId/);
assert.match(source("pages/AgentPage.jsx"), /resolvedPeriodParameters\(result\)/);
assert.match(source("pages/AgentPage.jsx"), /requestInFlight\.current/);
assert.match(source("pages/AgentPage.jsx"), /clarifiedQuestion\(submittedQuestion, suggestion, run\.error\?\.clarification_type\)/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /어떤 기간으로 분석할까요/);
assert.match(source("pages/AgentPage.jsx"), /분석할 질문을 입력해 주세요/);
assert.match(source("pages/AgentPage.jsx"), /MAX_QUESTION_LENGTH\.toLocaleString/);
assert.match(source("pages/AgentPage.jsx"), /APPROVED_QUESTIONS\.map/);
assert.match(source("pages/AgentPage.jsx"), /객실·식음 통합 매출을 비교해 줘/);
assert.match(source("pages/AgentPage.jsx"), /2026년 6월 객실 매출을 일별로 분석해 줘/);
assert.match(source("pages/AgentPage.jsx"), /onSuggestion=\{\(suggestion\)/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /analysis-suggestions/);
assert.match(source("api/analysisClient.ts"), /\/analysis\/progress\/\$\{encodeURIComponent\(traceId\)\}/);
assert.match(source("api/analysisClient.ts"), /cancelAnalysis\(traceId\)/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /분석 취소/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /내부 처리 순서는 추측해 표시하지 않습니다/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /ANALYSIS_PHASES|modelCount/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /supportedChartType/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /지원하지 않는 차트 형식입니다/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /run\.traceId \|\| "발급 전"/);
assert.match(source("contracts/analysis.ts"), /REQUEST_CANCELLED/);
assert.match(source("contracts/analysis.ts"), /NETWORK_UNAVAILABLE/);
assert.match(source("pages/AgentPage.jsx"), /NETWORK_UNAVAILABLE/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /REQUIRED_ACTION_COPY\[requiredAction\]/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /run\.error\?\.required_action/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /ERROR_ACTIONS|AT A GLANCE/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /KEY TAKEAWAY|VISUAL|DETAIL|SCOPE/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /actual_checkout_at: "체크아웃 시점"/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /\?\? "구분"/);
assert.match(source("components/auth/SessionLogin.jsx"), /\.login\(nextUsername, password\)/);
assert.match(source("components/auth/SessionLogin.jsx"), /Caps Lock이 켜져 있습니다/);
assert.match(source("components/auth/SessionLogin.jsx"), /비밀번호 표시/);
assert.match(source("components/auth/SessionLogin.jsx"), /onAuthenticated\(\{ role: session\.role \}\)/);
assert.doesNotMatch(source("api/analysisClient.ts"), /session_token/);
assert.doesNotMatch(source("components/auth/SessionLogin.jsx"), /액세스 토큰/);
assert.doesNotMatch([
  source("App.jsx"), source("pages/AgentPage.jsx"), source("pages/ReportsPage.jsx"),
].join("\n"), /authToken/);
assert.match(source("App.jsx"), /\(min-width: 1101px\)/);
assert.match(source("styles.css"), /@media\(min-width:901px\) and \(max-width:1100px\)[\s\S]*?\.scrim\{position:fixed;z-index:29;inset:0/);
assert.match(source("App.jsx"), /role === "report_admin"/);
assert.match(source("App.jsx"), /role !== "hotel_analyst"/);
assert.match(source("App.jsx"), /route\.page === "chat"\) navigate\(PAGE_PATHS\.reports\)/);
assert.match(source("App.jsx"), /세션이 만료되었습니다\. 작성 중인 내용은 유지됩니다/);
assert.match(source("App.jsx"), /session-reauth-layer/);
assert.match(source("App.jsx"), /answervice:report-dirty/);
assert.match(source("App.jsx"), /reportDirty && !window\.confirm\("저장하지 않은 보고서 변경사항이 있습니다\. 페이지를 이동할까요\?"\)/);
assert.match(source("App.jsx"), /reportDirty && !window\.confirm\("저장하지 않은 보고서 변경사항이 있습니다\. 로그아웃할까요\?"\)/);
assert.match(source("App.jsx"), /\["hotel_analyst", "report_admin"\]\.includes\(role\)/);
assert.match(source("App.jsx"), /현재 계정에 허용된 서비스 메뉴가 없습니다/);
assert.match(source("App.jsx"), /<AppSidebar page=\{route\.page\} role=\{role\}/);
assert.match(source("components/layout/AppSidebar.jsx"), /item\.roles\.includes\(role\)/);
assert.match(source("App.jsx"), /\["보고서 편집", "근거가 연결된 분석 결과와 설명을 블록으로 구성하고 저장합니다\."\]/);
assert.match(source("pages/ReportsPage.jsx"), /if \(isAdmin\) void loadSchedules\(\)/);
assert.match(source("pages/ReportsPage.jsx"), /브라우저 위치와 관계없이 서울 현지 시각으로 저장합니다/);
assert.match(source("pages/ReportsPage.jsx"), /seoulWallClockToIso\(scheduleAt\)/);
assert.match(source("pages/ReportsPage.jsx"), /setScheduleEnabled\(schedule\.schedule_id, !schedule\.enabled\)/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), />due 실행<\/button>/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), /REPORT_DRAFT scope|ACTUAL REPORT API/);
assert.match(source("pages/ReportsPage.jsx"), /DndContext/);
assert.match(source("pages/ReportsPage.jsx"), /useDraggable/);
assert.match(source("pages/ReportsPage.jsx"), /PointerSensor/);
assert.match(source("pages/ReportsPage.jsx"), /TouchSensor/);
assert.match(source("pages/ReportsPage.jsx"), /KeyboardSensor/);
assert.match(source("pages/ReportsPage.jsx"), /placeDraftBlock\(current, activeId, position\.requestedX, position\.y\)/);
assert.match(source("pages/ReportsPage.jsx"), /gridRow:/);
assert.match(source("pages/ReportsPage.jsx"), /aria-label="보고서 저장"/);
assert.match(source("pages/ReportsPage.jsx"), /notion-report-editor/);
assert.match(source("pages/ReportsPage.jsx"), /function MarkdownText/);
assert.match(source("pages/ReportsPage.jsx"), /MARKDOWN_INSERT_COMMANDS/);
assert.match(source("pages/ReportsPage.jsx"), /aria-label="Markdown 블록 삽입"/);
assert.match(source("pages/ReportsPage.jsx"), /aria-activedescendant/);
assert.match(source("pages/ReportsPage.jsx"), /event\.key === "Home"/);
assert.match(source("pages/ReportsPage.jsx"), /event\.key === "End"/);
assert.match(source("pages/ReportsPage.jsx"), /<EnterpriseChart/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), /from "recharts"/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), /className="legacy-report-row"[^>]*onClick/);
assert.match(source("pages/ReportsPage.jsx"), /className="editor-tools-scrim" aria-label="블록 도구 닫기"/);
assert.match(source("pages/ReportsPage.jsx"), /ReactMarkdown/);
assert.match(source("pages/ReportsPage.jsx"), /remarkGfm/);
assert.match(source("pages/ReportsPage.jsx"), /function ReportBlockMenu/);
assert.match(source("pages/ReportsPage.jsx"), /name="report-block-menu"/);
assert.match(source("pages/ReportsPage.jsx"), /report-resize-handle/);
assert.match(source("pages/ReportsPage.jsx"), /report-markdown-toolbar/);
assert.match(source("pages/ReportsPage.jsx"), /id: "artifact-table"/);
assert.match(source("pages/ReportsPage.jsx"), /id: "artifact-chart"/);
assert.match(source("pages/ReportsPage.jsx"), /function ReportTemplateTile/);
assert.match(source("pages/ReportsPage.jsx"), /className="report-template-add"/);
assert.match(source("pages/ReportsPage.jsx"), /className="report-template-drag"/);
assert.match(source("pages/ReportsPage.jsx"), /setActivatorNodeRef/);
assert.match(source("pages/ReportsPage.jsx"), /DragOverlay/);
assert.match(source("pages/ReportsPage.jsx"), /dropPositionRef\.current/);
assert.match(source("pages/ReportsPage.jsx"), /원하는 위치로 끌어다 놓으세요/);
assert.match(source("pages/ReportsPage.jsx"), /행은 빈 공간 없이 자동 정렬됩니다/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), /notion-block-toolbar/);
assert.match(source("pages/ReportsPage.jsx"), /function ReportArtifactContent/);
assert.match(source("pages/ReportsPage.jsx"), /metric\.result_field === resultField/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), /revenue\|_krw/);
assert.match(source("pages/ReportsPage.jsx"), /REPORT_DIMENSION_LABELS\[column\] \|\| "구분"/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), /y_fields\.slice/);
assert.doesNotMatch(source("api/analysisClient.ts"), /restoredMetrics|row\[metric\.metric_id\]/);
assert.match(source("pages/ReportsPage.jsx"), /function reportEvidenceReady/);
assert.match(source("pages/ReportsPage.jsx"), /if \(!reportEvidenceReady\(artifact\)\)/);
assert.match(source("pages/ReportsPage.jsx"), /const canEdit = Boolean\(isDraft && !pending\)/);
assert.match(source("pages/ReportsPage.jsx"), /aria-busy=\{pending === "save"\}/);
assert.match(source("pages/ReportsPage.jsx"), /existingDraft/);
assert.match(source("pages/ReportsPage.jsx"), /window\.confirm\(`확정본 v\$\{current\.version\}을 기준으로 새 편집 버전을 만들까요\?`\)/);
assert.match(source("pages/ReportsPage.jsx"), /selectedArtifactSource\?\.artifactId/);
assert.match(source("pages/ReportsPage.jsx"), /선택한 원본으로 AI 초안 생성/);
assert.match(source("pages/ReportsPage.jsx"), /AI 초안 · 검토 필요/);
assert.match(source("pages/ReportsPage.jsx"), /status: "loading"/);
assert.match(source("pages/ReportsPage.jsx"), /artifactState\.status === "empty"/);
assert.match(source("pages/ReportsPage.jsx"), /artifactState\.status === "error"/);
assert.match(source("pages/ReportsPage.jsx"), /다시 불러오기/);
assert.match(source("pages/ReportsPage.jsx"), /screenReaderInstructions/);
assert.match(source("pages/ReportsPage.jsx"), /실제 호텔 운영 데이터로 해석하지 마세요/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), /검증된 데이터/);
assert.match(source("features/reports/report-a4.css"), /\.answer-report-page \.report-data-provenance/);
assert.match(source("pages/ReportsPage.jsx"), /onDragMove/);
assert.match(source("pages/ReportsPage.jsx"), /저장되지 않은 변경/);
assert.match(source("pages/ReportsPage.jsx"), /저장 실패/);
assert.match(source("pages/ReportsPage.jsx"), /resizeRow && block\.y === sourceBlock\.y/);
assert.match(source("pages/ReportsPage.jsx"), /event\.buttons & 1/);
assert.match(source("pages/ReportsPage.jsx"), /await loadArtifacts\(current\)/);
assert.match(source("pages/ReportsPage.jsx"), /<ReportArtifactContent block=\{block\}/);
assert.match(source("styles.css"), /\.report-api-blocks\.notion-canvas>article\{grid-column:var\(--block-x\)\/span var\(--block-w\)\}/);
assert.match(source("pages/ReportsPage.jsx"), /setView\("editor"\)/);
assert.match(source("pages/ReportsPage.jsx"), /setView\("document"\)/);
assert.match(source("pages/ReportsPage.jsx"), /restoreEditorFocus/);
assert.match(source("pages/ReportsPage.jsx"), /pageCanvasRefs\.current\.values\(\)/);
assert.match(source("pages/ReportsPage.jsx"), /canvas\.querySelector\("\[data-block-id\]"\)/);
assert.match(source("pages/ReportsPage.jsx"), /enterprise-reports-list/);
assert.match(source("pages/ReportsPage.jsx"), /legacy-report-document generated-preview/);
assert.match(source("pages/ReportsPage.jsx"), /createNextDraft/);
assert.match(source("pages/ReportsPage.jsx"), /blocks: initialContent \? \[\{/);
assert.match(source("pages/ReportsPage.jsx"), /resetBlocks\(\[\{ id: blockId, title: "운영 요약"/);
assert.match(source("pages/AgentPage.jsx"), /savedRuns\.slice\(0, visibleRunCount\)/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /<EnterpriseChart/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /label: "기본 제외"/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /chartFieldsMatchTable/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /차트 필드와 상세 데이터 열이 일치하지 않아/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /dataProvenanceLabel\(run\.sources\)/);
assert.match(source("utils/presentation.ts"), /합성 데모 데이터/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /검증된 결과/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /from "recharts"/);
assert.match(source("components/charts/EnterpriseChart.jsx"), /accessibilityLayer/);
assert.match(source("components/charts/EnterpriseChart.jsx"), /<ChartTooltip/);
assert.match(source("pages/AgentPage.jsx"), /const reportModalRef = useRef\(null\)/);
assert.match(source("pages/AgentPage.jsx"), /event\.key === "Escape"/);
assert.match(source("pages/AgentPage.jsx"), /previousFocus\?\.focus\?\.\(\)/);
assert.match(source("pages/AgentPage.jsx"), /aria-controls="analysis-evidence-panel"/);
assert.match(source("pages/AgentPage.jsx"), /id="analysis-evidence-panel"/);
assert.match(source("pages/AgentPage.jsx"), /evidenceReturnFocusRef\.current\?\.focus\?\.\(\)/);
assert.match(source("pages/AgentPage.jsx"), /role="tabpanel" aria-labelledby="evidence-tab-/);
assert.match(source("pages/AgentPage.jsx"), /handleArtifactTabKeyDown/);
assert.match(source("pages/AgentPage.jsx"), /analysisClient\.getRunArtifact\(result\.request_id\)/);
assert.match(source("pages/AgentPage.jsx"), /이전 분석 결과를 불러왔습니다/);
assert.match(source("pages/AgentPage.jsx"), />결과 열기<\/button>/);
assert.match(source("pages/AgentPage.jsx"), /const historicalQuestion = savedRun\.question/);
assert.match(source("pages/AgentPage.jsx"), /report-analysis-preview"><AnalysisStatePanel run=\{run\}/);
assert.match(source("pages/AgentPage.jsx"), /inert=\{Boolean\(reportModal\)\}/);
assert.match(source("api/analysisClient.ts"), /\/analysis\/runs\/\$\{encodeURIComponent\(requestId\)\}\/artifact/);

for (const exposedImplementationCopy of [
  /Saved Analysis/, /Run History/, /Authenticated Session/, /세션 종료/,
  /제목 또는 ID 검색/, /window\.location\.reload/,
]) assert.doesNotMatch(productSources, exposedImplementationCopy);
assert.match(source("pages/ReportsPage.jsx"), /<details><summary>기술 정보<\/summary><code>Artifact/);
assert.match(source("components/layout/AppHeader.jsx"), /호텔 분석가/);
assert.match(source("components/layout/AppHeader.jsx"), /로그아웃/);
assert.match(source("pages/AgentPage.jsx"), /className="run-history-panel"/);
assert.match(source("pages/AgentPage.jsx"), /className="analysis-notice"/);
assert.match(source("pages/AgentPage.jsx"), /function reportTitleForRun/);
assert.match(source("pages/AgentPage.jsx"), /createDraftFromArtifact\(run\.artifact\.artifactId, reportTitle\.trim\(\) \|\| reportTitleForRun\(run\)\)/);
assert.match(source("pages/AgentPage.jsx"), /definitions\.filter/);
assert.match(source("pages/AgentPage.jsx"), /filteredDefinitions\.slice\(0, visibleDefinitionCount\)/);
assert.match(source("pages/ReportsPage.jsx"), /filteredRuns\.slice\(0, visibleRunCount\)/);
assert.match(source("styles.css"), /@media\(max-width:1200px\)[\s\S]*\.chat-layout \.evidence-panel\{position:fixed/);
assert.doesNotMatch(source("styles.css"), /\.page-stage\{[^}]*animation:[^}]*\sboth\}/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /AnalysisProgress run=\{run\} loading=\{false\}/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /READY: \{ title: "분석 완료"/);

const reorderedBlocks = reorderDraftBlocks([
  { id: "left", title: "왼쪽", columns: 6, type: "text", content: "왼쪽", x: 0, y: 0, w: 6, h: 2 },
  { id: "right", title: "오른쪽", columns: 6, type: "text", content: "오른쪽", x: 6, y: 0, w: 6, h: 2 },
], "right", "left");
assert.deepEqual(reorderedBlocks.map((block) => block.id), ["right", "left"]);
assert.deepEqual(reorderedBlocks.map((block) => [block.x, block.y]), [[0, 0], [6, 0]]);

const compactlyPlacedBlocks = placeDraftBlock(reorderedBlocks, "right", 6, 3);
assert.deepEqual(compactlyPlacedBlocks.find((block) => block.id === "right"), {
  id: "right", title: "오른쪽", columns: 12, type: "text", content: "오른쪽", x: 0, y: 2, w: 12, h: 2,
});
const collisionAvoidedBlocks = placeDraftBlock(compactlyPlacedBlocks, "left", 6, 3);
assert.deepEqual(collisionAvoidedBlocks.map((block) => [block.x, block.y]), [[0, 0], [6, 0]]);

const movedOutOfPair = placeDraftBlock([
  { id: "pair-left", title: "Left", columns: 6, type: "text", x: 0, y: 0, w: 6, h: 4 },
  { id: "pair-right", title: "Right", columns: 6, type: "text", x: 6, y: 0, w: 6, h: 4 },
  { id: "full-target", title: "Target", columns: 12, type: "text", x: 0, y: 4, w: 12, h: 4 },
], "pair-right", 0, 4);
assert.deepEqual(
  movedOutOfPair.map(({ id, x, y, w }) => ({ id, x, y, w })),
  [
    { id: "pair-left", x: 0, y: 0, w: 12 },
    { id: "pair-right", x: 0, y: 4, w: 6 },
    { id: "full-target", x: 6, y: 4, w: 6 },
  ],
);

const splitFullRow = placeDraftBlock([
  { id: "table", title: "표", columns: 12, type: "table", x: 0, y: 0, w: 12, h: 5 },
  { id: "chart", title: "차트", columns: 12, type: "chart", x: 0, y: 0, w: 12, h: 6 },
], "chart", 6, 2);
assert.deepEqual(splitFullRow.map((block) => [block.x, block.y, block.w, block.h]), [[0, 0, 6, 6], [6, 0, 6, 6]]);

const gaplessRows = compactDraftLayout([
  { id: "summary", title: "요약", columns: 12, type: "text", x: 0, y: 9, w: 12, h: 4 },
  { id: "table", title: "표", columns: 12, type: "table", x: 0, y: 30, w: 12, h: 5 },
]);
assert.deepEqual(gaplessRows.map((block) => [block.x, block.y]), [[0, 0], [0, 4]]);

const filledRows = compactDraftLayout([
  { id: "summary", title: "요약", columns: 6, type: "text", x: 0, y: 0, w: 6, h: 4 },
  { id: "table", title: "표", columns: 12, type: "table", x: 0, y: 4, w: 12, h: 5 },
]);
assert.deepEqual(filledRows.map((block) => [block.x, block.y, block.w]), [[0, 0, 12], [0, 4, 12]]);

const invariantLayout = compactDraftLayout([
  { id: "a", title: "A", columns: 4, type: "text", x: 8, y: 30, w: 4, h: 4 },
  { id: "b", title: "B", columns: 6, type: "chart", x: 0, y: 0, w: 6, h: 7 },
  { id: "c", title: "C", columns: 12, type: "table", x: 0, y: 99, w: 12, h: 5 },
]);
for (const block of invariantLayout) {
  assert.ok(block.x >= 0 && block.y >= 0 && block.w > 0 && block.h > 0);
  assert.ok(block.x + block.w <= 12);
}
for (let left = 0; left < invariantLayout.length; left += 1) {
  for (let right = left + 1; right < invariantLayout.length; right += 1) {
    const a = invariantLayout[left];
    const b = invariantLayout[right];
    const overlaps = a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
    assert.equal(overlaps, false, `${a.id} and ${b.id} must not overlap`);
  }
}
const layoutRows = [...new Map(invariantLayout.map((block) => [block.y, block.h])).entries()].sort((a, b) => a[0] - b[0]);
assert.equal(layoutRows[0][0], 0);
for (let index = 1; index < layoutRows.length; index += 1) {
  assert.equal(layoutRows[index][0], layoutRows[index - 1][0] + layoutRows[index - 1][1]);
}
assert.deepEqual(compactDraftLayout(invariantLayout), invariantLayout);

const apiResponse = {
  data: {
    status: "SUCCEEDED",
    artifact: { artifact_id: "artifact-1", query_id: "query-1", context_hash: "context-1" },
    result: {
      summary: "API result",
      metrics: [{ metric_id: "metric", result_field: "metric", label: "Metric", definition: "Metric definition", value: 3, unit: "count" }],
      table: { columns: ["metric"], rows: [{ metric: 3 }] },
      chart: null,
      evidence: {
        artifact_id: "artifact-1", query_id: "query-1", as_of: "2030-01-02", timezone: "Asia/Seoul",
        period: { start: "2030-01-01", end_exclusive: "2030-01-03" }, filters: {}, cached: false,
        context_release: "context-v1", policy_version: "policy-v1", model_version: "model-v1",
        metrics: [{ metric_id: "metric", result_field: "metric", label: "Metric", definition: "Metric definition", unit: "count" }],
        models: [{ node: "node3", model_version: "model-v1", prompt_id: "node3-prompt", prompt_version: "v1" }],
        gates: { g1: "PASSED", g2: "PASSED", g3: "PASSED" },
        gate_history: { g1: ["PASSED"], g2: ["BLOCKED", "PASSED"], g3: ["PASSED"] },
        sampling: { applied: false, returned_rows: 1, total_rows: 1 },
        masking: { applied: true, fields: ["guest_id"] },
        sources: [{ name: "source", urn: "urn:source", fqn: "catalog.schema.table", schema_version: "1", seed_version: "2", synthetic: true }],
      },
    },
  },
  meta: { request_id: "request-1", trace_id: "trace-1", as_of: "2030-01-02", contract_version: OPENAPI_VERSION, timestamp: "2030-01-02T00:00:00Z" },
  error: null,
};
const normalized = normalizeApiResponse(apiResponse, "question");
assert.equal(normalized.status, "success");
assert.equal(resolveViewState(normalized), "READY");
assert.equal(normalized.artifact.queryId, "query-1");
assert.equal(normalized.sources[0].fqn, "catalog.schema.table");
assert.equal(normalized.sources[0].status, "success");
assert.equal(normalized.sources[0].synthetic, true);
assert.equal(dataProvenanceLabel(normalized.sources), "합성 데모 데이터");
assert.equal(dataProvenanceLabel([{ synthetic: true }, {}]), "합성 데모 데이터 포함");
assert.equal(dataProvenanceLabel([{ synthetic: false }, {}]), null);
assert.equal(normalized.metrics[0].definition, "Metric definition");
assert.equal(normalized.metrics[0].resultField, "metric");
assert.equal(normalized.evidence.metrics[0].definition, "Metric definition");
assert.equal(normalized.evidence.models[0].promptId, "node3-prompt");
assert.equal(normalized.evidence.gates.g3, "PASSED");
assert.deepEqual(normalized.evidence.gateHistory.g2, ["BLOCKED", "PASSED"]);
assert.deepEqual(normalized.evidence.masking.fields, ["guest_id"]);
assert.equal(normalized.meta.synthetic, undefined);

const partialResponse = structuredClone(apiResponse);
partialResponse.data.status = "PARTIAL";
const partial = normalizeApiResponse(partialResponse, "question");
assert.equal(resolveViewState(partial), "PARTIAL");
assert.deepEqual(partial.sources.map((item) => item.status), ["unknown"]);

const incompletePartialResponse = structuredClone(partialResponse);
incompletePartialResponse.data.result.evidence.sources = [];
const incompletePartial = normalizeApiResponse(incompletePartialResponse, "question");
assert.equal(resolveViewState(incompletePartial), "INSUFFICIENT_EVIDENCE");
assert.equal(incompletePartial.error.code, "INSUFFICIENT_EVIDENCE");
assert.equal(incompletePartial.error.required_action, "NONE");
assert.equal(incompletePartial.artifact, undefined);
assert.equal(incompletePartial.summary, undefined);
assert.deepEqual(incompletePartial.metrics, []);
assert.equal(incompletePartial.table, undefined);

const rateLimitedClient = createHttpAnalysisClient("http://backend.test", async () => new Response(JSON.stringify({ error: { code: "RATE_LIMITED", message: "잠시 후 다시 시도해 주세요.", retryable: true, required_action: "RETRY", trace_id: "server-trace" } }), { status: 429 }), "runtime-token");
await assert.rejects(
  () => rateLimitedClient.analyze("question"),
  (error) => error instanceof AnalysisApiError && error.status === 429 && error.code === "RATE_LIMITED" && error.retryable && error.requiredAction === "RETRY" && error.traceId === "server-trace",
);

const clarification = normalizeApiResponse({
  data: { status: "BLOCKED", result: null },
  meta: apiResponse.meta,
  error: {
    code: "CONTEXT_INCOMPLETE",
    message: "분석할 기준을 선택해 주세요.",
    retryable: false,
    suggestions: ["인식 객실 매출", "숙박일 배분 객실 매출"],
  },
}, "2026년 6월 객실 매출");
assert.deepEqual(clarification.error.suggestions, ["인식 객실 매출", "숙박일 배분 객실 매출"]);

let analysisRequest;
const analysisClient = createHttpAnalysisClient("http://backend.test/", async (url, init) => {
  analysisRequest = { url, init };
  return new Response(JSON.stringify(apiResponse), { status: 200, headers: { "Content-Type": "application/json" } });
}, "runtime-token");
await analysisClient.analyze("question", { period_start: "2030-01-01", period_end_exclusive: "2030-01-03" }, { traceId: "client-trace" });
assert.equal(analysisRequest.url, "http://backend.test/analysis");
assert.equal(analysisRequest.init.headers.Authorization, "Bearer runtime-token");
assert.equal(analysisRequest.init.headers["X-Contract-Version"], OPENAPI_VERSION);
assert.equal(analysisRequest.init.headers["X-Trace-Id"], "client-trace");
assert.deepEqual(JSON.parse(analysisRequest.init.body).parameters, { period_start: "2030-01-01", period_end_exclusive: "2030-01-03" });

const savedArtifact = {
  request_id: "saved-request", trace_id: "saved-trace", status: "SUCCEEDED",
  question: "점유율", summary: "저장된 점유율", artifact_id: "artifact-1", query_id: "query-1",
  artifact_checksum: "a".repeat(64),
  metrics: [{ metric_id: "occupancy_rate", result_field: "occ_pct", label: "점유율", definition: "판매 가능 객실 대비 판매 객실", value: 0.5, unit: "%" }],
  table: { columns: ["month", "occ_pct"], rows: [{ month: "1월", occ_pct: 0.4 }, { month: "2월", occ_pct: 0.6 }] },
  chart: { chart_type: "line", x_field: "month", y_fields: ["occ_pct"] },
  evidence: {
    ...apiResponse.data.result.evidence,
    metrics: [{ metric_id: "occupancy_rate", result_field: "occ_pct", label: "점유율", definition: "판매 가능 객실 대비 판매 객실", unit: "%" }],
  },
};
const savedArtifactClient = createHttpAnalysisClient("http://backend.test", async () => new Response(JSON.stringify(savedArtifact), { status: 200 }));
const restoredArtifact = await savedArtifactClient.getRunArtifact("saved-request");
assert.equal(restoredArtifact.metrics[0].metricId, "occupancy_rate");
assert.equal(restoredArtifact.metrics[0].resultField, "occ_pct");
assert.equal(restoredArtifact.metrics[0].value, 0.5);

assert.equal(seoulWallClockToIso("2030-01-02T09:30"), "2030-01-02T00:30:00.000Z");
assert.throws(() => seoulWallClockToIso("2030-02-30T09:30"), /유효한 서울 실행 시각/);

await analysisClient.cancelAnalysis("client-trace");
assert.equal(analysisRequest.url, "http://backend.test/analysis/progress/client-trace/cancel");
assert.equal(analysisRequest.init.method, "POST");

const sessionClient = createHttpAnalysisClient("http://backend.test", async (url, init) => {
  assert.equal(url, "http://backend.test/auth/session");
  assert.equal(init.headers.Authorization, "Bearer runtime-token");
  return new Response(JSON.stringify({ data: { status: "authenticated", role: "hotel_analyst" } }), { status: 200 });
}, "runtime-token");
assert.deepEqual(await sessionClient.validateSession(), { status: "authenticated", role: "hotel_analyst" });

let loginRequest;
const loginClient = createHttpAnalysisClient("http://backend.test", async (url, init) => {
  loginRequest = { url, init };
  return new Response(JSON.stringify({ data: { status: "authenticated", role: "report_admin" } }), { status: 200 });
});
assert.deepEqual(await loginClient.login("admin", "admin1234!"), {
  status: "authenticated", role: "report_admin",
});
assert.equal(loginRequest.url, "http://backend.test/auth/login");
assert.deepEqual(JSON.parse(loginRequest.init.body), { username: "admin", password: "admin1234!" });

let defaultRequests = 0;
assert.throws(
  () => createAnalysisClient(async () => { defaultRequests += 1; return new Response(JSON.stringify(apiResponse)); }, "runtime-token"),
  /VITE_BACKEND_BASE_URL is required/,
);
assert.equal(defaultRequests, 0);

const unauthorizedReport = createReportClient("http://backend.test", async () => new Response(JSON.stringify({ error: { code: "ACCESS_DENIED", message: "denied" } }), { status: 403 }), "runtime-token");
await assert.rejects(() => unauthorizedReport.listDefinitions(), (error) => error instanceof ReportApiError && error.status === 403 && error.code === "ACCESS_DENIED");

let reportExpired = false;
globalThis.window = { dispatchEvent: (event) => { reportExpired = event.type === "answervice:session-expired"; } };
const expiredReport = createReportClient("http://backend.test", async () => new Response(JSON.stringify({ error: { code: "ACCESS_DENIED" } }), { status: 401 }));
await assert.rejects(() => expiredReport.listDefinitions(), (error) => error instanceof ReportApiError && error.status === 401);
assert.equal(reportExpired, true);
delete globalThis.window;

let scheduleRequest;
const scheduleClient = createReportClient("http://backend.test", async (url, init) => {
  scheduleRequest = { url, init };
  return new Response(JSON.stringify({
    schedule_id: "schedule-1", definition_id: "definition-1", version: 1,
    cadence: "daily", next_run_at: "2030-01-02T00:00:00Z", timezone: "Asia/Seoul",
    enabled: false, last_run_id: null,
  }), { status: 200, headers: { "Content-Type": "application/json" } });
}, "runtime-token");
await scheduleClient.setScheduleEnabled("schedule-1", false);
assert.equal(scheduleRequest.url, "http://backend.test/reports/schedules/schedule-1");
assert.equal(scheduleRequest.init.method, "PUT");
assert.deepEqual(JSON.parse(scheduleRequest.init.body), { enabled: false });

console.log("frontend contract tests passed");
