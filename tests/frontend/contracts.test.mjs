import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normalizeApiResponse, OPENAPI_VERSION, resolveViewState, UI_CONTRACT_VERSION } from "../../app/frontend/src/contracts/analysis.ts";
import { compactDraftLayout, placeDraftBlock, REPORT_CONTRACT_VERSION, REPORT_RUN_STATUSES, reorderDraftBlocks, seoulWallClockToIso } from "../../app/frontend/src/contracts/report.ts";
import { AnalysisApiError, createAnalysisClient, createHttpAnalysisClient, normalizeConversationCommandProgress } from "../../app/frontend/src/api/analysisClient.ts";
import { AdminApiError, createAdminClient } from "../../app/frontend/src/api/adminClient.ts";
import { normalizeAuditTrailDetail, normalizeAuditTrailPage } from "../../app/frontend/src/features/admin/audit/auditTrailTypes.ts";
import { createReportClient, ReportApiError } from "../../app/frontend/src/api/reportClient.ts";
import { resolveRoute } from "../../app/frontend/src/routing.js";
import { dataProvenanceLabel } from "../../app/frontend/src/utils/presentation.ts";
import { commandErrorRun, hasReusablePresentationArtifact, hydrateTurnsFromServer, scopeNoticeRun } from "../../app/frontend/src/pages/agentPageHelpers.js";
import { reportFeatureSource, reportSources } from "./report-source-contract.mjs";

const source = (path) => readFileSync(new URL(`../../app/frontend/src/${path}`, import.meta.url), "utf8");
const nginx = readFileSync(new URL("../../app/frontend/nginx.conf", import.meta.url), "utf8");
const frontendCompose = readFileSync(new URL("../../app/frontend/compose.fragment.yml", import.meta.url), "utf8");
const frontendDockerfile = readFileSync(new URL("../../app/frontend/Dockerfile", import.meta.url), "utf8");
const frontendPackage = JSON.parse(readFileSync(new URL("../../app/frontend/package.json", import.meta.url), "utf8"));
const viteConfig = readFileSync(new URL("../../app/frontend/vite.config.js", import.meta.url), "utf8");
const productSources = [
  "App.jsx", "routing.js", "api/analysisClient.ts", "api/adminClient.ts", "api/reportClient.ts",
  "pages/AgentPage.jsx", "pages/AdminPage.jsx",
  "features/admin/audit/AuditTrailPanel.tsx", "features/admin/audit/AuditTrailDetail.tsx",
  "features/admin/audit/auditTrailTypes.ts",
  "components/analysis/AnalysisStatePanel.tsx", "components/analysis/AnalysisStatePanelParts.tsx",
  "components/analysis/AnalysisFailureState.tsx",
  "components/layout/AppHeader.jsx",
].map(source).concat(reportFeatureSource).join("\n");
const reportA4Styles = [
  "features/reports/report-a4-paper.css",
  "features/reports/report-a4-content.css",
  "features/reports/report-a4-artifact.css",
  "features/reports/report-a4-print.css",
].map(source).join("\n");
const globalStyles = source("styles.css");
const reportAssistantPanelSource = source("features/reports/components/ReportAssistantPanel.jsx");

