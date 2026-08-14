import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normalizeApiResponse, OPENAPI_VERSION, resolveViewState, UI_CONTRACT_VERSION } from "../../app/frontend/src/contracts/analysis.ts";
import { compactDraftLayout, placeDraftBlock, REPORT_CONTRACT_VERSION, REPORT_RUN_STATUSES, reorderDraftBlocks } from "../../app/frontend/src/contracts/report.ts";
import { AnalysisApiError, createAnalysisClient, createHttpAnalysisClient } from "../../app/frontend/src/api/analysisClient.ts";
import { createReportClient, ReportApiError } from "../../app/frontend/src/api/reportClient.ts";
import { resolveRoute } from "../../app/frontend/src/routing.js";

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
assert.match(source("pages/AgentPage.jsx"), /analysisClient\.analyze\(normalizedQuestion, conversationId, \{\}, \{/);
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
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /현재 단계와 경과 시간을 자동으로 갱신/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /run\.traceId \|\| "발급 전"/);
assert.match(source("contracts/analysis.ts"), /REQUEST_CANCELLED/);
assert.match(source("contracts/analysis.ts"), /NETWORK_UNAVAILABLE/);
assert.match(source("pages/AgentPage.jsx"), /NETWORK_UNAVAILABLE/);
assert.match(source("components/analysis/AnalysisStatePanel.tsx"), /ERROR_ACTIONS\[run\.error\.code\]/);
assert.match(source("components/auth/SessionLogin.jsx"), /\.login\(nextUsername, password\)/);
assert.match(source("components/auth/SessionLogin.jsx"), /Caps Lock이 켜져 있습니다/);
assert.match(source("components/auth/SessionLogin.jsx"), /비밀번호 표시/);
assert.match(source("components/auth/SessionLogin.jsx"), /onAuthenticated\(\{ token: "", role: session\.role \}\)/);
assert.doesNotMatch(source("api/analysisClient.ts"), /session_token/);
assert.doesNotMatch(source("components/auth/SessionLogin.jsx"), /액세스 토큰/);
assert.match(source("App.jsx"), /<ReportsPage authToken=\{authToken\} role=\{role\}/);
assert.match(source("App.jsx"), /role === "report_admin"/);
assert.match(source("App.jsx"), /role !== "hotel_analyst"/);
assert.match(source("App.jsx"), /route\.page === "chat"\) navigate\(PAGE_PATHS\.reports\)/);
assert.match(source("App.jsx"), /세션이 만료되었습니다\. 작성 중인 내용은 유지됩니다/);
assert.match(source("App.jsx"), /session-reauth-layer/);
assert.match(source("App.jsx"), /\["hotel_analyst", "report_admin"\]\.includes\(role\)/);
assert.match(source("App.jsx"), /현재 계정에 허용된 서비스 메뉴가 없습니다/);
assert.match(source("App.jsx"), /<AppSidebar page=\{route\.page\} role=\{role\}/);
assert.match(source("components/layout/AppSidebar.jsx"), /item\.roles\.includes\(role\)/);
assert.match(source("App.jsx"), /\["보고서 편집", "검증된 분석 결과와 설명을 블록으로 구성하고 저장합니다\."\]/);
assert.match(source("pages/ReportsPage.jsx"), /if \(isAdmin\) void loadSchedules\(\)/);
assert.match(source("pages/ReportsPage.jsx"), /서울 시간 기준으로 자동 실행합니다/);
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
assert.match(source("pages/ReportsPage.jsx"), /ReactMarkdown/);
assert.match(source("pages/ReportsPage.jsx"), /remarkGfm/);
assert.match(source("pages/ReportsPage.jsx"), /function ReportBlockMenu/);
assert.match(source("pages/ReportsPage.jsx"), /name="report-block-menu"/);
assert.match(source("pages/ReportsPage.jsx"), /report-resize-handle/);
assert.match(source("pages/ReportsPage.jsx"), /report-markdown-toolbar/);
assert.match(source("pages/ReportsPage.jsx"), /id: "artifact-table"/);
assert.match(source("pages/ReportsPage.jsx"), /id: "artifact-chart"/);
assert.match(source("pages/ReportsPage.jsx"), /function ReportTemplateTile/);
assert.match(source("pages/ReportsPage.jsx"), /DragOverlay/);
assert.match(source("pages/ReportsPage.jsx"), /원하는 위치로 끌어다 놓으세요/);
assert.match(source("pages/ReportsPage.jsx"), /행은 빈 공간 없이 자동 정렬됩니다/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), /notion-block-toolbar/);
assert.match(source("pages/ReportsPage.jsx"), /function ReportArtifactContent/);
assert.match(source("pages/ReportsPage.jsx"), /await loadArtifacts\(current\)/);
assert.match(source("pages/ReportsPage.jsx"), /<ReportArtifactContent block=\{block\}/);
assert.match(source("styles.css"), /\.report-api-blocks\.notion-canvas>article\{grid-column:var\(--block-x\)\/span var\(--block-w\)\}/);
assert.match(source("pages/ReportsPage.jsx"), /setView\("editor"\)/);
assert.match(source("pages/ReportsPage.jsx"), /setView\("document"\)/);
assert.match(source("pages/ReportsPage.jsx"), /enterprise-reports-list/);
assert.match(source("pages/ReportsPage.jsx"), /legacy-report-document generated-preview/);
assert.match(source("pages/ReportsPage.jsx"), /createNextDraft/);
assert.match(source("pages/ReportsPage.jsx"), /blocks: initialContent \? \[\{/);
assert.match(source("pages/ReportsPage.jsx"), /resetBlocks\(\[\{ id: blockId, title: "운영 요약"/);
assert.match(source("pages/AgentPage.jsx"), /savedRuns\.slice\(0, visibleRunCount\)/);
assert.match(source("pages/AgentPage.jsx"), /analysisClient\.getRunArtifact\(result\.request_id, conversationId\)/);
assert.match(source("pages/AgentPage.jsx"), /이전 분석 결과를 불러왔습니다/);
assert.match(source("pages/AgentPage.jsx"), />결과 열기<\/button>/);
assert.match(source("api/analysisClient.ts"), /\/analysis\/runs\/\$\{encodeURIComponent\(requestId\)\}\/artifact/);

for (const exposedImplementationCopy of [
  /Saved Analysis/, /Run History/, /Authenticated Session/, /세션 종료/,
  /제목 또는 ID 검색/, /window\.location\.reload/, />Artifact /, />Query /,
]) assert.doesNotMatch(productSources, exposedImplementationCopy);
assert.match(source("components/layout/AppHeader.jsx"), /호텔 분석가/);
assert.match(source("components/layout/AppHeader.jsx"), /로그아웃/);
assert.match(source("pages/AgentPage.jsx"), /className="run-history-panel"/);
assert.match(source("pages/AgentPage.jsx"), /className="analysis-notice"/);
assert.match(source("pages/AgentPage.jsx"), /function reportTitleForRun/);
assert.match(source("pages/AgentPage.jsx"), /createDraftFromArtifact\(run\.artifact\.artifactId, reportTitle\.trim\(\) \|\| reportTitleForRun\(run\)\)/);
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
  id: "right", title: "오른쪽", columns: 6, type: "text", content: "오른쪽", x: 6, y: 0, w: 6, h: 2,
});
const collisionAvoidedBlocks = placeDraftBlock(compactlyPlacedBlocks, "left", 6, 3);
assert.deepEqual(collisionAvoidedBlocks.map((block) => [block.x, block.y]), [[0, 0], [6, 0]]);

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
        sources: [{ name: "source", urn: "urn:source", fqn: "catalog.schema.table", schema_version: "1", seed_version: "2" }],
      },
    },
  },
  meta: { request_id: "request-1", trace_id: "trace-1", as_of: "2030-01-02", contract_version: OPENAPI_VERSION, timestamp: "2030-01-02T00:00:00Z" },
  error: null,
};
const normalized = normalizeApiResponse(apiResponse, "question", "conversation-1");
assert.equal(normalized.status, "success");
assert.equal(resolveViewState(normalized), "READY");
assert.equal(normalized.artifact.queryId, "query-1");
assert.equal(normalized.sources[0].fqn, "catalog.schema.table");
assert.equal(normalized.metrics[0].definition, "Metric definition");
assert.equal(normalized.metrics[0].resultField, "metric");
assert.equal(normalized.evidence.metrics[0].definition, "Metric definition");
assert.equal(normalized.evidence.models[0].promptId, "node3-prompt");
assert.equal(normalized.evidence.gates.g3, "PASSED");
assert.deepEqual(normalized.evidence.gateHistory.g2, ["BLOCKED", "PASSED"]);
assert.deepEqual(normalized.evidence.masking.fields, ["guest_id"]);
assert.equal(normalized.meta.synthetic, undefined);

