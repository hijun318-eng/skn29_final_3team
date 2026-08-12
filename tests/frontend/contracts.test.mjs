import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import {
  normalizeApiResponse,
  OPENAPI_VERSION,
  resolveViewState,
} from "../../app/enterprise-react/src/contracts/analysis.ts";
import {
  approveDraft,
  createDraft,
  normalizeDraftLayout,
  REPORT_CONTRACT_VERSION,
  serializeDraftLayout,
} from "../../app/enterprise-react/src/contracts/report.ts";
import { AnalysisRequestError, createAnalysisClient, createHttpAnalysisClient } from "../../app/enterprise-react/src/api/analysisClient.ts";
import { createReportClient, ReportApiError } from "../../app/enterprise-react/src/api/reportClient.ts";
import { createAuditClient } from "../../app/enterprise-react/src/api/auditClient.ts";
import { resolveRoute } from "../../app/enterprise-react/src/routing.js";

globalThis.sessionStorage = {
  getItem: (key) => key === "answervice.auth.token" ? "contract-test-token" : null,
  setItem() {},
  removeItem() {},
};

const frontendRoot = new URL("../../app/enterprise-react/src/", import.meta.url);
const analysisContractSource = readFileSync(new URL("contracts/analysis.ts", frontendRoot), "utf8");
const analysisClientSource = readFileSync(new URL("api/analysisClient.ts", frontendRoot), "utf8");
const reportClientSource = readFileSync(new URL("api/reportClient.ts", frontendRoot), "utf8");
const reportsPageSource = readFileSync(new URL("pages/ReportsPage.jsx", frontendRoot), "utf8");
const agentPageSource = readFileSync(new URL("pages/AgentPage.jsx", frontendRoot), "utf8");
const routingSource = readFileSync(new URL("routing.js", frontendRoot), "utf8");
const auditPageSource = readFileSync(new URL("pages/AuditPage.jsx", frontendRoot), "utf8");
const analysisPanelSource = readFileSync(new URL("components/analysis/AnalysisStatePanel.tsx", frontendRoot), "utf8");

assert.deepEqual(resolveRoute("/"), { page: "chat", path: "/agent", redirected: true });
assert.deepEqual(resolveRoute("/agent"), { page: "chat", path: "/agent", redirected: false });
assert.deepEqual(resolveRoute("/reports"), { page: "reports", path: "/reports", redirected: false });
assert.deepEqual(resolveRoute("/operations/audit"), { page: "audit", path: "/operations/audit", redirected: false });
for (const removedPath of ["/catalog", "/catalog/connections", "/connections", "/customer-360"]) {
  assert.equal(resolveRoute(removedPath).page, "notFound");
}
assert.doesNotMatch(routingSource, /catalog|connections|customer/i);

const analysisResponse = {
  data: {
    status: "SUCCEEDED",
    transitions: ["RECEIVED", "ROUTED", "SUCCEEDED"],
    trace: [{ stage: "G2", outcome: "PASSED", detail: "read-only" }],
    artifact: { artifact_id: "artifact-1", query_id: "query-1", context_hash: "context-1" },
    result: {
      summary: "API 분석 결과",
      metrics: [{ metric_id: "revenue", label: "매출", value: 100, unit: "KRW" }],
      table: { columns: ["day", "revenue"], rows: [{ day: "2026-08-12", revenue: 100 }] },
      chart: { chart_type: "bar", x_field: "day", y_fields: ["revenue"] },
      evidence: {
        artifact_id: "artifact-1",
        query_id: "query-1",
        as_of: "2026-08-12",
        filters: {},
        cached: false,
        sampling: { applied: false, returned_rows: 1, total_rows: 1 },
        sources: [{ name: "PMS", urn: "urn:pms", fqn: "pms.stays", schema_version: "1", seed_version: "1" }],
      },
    },
  },
  meta: {
    request_id: "request-1",
    trace_id: "trace-1",
    as_of: "2026-08-12",
    contract_version: OPENAPI_VERSION,
    timestamp: "2026-08-12T00:00:00Z",
  },
  error: null,
};

