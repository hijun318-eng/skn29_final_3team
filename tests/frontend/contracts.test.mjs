import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normalizeApiResponse, OPENAPI_VERSION, resolveViewState, UI_CONTRACT_VERSION } from "../../app/enterprise-react/src/contracts/analysis.ts";
import { placeDraftBlock, REPORT_CONTRACT_VERSION, REPORT_RUN_STATUSES, reorderDraftBlocks } from "../../app/enterprise-react/src/contracts/report.ts";
import { createAnalysisClient, createHttpAnalysisClient } from "../../app/enterprise-react/src/api/analysisClient.ts";
import { createReportClient, ReportApiError } from "../../app/enterprise-react/src/api/reportClient.ts";
import { resolveRoute } from "../../app/enterprise-react/src/routing.js";

const source = (path) => readFileSync(new URL(`../../app/enterprise-react/src/${path}`, import.meta.url), "utf8");
const productSources = [
  "App.jsx", "routing.js", "api/analysisClient.ts", "api/reportClient.ts",
  "pages/AgentPage.jsx", "pages/ReportsPage.jsx",
  "components/analysis/AnalysisStatePanel.tsx", "components/layout/AppHeader.jsx", "components/layout/AppSidebar.jsx",
].map(source).join("\n");

assert.equal(UI_CONTRACT_VERSION, "UI-v1.0.0");
assert.equal(OPENAPI_VERSION, "OPENAPI-v1.0.0");
assert.equal(REPORT_CONTRACT_VERSION, "REPORT-v1.0.0");
assert.deepEqual(REPORT_RUN_STATUSES, ["queued", "running", "success", "partial", "failed", "cancelled"]);
assert.equal(resolveRoute("/").path, "/agent");
assert.equal(resolveRoute("/agent").page, "chat");
assert.equal(resolveRoute("/reports").page, "reports");
assert.equal(resolveRoute("/catalog").page, "notFound");
assert.equal(resolveRoute("/connections").page, "notFound");

for (const forbidden of [
  /analysisFixtures|catalogFixtures|enterpriseDemoData/,
  /usesMockAnalysisClient|usesFixtureReportClient/,
  /localStorage|sessionStorage/,
  /RECENT_ANALYSES|TRACE_STEPS|SYNTHETIC EXECUTION TRACE/,
  /CatalogPage|ConnectionsPage|Customer360Page/,
  /VITE_ANALYSIS_MODE|VITE_REPORT_MODE/,
  /2026-06-01|2026-07-01/,
]) assert.doesNotMatch(productSources, forbidden);

assert.match(source("pages/AgentPage.jsx"), /nextPeriodStart >= nextPeriodEnd/);
assert.match(source("pages/AgentPage.jsx"), /setPeriodStart\(nextPeriodStart\)/);
assert.match(source("pages/AgentPage.jsx"), /setPeriodEnd\(nextPeriodEnd\)/);
assert.match(source("components/auth/SessionLogin.jsx"), /\.login\(nextUsername, password\)/);
assert.match(source("components/auth/SessionLogin.jsx"), /onAuthenticated\(\{ token: session\.session_token, role: session\.role \}\)/);
assert.doesNotMatch(source("components/auth/SessionLogin.jsx"), /액세스 토큰/);
assert.match(source("App.jsx"), /<ReportsPage authToken=\{authToken\} role=\{role\}/);
assert.match(source("App.jsx"), /role === "report_admin"/);
assert.match(source("App.jsx"), /role !== "hotel_analyst"/);
assert.match(source("App.jsx"), /route\.page === "chat"\) navigate\(PAGE_PATHS\.reports\)/);
assert.match(source("App.jsx"), /<AppSidebar page=\{route\.page\} role=\{role\}/);
assert.match(source("components/layout/AppSidebar.jsx"), /item\.roles\.includes\(role\)/);
assert.match(source("App.jsx"), /보고서 초안을 작성하고 조회합니다/);
assert.match(source("pages/ReportsPage.jsx"), /if \(isAdmin\) await loadSchedules\(\)/);
assert.match(source("pages/ReportsPage.jsx"), /서버가 Asia\/Seoul 기준으로 자동 실행합니다/);
assert.match(source("pages/ReportsPage.jsx"), /setScheduleEnabled\(schedule\.schedule_id, !schedule\.enabled\)/);
assert.doesNotMatch(source("pages/ReportsPage.jsx"), />due 실행<\/button>/);
assert.match(source("pages/ReportsPage.jsx"), /REPORT_DRAFT scope/);
assert.match(source("pages/ReportsPage.jsx"), /draggable/);
assert.match(source("pages/ReportsPage.jsx"), /placeDraftBlock\(current, sourceId, position\.x, position\.y\)/);
assert.match(source("pages/ReportsPage.jsx"), /gridRow:/);
assert.match(source("pages/ReportsPage.jsx"), /배치 저장/);
assert.match(source("pages/AgentPage.jsx"), /role="alert"/);
assert.match(source("pages/AgentPage.jsx"), /savedRuns\.slice\(0, visibleRunCount\)/);
assert.match(source("pages/AgentPage.jsx"), /analysisClient\.getRunArtifact\(result\.request_id, conversationId\)/);
assert.match(source("pages/AgentPage.jsx"), /저장 결과 불러옴/);
assert.match(source("pages/AgentPage.jsx"), />결과 보기<\/button>/);
assert.match(source("api/analysisClient.ts"), /\/analysis\/runs\/\$\{encodeURIComponent\(requestId\)\}\/artifact/);

