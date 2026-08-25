import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normalizeApiResponse, OPENAPI_VERSION, resolveViewState, UI_CONTRACT_VERSION } from "../../app/frontend/src/contracts/analysis.ts";
import { compactDraftLayout, placeDraftBlock, REPORT_CONTRACT_VERSION, REPORT_RUN_STATUSES, reorderDraftBlocks, seoulWallClockToIso } from "../../app/frontend/src/contracts/report.ts";
import { AnalysisApiError, createAnalysisClient, createHttpAnalysisClient } from "../../app/frontend/src/api/analysisClient.ts";
import { createReportClient, ReportApiError } from "../../app/frontend/src/api/reportClient.ts";
import { resolveRoute } from "../../app/frontend/src/routing.js";
import { dataProvenanceLabel } from "../../app/frontend/src/utils/presentation.ts";
import { commandErrorRun, hasReusablePresentationArtifact, hydrateTurnsFromServer, quickViewAction } from "../../app/frontend/src/pages/agentPageHelpers.js";
import { reportFeatureSource, reportSources } from "./report-source-contract.mjs";

const source = (path) => readFileSync(new URL(`../../app/frontend/src/${path}`, import.meta.url), "utf8");
const nginx = readFileSync(new URL("../../app/frontend/nginx.conf", import.meta.url), "utf8");
const frontendCompose = readFileSync(new URL("../../app/frontend/compose.fragment.yml", import.meta.url), "utf8");
const frontendDockerfile = readFileSync(new URL("../../app/frontend/Dockerfile", import.meta.url), "utf8");
const frontendPackage = JSON.parse(readFileSync(new URL("../../app/frontend/package.json", import.meta.url), "utf8"));
const viteConfig = readFileSync(new URL("../../app/frontend/vite.config.js", import.meta.url), "utf8");
const productSources = [
  "App.jsx", "routing.js", "api/analysisClient.ts", "api/reportClient.ts",
  "pages/AgentPage.jsx", "pages/AdminPage.jsx",
  "components/analysis/AnalysisStatePanel.tsx", "components/analysis/AnalysisStatePanelParts.tsx",
  "components/analysis/AnalysisFailureState.tsx",
  "components/layout/AppHeader.jsx", "components/layout/AppSidebar.jsx",
].map(source).concat(reportFeatureSource).join("\n");
const reportA4Styles = [
  "features/reports/report-a4-paper.css",
  "features/reports/report-a4-content.css",
  "features/reports/report-a4-artifact.css",
  "features/reports/report-a4-print.css",
].map(source).join("\n");