const normalized = normalizeApiResponse(analysisResponse, "매출 분석", "conversation-1");
assert.equal(resolveViewState(normalized), "READY");
assert.equal(normalized.artifact.artifactId, "artifact-1");
assert.equal(normalized.metrics[0].value, 100);
assert.equal(normalized.sources[0].urn, "urn:pms");
assert.equal(normalized.trace[0].stage, "G2");

const auditSummary = { request_id: "request-1", user_id: "user-1", user_role: "HOTEL_ANALYST", request_type: "analysis", status: "SUCCEEDED", error_type: null, trace_id: "trace-1", started_at: "2026-08-12T00:00:00Z", completed_at: "2026-08-12T00:00:01Z" };
const auditTrace = { ...auditSummary, transitions: [], analysis_definition: null, context: { release_id: null, release_key: null, release_version: null, release_hash: null, package_id: null, package_hash: null }, policy: { sql_policy_version: "g2-v1", policy_version: "ACCESS-POLICY-v1.0.0", entitlement_hash: "entitlement-hash" }, access: { access_profile: "pms_only", allowed_domains: ["rooms"], datahub_actor: "urn:li:corpuser:answervice_pms_only", allowed_urns: ["urn:source"], trino_role: "answervice_pms_only", datahub_search_attempted: true, trino_execution_attempted: true }, model: null, query: { query_id: "q1", generation_mode: "TEMPLATE", validation_status: "ALLOWED", execution_status: "SUCCEEDED", duration_ms: 1, source_urns: ["urn:source"] }, artifact: { artifact_id: "a1", artifact_type: "COMPOSITE", freshness_status: "FRESH", status: "APPROVED", artifact_checksum: "sum", masking: { applied: true, fields: ["guest_id"] } }, reports: [] };
const effectiveAccess = { policy_version: "ACCESS-POLICY-v1.0.0", subject: "user-1", role: "hotel_analyst", mapping_source: "test_seed" };
const recoveryStatus = { generated_at: "2026-08-12T00:00:00Z", retention: { status: "dry_run", last_run_at: "2026-08-12T00:00:00Z" }, backup: { status: "available", created_at: "2026-08-12T00:00:00Z", age_hours: 1, sha256: "a".repeat(64), rpo_target_hours: 24, rpo_passed: true }, restore: { status: "verified", verified_at: "2026-08-12T00:00:00Z", mode: "archive-list-only", backup_age_hours: 1, restore_duration_hours: 0.1, rpo_target_hours: 24, rpo_passed: true, rto_target_hours: 4, rto_passed: true, backup_sha256: "a".repeat(64) } };
const auditRequests = [];
const auditClient = createAuditClient("http://backend.test/", async (url, init) => {
  auditRequests.push({ url, init });
  const body = url.endsWith("/access") ? effectiveAccess : url.endsWith("/recovery") ? recoveryStatus : url.includes("/request-1") ? auditTrace : { items: [auditSummary] };
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
});
assert.equal((await auditClient.search("request-1"))[0].request_id, "request-1");
const fetchedAuditTrace = await auditClient.get("request-1");
assert.equal(fetchedAuditTrace.policy.sql_policy_version, "g2-v1");
assert.equal(fetchedAuditTrace.access.trino_role, "answervice_pms_only");
assert.equal((await auditClient.getAccess()).policy_version, "ACCESS-POLICY-v1.0.0");
assert.equal((await auditClient.getRecovery()).restore.mode, "archive-list-only");
assert.equal(auditRequests[0].url, "http://backend.test/operations/audit?request_id=request-1");
assert.equal(auditRequests[1].url, "http://backend.test/operations/audit/request-1");
assert.equal(auditRequests[2].url, "http://backend.test/operations/audit/access");
assert.equal(auditRequests[3].url, "http://backend.test/operations/audit/recovery");
assert.equal(auditRequests[0].init.headers.Authorization, "Bearer contract-test-token");
assert.equal(auditRequests[0].init.headers["X-Contract-Version"], OPENAPI_VERSION);