assert.equal(UI_CONTRACT_VERSION, "UI-v1.0.0");
assert.equal(OPENAPI_VERSION, "OPENAPI-v1.0.0");
assert.equal(REPORT_CONTRACT_VERSION, "REPORT-v1.0.0");
assert.match(nginx, /location \/assets\/ \{[\s\S]*try_files \$uri =404/);
assert.match(nginx, /Cache-Control "no-cache, no-store, must-revalidate"/);
assert.match(nginx, /location \/api\/ \{[\s\S]*proxy_pass http:\/\/backend:8000\//);
assert.equal(frontendPackage.scripts["dev:compose"], "vite --mode compose");
assert.match(viteConfig, /composeMode \? "http:\/\/127\.0\.0\.1:28000"/);
assert.match(viteConfig, /composeMode \? "\/api"/);
assert.match(frontendCompose, /VITE_BACKEND_BASE_URL: "\$\{VITE_BACKEND_BASE_URL:-\/api\}"/);
assert.match(frontendDockerfile, /ARG VITE_BACKEND_BASE_URL=\/api/);
assert.match(frontendDockerfile, /^FROM node:24-alpine@sha256:[a-f0-9]{64} AS build$/m);
assert.match(frontendDockerfile, /^FROM nginx:1\.28-alpine@sha256:[a-f0-9]{64}$/m);
for (const key of [
  "ANSWERVICE_SOURCE_REVISION",
  "ANSWERVICE_SOURCE_DIRTY",
  "ANSWERVICE_SOURCE_FINGERPRINT",
]) {
  assert.match(frontendCompose, new RegExp(`${key}: \\S*\\$\\{${key}:-\\}`));
  assert.match(frontendDockerfile, new RegExp(`^ARG ${key}$`, "m"));
}
assert.match(frontendDockerfile, /org\.opencontainers\.image\.revision="\$\{ANSWERVICE_SOURCE_REVISION\}"/);
assert.match(frontendDockerfile, /io\.answervice\.source\.dirty="\$\{ANSWERVICE_SOURCE_DIRTY\}"/);
assert.match(frontendDockerfile, /io\.answervice\.source\.fingerprint="\$\{ANSWERVICE_SOURCE_FINGERPRINT\}"/);
assert.match(frontendDockerfile, /grep -Eq '\^\[0-9a-f\]\{40\}\$'/);
assert.match(frontendDockerfile, /grep -Eq '\^\(true\|false\)\$'/);
assert.match(frontendDockerfile, /grep -Eq '\^\[0-9a-f\]\{64\}\$'/);
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
assert.doesNotMatch(source("pages/AgentPage.jsx"), /onQuickView|quickViewAction/);
assert.doesNotMatch(source("components/analysis/AnalysisDashboardViews.tsx"), /요약으로 보기|KPI만 보기|표로 보기|그래프로 보기/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /AnalysisArtifactReuseNotice/);
assert.equal(hasReusablePresentationArtifact({
  artifact: { artifactId: "artifact-1", queryId: "query-1" },
  evidence: { artifactId: "artifact-1", queryId: "query-1" },
}), true);
assert.equal(hasReusablePresentationArtifact({
  artifact: { artifactId: "artifact-1", queryId: "query-1" },
  evidence: { artifactId: "artifact-1", queryId: "query-other" },
}), false);
assert.equal(hasReusablePresentationArtifact(null), false);
assert.match(source("pages/AgentPage.jsx"), /setTurns\(\(prev\) => \[\.\.\.prev, optimisticTurn\]\)/);
assert.match(source("pages/AgentPage.jsx"), /isPresentationAction && !hasReusablePresentationArtifact\(sourceRun\)/);
assert.match(source("pages/AgentPage.jsx"), /requestGeneration\.current !== generation/);
assert.match(source("pages/AgentPage.jsx"), /analysisClient\.replayDefinition\(definition\.definition_id, \{\}\)/);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /onClick=\{\(\) => void analyzeQuestion\(d\.question\)\}/);
assert.match(source("pages/AgentPage.jsx"), /stale head는 서버 이력으로 복원만 한다/);
assert.match(source("pages/AgentPage.jsx"), /setTurns\(hydrateTurnsFromServer\(serverTurns\)\)/);
assert.doesNotMatch(
  source("pages/AgentPage.jsx"),
  /cmdErr\.status === 409[\s\S]*?submitTurnCommand[\s\S]*?else if \(cmdErr/,
);
assert.match(source("pages/AgentPage.jsx"), /clarifiedQuestion\(turnItem\.question, sugg/);
assert.match(source("components/analysis/AnalysisFailureState.tsx"), /분석 기간을 선택해 주세요/);
assert.match(source("pages/AgentPage.jsx"), /maxLength=\{MAX_QUESTION_LENGTH\}/);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /MAX_QUESTION_LENGTH\.toLocaleString|question-help/);
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
assert.match(analysisPanelSource, /서버가 반환한 실행 트레이스를 업무 단계로 묶어 표시합니다/);
assert.doesNotMatch(analysisPanelSource, /ANALYSIS_PHASES|modelCount/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /supportedChartType/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /문의 코드/);
assert.match(source("contracts/analysis.ts"), /REQUEST_CANCELLED/);
assert.match(source("contracts/analysis.ts"), /NETWORK_UNAVAILABLE/);
assert.match(source("contracts/analysis.ts"), /PRESENTATION_NOT_SUPPORTED/);
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
assert.match(analysisPanelSource, /metric \? metricDisplayLabel\(metric\) : column/);
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
assert.doesNotMatch(source("App.jsx"), /menuOpen|AppSidebar|sidebar-collapsed/);
assert.doesNotMatch(source("styles.css"), /\.scrim\{|\.mobile-menu\{|(?:^|\n)\.sidebar\{/);
assert.match(source("App.jsx"), /hasCapability\(capabilities, CAPABILITY\.runAnalysis\)/);
assert.match(source("App.jsx"), /hasCapability\(capabilities, CAPABILITY\.manageReport\)/);
assert.match(source("App.jsx"), /hasCapability\(capabilities, CAPABILITY\.manageSystem\)/);
assert.match(source("App.jsx"), /else if \(canUseAdmin\) navigate\(PAGE_PATHS\.admin\)/);
assert.match(source("App.jsx"), /세션이 만료되었습니다\. 안전을 위해 사용자 임시 상태를 지웠습니다/);
assert.match(source("App.jsx"), /clearAuthenticatedBrowserState\(\)/);
assert.doesNotMatch(source("App.jsx"), /session-reauth-layer/);
assert.match(source("App.jsx"), /answervice:report-dirty/);
assert.match(source("App.jsx"), /reportDirty && !window\.confirm\("저장하지 않은 보고서 변경사항이 있습니다\. 페이지를 이동할까요\?"\)/);
assert.match(source("App.jsx"), /reportDirty && !window\.confirm\("저장하지 않은 보고서 변경사항이 있습니다\. 로그아웃할까요\?"\)/);
assert.match(source("App.jsx"), /현재 계정에 허용된 서비스 메뉴가 없습니다/);
assert.match(source("App.jsx"), /<AppHeader page=\{route\.page\}[\s\S]*?capabilities=\{capabilities\}[\s\S]*?onNavigate=\{navigate\}/);
assert.match(source("components/layout/AppHeader.jsx"), /hasCapability\(capabilities, item\.capability\)/);
assert.match(source("components/layout/AppHeader.jsx"), /label: "관리자"[\s\S]*?CAPABILITY\.manageSystem/);
assert.match(source("components/layout/AppHeader.jsx"), /alternative: CAPABILITY\.manageReport/);
assert.match(source("components/layout/AppHeader.jsx"), /<nav className="top-navigation" aria-label="주요 메뉴">/);
assert.match(source("components/layout/AppHeader.jsx"), /aria-current=\{page === id \? "page" : undefined\}/);
assert.match(source("App.jsx"), /<AgentPage canDraftReport=\{canDraftReport\}/);
assert.match(source("authorization.ts"), /ServiceRole = "analyst" \| "report_admin" \| "data_admin" \| "platform_admin"/);
assert.match(source("pages/AdminPage.jsx"), /연결 상태/);
assert.match(source("pages/AdminPage.jsx"), /계정 관리/);
assert.match(source("pages/AdminPage.jsx"), /감사 로그/);
assert.match(source("pages/AdminPage.jsx"), /client\.listConnections\(\)/);
assert.match(source("pages/AdminPage.jsx"), /client\.listAccounts\(accountPage, accountSearch\)/);
assert.match(source("pages/AdminPage.jsx"), /<AuditTrailPanel client=\{client\}/);
assert.match(source("App.jsx"), /const adminClient = useMemo\(\(\) => canUseAdmin \? createAdminClient\(undefined, fetch\) : null, \[canUseAdmin\]\)/);
assert.match(source("App.jsx"), /<AdminPage role=\{role\} client=\{adminClient\} \/>/);
assert.doesNotMatch(source("pages/AdminPage.jsx"), /createAdminClient|VITE_BACKEND_BASE_URL|https?:\/\/|localhost|127\.0\.0\.1|\bfetch\b/);
assert.doesNotMatch(source("api/adminClient.ts"), /https?:\/\/|localhost|127\.0\.0\.1|:[0-9]{2,5}/);
assert.match(source("pages/AdminPage.jsx"), /client\.resetPassword/);
assert.match(source("pages/AdminPage.jsx"), /client\.deleteAccount/);
assert.match(globalStyles, /\.admin-console\{display:grid;gap:18px;padding-top:22px\}/);
assert.match(globalStyles, /\.admin-connection-grid\{display:grid;grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
assert.match(globalStyles, /\.admin-data-table__head,\.admin-data-table__row\{[^}]*display:grid/);
assert.match(globalStyles, /\.ppt-theme \.admin-console__tabs button\.is-active\{/);
assert.match(globalStyles, /@media\(max-width:700px\)\{\.admin-console\{padding-top:14px\}/);
assert.match(globalStyles, /\.admin-data-table__row>\[role=cell\]::before\{content:attr\(data-label\)/);
assert.match(source("pages/AdminPage.jsx"), /role="cell" data-label="사용자 아이디"/);
assert.match(globalStyles, /@media\(max-width:700px\)\{[\s\S]*?\.top-actions>\.session-signout>span\{display:none\}/);
assert.match(source("features/admin/audit/AuditTrailPanel.tsx"), /client\.listAuditTrails\(filters, cursor\)/);
assert.match(source("features/admin/audit/AuditTrailPanel.tsx"), /client\.getAuditTrail\(selectedTrailId\)/);
assert.doesNotMatch(source("components/layout/AppHeader.jsx"), /inert=|메뉴 열기|메뉴 닫기/);
assert.match(source("App.jsx"), /\["보고서 편집", "근거가 연결된 분석 결과와 설명을 블록으로 구성하고 저장합니다\."\]/);
assert.match(reportSources.lifecycle, /if \(isAdmin\) void loadSchedules\(\)/);
assert.doesNotMatch(reportSources.page, /ReportAssistantOperationsPanel/);
assert.doesNotMatch(reportSources.lifecycle, /loadAssistantOperations/);
assert.match(source("api/reportClient.ts"), /getAssistantOperationsSummary/);
assert.match(source("api/reportClient.ts"), /\/reports\/assistant\/operations\/summary/);
assert.match(source("api/reportClient.ts"), /getAssistantOperationFailures/);
assert.doesNotMatch(source("api/reportClient.ts"), /raw_model_response|sql_text/);
assert.match(reportSources.lifecycle, /reportClient\.getAssistantEvaluation\(session\.assistant_request_id\)/);
assert.match(reportSources.lifecycle, /const assistantRequestRef = useRef\(0\)/);
assert.match(reportSources.lifecycle, /assistantRequestRef\.current !== request/);
assert.match(reportSources.lifecycle, /if \(isCurrent\(\)\) setError\(reportApiError\(nextError\)\)/);
assert.match(reportSources.lifecycle, /setAssistantSession\(null\)/);
assert.match(reportSources.lifecycle, /reportClient\.retryAssistantSession\(current\.assistant_request_id\)/);
assert.match(reportSources.lifecycle, /reportClient\.getAssistantSession\(session\.assistant_request_id\)/);
assert.match(reportSources.lifecycle, /if \(recovered && assistantRequestRef\.current === request\) setAssistantSession\(recovered\)/);
assert.match(reportSources.lifecycle, /setAssistantEvaluation\(null\)/);
assert.match(reportSources.page, /evaluation=\{lifecycle\.assistantEvaluation\}/);
assert.match(reportSources.page, /onRetry=\{lifecycle\.retryAssistantSession\}/);
assert.match(reportSources.page, /onReview=\{page\.reviewAssistantReport\}/);
assert.match(reportSources.lifecycle, /reportClient\.reviewAssistantSession\(session\.assistant_request_id, selectedBlockId\)/);
assert.match(reportAssistantPanelSource, /요청 처리를 확인했습니다/);
assert.match(reportAssistantPanelSource, /report-assistant-technical-detail/);
assert.match(reportAssistantPanelSource, /비저장 품질 검토/);
assert.match(reportAssistantPanelSource, /이 항목 수정하기/);
assert.match(reportAssistantPanelSource, /종합 편집 근거 선택/);
assert.match(reportSources.page, /onSelectArtifacts=\{artifacts\.setAssistantArtifacts\}/);
assert.match(reportAssistantPanelSource, /failed" && retryable/);
assert.match(reportAssistantPanelSource, /새 세션으로 다시 시도/);
assert.match(reportSources.page, /evidenceRefs: lifecycle\.assistantSession\.patch_evidence_refs/);
assert.match(source("contracts/reportNormalization.ts"), /evidenceRefs: \[\.\.\.\(block\.evidence_refs \?\? \[\]\)\]/);
assert.match(source("contracts/reportNormalization.ts"), /evidence_refs: \[\.\.\.\(block\.evidenceRefs \?\? \[\]\)\]/);
assert.match(reportSources.draftState, /change\.content !== block\.content[\s\S]*evidenceRefs: \[\]/);
assert.match(reportSources.page, /key=\{`\$\{lifecycle\.selectedDefinition\?\.definitionId/);
assert.match(reportSources.controller, /assistantArtifactIds\.join\(":"\)/);
assert.match(reportAssistantPanelSource, /사용 근거/);
assert.match(source("contracts/reportContract.ts"), /artifact_narrative/);
assert.doesNotMatch(reportAssistantPanelSource, /요약을 세 줄로 줄여줘/);
assert.match(reportAssistantPanelSource, /suggestions\.map/);
assert.doesNotMatch(reportAssistantPanelSource, /estimated_cost|raw_model_response|sql_text/);
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
assert.match(reportSources.presentation, /id: "artifact-summary"/);
assert.match(reportSources.presentation, /id: "artifact-kpi"/);
assert.match(reportSources.blockControls, /memo\(function ReportTemplateTile/);
assert.match(reportSources.blockControls, /className="report-template-add"/);
assert.match(reportSources.blockControls, /setActivatorNodeRef/);
assert.match(reportSources.blockControls, /<button\s+ref=\{setActivatorNodeRef\}[\s\S]*?className="report-template-add"[\s\S]*?\{\.\.\.listeners\}[\s\S]*?\{\.\.\.attributes\}/);
assert.doesNotMatch(reportSources.blockControls, /report-template-drag|report-template-grip|GripVertical/);
assert.match(reportSources.page, /DragOverlay/);
assert.match(reportSources.dragAndDrop, /dropPositionRef\.current/);
assert.match(reportSources.toolPanel, /필요한 항목만 열어 클릭하거나 캔버스로 끌어 놓으세요/);
assert.match(reportSources.toolPanel, /<details className="report-library-group" open>/);
assert.doesNotMatch(reportFeatureSource, /notion-block-toolbar/);
assert.match(reportSources.artifactContent, /memo\(function ReportArtifactContent/);
assert.match(reportSources.presentation, /metric\.result_field === resultField/);
assert.doesNotMatch(reportFeatureSource, /revenue\|_krw|REPORT_DIMENSION_LABELS/);
assert.match(reportSources.presentation, /humanizeColumnIdentifier\(column\)/);
assert.doesNotMatch(reportSources.artifactContent, /y_fields\.slice/);
assert.doesNotMatch(source("api/analysisClient.ts"), /restoredMetrics|row\[metric\.metric_id\]/);
assert.match(reportSources.evidence, /export function reportEvidenceReady/);
assert.match(reportSources.artifacts, /if \(!artifact \|\| !reportEvidenceReady\(artifact\)\)/);
assert.match(reportSources.artifacts, /if \(includeLibrary\) \{[\s\S]*discoveredAnalysisSources\.forEach\(\(source\) => hydrationIds\.add\(source\.artifactId\)\)/);
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
assert.match(reportSources.documentView, /legacy-report-document generated-preview/);
assert.match(reportSources.lifecycle, /createNextDraft/);
assert.match(reportSources.lifecycle, /const blocks: ReportBlockRequest\[\] = initialContent \? \[\{/);
assert.match(reportSources.controller, /blocks: \[\{ id: result\.blockId, title: "운영 요약"/);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /run-history-panel|listRuns\(/);
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
assert.match(source("components/TurnReportModal.jsx"), /className=\{isDraft \? "report-transfer-modal"/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /evidence-panel/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /결과 요약/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /문맥·SQL·결과 검증 통과/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /분석 기간/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /analysisTitle\(run\)/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /userFacingAnalysisSummary\(run, valueScale\)/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /"분석 데이터"/);
assert.doesNotMatch(source("components/TurnEvidenceDrawer.jsx"), /analytics_v4_3|SOURCE_LABELS_KO/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /timezone === "Asia\/Seoul" \? "서울 시간"/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /run\.evidence\?\.productReleaseId/);
assert.match(source("components/TurnEvidenceDrawer.jsx"), /run\.evidence\?\.evidenceCutoff/);
assert.match(globalStyles, /\.theme-light \.artifact-report-summary\{[^}]*background:#f8fbff/);
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
assert.doesNotMatch(source("pages/AgentPage.jsx"), /className="run-history-panel"/);
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
  id: "right", title: "오른쪽", columns: 6, type: "text", content: "오른쪽", x: 0, y: 2, w: 6, h: 2,
});
const collisionAvoidedBlocks = placeDraftBlock(compactlyPlacedBlocks, "left", 6, 3);
assert.deepEqual(collisionAvoidedBlocks.map((block) => [block.x, block.y]), [[0, 0], [0, 2]]);

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
assert.deepEqual(filledRows.map((block) => [block.x, block.y, block.w]), [[0, 0, 6], [0, 4, 12]]);

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
      metrics: [{ metric_id: "metric", result_field: "metric", label: "Metric", display_label: "승인 지표", definition: "Metric definition", value: 3, unit: "count", display_unit: "건" }],
      table: { columns: ["metric"], rows: [{ metric: 3 }] },
      chart: null,
      evidence: {
        artifact_id: "artifact-1", query_id: "query-1", as_of: "2030-01-02", timezone: "Asia/Seoul",
        period: { start: "2030-01-01", end_exclusive: "2030-01-03" }, filters: {}, cached: false,
        comparison_period: { start: "2029-12-01", end_exclusive: "2030-01-01" },
        context_release: "context-v1",
        product_release_id: "walkerhill-v4.3-sql-20260815-derived.1",
        evidence_cutoff: "2026-08-15",
        policy_version: "policy-v1", model_version: "model-v1",
        metrics: [{ metric_id: "metric", result_field: "metric", label: "Metric", display_label: "승인 지표", definition: "Metric definition", unit: "count", display_unit: "건" }],
        models: [{ node: "node3", model_version: "model-v1", prompt_id: "node3-prompt", prompt_version: "v1" }],
        gates: { g1: "PASSED", g2: "PASSED", g3: "PASSED" },
        gate_history: { g1: ["PASSED"], g2: ["BLOCKED", "PASSED"], g3: ["PASSED"] },
        sampling: { applied: false, returned_rows: 1, total_rows: 1 },
        masking: { applied: true, fields: ["guest_id"] },
        execution: { processed_rows: 4, scan_bytes: 128, warning_count: 1, critical_warning_count: 0 },
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
assert.equal(normalized.metrics[0].displayLabel, "승인 지표");
assert.equal(normalized.metrics[0].displayUnit, "건");
assert.equal(normalized.evidence.metrics[0].definition, "Metric definition");
assert.equal(normalized.evidence.metrics[0].displayLabel, "승인 지표");
assert.equal(normalized.evidence.productReleaseId, "walkerhill-v4.3-sql-20260815-derived.1");
assert.deepEqual(normalized.evidence.comparisonPeriod, {
  start: "2029-12-01",
  endExclusive: "2030-01-01",
});
assert.equal(normalized.evidence.evidenceCutoff, "2026-08-15");
assert.equal(normalized.evidence.models[0].promptId, "node3-prompt");
assert.equal(normalized.evidence.gates.g3, "PASSED");
assert.deepEqual(normalized.evidence.gateHistory.g2, ["BLOCKED", "PASSED"]);
assert.deepEqual(normalized.evidence.masking.fields, ["guest_id"]);
assert.deepEqual(normalized.evidence.execution, {
  processedRows: 4,
  scanBytes: 128,
  warningCount: 1,
  criticalWarningCount: 0,
});
assert.equal(normalized.meta.synthetic, undefined);

const snapshotResponse = structuredClone(apiResponse);
delete snapshotResponse.data.result.evidence.period;
delete snapshotResponse.data.result.evidence.comparison_period;
snapshotResponse.data.result.evidence.snapshot = {
  cutoff: "2030-01-02",
  selection: "max_source_value_lt_as_of",
};
const normalizedSnapshot = normalizeApiResponse(snapshotResponse, "question");
assert.equal(resolveViewState(normalizedSnapshot), "READY");
assert.deepEqual(normalizedSnapshot.evidence.snapshot, {
  cutoff: "2030-01-02",
  selection: "max_source_value_lt_as_of",
});

const conflictingTimeEvidence = structuredClone(snapshotResponse);
conflictingTimeEvidence.data.result.evidence.period = {
  start: "2030-01-01",
  end_exclusive: "2030-01-03",
};
assert.equal(
  resolveViewState(normalizeApiResponse(conflictingTimeEvidence, "question")),
  "INSUFFICIENT_EVIDENCE",
);

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

const emptyResultResponse = {
  data: {
    status: "BLOCKED",
    result: null,
    evidence: {
      query_id: "query-empty-1",
      as_of: "2030-01-02",
      timezone: "Asia/Seoul",
      period: { start: "2030-01-01", end_exclusive: "2030-01-03" },
      filters: { "catalog.schema.table.hotel_name": "비스타 호텔" },
      sampling: { applied: false, returned_rows: 0, total_rows: 0 },
      sources: [{ name: "source", urn: "urn:source", fqn: "catalog.schema.table", schema_version: "1", seed_version: "2" }],
    },
  },
  meta: apiResponse.meta,
  error: {
    code: "EMPTY_RESULT",
    message: "요청한 기간과 조건에 해당하는 결과가 없습니다.",
    retryable: false,
    required_action: "MODIFY_REQUEST",
  },
};
const emptyResult = normalizeApiResponse(emptyResultResponse, "question");
assert.equal(resolveViewState(emptyResult), "EMPTY");
assert.equal(emptyResult.evidence.queryId, "query-empty-1");
assert.deepEqual(emptyResult.evidence.period, {
  start: "2030-01-01",
  endExclusive: "2030-01-03",
});
assert.equal(emptyResult.evidence.filters["catalog.schema.table.hotel_name"], "비스타 호텔");
assert.equal(emptyResult.sources[0].name, "source");

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

const scopeNotice = scopeNoticeRun("오늘 날씨 어때?", "지원 범위에 맞게 요청해 주세요.");
assert.equal(scopeNotice.status, "blocked");
assert.equal(scopeNotice.scopeNotice.message, "지원 범위에 맞게 요청해 주세요.");
const hydratedScopeNotice = hydrateTurnsFromServer([{
  turn_id: "turn-out-of-scope",
  user_message: "오늘 날씨 어때?",
  route: "OUT_OF_SCOPE",
  terminal_status: "BLOCKED",
  resolved_slots: {
    scope_rejection: { message: "지원 범위에 맞게 요청해 주세요." },
  },
}]);
assert.equal(hydratedScopeNotice[0].viewType, "CHAT");
assert.equal(hydratedScopeNotice[0].run.scopeNotice.message, "지원 범위에 맞게 요청해 주세요.");
assert.equal(hydratedScopeNotice[0].run.artifact, undefined);

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
  terminal_status: "SUCCEEDED",
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
assert.equal(hydratedSuccess.length, 2);
assert.deepEqual(hydratedSuccess.map((turn) => turn.turnId), ["turn-success", "turn-table-view"]);
assert.deepEqual(hydratedSuccess.map((turn) => turn.question), ["임의 지표를 보여줘", "표로 보여줘"]);
assert.equal(hydratedSuccess[0].viewType, "SUMMARY");
assert.equal(hydratedSuccess[1].viewType, "TABLE");
assert.equal(hydratedSuccess[1].run.artifact.artifactId, hydratedSuccess[0].run.artifact.artifactId);
assert.equal(hydratedSuccess[1].run.artifact.queryId, hydratedSuccess[0].run.artifact.queryId);
assert.equal(hydratedSuccess[1].run.summary, hydratedSuccess[0].run.summary);
assert.equal(hydratedSuccess[1].isArtifactReuse, true);
assert.equal(hydratedSuccess[1].viewSpecId, "view-spec-table");

const mismatchedPresentation = hydrateTurnsFromServer([{
  turn_id: "turn-source",
  user_message: "원본 분석",
  route: "ANALYSIS",
  command_status: "COMPLETED",
  artifact_id: "artifact-source",
  data_snapshot_json: { columns: ["value"], rows: [{ value: 1 }] },
  evidence_json: {
    artifact_id: "artifact-source",
    query_id: "query-source",
    as_of: "2031-04-05",
    filters: {},
    metrics: [],
    sources: [],
  },
}, {
  turn_id: "turn-mismatch",
  user_message: "표로 보여줘",
  route: "PRESENTATION",
  terminal_status: "SUCCEEDED",
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
  return new Response(JSON.stringify({ status: "COMPLETED" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
await presentationClient.submitTurnCommand("conversation-1", {
  user_message: "표로 보여줘",
  requested_route: "PRESENTATION",
  presentation_type: "TABLE",
});
assert.equal(presentationRequest.url, "http://backend.test/conversations/conversation-1/commands");
assert.equal(presentationRequest.url.includes("/analysis"), false);
assert.equal(JSON.parse(presentationRequest.init.body).requested_route, "PRESENTATION");

const commandProgressSnapshot = {
  trace_id: "command-trace",
  request_id: "58e54349-1f44-4d5f-9839-c5a81d437ad6",
  status: "ROUTED",
  started_at: "2026-08-28T00:00:00Z",
  elapsed_seconds: 2.4,
  cancel_requested: false,
  trace: [
    { stage: "ROUTER", outcome: "PASSED" },
    { stage: "CONTROLLER", outcome: "PASSED" },
    { stage: "CONTEXT", outcome: "PASSED" },
    { stage: "G1", outcome: "PASSED" },
  ],
};
const normalizedCommandProgress = normalizeConversationCommandProgress(commandProgressSnapshot);
assert.equal(normalizedCommandProgress.traceId, "command-trace");
assert.deepEqual(normalizedCommandProgress.steps.map((step) => step.state), [
  "complete", "complete", "active", "pending", "pending", "pending",
]);
assert.match(normalizedCommandProgress.steps[2].label, /SQL/);

let commandResponseResolve;
let receivedCommandProgress = null;
const commandProgressRequests = [];
const commandAbortController = new AbortController();
const commandProgressClient = createHttpAnalysisClient("http://backend.test", async (url, init) => {
  commandProgressRequests.push({ url, init });
  if (url.endsWith("/commands")) {
    return new Promise((resolve) => { commandResponseResolve = resolve; });
  }
  setTimeout(() => commandResponseResolve(new Response(JSON.stringify({ status: "SUCCESS" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })), 10);
  return new Response(JSON.stringify({ data: commandProgressSnapshot }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
await commandProgressClient.submitTurnCommand("conversation-1", {
  user_message: "5월 객실 매출",
  requested_route: "ANALYSIS",
}, {
  traceId: "command-trace",
  signal: commandAbortController.signal,
  onProgress: (progress) => { receivedCommandProgress = progress; },
});
const commandRequest = commandProgressRequests.find((item) => item.url.endsWith("/commands"));
assert.equal(commandRequest.init.headers["X-Trace-Id"], "command-trace");
assert.equal(commandRequest.init.signal, commandAbortController.signal);
assert.equal(commandProgressRequests.some((item) => item.url.endsWith("/analysis/progress/command-trace/poll")), true);
assert.equal(receivedCommandProgress?.steps[2].state, "active");

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
assert.match(source("pages/AgentPage.jsx"), /processViewModel: null/);
assert.doesNotMatch(source("pages/AgentPage.jsx"), /completedAnalysisProcess|normalizeConversationCommandProgress/);
assert.doesNotMatch(source("components/analysis/AnalysisStatePanel.tsx"), /showCompletedAnalysisProcess/);
assert.match(source("pages/AgentPage.jsx"), /submitTurnCommand\(activeConvId,[\s\S]*?commandOptions\)/);
assert.match(source("pages/AgentPage.jsx"), /requested_route: "INTERNAL_GUIDELINE",[\s\S]*?inherit_previous_context: true/);

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
await analysisClient.listRuns({ limit: 7, approvedOnly: true });
assert.equal(analysisRequest.url, "http://backend.test/analysis/runs?limit=7&approved_only=true");

let ragCatalogRequest;
const ragCatalogClient = createHttpAnalysisClient("http://backend.test", async (url, init) => {
  ragCatalogRequest = { url, init };
  return new Response(JSON.stringify({
    status: "SUCCESS",
    data: {
      documents: [{
        manual_id: "manual-approved",
        title: "승인 운영 매뉴얼",
        version: "v3",
        document_type: "OPERATIONS_MANUAL",
        owner_team: "운영팀",
      }],
    },
  }), { status: 200 });
}, "runtime-token");
assert.deepEqual(await ragCatalogClient.listInternalManuals(), [{
  manual_id: "manual-approved",
  title: "승인 운영 매뉴얼",
  version: "v3",
  document_type: "OPERATIONS_MANUAL",
  owner_team: "운영팀",
}]);
assert.equal(ragCatalogRequest.url, "http://backend.test/rag/documents");
assert.equal(ragCatalogRequest.init.headers.Authorization, "Bearer runtime-token");

const invalidRagCatalogClient = createHttpAnalysisClient("http://backend.test", async () => new Response(JSON.stringify({
  data: { documents: [{ manual_id: "manual-missing-approved-metadata" }] },
}), { status: 200 }));
await assert.rejects(
  () => invalidRagCatalogClient.listInternalManuals(),
  /내부 문서 API가 올바르지 않은 응답/,
);

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

await analysisClient.submitTurnCommand("conversation-1", {
  user_message: "question",
  expected_head_turn_id: null,
  idempotency_key: "command-1",
}, { traceId: "conversation-trace" });
assert.equal(analysisRequest.url, "http://backend.test/conversations/conversation-1/commands");
assert.equal(analysisRequest.init.headers["X-Trace-Id"], "conversation-trace");

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

const account = {
  subject: "00000000-0000-0000-0000-000000000001",
  username: "analyst",
  role: "analyst",
  active: true,
  created_at: "2030-01-01T00:00:00Z",
  updated_at: "2030-01-01T00:00:00Z",
  deactivated_at: null,
  deleted_at: null,
};
let adminRequest;
const adminClient = createAdminClient("http://backend.test", async (url, init) => {
  adminRequest = { url, init };
  if (url.endsWith("/password") || init.method === "DELETE") return new Response(null, { status: 204 });
  if (["POST", "PATCH"].includes(init.method)) return new Response(JSON.stringify({ data: account }), { status: init.method === "POST" ? 201 : 200 });
  return new Response(JSON.stringify({ data: { items: [account], page: 2, page_size: 50, total: 51 } }), { status: 200 });
});
assert.deepEqual(await adminClient.listAccounts(2, "kim hong"), { items: [account], page: 2, page_size: 50, total: 51 });
assert.equal(adminRequest.url, "http://backend.test/admin/accounts?page=2&page_size=50&search=kim+hong");
assert.equal(adminRequest.init.credentials, "include");
assert.equal(adminRequest.init.headers["X-Contract-Version"], OPENAPI_VERSION);
assert.deepEqual(await adminClient.createAccount({ username: "analyst", password: "temporary-pass", role: "analyst" }), account);
assert.deepEqual(JSON.parse(adminRequest.init.body), { username: "analyst", password: "temporary-pass", role: "analyst" });
assert.deepEqual(await adminClient.updateAccount(account.subject, { role: "report_admin", active: true }), account);
assert.equal(adminRequest.init.method, "PATCH");
await adminClient.resetPassword(account.subject, "rotated-password");
assert.equal(adminRequest.url, `http://backend.test/admin/accounts/${account.subject}/password`);
assert.deepEqual(JSON.parse(adminRequest.init.body), { password: "rotated-password" });
await adminClient.deleteAccount(account.subject);
assert.equal(adminRequest.init.method, "DELETE");

const protectedAdminClient = createAdminClient("http://backend.test", async () => new Response(JSON.stringify({
  error: { code: "LAST_ADMIN_REQUIRED", message: "마지막 활성 관리자는 변경할 수 없습니다." },
}), { status: 409 }));
await assert.rejects(
  () => protectedAdminClient.deleteAccount(account.subject),
  (nextError) => nextError instanceof AdminApiError
    && nextError.status === 409
    && nextError.code === "LAST_ADMIN_REQUIRED",
);

const auditTrailSummary = {
  trail_id: "request:00000000-0000-0000-0000-000000000002",
  headline: "분석 요청 실행",
  started_at: "2030-01-01T00:00:00Z",
  ended_at: "2030-01-01T00:00:03Z",
  outcome: "DENIED",
  event_count: 1,
  actor: { subject: account.subject, display_name: "분석 사용자", role: "analyst" },
  primary_object: { type: "ANALYSIS_REQUEST", id: "00000000-0000-0000-0000-000000000002" },
  correlation: { type: "REQUEST", id: "00000000-0000-0000-0000-000000000002" },
};
const auditTrailDetail = {
  trail_id: auditTrailSummary.trail_id,
  headline: auditTrailSummary.headline,
  started_at: auditTrailSummary.started_at,
  ended_at: auditTrailSummary.ended_at,
  outcome: "DENIED",
  events: [{
    event_id: "00000000-0000-0000-0000-000000000003",
    occurred_at: "2030-01-01T00:00:01Z",
    sequence: 1,
    action_code: "ANALYSIS_DENIED",
    action_label: "분석 요청 거부",
    summary: "정책 검증에서 요청을 거부했습니다.",
    outcome: "DENIED",
    actor: auditTrailSummary.actor,
    object: auditTrailSummary.primary_object,
    evidence: {
      request_id: "00000000-0000-0000-0000-000000000002",
      trace_id: "trace-1",
      query_execution_id: null,
      query_id: null,
      artifact_id: null,
      report_run_id: null,
      context_release_id: null,
      model_version_id: null,
      sql_policy_version: "policy-v1",
    },
    details_redacted: { reason: "PERMISSION" },
  }],
};
let adminQueryUrl;
const adminQueryClient = createAdminClient("http://backend.test", async (url) => {
  adminQueryUrl = url;
  if (url.endsWith("/connections")) return new Response(JSON.stringify({ data: { items: [{ id: "app_db", name: "App DB", kind: "PostgreSQL", status: "ready", latency_ms: 8, checked_at: "2030-01-01T00:00:00Z" }] } }), { status: 200 });
  if (url.includes("/admin/audit-trails?")) return new Response(JSON.stringify({ data: { items: [auditTrailSummary], next_cursor: "cursor-2" } }), { status: 200 });
  return new Response(JSON.stringify({ data: auditTrailDetail }), { status: 200 });
});
assert.equal((await adminQueryClient.listConnections())[0].status, "ready");
assert.equal(adminQueryUrl, "http://backend.test/admin/connections");
assert.equal((await adminQueryClient.listAuditTrails({ query: "kim hong", outcome: "DENIED", action: "ANALYSIS", from: "2030-01-01", to: "2030-01-02" }, "opaque cursor")).items[0].outcome, "DENIED");
assert.equal(adminQueryUrl, "http://backend.test/admin/audit-trails?cursor=opaque+cursor&limit=30&query=kim+hong&outcome=DENIED&action=ANALYSIS&from=2030-01-01&to=2030-01-02");
assert.equal((await adminQueryClient.getAuditTrail(auditTrailSummary.trail_id)).events[0].details_redacted.reason, "PERMISSION");
assert.equal(normalizeAuditTrailPage({ items: [auditTrailSummary], next_cursor: null }).items[0].event_count, 1);
assert.equal(normalizeAuditTrailDetail(auditTrailDetail).events[0].event_id, auditTrailDetail.events[0].event_id);
assert.throws(() => normalizeAuditTrailPage({ items: [{ ...auditTrailSummary, outcome: "SUCCESS" }], next_cursor: null }), /지원하지 않는 결과 상태/);
assert.throws(() => normalizeAuditTrailDetail({ ...auditTrailDetail, events: {} }), /올바르지 않은 응답/);

for (const role of ["report_admin", "data_admin", "platform_admin"]) {
  const roleClient = createAdminClient("http://backend.test", async () => new Response(JSON.stringify({ data: { items: [{ ...account, role }], page: 1, page_size: 50, total: 1 } }), { status: 200 }));
  assert.equal((await roleClient.listAccounts()).items[0].role, role);
}
const legacyRoleClient = createAdminClient("http://backend.test", async () => new Response(JSON.stringify({ data: { items: [{ ...account, role: "admin" }], page: 1, page_size: 50, total: 1 } }), { status: 200 }));
await assert.rejects(() => legacyRoleClient.listAccounts(), /관리자 계정 API가 올바르지 않은 응답/);

let defaultRequests = 0;
assert.throws(
  () => createAnalysisClient(async () => { defaultRequests += 1; return new Response(JSON.stringify(apiResponse)); }, "runtime-token"),
  /VITE_BACKEND_BASE_URL is required/,
);
assert.equal(defaultRequests, 0);

let defaultAdminRequests = 0;
assert.throws(
  () => createAdminClient(undefined, async () => { defaultAdminRequests += 1; return new Response(); }),
  /VITE_BACKEND_BASE_URL is required/,
);
assert.equal(defaultAdminRequests, 0);

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

let assistantSessionRequest;
const assistantSessionClient = createReportClient("http://backend.test", async (url, init) => {
  assistantSessionRequest = { url, init };
  const session = {
    assistant_request_id: "assistant/1", phase: "ready", operation_scope: "full_report",
    definition_id: "definition-1", definition_version: 2, base_revision: 2,
    artifact_id: "artifact-1", artifact_ids: ["artifact-1"], analysis_plan: null,
    patch_request_id: null, patch_summary: null, patch_operations: [], patch_evidence_refs: [], result_artifact_id: null,
    patch_preview: [], approved_operation_indexes: [],
    result_revision: null, error_code: null, retryable: false, required_action: "NONE",
    retry_of_assistant_request_id: null,
    turn_history: [],
  };
  const retrySession = url.endsWith("/retry") ? {
    ...session, assistant_request_id: "assistant-2",
    retry_of_assistant_request_id: "assistant/1",
  } : null;
  const cancelledSession = url.endsWith("/cancel") ? {
    ...session, phase: "cancelled", error_code: "ASSISTANT_CANCELLED",
  } : null;
  const patchApproval = url.endsWith("/patch-approval") ? JSON.parse(init.body) : null;
  const approval = url.endsWith("/approval") && !patchApproval ? JSON.parse(init.body) : null;
  const approvalSession = approval ? {
    ...session,
    phase: approval.approved ? "completed" : "ready",
    result_artifact_id: approval.approved ? "artifact-2" : null,
    result_revision: approval.approved ? 3 : null,
    analysis_plan: {
      request_id: approval.request_id,
      question: "현재 지표를 직전 월과 비교해 줘",
      reason: "직전 월 값이 필요합니다.",
      scope: { period: "현재 기간과 직전 월", metrics: ["승인 지표"], dimensions: [] },
    },
  } : null;
  const patchSession = patchApproval ? {
    ...session,
    phase: patchApproval.approved ? "completed" : "ready",
    patch_request_id: patchApproval.request_id,
    patch_summary: "표 제목 변경",
    patch_operations: ["set_report_title"],
    patch_evidence_refs: [],
    patch_preview: [{
      index: 0, operation: "set_report_title", target: "보고서 제목",
      before: "기존 제목", after: "새 제목",
      impact_category: "CONTENT", evidence_required: false, evidence_count: 0,
    }],
    approved_operation_indexes: patchApproval.approved ? patchApproval.operation_indexes || [0] : [],
    result_revision: patchApproval.approved ? 3 : null,
  } : null;
  const messageBody = url.endsWith("/messages") ? JSON.parse(init.body) : null;
  const instruction = messageBody?.instruction || "";
  const review = url.endsWith("/review") ? {
    assistant_request_id: "assistant/1",
    summary: "품질 문제 한 건을 찾았습니다.",
    suggestions: ["선택한 블록의 제목을 간결하게 바꿔 줘"],
    findings: [{
      category: "title_mismatch", severity: "warning", block_id: "block-1",
      title: "제목 확인", detail: "차트 제목을 확인해 주세요.",
      suggested_instruction: "차트 제목을 승인 지표에 맞춰 바꿔 줘", evidence_refs: ["metric_1"],
    }],
    trace: {
      model_version: "report-model", prompt_id: "report.assistant.review",
      prompt_version: "PROMPT-v1.0.0", prompt_hash: "b".repeat(64), attempts: 1, duration_ms: 10,
    },
  } : null;
  return new Response(JSON.stringify(review || retrySession || cancelledSession || patchSession || approvalSession || (url.endsWith("/messages") ? {
    change_kind: instruction === "모호한 요청" ? "clarification" : "existing_artifact",
    message: instruction === "모호한 요청" ? "어느 기간을 기준으로 할까요?" : "기존 근거로 수정할 수 있습니다.",
    suggestions: ["선택한 블록의 제목을 간결하게 바꿔 줘"],
    session: instruction === "모호한 요청" ? {
      ...session,
      operation_scope: messageBody.operation_scope,
      turn_history: [
        { role: "user", content: instruction },
        { role: "assistant", content: "어느 기간을 기준으로 할까요?" },
      ],
    } : {
      ...session,
      phase: "waiting_patch_approval",
      operation_scope: messageBody.operation_scope,
      turn_history: [
        { role: "user", content: instruction },
        { role: "assistant", content: "기존 근거로 수정할 수 있습니다." },
      ],
      patch_request_id: "patch-1", patch_summary: "표 제목 변경",
      patch_operations: ["set_report_title"], patch_evidence_refs: [],
      patch_preview: [{
        index: 0, operation: "set_report_title", target: "보고서 제목",
        before: "기존 제목", after: "새 제목",
        impact_category: "CONTENT", evidence_required: false, evidence_count: 0,
      }],
    },
  } : session)), { status: 200, headers: { "Content-Type": "application/json" } });
}, "runtime-token");
const assistantSession = await assistantSessionClient.createAssistantSession(
  "definition-1", 2, "artifact-1",
);
assert.equal(assistantSession.phase, "ready");
assert.equal(assistantSessionRequest.url, "http://backend.test/reports/assistant/sessions");
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), {
  definition_id: "definition-1", definition_version: 2, artifact_id: "artifact-1",
  additional_artifact_ids: [],
});

const retriedAssistant = await assistantSessionClient.retryAssistantSession("assistant/1");
assert.equal(retriedAssistant.phase, "ready");
assert.equal(retriedAssistant.retry_of_assistant_request_id, "assistant/1");
assert.equal(assistantSessionRequest.url, "http://backend.test/reports/assistant/sessions/assistant%2F1/retry");
assert.equal(assistantSessionRequest.init.method, "POST");

const cancelledAssistant = await assistantSessionClient.cancelAssistantSession("assistant/1");
assert.equal(cancelledAssistant.phase, "cancelled");
assert.equal(assistantSessionRequest.url, "http://backend.test/reports/assistant/sessions/assistant%2F1/cancel");
assert.equal(assistantSessionRequest.init.method, "POST");

await assistantSessionClient.getAssistantSession("assistant/1");
assert.equal(
  assistantSessionRequest.url,
  "http://backend.test/reports/assistant/sessions/assistant%2F1",
);

const assistantReview = await assistantSessionClient.reviewAssistantSession("assistant/1");
assert.equal(assistantReview.findings[0].category, "title_mismatch");
assert.equal(
  assistantSessionRequest.url,
  "http://backend.test/reports/assistant/sessions/assistant%2F1/review",
);
assert.equal(assistantSessionRequest.init.method, "POST");
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), { selected_block_id: null });

const assistantProposal = await assistantSessionClient.submitAssistantMessage(
  "assistant/1", "표 제목을 바꿔 줘",
);
assert.equal(assistantProposal.change_kind, "existing_artifact");
assert.equal(
  assistantSessionRequest.url,
  "http://backend.test/reports/assistant/sessions/assistant%2F1/messages",
);
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), {
  instruction: "표 제목을 바꿔 줘", expected_patch_request_id: null, selected_block_id: null,
  operation_scope: "full_report",
});

const titleProposal = await assistantSessionClient.submitAssistantMessage(
  "assistant/1", "보고서 제목을 제안해 줘", null, null, "report_title",
);
assert.equal(titleProposal.session.operation_scope, "report_title");
assert.deepEqual(titleProposal.session.turn_history, [
  { role: "user", content: "보고서 제목을 제안해 줘" },
  { role: "assistant", content: "기존 근거로 수정할 수 있습니다." },
]);
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), {
  instruction: "보고서 제목을 제안해 줘", expected_patch_request_id: null, selected_block_id: null,
  operation_scope: "report_title",
});

await assistantSessionClient.submitAssistantMessage(
  "assistant/1", "제목은 유지하고 요약만 줄여 줘", "patch-1",
);
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), {
  instruction: "제목은 유지하고 요약만 줄여 줘", expected_patch_request_id: "patch-1", selected_block_id: null,
  operation_scope: "full_report",
});

await assert.rejects(
  () => assistantSessionClient.submitAssistantMessage(
    "assistant/1", "잘못된 범위", null, null, "unsupported_scope",
  ),
  /지원하지 않는 Report Assistant 작업 범위/,
);

const approvedPatch = await assistantSessionClient.approveAssistantPatch(
  "assistant/1", "patch-1", [0],
);
assert.equal(approvedPatch.phase, "completed");
assert.equal(
  assistantSessionRequest.url,
  "http://backend.test/reports/assistant/sessions/assistant%2F1/patch-approval",
);
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), {
  request_id: "patch-1", approved: true, operation_indexes: [0],
});

const rejectedPatch = await assistantSessionClient.rejectAssistantPatch(
  "assistant/1", "patch-1",
);
assert.equal(rejectedPatch.phase, "ready");
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), {
  request_id: "patch-1", approved: false,
});

const clarificationProposal = await assistantSessionClient.submitAssistantMessage(
  "assistant/1", "모호한 요청",
);
assert.equal(clarificationProposal.change_kind, "clarification");
assert.equal(clarificationProposal.session.phase, "ready");

const approvedAssistant = await assistantSessionClient.approveAssistantPlan(
  "assistant/1", "request-1",
);
assert.equal(approvedAssistant.phase, "completed");
assert.equal(approvedAssistant.result_revision, 3);
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), {
  request_id: "request-1", approved: true,
});

