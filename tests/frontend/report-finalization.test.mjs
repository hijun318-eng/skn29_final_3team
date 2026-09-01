import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createReportClient } from "../../app/frontend/src/api/reportClient.ts";
import {
  normalizeReportDefinition,
  normalizeReportDefinitionLifecycle,
  normalizeReportDocument,
} from "../../app/frontend/src/contracts/report.ts";
import { reportFeatureSource, reportSources, sourceSection } from "./report-source-contract.mjs";

const applicationStyles = readFileSync(new URL("../../app/frontend/src/styles.css", import.meta.url), "utf8");

const definition = {
  contract_version: "REPORT-v1.0.0",
  definition_id: "00000000-0000-0000-0000-000000000010",
  version: 3,
  draft_revision: 4,
  status: "approved",
  title: "7월 영업 실적 보고서",
  blocks: [],
  orientation: "landscape",
  currency_display_unit: "million",
  approved_at: "2026-08-14T09:30:00Z",
  archived_at: null,
  archived_by: null,
};
const draftDefinition = { ...definition, status: "draft", approved_at: null };
const archivedAt = "2026-08-31T09:30:00+09:00";
const archivedDefinition = {
  ...definition,
  archived_at: archivedAt,
  archived_by: "00000000-0000-0000-0000-000000000011",
};
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
  title: "  8월 영업 실적 보고서  ",
  expectedDraftRevision: 4,
  orientation: "landscape",
  currencyDisplayUnit: "million",
});
assert.deepEqual(JSON.parse(requests.at(-1).init.body), {
  blocks: [],
  title: "8월 영업 실적 보고서",
  expected_draft_revision: 4,
  orientation: "landscape",
  currency_display_unit: "million",
});

const reentered = await client.getDefinition(definition.definition_id, 3);
assert.equal(reentered.orientation, "landscape");
assert.equal(reentered.currencyDisplayUnit, "million");
assert.equal(reentered.draftRevision, 4);
await assert.rejects(
  () => client.replaceDraftBlocks(definition.definition_id, 3, [], { expectedDraftRevision: 0 }),
  /draft revision/,
);
await assert.rejects(
  () => client.replaceDraftBlocks(definition.definition_id, 3, [], {
    expectedDraftRevision: 4,
    title: "잘못된\n제목",
  }),
  /줄바꿈·제어문자 없이/,
);
await assert.rejects(
  () => client.replaceDraftBlocks(definition.definition_id, 3, [], {
    expectedDraftRevision: 4,
    title: "잘못된\t제목",
  }),
  /줄바꿈·제어문자 없이/,
);

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
assert.throws(
  () => normalizeReportDefinition({ ...definition, draft_revision: 0 }),
  /draft revision/,
);
assert.equal(normalizeReportDefinition(archivedDefinition).archivedAt, archivedAt);
assert.throws(
  () => normalizeReportDefinition({ ...definition, archived_at: archivedAt }),
  /함께 제공/,
);
assert.throws(
  () => normalizeReportDefinitionLifecycle({
    definition_id: definition.definition_id,
    archived: false,
    archived_at: archivedAt,
    archived_by: archivedDefinition.archived_by,
  }),
  /receipt가 일치/,
);

const archiveRequests = [];
const archiveClient = createReportClient("http://backend.test", async (url, init) => {
  archiveRequests.push({ url, init });
  if (url.endsWith("?archived=true")) {
    return Response.json({ contract_version: "REPORT-v1.0.0", items: [archivedDefinition] });
  }
  if (url.endsWith("/archive")) {
    return Response.json({
      definition_id: definition.definition_id,
      archived: true,
      archived_at: archivedAt,
      archived_by: archivedDefinition.archived_by,
    });
  }
  if (url.endsWith("/restore")) {
    return Response.json({
      definition_id: definition.definition_id,
      archived: false,
      archived_at: null,
      archived_by: null,
    });
  }
  return Response.json({ contract_version: "REPORT-v1.0.0", items: [definition] });
}, "runtime-token");
assert.equal((await archiveClient.listDefinitions())[0].archivedAt, undefined);
assert.equal(archiveRequests.at(-1).url, "http://backend.test/reports/definitions");
assert.equal((await archiveClient.listDefinitions(true))[0].archivedAt, archivedAt);
assert.equal(archiveRequests.at(-1).url, "http://backend.test/reports/definitions?archived=true");
assert.equal((await archiveClient.archiveDefinition(definition.definition_id)).archived, true);
assert.equal(archiveRequests.at(-1).init.method, "POST");
assert.equal((await archiveClient.restoreDefinition(definition.definition_id)).archived, false);
assert.equal(archiveRequests.at(-1).init.method, "POST");

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