const reorderedBlocks = reorderDraftBlocks([
  { id: "left", title: "왼쪽", columns: 6, type: "text", content: "왼쪽", x: 0, y: 0, w: 6, h: 2 },
  { id: "right", title: "오른쪽", columns: 6, type: "text", content: "오른쪽", x: 6, y: 0, w: 6, h: 2 },
], "right", "left");
assert.deepEqual(reorderedBlocks.map((block) => block.id), ["right", "left"]);
assert.deepEqual(reorderedBlocks.map((block) => [block.x, block.y]), [[0, 0], [6, 0]]);

const freelyPlacedBlocks = placeDraftBlock(reorderedBlocks, "right", 6, 3);
assert.deepEqual(freelyPlacedBlocks.find((block) => block.id === "right"), {
  id: "right", title: "오른쪽", columns: 6, type: "text", content: "오른쪽", x: 6, y: 3, w: 6, h: 2,
});
const collisionAvoidedBlocks = placeDraftBlock(freelyPlacedBlocks, "left", 6, 3);
assert.equal(collisionAvoidedBlocks.find((block) => block.id === "left").y, 5);

const apiResponse = {
  data: {
    status: "SUCCEEDED",
    artifact: { artifact_id: "artifact-1", query_id: "query-1", context_hash: "context-1" },
    result: {
      summary: "API result",
      metrics: [{ metric_id: "metric", label: "Metric", value: 3, unit: "count" }],
      table: { columns: ["metric"], rows: [{ metric: 3 }] },
      chart: null,
      evidence: {
        artifact_id: "artifact-1", query_id: "query-1", as_of: "2030-01-02",
        period: { start: "2030-01-01", end_exclusive: "2030-01-03" }, filters: {}, cached: false,
        sampling: { applied: false, returned_rows: 1, total_rows: 1 },
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
assert.equal(normalized.meta.synthetic, undefined);

let analysisRequest;
const analysisClient = createHttpAnalysisClient("http://backend.test/", async (url, init) => {
  analysisRequest = { url, init };
  return new Response(JSON.stringify(apiResponse), { status: 200, headers: { "Content-Type": "application/json" } });
}, "runtime-token");
await analysisClient.analyze("question", "conversation-1", { period_start: "2030-01-01", period_end_exclusive: "2030-01-03" });
assert.equal(analysisRequest.url, "http://backend.test/analysis");
assert.equal(analysisRequest.init.headers.Authorization, "Bearer runtime-token");
assert.equal(analysisRequest.init.headers["X-Contract-Version"], OPENAPI_VERSION);
assert.deepEqual(JSON.parse(analysisRequest.init.body).parameters, { period_start: "2030-01-01", period_end_exclusive: "2030-01-03" });

const sessionClient = createHttpAnalysisClient("http://backend.test", async (url, init) => {
  assert.equal(url, "http://backend.test/auth/session");
  assert.equal(init.headers.Authorization, "Bearer runtime-token");
  return new Response(JSON.stringify({ data: { status: "authenticated", role: "hotel_analyst" } }), { status: 200 });
}, "runtime-token");
assert.deepEqual(await sessionClient.validateSession(), { status: "authenticated", role: "hotel_analyst" });

let loginRequest;
const loginClient = createHttpAnalysisClient("http://backend.test", async (url, init) => {
  loginRequest = { url, init };
  return new Response(JSON.stringify({ data: { status: "authenticated", role: "report_admin", session_token: "signed-session" } }), { status: 200 });
});
assert.deepEqual(await loginClient.login("admin", "admin1234!"), {
  status: "authenticated", role: "report_admin", session_token: "signed-session",
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
