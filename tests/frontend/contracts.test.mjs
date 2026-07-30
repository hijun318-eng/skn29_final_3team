import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  normalizeApiResponse,
  OPENAPI_VERSION,
  resolveViewState,
} from "../../app/enterprise-react/src/contracts/analysis.ts";
import { approveDraft, createDraft } from "../../app/enterprise-react/src/contracts/report.ts";
import { analysisFixtures } from "../../app/enterprise-react/src/data/analysisFixtures.ts";
import { resolveRoute } from "../../app/enterprise-react/src/routing.js";

const packageJson = JSON.parse(readFileSync(new URL("../../app/enterprise-react/package.json", import.meta.url)));
assert.equal(OPENAPI_VERSION, "DRAFT-OPENAPI-v0.1");
assert.ok(Object.values({ ...packageJson.dependencies, ...packageJson.devDependencies }).every((version) => version !== "latest"));
assert.equal(resolveRoute("/customers").page, "notFound");
assert.equal(resolveRoute("/catalog/tools").page, "notFound");

for (const [expected, run] of Object.entries(analysisFixtures)) {
  assert.equal(resolveViewState(run).toLowerCase(), expected);
}

const normalized = normalizeApiResponse({
  data: { status: "SUCCEEDED", transitions: ["RECEIVED", "ROUTED", "SUCCEEDED"], result: { summary: "Fake 분석 결과입니다.", assets: [{ name: "PMS guest fixture", urn: "urn:answervice:dataset:pms.public.pms_guests" }] } },
  meta: { request_id: "req-api-001", trace_id: "trace-api-001", as_of: "2026-07-30", contract_version: OPENAPI_VERSION, timestamp: "2026-07-30T03:00:00Z" },
  error: null,
}, "객실 분석", "conv-api-001");
assert.equal(normalized.status, "success");
assert.equal(normalized.requestId, "req-api-001");
assert.equal(normalized.sources[0].urn, "urn:answervice:dataset:pms.public.pms_guests");

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