assert.match(reportSources.documentView, /보고서 내용을 확인하세요/);
assert.match(reportSources.controller, /저장된 보고서 버전.*PDF가 생성되며/);
assert.doesNotMatch(reportSources.documentView, /HTML 초안|확정하고 PDF 생성|보고서 실행/);
assert.match(reportSources.documentView, /최신 데이터로 다시 생성/);
assert.doesNotMatch(reportFeatureSource, /현재 PDF에 포함되지 않아 확정할 수 없습니다|pdfUnsupportedBlocks/);
assert.match(reportSources.documentView, /disabled=\{Boolean\(pending\) \|\| isDirty\}/);
assert.match(reportSources.documentView, /PDF 새 탭에서 열기/);
assert.match(reportSources.documentView, /PDF 다운로드/);
assert.match(reportSources.listView, /report-collection-tabs/);
assert.match(reportSources.listView, /활성 보고서/);
assert.match(reportSources.listView, /휴지통/);
assert.match(reportSources.listView, /className="delete"/);
assert.match(reportSources.listView, /이 보고서를 삭제할까요\?/);
assert.match(reportSources.listView, /휴지통으로 이동합니다/);
assert.match(reportSources.listView, /MoreHorizontal/);
assert.match(reportSources.listView, /<dialog/);
assert.match(reportSources.listView, /dialog\.showModal\(\)/);
assert.match(reportSources.listView, /if \(pending\) event\.preventDefault\(\)/, "Escape must not close a pending archive command");
assert.match(reportSources.listView, /dialogCancelRef\.current\?\.focus\(\)/, "opening the dialog must move focus inside");
assert.match(reportSources.listView, /lifecycleDialog\.trigger\?\.focus\?\.\(\)/, "closing the dialog must restore focus");
assert.match(reportSources.listView, /if \(result\) setLifecycleDialog\(null\)/, "a failed archive command must keep the dialog open");
assert.match(reportSources.listView, /disabled=\{Boolean\(pending\)\}/, "pending archive commands must lock dismissal controls");
assert.match(reportSources.documentView, /삭제된 보고서 · 읽기 전용/);
assert.match(reportSources.documentView, /!archived && <button onClick=\{onReturnToEditor\}/);
assert.match(reportSources.documentView, /!archived && isAdmin && approved/);
assert.match(reportSources.controller, /const isArchived = Boolean\(lifecycle\.selectedDefinition\?\.archivedAt\)/);
assert.match(reportSources.controller, /if \(definition\.archivedAt\)/);
assert.match(reportSources.lifecycle, /reportClient\.listDefinitions\(collection === "archived"\)/);
assert.match(reportSources.lifecycle, /reportClient\.archiveDefinition\(definitionId\)/);
assert.match(reportSources.lifecycle, /reportClient\.restoreDefinition\(definitionId\)/);
assert.match(reportSources.lifecycle, /const ensureAssistantEditable/);
assert.match(reportSources.lifecycle, /if \(!ensureAssistantEditable\(\)\) return null/);
const createDefinitionSource = sourceSection(reportSources.lifecycle, "const createDefinition", "const createNextDraft");
assert.match(createDefinitionSource, /block_id: createUuid\(\)/);
assert.doesNotMatch(createDefinitionSource, /const blockId = createUuid\(\)/);
assert.match(reportSources.controller, /const initialBlockId = createUuid\(\)/);
assert.match(applicationStyles, /\.theme-light \[data-report-render-root="screen-preview"\] \.answer-report-canvas--preview/);
assert.match(applicationStyles, /--answer-report-workbench:#e8eef6/);
assert.doesNotMatch(applicationStyles, /\.theme-light \[data-report-render-root="print"\]/);
assert.match(
  reportSources.controller,
  /replaceDraftBlocks\([\s\S]*title,[\s\S]*expectedDraftRevision: definition\.draftRevision,[\s\S]*orientation: draft\.reportOrientation,[\s\S]*currencyDisplayUnit: draft\.reportCurrencyPolicy\.displayUnit/,
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
assert.doesNotMatch(
  editorSource,
  /localDraft\.title !== current\.title|title: localDraft\.title/,
  "server revision title must remain authoritative when a local layout snapshot is restored",
);
const saveSource = sourceSection(reportSources.controller, "const saveDraft", "const approveDefinition");
assert.ok(
  saveSource.indexOf("const persistedBlocks = compactDraftLayout(draft.orderedBlocks)")
    < saveSource.indexOf("const snapshot = createFrontendDraftSnapshot"),
  "the recovery snapshot must be built from the exact compacted layout sent to the server",
);
assert.match(
  saveSource,
  /const snapshot = createFrontendDraftSnapshot\(\{[\s\S]*blocks: persistedBlocks,/,
  "the browser recovery snapshot and server request must share the persisted block layout",
);
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
assert.match(saveSource, /title: draft\.titleRef\.current\.trim|const title = draft\.titleRef\.current\.trim/);
assert.match(reportSources.finalDocument, /new AbortController\(\)/);
assert.match(reportSources.finalDocument, /FINAL_DOCUMENT_TIMEOUT_MS = 15_000/);
assert.match(reportSources.finalDocument, /controller\.abort\(\)/);
assert.match(reportSources.finalDocument, /if \(operationId\) endOperation\(operationId\)/);
assert.match(reportSources.finalDocument, /controller\.signal/);
const leaveSource = sourceSection(reportSources.controller, "const leaveEditor", "const previewEditor");
assert.match(leaveSource, /openRequestRef\.current \+= 1/);
assert.match(leaveSource, /artifacts\.invalidateLoads\(\)/);
assert.match(leaveSource, /lifecycle\.loadFinalDocument\(null\)/);
assert.match(leaveSource, /lifecycle\.clearFeedback\(\)/);
assert.doesNotMatch(
  [reportSources.documentView, reportSources.lifecycle].join("\n"),
  /loadFrontendDraft|saveFrontendDraft|sessionStorage/,
  "document rendering and server lifecycle must not depend on browser recovery storage",
);

console.log("frontend report finalization tests passed");