const rateLimitedClient = createHttpAnalysisClient("http://backend.test", async () => new Response(JSON.stringify({ error: { code: "RATE_LIMITED", message: "잠시 후 다시 시도해 주세요.", retryable: true } }), { status: 429 }), "runtime-token");
await assert.rejects(
  () => rateLimitedClient.analyze("question", "conversation-1"),
  (error) => error instanceof AnalysisApiError && error.status === 429 && error.code === "RATE_LIMITED" && error.retryable,
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
}, "2026년 6월 객실 매출", "conversation-2");
assert.deepEqual(clarification.error.suggestions, ["인식 객실 매출", "숙박일 배분 객실 매출"]);

let analysisRequest;
const analysisClient = createHttpAnalysisClient("http://backend.test/", async (url, init) => {
  analysisRequest = { url, init };
  return new Response(JSON.stringify(apiResponse), { status: 200, headers: { "Content-Type": "application/json" } });
}, "runtime-token");
await analysisClient.analyze("question", "conversation-1", { period_start: "2030-01-01", period_end_exclusive: "2030-01-03" }, { traceId: "client-trace" });
assert.equal(analysisRequest.url, "http://backend.test/analysis");
assert.equal(analysisRequest.init.headers.Authorization, "Bearer runtime-token");
assert.equal(analysisRequest.init.headers["X-Contract-Version"], OPENAPI_VERSION);
assert.equal(analysisRequest.init.headers["X-Trace-Id"], "client-trace");
assert.deepEqual(JSON.parse(analysisRequest.init.body).parameters, { period_start: "2030-01-01", period_end_exclusive: "2030-01-03" });

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
