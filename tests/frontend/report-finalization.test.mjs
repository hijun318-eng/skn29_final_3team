import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createReportClient } from "../../app/frontend/src/api/reportClient.ts";
import {
  normalizeReportDefinition,
  normalizeReportDocument,
} from "../../app/frontend/src/contracts/report.ts";
import { reportFeatureSource, reportSources, sourceSection } from "./report-source-contract.mjs";

const applicationStyles = readFileSync(new URL("../../app/frontend/src/styles.css", import.meta.url), "utf8");

const definition = {
  contract_version: "REPORT-v1.0.0",
  definition_id: "00000000-0000-0000-0000-000000000010",
  version: 3,
  status: "approved",
  title: "7월 영업 실적 보고서",
  blocks: [],
  orientation: "landscape",
  currency_display_unit: "million",
  approved_at: "2026-08-14T09:30:00Z",
};
const draftDefinition = { ...definition, status: "draft", approved_at: null };
const documentMetadata = {
  definition_id: definition.definition_id,
  definition_version: 3,
  orientation: "landscape",
  currency_display_unit: "million",
  renderer_version: "weasyprint-69",
  source_checksum: "a".repeat(64),
  html_checksum: "b".repeat(64),
  pdf_checksum: "c".repeat(64),
  artifact_versions: [{
    artifact_id: "00000000-0000-0000-0000-000000000099",
    artifact_checksum: "d".repeat(64),
    query_id: "query-1",
  }],
  confirmed_at: "2026-08-14T09:30:00Z",
};

const requests = [];
const client = createReportClient("http://backend.test", async (url, init) => {
  requests.push({ url, init });
  if (url.endsWith("/approve")) return Response.json(definition);
  if (url.endsWith("/blocks")) return Response.json(draftDefinition);
  if (url.endsWith("/document")) return Response.json(documentMetadata);
  if (url.endsWith("/document.html")) return new Response("<!doctype html><title>확정본</title>", {
    headers: { "Content-Type": "text/html" },
  });
  if (url.endsWith("/document.pdf")) return new Response(new TextEncoder().encode("%PDF-1.7"), {
    headers: { "Content-Type": "application/pdf" },
  });
  if (url.endsWith("/versions/3")) return Response.json(draftDefinition);
  return Response.json({ error: { message: "not found" } }, { status: 404 });
}, "runtime-token");

const approved = await client.approveDefinition(definition.definition_id, 3, definition.approved_at, "landscape");
const approveBody = JSON.parse(requests[0].init.body);
assert.deepEqual(approveBody, {
  approved_at: definition.approved_at,
  orientation: "landscape",
});
assert.equal(Object.hasOwn(approveBody, "currency_display_unit"), false);
assert.equal(approved.orientation, "landscape");
assert.equal(approved.currencyDisplayUnit, "million");

await client.replaceDraftBlocks(definition.definition_id, 3, [], {
  orientation: "landscape",
  currencyDisplayUnit: "million",
});
assert.deepEqual(JSON.parse(requests.at(-1).init.body), {
  blocks: [],
  orientation: "landscape",
  currency_display_unit: "million",
});

const reentered = await client.getDefinition(definition.definition_id, 3);
assert.equal(reentered.orientation, "landscape");
assert.equal(reentered.currencyDisplayUnit, "million");

await client.replaceDraftBlocks(definition.definition_id, 3, []);
assert.deepEqual(JSON.parse(requests.at(-1).init.body), { blocks: [] }, "legacy caller remains compatible");

const legacyUnit = normalizeReportDefinition({ ...definition, currency_display_unit: "billion" });
assert.equal(legacyUnit.currencyDisplayUnit, "billion");
assert.throws(
  () => normalizeReportDefinition({ ...definition, orientation: "square" }),
  /용지 방향/,
);
assert.throws(
  () => normalizeReportDefinition({ ...definition, currency_display_unit: "trillion" }),
  /금액 표시 단위/,
);