let analysisRequest;
const analysisClient = createHttpAnalysisClient("http://backend.test/", async (url, init) => {
  analysisRequest = { url, init };
  return new Response(JSON.stringify(analysisResponse), { status: 200, headers: { "Content-Type": "application/json" } });
});
const analysisRun = await analysisClient.analyze("매출 분석", "conversation-1", "integrated_revenue");
assert.equal(analysisRequest.url, "http://backend.test/analysis");
assert.equal(analysisRequest.init.method, "POST");
assert.equal(analysisRequest.init.headers["X-Contract-Version"], OPENAPI_VERSION);
assert.equal(analysisRequest.init.headers.Authorization, "Bearer contract-test-token");
assert.equal(analysisRequest.init.headers["X-Access-Profile"], "integrated_revenue");
assert.deepEqual(JSON.parse(analysisRequest.init.body), { question: "매출 분석" });
for (const forbidden of ["allowed_domains", "role", "datahub", "trino", "credential"]) {
  assert.doesNotMatch(JSON.stringify(analysisRequest.init.headers).toLowerCase(), new RegExp(forbidden));
}
assert.equal(analysisRun.requestId, "request-1");

let defaultClientRequests = 0;
let defaultClientInit;
const defaultClient = createAnalysisClient(async (_url, init) => {
  defaultClientRequests += 1;
  defaultClientInit = init;
  return new Response(JSON.stringify(analysisResponse), { status: 200, headers: { "Content-Type": "application/json" } });
});
await defaultClient.analyze("기본 요청", "conversation-2");
assert.equal(defaultClientRequests, 1);
assert.equal(defaultClientInit.headers["X-Access-Profile"], "pms_only");

await assert.rejects(
  () => createHttpAnalysisClient("http://backend.test", async () => new Response(JSON.stringify({
    data: null,
    meta: null,
    error: { code: "ACCESS_DENIED", message: "인증 토큰이 유효하지 않습니다.", retryable: false },
  }), { status: 401, headers: { "Content-Type": "application/json" } })).analyze("실패 요청", "conversation-3"),
  (error) => error instanceof AnalysisRequestError
    && error.code === "ACCESS_DENIED"
    && error.message === "인증 토큰이 유효하지 않습니다."
    && error.retryable === false,
);

for (const request of [
  async () => new Response("{}", { status: 401 }),
  async () => new Response("{}", { status: 500 }),
  async () => new Response("{", { status: 200 }),
  async () => { throw new Error("network unavailable"); },
]) {
  await assert.rejects(() => createHttpAnalysisClient("http://backend.test", request).analyze("실패 요청", "conversation-3"));
}