const rejectedAssistant = await assistantSessionClient.rejectAssistantPlan(
  "assistant/1", "request-1",
);
assert.equal(rejectedAssistant.phase, "ready");
assert.deepEqual(JSON.parse(assistantSessionRequest.init.body), {
  request_id: "request-1", approved: false,
});

const staleApprovalClient = createReportClient("http://backend.test", async () => new Response(JSON.stringify({
  assistant_request_id: "assistant-1", phase: "ready", operation_scope: "full_report",
  definition_id: "definition-1", definition_version: 2, base_revision: 2,
  artifact_id: "artifact-1", artifact_ids: ["artifact-1"], analysis_plan: null,
  patch_request_id: null, patch_summary: null, patch_operations: [], patch_evidence_refs: [], result_artifact_id: null,
  result_revision: null, error_code: null, retryable: false, required_action: "NONE",
  retry_of_assistant_request_id: null, turn_history: [],
}), { status: 200, headers: { "Content-Type": "application/json" } }), "runtime-token");
await assert.rejects(
  () => staleApprovalClient.approveAssistantPlan("assistant-1", "request-1"),
  /실행 phase로 전이되지 않았습니다/,
);

const mismatchedSessionClient = createReportClient("http://backend.test", async () => new Response(JSON.stringify({
  assistant_request_id: "assistant-2", phase: "ready", operation_scope: "full_report",
  definition_id: "definition-1", definition_version: 2, base_revision: 2,
  artifact_id: "artifact-1", artifact_ids: ["artifact-1"], analysis_plan: null,
  patch_request_id: null, patch_summary: null, patch_operations: [], patch_evidence_refs: [], result_artifact_id: null,
  result_revision: null, error_code: null, retryable: false, required_action: "NONE",
  retry_of_assistant_request_id: null, turn_history: [],
}), { status: 200, headers: { "Content-Type": "application/json" } }), "runtime-token");
await assert.rejects(
  () => mismatchedSessionClient.getAssistantSession("assistant-1"),
  /세션 ID가 요청과 일치하지 않습니다/,
);

const invalidTurnHistoryClient = createReportClient("http://backend.test", async () => new Response(JSON.stringify({
  assistant_request_id: "assistant-1", phase: "ready", operation_scope: "full_report",
  definition_id: "definition-1", definition_version: 2, base_revision: 2,
  artifact_id: "artifact-1", artifact_ids: ["artifact-1"], analysis_plan: null,
  patch_request_id: null, patch_summary: null, patch_operations: [], patch_evidence_refs: [],
  patch_preview: [], approved_operation_indexes: [], result_artifact_id: null,
  result_revision: null, error_code: null, retryable: false, required_action: "NONE",
  retry_of_assistant_request_id: null,
  turn_history: [{ role: "system", content: "내부 지시" }],
}), { status: 200, headers: { "Content-Type": "application/json" } }), "runtime-token");
await assert.rejects(
  () => invalidTurnHistoryClient.getAssistantSession("assistant-1"),
  /대화 이력 계약이 올바르지 않습니다/,
);

console.log("frontend contract tests passed");