assert.equal(UI_CONTRACT_VERSION, "UI-v1.0.0");
assert.equal(OPENAPI_VERSION, "OPENAPI-v1.0.0");
assert.equal(REPORT_CONTRACT_VERSION, "REPORT-v1.0.0");
assert.match(nginx, /location \/assets\/ \{[\s\S]*try_files \$uri =404/);
assert.match(nginx, /Cache-Control "no-cache, no-store, must-revalidate"/);
assert.match(nginx, /location \/api\/ \{[\s\S]*proxy_pass http:\/\/backend:8000\//);
assert.equal(frontendPackage.scripts["dev:compose"], "vite --mode compose");
assert.match(viteConfig, /host: "localhost"/);
assert.match(viteConfig, /composeMode \? "http:\/\/127\.0\.0\.1:28000"/);
assert.match(viteConfig, /composeMode \? "\/api"/);
assert.match(frontendCompose, /VITE_BACKEND_BASE_URL: "\$\{VITE_BACKEND_BASE_URL:-\/api\}"/);
assert.match(frontendDockerfile, /ARG VITE_BACKEND_BASE_URL=\/api/);
assert.deepEqual(REPORT_RUN_STATUSES, ["queued", "running", "success", "partial", "failed", "cancelled"]);
assert.equal(resolveRoute("/").path, "/agent");
assert.equal(resolveRoute("/agent").page, "chat");
assert.equal(resolveRoute("/reports").page, "reports");
assert.equal(resolveRoute("/admin").page, "admin");
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
assert.match(source("pages/AgentPage.jsx"), /setConversationId\(""\);[\s\S]*?sessionStorage\.removeItem\(CONVERSATION_KEY\)/);
assert.match(source("pages/AgentPage.jsx"), /setEvidenceOpen\(false\);[\s\S]*?setSelectedEvidenceRun\(null\)/);
assert.match(source("pages/AgentPage.jsx"), /onClose=\{\(\) => \{[\s\S]*?setEvidenceOpen\(false\);[\s\S]*?setSelectedEvidenceRun\(null\)/);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /catch\s*\{[\s\S]*?return conversationId;/);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /const initConversation = async \(\) => \{[\s\S]*?setTurns\(\[\]\);[\s\S]*?return nextId;/);
assert.match(source("App.jsx"), /answervice:clear-drafts/);

assert.doesNotMatch(source("pages/AgentPage.jsx"), /type="date"|periodStart|periodEnd/);
assert.match(source("pages/AgentPage.jsx"), /analysisClient\.submitTurnCommand/);
assert.deepEqual(quickViewAction("TABLE"), {
  label: "표로 보기",
  action: { requested_route: "PRESENTATION", presentation_type: "TABLE" },
});
assert.deepEqual(quickViewAction("CHART"), {
  label: "그래프로 보기",
  action: { requested_route: "PRESENTATION", presentation_type: "BAR" },
});
assert.deepEqual(quickViewAction("SUMMARY"), {
  label: "요약으로 보기",
  action: { requested_route: "PRESENTATION", presentation_type: "SUMMARY" },
});
assert.deepEqual(quickViewAction("KPI")?.action, { requested_route: "PRESENTATION", presentation_type: "KPI" });
assert.equal(quickViewAction("FULL"), null);
assert.deepEqual(quickViewAction("CHART", { hasChart: true, hasTable: true })?.action, { requested_route: "PRESENTATION", presentation_type: "BAR" });
assert.deepEqual(quickViewAction("TABLE", { hasChart: true, hasTable: true })?.action, { requested_route: "PRESENTATION", presentation_type: "TABLE" });
assert.equal(quickViewAction("UNKNOWN"), null);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /setTurns\(\(prev\).*viewType: mode/);
assert.match(source("pages/AgentPage.jsx"), /setTurns\(\(prev\) => \[\.\.\.prev, optimisticTurn\]\)/);
assert.match(source("pages/AgentPage.jsx"), /isPresentationAction && !hasReusablePresentationArtifact\(sourceRun\)[\s\S]*?기존 분석 결과가 없어 해당 보기를 만들 수 없습니다[\s\S]*?return;/);
assert.match(source("pages/AgentPage.jsx"), /requestGeneration\.current !== generation/);
assert.equal(hasReusablePresentationArtifact({
  artifact: { artifactId: "artifact-1", queryId: "query-1" },
  evidence: { artifactId: "artifact-1", queryId: "query-1" },
}), true);
assert.equal(hasReusablePresentationArtifact({
  artifact: { artifactId: "artifact-1", queryId: "query-1" },
  evidence: { artifactId: "artifact-1", queryId: "query-other" },
}), false);
assert.equal(hasReusablePresentationArtifact(null), false);
assert.match(source("pages/AgentPage.jsx"), /clarifiedQuestion\(turnItem\.question, sugg/);
assert.match(source("components/analysis/AnalysisFailureState.tsx"), /분석 기간을 선택해 주세요/);
assert.match(source("pages/AgentPage.jsx"), /MAX_QUESTION_LENGTH\.toLocaleString/);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /APPROVED_QUESTIONS|객실·식음 통합 매출을 비교해 줘/);
assert.match(source("pages/AgentPage.jsx"), /onSuggestion=\{\(sugg\)/);
assert.match(source("components/analysis/AnalysisFailureState.tsx"), /analysis-diagnostic__options/);
assert.match(source("api/analysisClient.ts"), /\/analysis\/progress\/\$\{encodeURIComponent\(traceId\)\}/);
assert.match(source("api/analysisClient.ts"), /cancelAnalysis\(traceId\)/);
const analysisPanelSource = [
  source("components/analysis/AnalysisStatePanel.tsx"),
  source("components/analysis/AnalysisStatePanelParts.tsx"),
  source("components/analysis/AnalysisFailureState.tsx"),
].join("\n");
assert.match(analysisPanelSource, /분석 취소/);
assert.match(analysisPanelSource, /내부 처리 순서는 추측해 표시하지 않습니다/);
assert.doesNotMatch(analysisPanelSource, /ANALYSIS_PHASES|modelCount/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /supportedChartType/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /문의 코드/);
assert.match(source("contracts/analysis.ts"), /REQUEST_CANCELLED/);
assert.match(source("contracts/analysis.ts"), /NETWORK_UNAVAILABLE/);
assert.match(source("pages/AgentPage.jsx"), /NETWORK_UNAVAILABLE/);
assert.match(source("components/analysis/AnalysisFailureState.tsx"), /REQUIRED_ACTION_COPY\[action\]/);
assert.match(source("components/analysis/AnalysisFailureState.tsx"), /run\.error\?\.required_action/);
assert.doesNotMatch(source("components/analysis/AnalysisFailureState.tsx"), /2026년 7월|추천 질문으로 바로 분석하기|requestId|traceId/);
assert.doesNotMatch(source("components/TurnEvidenceDrawer.jsx"), /<dt>Request<\/dt>|<dt>Trace<\/dt>|run\.requestId|run\.traceId/);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /code: "NO_MATCH"/);
assert.doesNotMatch(source("pages/agentPageHelpers.js"), /code: "NO_MATCH"/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /ERROR_ACTIONS|AT A GLANCE/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /KEY TAKEAWAY|VISUAL|DETAIL|SCOPE/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /actual_checkout_at|membership_grade_code/);
assert.match(analysisPanelSource, /\?\? column/);
assert.match(source("components/auth/SessionLogin.jsx"), /\.login\(nextUsername, password\)/);
assert.match(source("components/auth/SessionLogin.jsx"), /Caps Lock이 켜져 있습니다/);
assert.match(source("components/auth/SessionLogin.jsx"), /비밀번호 표시/);
assert.match(source("components/auth/SessionLogin.jsx"), /onAuthenticated\(session\)/);
assert.doesNotMatch(source("api/analysisClient.ts"), /session_token/);
assert.doesNotMatch(source("components/auth/SessionLogin.jsx"), /액세스 토큰/);
assert.doesNotMatch([
  source("App.jsx"),
  source("pages/AgentPage.jsx"),
  ...Object.entries(reportSources)
    .filter(([name]) => name !== "reportClient")
    .map(([, reportSource]) => reportSource),
].join("\n"), /authToken/);
assert.match(source("App.jsx"), /\(min-width: 1101px\)/);
assert.match(source("styles.css"), /@media\(min-width:901px\) and \(max-width:1100px\)[\s\S]*?\.scrim\{position:fixed;z-index:29;inset:0/);
assert.match(source("App.jsx"), /hasCapability\(capabilities, CAPABILITY\.runAnalysis\)/);
assert.match(source("App.jsx"), /hasCapability\(capabilities, CAPABILITY\.manageReport\)/);
assert.match(source("App.jsx"), /hasCapability\(capabilities, CAPABILITY\.manageData\)/);
assert.match(source("App.jsx"), /else if \(canUseAdmin\) navigate\(PAGE_PATHS\.admin\)/);
assert.match(source("App.jsx"), /세션이 만료되었습니다\. 안전을 위해 사용자 임시 상태를 지웠습니다/);
assert.match(source("App.jsx"), /clearAuthenticatedBrowserState\(\)/);
assert.doesNotMatch(source("App.jsx"), /session-reauth-layer/);
assert.match(source("App.jsx"), /answervice:report-dirty/);
assert.match(source("App.jsx"), /reportDirty && !window\.confirm\("저장하지 않은 보고서 변경사항이 있습니다\. 페이지를 이동할까요\?"\)/);
assert.match(source("App.jsx"), /reportDirty && !window\.confirm\("저장하지 않은 보고서 변경사항이 있습니다\. 로그아웃할까요\?"\)/);
assert.match(source("App.jsx"), /현재 계정에 허용된 서비스 메뉴가 없습니다/);
assert.match(source("App.jsx"), /<AppSidebar page=\{route\.page\} role=\{role\} capabilities=\{capabilities\}/);
assert.match(source("components/layout/AppSidebar.jsx"), /hasCapability\(capabilities, item\.capability\)/);
assert.match(source("components/layout/AppSidebar.jsx"), /label: "관리자"[\s\S]*?CAPABILITY\.manageReport[\s\S]*?CAPABILITY\.manageData/);
assert.match(source("pages/AdminPage.jsx"), /연결 상태/);
assert.match(source("pages/AdminPage.jsx"), /권한 관리/);
assert.match(source("pages/AdminPage.jsx"), /감사 로그/);
assert.match(source("pages/AdminPage.jsx"), /data\?\.connections \?\? \[\]/);
assert.match(source("pages/AdminPage.jsx"), /ADMIN API 연결 전/);
for (const target of ["PMS", "POS", "CRM", "Facility", "Banquet", "App PostgreSQL", "Trino", "DataHub", "Model API"]) {
  assert.match(source("pages/AdminPage.jsx"), new RegExp(`name: "${target}"`));
}
assert.match(source("pages/AdminPage.jsx"), /disabled=\{!onRefreshConnections\}/);
assert.match(source("pages/AdminPage.jsx"), /disabled=\{!onCreateAccount\}/);
assert.doesNotMatch(source("pages/AdminPage.jsx"), /admin@gmail\.com|SUCCESS.*CONNECTION\.CHECK|status: "ready"/);
assert.match(source("authorization.ts"), /platform_admin/);
assert.match(source("App.jsx"), /\["보고서 편집", "근거가 연결된 분석 결과와 설명을 블록으로 구성하고 저장합니다\."\]/);
assert.match(reportSources.lifecycle, /if \(isAdmin\) void loadSchedules\(\)/);
assert.match(reportSources.operationsPanel, /브라우저 위치와 관계없이 서울 현지 시각으로 저장합니다/);
assert.match(reportSources.lifecycle, /seoulWallClockToIso\(values\.scheduleAt\)/);
assert.match(reportSources.operationsPanel, /onSetScheduleEnabled\(schedule\.schedule_id, !schedule\.enabled\)/);
assert.doesNotMatch(reportSources.operationsPanel, />due 실행<\/button>/);
assert.doesNotMatch(reportFeatureSource, /REPORT_DRAFT scope|ACTUAL REPORT API/);
assert.match(reportSources.page, /DndContext/);
assert.match(reportSources.editorBlock, /useDraggable/);
assert.match(reportSources.dragAndDrop, /PointerSensor/);
assert.match(reportSources.dragAndDrop, /TouchSensor/);
assert.match(reportSources.dragAndDrop, /KeyboardSensor/);
assert.match(reportSources.dragAndDrop, /placeDraftBlock\(current, activeId, position\.requestedX, position\.y\)/);
assert.match(reportSources.editorBlock, /gridRow:/);
assert.match(reportSources.editorToolbar, /aria-label="보고서 저장"/);
assert.match(reportSources.page, /notion-report-editor/);
assert.match(reportSources.artifactContent, /memo\(function MarkdownText/);
assert.match(reportSources.markdownEditor, /MARKDOWN_INSERT_COMMANDS/);
assert.match(reportSources.markdownEditor, /aria-label="Markdown 블록 삽입"/);
assert.match(reportSources.markdownEditor, /aria-activedescendant/);
assert.match(reportSources.markdownEditor, /event\.key === "Home"/);
assert.match(reportSources.markdownEditor, /event\.key === "End"/);
assert.match(reportSources.artifactContent, /<EnterpriseChart/);
assert.doesNotMatch(reportFeatureSource, /from "recharts"/);
assert.doesNotMatch(reportSources.listView, /className="legacy-report-row"[^>]*onClick/);
assert.match(reportSources.page, /className="editor-tools-scrim" aria-label="블록 도구 닫기"/);
assert.match(reportSources.artifactContent, /ReactMarkdown/);
assert.match(reportSources.artifactContent, /remarkGfm/);
assert.match(reportSources.blockControls, /memo\(function ReportBlockMenu/);
assert.match(reportSources.blockControls, /name="report-block-menu"/);
assert.match(reportSources.editorBlock, /report-resize-handle/);
assert.match(reportSources.markdownEditor, /report-markdown-toolbar/);
assert.match(reportSources.presentation, /id: "artifact-table"/);
assert.match(reportSources.presentation, /id: "artifact-chart"/);
assert.match(reportSources.blockControls, /memo\(function ReportTemplateTile/);
assert.match(reportSources.blockControls, /className="report-template-add"/);
assert.match(reportSources.blockControls, /className="report-template-drag"/);
assert.match(reportSources.blockControls, /setActivatorNodeRef/);
assert.match(reportSources.page, /DragOverlay/);
assert.match(reportSources.dragAndDrop, /dropPositionRef\.current/);
assert.match(reportSources.toolPanel, /원하는 위치로 끌어다 놓으세요/);
assert.match(reportSources.toolPanel, /행은 빈 공간 없이 자동 정렬됩니다/);
assert.doesNotMatch(reportFeatureSource, /notion-block-toolbar/);
assert.match(reportSources.artifactContent, /memo\(function ReportArtifactContent/);
assert.match(reportSources.presentation, /metric\.result_field === resultField/);
assert.doesNotMatch(reportFeatureSource, /revenue\|_krw|REPORT_DIMENSION_LABELS/);
assert.match(reportSources.presentation, /humanizeColumnIdentifier\(column\)/);
assert.doesNotMatch(reportSources.artifactContent, /y_fields\.slice/);
assert.doesNotMatch(source("api/analysisClient.ts"), /restoredMetrics|row\[metric\.metric_id\]/);
assert.match(reportSources.evidence, /export function reportEvidenceReady/);
assert.match(reportSources.artifacts, /if \(!artifact \|\| !reportEvidenceReady\(artifact\)\)/);
assert.match(reportSources.controller, /const canEdit = Boolean\(isDraft && !lifecycle\.pending\)/);
assert.match(reportSources.editorCanvas, /aria-busy=\{pending === "save"\}/);
assert.match(reportSources.controller, /existingDraft/);
assert.match(reportSources.controller, /window\.confirm\(`확정본 v\$\{current\.version\}을 기준으로 새 편집 버전을 만들까요\?`\)/);
assert.match(reportSources.controller, /selectedArtifactSource\?\.artifactId/);
assert.match(reportSources.toolPanel, /선택한 원본으로 AI 초안 생성/);
assert.match(reportSources.controller, /AI 초안 · 검토 필요/);
assert.match(reportSources.artifacts, /status: "loading"/);
assert.match(reportSources.artifactContent, /artifactState\.status === "empty"/);
assert.match(reportSources.artifactContent, /artifactState\.status === "error"/);
assert.match(reportSources.artifactContent, /다시 불러오기/);
assert.match(reportSources.dragAndDrop, /screenReaderInstructions/);
assert.match(reportSources.artifactContent, /실제 호텔 운영 데이터로 해석하지 마세요/);
assert.doesNotMatch(reportFeatureSource, /검증된 데이터/);
assert.match(reportA4Styles, /\.answer-report-page \.report-data-provenance/);
assert.match(reportSources.page, /onDragMove=\{dnd\.handleDragMove\}/);
assert.match(reportSources.editorToolbar, /저장되지 않은 변경/);
assert.match(reportSources.editorToolbar, /저장 실패/);
assert.match(reportSources.draftMutations, /resizeRow && block\.y === source\.y/);
assert.match(reportSources.editorBlock, /event\.buttons & 1/);
assert.match(reportSources.controller, /await artifacts\.loadArtifacts\(current\)/);
assert.match(reportSources.editorBlock, /<ReportArtifactContent/);
assert.match(source("styles.css"), /\.report-api-blocks\.notion-canvas>article\{grid-column:var\(--block-x\)\/span var\(--block-w\)\}/);
assert.match(reportSources.controller, /setView\("editor"\)/);
assert.match(reportSources.controller, /setView\("document"\)/);
assert.match(reportSources.controller, /focusReportBlock/);
assert.match(reportSources.controllerSupport, /pageCanvasRefs\.current\.values\(\)/);
assert.match(reportSources.controllerSupport, /canvas\.querySelector\("\[data-block-id\]"\)/);
assert.match(reportSources.listView, /enterprise-reports-list/);
assert.match(source("styles.css"), /@media\(max-width:700px\)\{[^\n]*\.enterprise-reports-list \.legacy-report-row\{min-width:0/);
assert.match(reportSources.documentView, /legacy-report-document generated-preview/);
assert.match(reportSources.lifecycle, /createNextDraft/);
assert.match(reportSources.lifecycle, /const blocks: ReportBlockRequest\[\] = initialContent \? \[\{/);
assert.match(reportSources.controller, /blocks: \[\{ id: result\.blockId, title: "운영 요약"/);
assert.match(source("pages/AgentPage.jsx"), /savedRuns\.slice\(0, visibleRunCount\)/);
assert.match(source("components/analysis/AnalysisDashboardViews.tsx"), /<EnterpriseChart/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /label: "기본 제외"|label: "GOLD"/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /chartFieldsMatchTable/);
assert.match(source("components/analysis/AnalysisDashboardViews.tsx"), /차트 필드와 상세 데이터 열이 일치하지 않아/);
assert.match(source("features/reports/components/ReportArtifactContent.jsx"), /dataProvenanceLabel\(/);
assert.doesNotMatch(source("utils/presentation.ts"), /합성 데모 데이터/);
assert.match(source("utils/presentation.ts"), /합성 데이터 포함/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /검증된 결과/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /from "recharts"/);
assert.match(source("components/charts/EnterpriseChart.jsx"), /accessibilityLayer/);
assert.match(source("components/charts/EnterpriseChart.jsx"), /<ChartTooltip/);
assert.match(source("components/TurnReportModal.jsx"), /className=\{`report-transfer-modal/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /evidence-panel/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /run\.evidence\?\.productReleaseId/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /run\.evidence\?\.evidenceCutoff/);
assert.match(source("pages/AgentPage.jsx"), /inert=\{Boolean\(reportModal\)\}/);
assert.match(source("api/analysisClient.ts"), /\/analysis\/runs\/\$\{encodeURIComponent\(requestId\)\}\/artifact/);

for (const exposedImplementationCopy of [
  /Saved Analysis/, /Run History/, /Authenticated Session/, /세션 종료/,
  /제목 또는 ID 검색/, /window\.location\.reload/,
]) assert.doesNotMatch(productSources, exposedImplementationCopy);
assert.match(reportSources.operationsPanel, /<details><summary>기술 정보<\/summary><code>Artifact/);
assert.match(source("authorization.ts"), /호텔 분석가/);
assert.match(source("authorization.ts"), /플랫폼 관리자/);
assert.match(source("components/layout/AppHeader.jsx"), /로그아웃/);
assert.match(source("pages/AgentPage.jsx"), /className="run-history-panel"/);
assert.match(source("pages/AgentPage.jsx"), /className="analysis-notice"/);
assert.match(source("pages/AgentPage.jsx"), /reportTitleForAnalysis/);
assert.match(source("pages/AgentPage.jsx"), /createDraftFromArtifact\(artId, reportTitle\.trim\(\) \|\| reportTitleForAnalysis\(reportModalRun\)\)/);
assert.match(source("pages/AgentPage.jsx"), /definitions\.filter/);
assert.match(source("pages/AgentPage.jsx"), /filteredDefinitions\.slice\(0, visibleDefinitionCount\)/);
assert.match(reportSources.lifecycle, /filteredRuns\.slice\(0, visibleRunCount\)/);
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
        context_release: "context-v1",
        product_release_id: "walkerhill-v4.3-sql-20260815-derived.1",
        evidence_cutoff: "2026-08-15",
        policy_version: "policy-v1", model_version: "model-v1",
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
assert.equal(dataProvenanceLabel(normalized.sources), "합성 데이터");
assert.equal(dataProvenanceLabel([{ synthetic: true }, {}]), "합성 데이터 포함");
assert.equal(dataProvenanceLabel([{ synthetic: false }, {}]), null);
assert.equal(normalized.metrics[0].definition, "Metric definition");
assert.equal(normalized.metrics[0].resultField, "metric");
assert.equal(normalized.evidence.metrics[0].definition, "Metric definition");
assert.equal(normalized.evidence.productReleaseId, "walkerhill-v4.3-sql-20260815-derived.1");
assert.equal(normalized.evidence.evidenceCutoff, "2026-08-15");
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

const catalogFailure = commandErrorRun("2026년 7월 호텔별 운영매출 보여줘", {
  status: "FAILED",
  code: "CONTEXT_SOURCE_FAILED",
  message: "질문 문제가 아니라 데이터 카탈로그 검증 실패로 분석을 시작하지 못했습니다.",
  retryable: true,
  required_action: "CONTACT_SUPPORT",
  detail: "urn:li:dataset:(internal)",
});
assert.equal(catalogFailure.error.code, "CONTEXT_SOURCE_FAILED");
assert.equal(catalogFailure.error.required_action, "CONTACT_SUPPORT");
assert.equal(catalogFailure.error.retryable, true);
assert.equal(catalogFailure.error.detail, undefined);

const hydratedCatalogFailure = hydrateTurnsFromServer([{
  turn_id: "turn-failed",
  user_message: "2026년 7월 호텔별 운영매출 보여줘",
  route: "ANALYSIS",
  command_status: "FAILED",
  command_error: {
    code: "CONTEXT_SOURCE_FAILED",
    message: "데이터 카탈로그 검증 실패로 분석을 시작하지 못했습니다.",
    retryable: true,
    required_action: "CONTACT_SUPPORT",
    detail: "checksum-internal",
  },
}]);
assert.equal(hydratedCatalogFailure[0].run.error.code, "CONTEXT_SOURCE_FAILED");
assert.equal(hydratedCatalogFailure[0].run.error.required_action, "CONTACT_SUPPORT");
assert.equal(hydratedCatalogFailure[0].run.error.detail, undefined);

const hydratedSuccess = hydrateTurnsFromServer([{
  turn_id: "turn-success",
  user_message: "임의 지표를 보여줘",
  route: "ANALYSIS",
  command_status: "COMPLETED",
  view_type: "CHART",
  request_id: "persisted-request",
  artifact_id: "persisted-artifact",
  narrative_markdown: "임의 지표는 123입니다.",
  data_snapshot_json: { columns: ["generic_value"], rows: [{ generic_value: 123 }] },
  chart_spec_json: { chart_type: "bar", x_field: "label", y_fields: ["generic_value"] },
  evidence_json: {
    artifact_id: "persisted-artifact",
    query_id: "persisted-query",
    as_of: "2031-04-05",
    timezone: "Asia/Seoul",
    filters: {},
    metrics: [{
      metric_id: "generic_metric",
      result_field: "generic_value",
      label: "Generic Metric",
      definition: "A governed generic metric.",
      unit: "COUNT",
    }],
    metric_values: [{
      metric_id: "generic_metric",
      result_field: "generic_value",
      label: "Generic Metric",
      definition: "A governed generic metric.",
      value: 123,
      unit: "COUNT",
    }],
    sources: [{
      name: "generic_source",
      urn: "urn:li:dataset:(generic)",
      fqn: "generic.catalog.source",
      schema_version: "v1",
      seed_version: "release-1",
      synthetic: false,
    }],
  },
}, {
  turn_id: "turn-table-view",
  user_message: "표로 보여줘",
  route: "PRESENTATION",
  artifact_id: "persisted-artifact",
  view_spec_id: "view-spec-table",
  view_type: "TABLE",
}]);
assert.equal(hydratedSuccess[0].run.metrics[0].metricId, "generic_metric");
assert.equal(hydratedSuccess[0].run.metrics[0].resultField, "generic_value");
assert.equal(hydratedSuccess[0].run.metrics[0].value, 123);
assert.equal(hydratedSuccess[0].run.chart.chartType, "bar");
assert.equal(hydratedSuccess[0].run.evidence.metrics[0].resultField, "generic_value");
assert.equal(hydratedSuccess[0].run.sources[0].schemaVersion, "v1");
assert.equal(hydratedSuccess[1].run.artifact.artifactId, hydratedSuccess[0].run.artifact.artifactId);
assert.equal(hydratedSuccess[1].run.artifact.queryId, hydratedSuccess[0].run.artifact.queryId);
assert.equal(hydratedSuccess[1].run.summary, hydratedSuccess[0].run.summary);
assert.equal(hydratedSuccess[1].isArtifactReuse, true);
assert.equal(hydratedSuccess[1].viewSpecId, "view-spec-table");
assert.equal(hydratedSuccess.length, 2);
assert.deepEqual(hydratedSuccess.map((turn) => turn.turnId), ["turn-success", "turn-table-view"]);
assert.deepEqual(hydratedSuccess.map((turn) => turn.question), ["임의 지표를 보여줘", "표로 보여줘"]);
assert.equal(hydratedSuccess[0].viewType, "CHART");
assert.equal(hydratedSuccess[1].viewType, "TABLE");
assert.match(source("pages/AgentPage.jsx"), /serverTurn\?\.view_type \|\| serverTurn\?\.resolved_slots\?\.target_chart_type \|\| "SUMMARY"/);

const mismatchedPresentation = hydrateTurnsFromServer([{
  turn_id: "turn-source",
  user_message: "원본 분석",
  route: "ANALYSIS",
  command_status: "COMPLETED",
  artifact_id: "artifact-source",
  data_snapshot_json: { columns: ["value"], rows: [{ value: 1 }] },
  evidence_json: {
    artifact_id: "artifact-source", query_id: "query-source", as_of: "2031-04-05",
    filters: {}, metrics: [], sources: [],
  },
}, {
  turn_id: "turn-mismatch",
  user_message: "표로 보여줘",
  route: "PRESENTATION",
  artifact_id: "artifact-other",
  view_spec_id: "view-spec-mismatch",
  view_type: "TABLE",
}]);
assert.equal(mismatchedPresentation[1].run.status, "failed");
assert.equal(mismatchedPresentation[1].run.error.code, "INSUFFICIENT_EVIDENCE");
assert.equal(mismatchedPresentation[1].run.artifact, undefined);
assert.equal(mismatchedPresentation[1].isArtifactReuse, false);

let presentationRequest;
const presentationClient = createHttpAnalysisClient("http://backend.test", async (url, init) => {
  presentationRequest = { url, init };
  return new Response(JSON.stringify({ status: "COMPLETED" }), { status: 200, headers: { "Content-Type": "application/json" } });
});
await presentationClient.submitTurnCommand("conversation-1", {
  user_message: "표로 보여줘",
  requested_route: "PRESENTATION",
  presentation_type: "TABLE",
});
assert.equal(presentationRequest.url, "http://backend.test/conversations/conversation-1/commands");
assert.equal(presentationRequest.url.includes("/analysis"), false);
assert.equal(JSON.parse(presentationRequest.init.body).requested_route, "PRESENTATION");

let commandProgressCalled = false;
const commandAbortController = new AbortController();
await presentationClient.submitTurnCommand("conversation-1", {
  user_message: "요약으로 보여줘",
  requested_route: "PRESENTATION",
  presentation_type: "SUMMARY",
}, {
  traceId: "command-trace",
  signal: commandAbortController.signal,
  onProgress: () => { commandProgressCalled = true; },
});
assert.equal(presentationRequest.init.headers["X-Trace-Id"], "command-trace");
assert.equal(presentationRequest.init.signal, commandAbortController.signal);
assert.equal(commandProgressCalled, false);

const abortingCommandClient = createHttpAnalysisClient("http://backend.test", async (_url, init) => new Promise((_resolve, reject) => {
  init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
}));
const abortingController = new AbortController();
const abortedCommand = abortingCommandClient.submitTurnCommand("conversation-1", {
  user_message: "분석해줘",
  requested_route: "ANALYSIS",
}, { signal: abortingController.signal });
abortingController.abort();
await assert.rejects(abortedCommand, (error) => error?.name === "AbortError");

assert.match(source("api/analysisClient.ts"), /interface SubmitTurnCommandOptions[\s\S]*?signal\?: AbortSignal[\s\S]*?onProgress\?: \(progress: ConversationCommandProgress\)/);
assert.match(source("contracts/analysis.ts"), /interface ConversationCommandProgress extends AnalysisProcessViewModel/);
assert.match(source("pages/AgentPage.jsx"), /activeCommandAbortController\.current\?\.abort\(\)/);
assert.match(source("pages/AgentPage.jsx"), /progress\?\.traceId !== traceId/);
assert.match(source("pages/AgentPage.jsx"), /submitTurnCommand\(activeConvId,[\s\S]*?commandOptions\)/);
assert.match(source("components/layout/AppSidebar.jsx"), /inert=\{!open\}/);
assert.match(source("components/layout/AppSidebar.jsx"), /aria-hidden=\{!open\}/);

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
assert.equal(analysisRequest.init.headers["X-As-Of"], undefined);
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
  return new Response(JSON.stringify({ data: { status: "authenticated", role: "analyst", capabilities: ["analysis.run", "analysis.read", "report.draft"] } }), { status: 200 });
}, "runtime-token");
assert.deepEqual(await sessionClient.validateSession(), { status: "authenticated", role: "analyst", capabilities: ["analysis.run", "analysis.read", "report.draft"] });

let loginRequest;
const loginClient = createHttpAnalysisClient("http://backend.test", async (url, init) => {
  loginRequest = { url, init };
  return new Response(JSON.stringify({ data: { status: "authenticated", role: "report_admin", capabilities: ["report.draft", "report.manage"] } }), { status: 200 });
});
assert.deepEqual(await loginClient.login("admin", "admin1234!"), {
  status: "authenticated", role: "report_admin", capabilities: ["report.draft", "report.manage"],
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
assert.equal(scheduleRequest.init.headers["X-As-Of"], undefined);
assert.deepEqual(JSON.parse(scheduleRequest.init.body), { enabled: false });

console.log("frontend contract tests passed");