const metadata = await client.getFinalDocument(definition.definition_id, 3);
assert.equal(metadata.orientation, "landscape");
assert.equal(metadata.currencyDisplayUnit, "million");
assert.equal(metadata.pdfChecksum, "c".repeat(64));
assert.deepEqual(metadata.artifactVersions, [{
  artifactId: documentMetadata.artifact_versions[0].artifact_id,
  artifactChecksum: "d".repeat(64),
  queryId: "query-1",
}]);
assert.throws(
  () => normalizeReportDocument({ ...documentMetadata, currency_display_unit: "trillion" }),
  /금액 표시 단위/,
);
assert.match(await client.getFinalHtml(definition.definition_id, 3), /확정본/);
const pdf = await client.getFinalPdf(definition.definition_id, 3);
assert.equal(pdf.type, "application/pdf");
assert.equal(new TextDecoder().decode(await pdf.arrayBuffer()), "%PDF-1.7");
assert.equal(requests.every(({ init }) => init.credentials === "include"), true);
assert.equal(requests.every(({ init }) => init.headers.Authorization === "Bearer runtime-token"), true);
const finalSignal = new AbortController().signal;
await client.getFinalDocument(definition.definition_id, 3, finalSignal);
assert.equal(requests.at(-1).init.signal, finalSignal, "final-document cancellation must reach fetch");

assert.match(reportSources.documentView, /저장된 HTML 초안을 확인하세요/);
assert.match(reportSources.controller, /수정할 수 없는 PDF를 생성할까요/);
assert.doesNotMatch(reportFeatureSource, /현재 PDF에 포함되지 않아 확정할 수 없습니다|pdfUnsupportedBlocks/);
assert.match(reportSources.documentView, /disabled=\{Boolean\(pending\) \|\| isDirty\}/);
assert.match(reportSources.documentView, /PDF 새 탭에서 열기/);
assert.match(reportSources.documentView, /PDF 다운로드/);
assert.match(applicationStyles, /\.theme-light \[data-report-render-root="screen-preview"\] \.answer-report-canvas--preview/);
assert.match(applicationStyles, /--answer-report-workbench:#e8eef6/);
assert.doesNotMatch(applicationStyles, /\.theme-light \[data-report-render-root="print"\]/);
assert.match(
  reportSources.controller,
  /replaceDraftBlocks\([\s\S]*\{ orientation: draft\.reportOrientation, currencyDisplayUnit: draft\.reportCurrencyPolicy\.displayUnit \}/,
  "the editor must persist display settings with the server draft",
);
const previewSource = sourceSection(reportSources.controller, "const openPreview", "const openEditor");
assert.match(previewSource, /await lifecycle\.fetchDefinition\(definition\)/);
assert.doesNotMatch(
  previewSource,
  /loadFrontendDraft/,
  "saved-document preview must use the server response rather than a browser snapshot",
);
const editorSource = sourceSection(reportSources.controller, "const openEditor", "const saveDraft");
assert.match(editorSource, /loadFrontendDraft\(window\.sessionStorage, current\.definitionId, current\.version\)/);
const saveSource = sourceSection(reportSources.controller, "const saveDraft", "const approveDefinition");
assert.ok(
  saveSource.indexOf("replaceDraftBlocks") < saveSource.indexOf("saveFrontendDraft"),
  "the browser recovery snapshot must only advance after the server accepts the draft",
);
const snapshotCatch = saveSource.indexOf("catch {");
const serverStateCommit = saveSource.indexOf("applyDefinition({ ...saved");
assert.ok(snapshotCatch >= 0 && snapshotCatch < serverStateCommit);
assert.doesNotMatch(
  saveSource.slice(snapshotCatch, serverStateCommit),
  /\breturn\b/,
  "browser storage failure must not prevent the accepted server definition from becoming current",
);
assert.match(
  saveSource,
  /catch \{\s*localSnapshotSaved = false;\s*\}\s*applyDefinition\(\{ \.\.\.saved/,
);
assert.match(saveSource, /서버에는 저장했지만 이 브라우저의 임시 복구본은 갱신하지 못했습니다/);
assert.match(reportSources.finalDocument, /new AbortController\(\)/);
assert.match(reportSources.finalDocument, /FINAL_DOCUMENT_TIMEOUT_MS = 15_000/);
assert.match(reportSources.finalDocument, /controller\.abort\(\)/);
assert.match(reportSources.finalDocument, /if \(operationId\) endOperation\(operationId\)/);
assert.match(reportSources.finalDocument, /controller\.signal/);
const leaveSource = sourceSection(reportSources.controller, "const leaveEditor", "const previewEditor");
assert.match(leaveSource, /openRequestRef\.current \+= 1/);
assert.match(leaveSource, /artifacts\.invalidateLoads\(\)/);
assert.match(leaveSource, /lifecycle\.loadFinalDocument\(null\)/);
assert.doesNotMatch(
  [reportSources.documentView, reportSources.lifecycle].join("\n"),
  /loadFrontendDraft|saveFrontendDraft|sessionStorage/,
  "document rendering and server lifecycle must not depend on browser recovery storage",
);

console.log("frontend report finalization tests passed");