const definitionResponse = {
  contract_version: REPORT_CONTRACT_VERSION,
  definition_id: "definition-1",
  version: 1,
  status: "draft",
  title: "주간 보고서",
  blocks: [{ block_id: "block-1", title: "내용", artifact_id: null, query_id: null, columns: 12, type: "text", x: 0, y: 0, w: 12, h: 2, content: "검토" }],
  approved_at: null,
};
const runResponse = {
  contract_version: REPORT_CONTRACT_VERSION,
  run_id: "run-1",
  definition_id: "definition-1",
  definition_version: 1,
  as_of: "2026-08-12T00:00:00Z",
  policy_version: "policy-v1",
  context_hash: "context-1",
  watermark: {},
  status: "success",
  blocks: [{ block_id: "block-1", artifact_id: "artifact-1", query_id: "query-1", snapshot_checksum: "checksum-1", status: "success" }],
};
const commandResponse = {
  contract_version: REPORT_CONTRACT_VERSION,
  command_id: "command-1",
  definition_id: "definition-1",
  version: 1,
  as_of: "2026-08-12T00:00:00Z",
  idempotency_key: "key-1",
  status: "queued",
};
const scheduleResponse = {
  contract_version: REPORT_CONTRACT_VERSION,
  schedule_id: "schedule-1",
  definition_id: "definition-1",
  version: 1,
  frequency: "weekly",
  hour: 9,
  minute: 30,
  timezone: "Asia/Seoul",
  weekday: 0,
  day_of_month: null,
  enabled: true,
  next_run_at: "2026-08-17T09:30:00+09:00",
};
const reportResponses = [
  definitionResponse,
  { contract_version: REPORT_CONTRACT_VERSION, items: [definitionResponse] },
  definitionResponse,
  { ...definitionResponse, status: "approved", approved_at: "2026-08-12T00:00:00Z" },
  { ...definitionResponse, version: 2 },
  definitionResponse,
  { contract_version: REPORT_CONTRACT_VERSION, items: [runResponse] },
  runResponse,
  commandResponse,
  { contract_version: REPORT_CONTRACT_VERSION, items: [scheduleResponse] },
  scheduleResponse,
];
const reportRequests = [];
const reportClient = createReportClient("http://backend.test/", async (url, init) => {
  reportRequests.push({ url, init });
  return new Response(JSON.stringify(reportResponses.shift()), { status: 200, headers: { "Content-Type": "application/json" } });
});
const blockRequest = { block_id: "block-1", title: "분석 결과", artifact_id: "artifact-1", query_id: "query-1", columns: 12, type: "table", x: 0, y: 0, w: 12, h: 4, content: "" };
await reportClient.createDefinition({ definition_id: "definition-1", title: "주간 보고서", blocks: [blockRequest] });
await reportClient.listDefinitions();
await reportClient.getDefinition("definition-1", 1);
await reportClient.approveDefinition("definition-1", 1, "2026-08-12T00:00:00Z");
await reportClient.createNextDraft("definition-1", 1);
await reportClient.replaceDraftBlocks("definition-1", 1, [blockRequest]);
await reportClient.listRuns("definition-1");
await reportClient.getRun("run-1");
const command = await reportClient.createManualRun({ definition_id: "definition-1", version: 1, as_of: commandResponse.as_of, idempotency_key: "key-1" });
const schedules = await reportClient.listSchedules();
const savedSchedule = await reportClient.upsertSchedule("definition-1", 1, { frequency: "weekly", hour: 9, minute: 30, weekday: 0, enabled: true });
assert.equal(reportRequests.length, 11);
assert.deepEqual(reportRequests.map(({ init }) => init.method), ["POST", "GET", "GET", "POST", "POST", "PUT", "GET", "GET", "POST", "GET", "PUT"]);
assert.equal(command.status, "queued");
assert.equal(schedules[0].nextRunAt, scheduleResponse.next_run_at);
assert.equal(savedSchedule.weekday, 0);
assert.deepEqual(JSON.parse(reportRequests[10].init.body), { frequency: "weekly", hour: 9, minute: 30, weekday: 0, enabled: true });
const artifactDefinitionBody = JSON.parse(reportRequests[0].init.body);
assert.equal(artifactDefinitionBody.blocks[0].artifact_id, "artifact-1");
assert.equal(artifactDefinitionBody.blocks[0].query_id, "query-1");
for (const { init } of reportRequests) {
  assert.equal(init.headers["X-Contract-Version"], OPENAPI_VERSION);
  assert.equal(init.headers.Authorization, "Bearer contract-test-token");
}

const deniedClient = createReportClient("http://backend.test", async () => new Response(JSON.stringify({ error: { code: "REPORT_FORBIDDEN", message: "권한이 없습니다." } }), { status: 403 }));
await assert.rejects(() => deniedClient.listDefinitions(), (error) => error instanceof ReportApiError && error.status === 403 && error.code === "REPORT_FORBIDDEN");

