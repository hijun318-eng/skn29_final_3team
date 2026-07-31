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
  REPORT_CONTRACT_VERSION,
} from "../../app/enterprise-react/src/contracts/report.ts";
import {
  analysisFixtures,
  FIXTURE_VERSION,
} from "../../app/enterprise-react/src/data/analysisFixtures.ts";
import { resolveRoute } from "../../app/enterprise-react/src/routing.js";

const packageJson = JSON.parse(readFileSync(new URL("../../app/enterprise-react/package.json", import.meta.url)));
assert.equal(UI_CONTRACT_VERSION, "UI-v1.0.0");
assert.equal(REPORT_CONTRACT_VERSION, "REPORT-v1.0.0");
assert.equal(FIXTURE_VERSION, "UI-FIXTURE-v1.0.0");
assert.equal(OPENAPI_VERSION, "OPENAPI-v1.0.0");
assert.ok(Object.values({ ...packageJson.dependencies, ...packageJson.devDependencies }).every((version) => version !== "latest"));
assert.equal(resolveRoute("/customers").page, "notFound");
assert.equal(resolveRoute("/catalog/tools").page, "notFound");

for (const [expected, run] of Object.entries(analysisFixtures)) {
  assert.equal(resolveViewState(run).toLowerCase(), expected);
}

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
assert.equal(next.version, 2);
assert.equal(next.status, "approved");
assert.ok(Object.isFrozen(next));
assert.ok(Object.isFrozen(next.blocks));
assert.throws(() => approveDraft(approved, "2026-07-30T12:00:00+09:00"), /draft Report version/);

console.log("R5 contract checks passed");