const approved = Object.freeze({ definitionId: "definition-1", version: 1, status: "approved", title: "주간 보고서", blocks: Object.freeze([{ id: "block-1", title: "내용", columns: 12 }]) });
const draft = createDraft(approved);
assert.equal(approveDraft(draft, "2026-08-12T00:00:00Z").status, "approved");
const layout = normalizeDraftLayout([{ id: "a", title: "A", columns: 8, w: 8, h: 3 }, { id: "b", title: "B", columns: 6, w: 6, h: 4 }]);
assert.deepEqual(layout.map(({ x, y, w, h }) => ({ x, y, w, h })), [{ x: 0, y: 0, w: 8, h: 3 }, { x: 0, y: 3, w: 6, h: 4 }]);
assert.equal(JSON.parse(serializeDraftLayout(layout))[0].w, 8);

for (const source of [analysisClientSource, reportClientSource, reportsPageSource, agentPageSource, auditPageSource]) {
  assert.doesNotMatch(source, /fixture|mock|demo/i);
}
assert.doesNotMatch(analysisClientSource, /VITE_ANALYSIS_MODE|VITE_ANALYSIS_DEMO|scenario/);
assert.doesNotMatch(reportClientSource, /VITE_REPORT_MODE/);
assert.doesNotMatch(reportsPageSource, /localStorage|sessionStorage/);
assert.match(reportsPageSource, /createReportClient\(\)/);
assert.match(agentPageSource, /createAnalysisClient\(\)/);
assert.match(agentPageSource, /보고서에 담기/);
assert.match(agentPageSource, /artifact_id: run\.artifact\.artifactId/);
assert.match(agentPageSource, /query_id: run\.artifact\.queryId/);
assert.match(agentPageSource, /type: run\.chart \? "chart" : "table"/);
assert.match(agentPageSource, /useState\("pms_only"\)/);
for (const profile of ["pms_only", "crm_only", "pms_crm", "integrated_revenue"]) assert.match(agentPageSource, new RegExp(profile));
assert.match(agentPageSource, /htmlFor="analysis-access-profile"/);
assert.match(agentPageSource, /id="analysis-access-profile"/);
assert.match(agentPageSource, /disabled=\{submitting\}/);
assert.match(agentPageSource, /aria-describedby="analysis-access-domain"/);
assert.match(agentPageSource, /접근 Domain/);
assert.doesNotMatch(agentPageSource, /allowed_domains|DataHub token|Trino.*credential/i);
assert.match(analysisContractSource, /export type AccessProfile/);
assert.match(reportsPageSource, /client\.listSchedules\(\)/);
assert.match(reportsPageSource, /client\.upsertSchedule/);
assert.match(reportsPageSource, /frequency === "weekly"/);
assert.match(reportsPageSource, /frequency === "monthly"/);
for (const label of ["텍스트 블록 추가", "12열 배치", "너비", "높이", "삭제"]) assert.match(reportsPageSource, new RegExp(label));
assert.match(reportsPageSource, /gridColumn/);
assert.match(analysisPanelSource, /chart\.chartType === "bar"/);
assert.match(analysisPanelSource, /<BarChart/);
assert.match(auditPageSource, /createAuditClient\(\)/);
for (const label of ["접근 Profile", "허용 Domain", "DataHub actor", "Entitlement hash", "Trino role", "DataHub 검색 시도", "Trino 실행 시도", "허용 URNs"]) assert.match(auditPageSource, new RegExp(label));
for (const label of ["보존 정책", "암호화 백업", "복구 검증", "RPO", "RTO"]) assert.match(auditPageSource, new RegExp(label));
assert.doesNotMatch(auditPageSource, /question|parameters|result_snapshot/i);

for (const removedDataFile of ["analysisFixtures.ts", "catalogFixtures.ts", "enterpriseDemoData.js"]) {
  assert.equal(existsSync(new URL(`data/${removedDataFile}`, frontendRoot)), false);
}

console.log("Frontend API contract checks passed");
