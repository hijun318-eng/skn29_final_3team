import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  REPORT_CONTRACT_VERSION,
  compactDraftLayout,
  normalizeReportDefinition,
  toReportBlockRequest,
} from "../../app/frontend/src/contracts/report.ts";

import {
  FRONTEND_REPORT_DRAFT_VERSION,
  adaptAnalysisRunArtifact,
  analysisArtifactTitle,
  analysisRunArtifactSources,
  analysisTimeLabel,
  artifactViewTitle,
  artifactViewBlockSettings,
  artifactMetricCards,
  availableArtifactViews,
  canonicalDraftBlockContent,
  createFrontendDraftSnapshot,
  deleteFrontendBlock,
  estimateArtifactBlockLayout,
  estimateArtifactViewBlockLayout,
  fitFrontendArtifactBlock,
  fitFrontendArtifactViewBlock,
  frontendBlocksToDocument,
  frontendTextBlockLayout,
  insertFrontendArtifact,
  keyboardEndDropPosition,
  loadFrontendDraft,
  moveFrontendBlock,
  orientFrontendBlocks,
  reportArtifactLibrarySources,
  reportAssistantArtifactOptions,
  reportAssistantRepresentativeBlock,
  saveFrontendDraft,
} from "../../app/frontend/src/features/reports/reportDraftV2.js";
import { reportEvidenceReady } from "../../app/frontend/src/features/reports/reportArtifactEvidence.ts";
import { resizeDraftBlocks } from "../../app/frontend/src/features/reports/reportDraftMutations.ts";
import { splitLegacyCompositeArtifactBlocks } from "../../app/frontend/src/features/reports/reportDraftMutations.ts";
import { reportFeatureSource, reportSources } from "./report-source-contract.mjs";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));

const report = { definitionId: "report-1", version: 3, title: "월간 영업 성과 보고서", orientation: "portrait" };
const textBlock = {
  id: "summary", title: "경영진 요약", type: "text", content: "핵심 변화", columns: 12,
  x: 0, y: 0, w: 12, h: 4,
};
const chartContentA = { ...textBlock, id: "chart-a", type: "chart", artifactId: "artifact-a", content: '{"visibleViews":["chart"],"sizeMode":"auto"}' };
const chartContentB = { ...chartContentA, content: '{"sizeMode":"auto","visibleViews":["chart"]}' };
assert.equal(
  canonicalDraftBlockContent(chartContentA),
  canonicalDraftBlockContent(chartContentB),
  "server JSON key ordering must not create a false unsaved recovery state",
);
assert.notEqual(
  canonicalDraftBlockContent(chartContentA),
  canonicalDraftBlockContent({ ...chartContentB, content: '{"sizeMode":"manual","visibleViews":["chart"]}' }),
  "a meaningful artifact setting change must remain dirty",
);
assert.match(reportSources.presentation, /content: canonicalDraftBlockContent\(block\)/);
const sourceA = {
  artifactId: "artifact-a", queryId: "query-a", title: "객실 매출 분석",
  artifactChecksum: "sha256:a", sourceUrns: ["urn:rooms"],
};
const sourceB = { artifactId: "artifact-b", queryId: "query-b", title: "채널 구성 분석" };

const rejectedWhole = insertFrontendArtifact([textBlock], { ...sourceA, blockId: "legacy-whole" }, report);
assert.equal(rejectedWhole.ok, false);
assert.match(rejectedWhole.errors[0], /하나의 view/);
const first = insertFrontendArtifact([textBlock], {
  ...sourceA, blockId: "whole-a", visibleViews: ["summary"], width: 12,
}, report);
assert.equal(first.ok, true, first.errors?.join("; "));
assert.equal(first.blocks.find((block) => block.id === "whole-a").type, "artifact");
assert.equal(first.blocks.find((block) => block.id === "whole-a").artifactId, "artifact-a");
assert.equal(JSON.parse(first.blocks.find((block) => block.id === "whole-a").content).sizeMode, "auto");

const atomicArtifact = {
  summary: "핵심 결론",
  metrics: [{ metric_id: "metric-a", label: "승인 지표", value: 12, unit: "count" }],
  chart: { chart_type: "bar", x_field: "period", y_fields: ["metric_a"] },
  table: { columns: ["period", "metric_a"], rows: [{ period: "1월", metric_a: 12 }] },
};
assert.deepEqual(availableArtifactViews(atomicArtifact), ["summary", "kpi", "chart", "table"]);
assert.deepEqual(availableArtifactViews({ summary: "요약만" }), ["summary"]);
assert.deepEqual(
  availableArtifactViews({
    chart: { chart_type: "bar", x_field: "period", y_fields: ["value"] },
    table: { columns: ["period", "value"], rows: [] },
  }),
  [],
  "chart and table views require actual rows just like the server availability contract",
);
assert.equal(artifactViewTitle("객실 매출 분석", "kpi"), "객실 매출 분석 · 핵심 지표");
const boundedArtifactTitle = artifactViewTitle("가".repeat(255), "kpi");
assert.equal(Array.from(boundedArtifactTitle).length, 255);
assert.match(boundedArtifactTitle, / · 핵심 지표$/);
const legacyComposite = {
  id: "legacy-composite", title: "보고서 제목과 같았던 이전 블록", type: "artifact",
  artifactId: "artifact-a", viewSpecId: "legacy-view-spec", columns: 12,
  x: 0, y: 0, w: 12, h: 12,
  content: JSON.stringify({
    schemaVersion: "ANSWER-ARTIFACT-BLOCK-v1",
    presentationMode: "standard",
    visibleViews: ["summary", "kpi", "chart", "table"],
  }),
};
let migratedId = 0;
const migratedComposite = splitLegacyCompositeArtifactBlocks(
  [legacyComposite],
  { "artifact-a": { ...atomicArtifact, title: "Analysis result" } },
  [{
    artifactId: "artifact-a",
    title: "2026년 3월부터 8월 객실 매출 분석",
    definitionTitle: "보고서 정의 제목",
  }],
  "landscape",
  () => `migrated-${migratedId += 1}`,
);
assert.equal(migratedComposite.migratedSourceCount, 1);
assert.deepEqual(
  migratedComposite.blocks.map((block) => ({
    id: block.id,
    title: block.title,
    type: block.type,
    views: JSON.parse(block.content).visibleViews,
    artifactId: block.artifactId,
    viewSpecId: block.viewSpecId,
  })),
  [
    { id: "migrated-1", title: "2026년 3월부터 8월 객실 매출 분석 · 요약", type: "artifact", views: ["summary"], artifactId: "artifact-a", viewSpecId: undefined },
    { id: "migrated-2", title: "2026년 3월부터 8월 객실 매출 분석 · 핵심 지표", type: "artifact", views: ["kpi"], artifactId: "artifact-a", viewSpecId: undefined },
    { id: "migrated-3", title: "2026년 3월부터 8월 객실 매출 분석 · 차트", type: "chart", views: ["chart"], artifactId: "artifact-a", viewSpecId: undefined },
    { id: "migrated-4", title: "2026년 3월부터 8월 객실 매출 분석 · 표", type: "table", views: ["table"], artifactId: "artifact-a", viewSpecId: undefined },
  ],
  "legacy composite content must become newly identified immutable artifact views without reusing the report title or legacy block identity",
);
assert.equal(migratedComposite.blocks.every((block) => block.w <= 8 && block.h < 12), true);
assert.equal(frontendBlocksToDocument({ ...report, blocks: migratedComposite.blocks }).ok, true);
assert.deepEqual(
  splitLegacyCompositeArtifactBlocks(
    [{ ...legacyComposite, content: '{"visibleViews":["summary","unknown"]}' }],
    { "artifact-a": atomicArtifact },
    [],
    "landscape",
    () => "must-not-run",
  ).blocks,
  [{ ...legacyComposite, content: '{"visibleViews":["summary","unknown"]}' }],
  "corrupt or unknown legacy view settings must remain fail-closed",
);
const atomicSummary = insertFrontendArtifact([textBlock], {
  ...sourceA,
  blockId: "atomic-summary",
  artifact: atomicArtifact,
  visibleViews: ["summary"],
}, report);
assert.equal(atomicSummary.ok, true, atomicSummary.errors?.join("; "));
const atomicKpi = insertFrontendArtifact(atomicSummary.blocks, {
  ...sourceA,
  blockId: "atomic-kpi",
  artifact: atomicArtifact,
  visibleViews: ["kpi"],
}, report);
assert.equal(atomicKpi.ok, true, atomicKpi.errors?.join("; "));
assert.deepEqual(
  atomicKpi.blocks.filter((block) => block.id.startsWith("atomic-")).map((block) => ({
    id: block.id,
    type: block.type,
    views: JSON.parse(block.content).visibleViews,
  })),
  [
    { id: "atomic-summary", type: "artifact", views: ["summary"] },
    { id: "atomic-kpi", type: "artifact", views: ["kpi"] },
  ],
  "summary and KPI must persist as separate blocks that share only the governed artifact reference",
);
const atomicDocument = frontendBlocksToDocument({ ...report, blocks: atomicKpi.blocks });
assert.equal(atomicDocument.ok, true, atomicDocument.errors?.join("; "));
assert.deepEqual(
  atomicDocument.document.pages.flatMap((page) => page.blocks)
    .filter((block) => block.id.startsWith("atomic-"))
    .map((block) => block.visibleViews),
  [["summary"], ["kpi"]],
);
const legacyDocument = frontendBlocksToDocument({
  ...report,
  blocks: [{
    ...atomicSummary.blocks.find((block) => block.id === "atomic-summary"),
    content: JSON.stringify({ visibleViews: ["summary", "kpi"] }),
  }],
});
assert.equal(legacyDocument.ok, false);
assert.match(legacyDocument.errors[0], /Artifact 참조|원자 view|데이터 블록/);
const migratedChartRequest = toReportBlockRequest({
  id: "legacy-chart-request", title: "차트", type: "chart", artifactId: "artifact-a",
  columns: 6, x: 0, y: 0, w: 6, h: 7, content: '{"showLegend":true}',
});
assert.deepEqual(JSON.parse(migratedChartRequest.content).visibleViews, ["chart"]);
assert.equal(frontendBlocksToDocument({
  ...report,
  blocks: [{
    id: "migrated-chart", title: "차트", type: "chart", artifactId: "artifact-a",
    columns: 6, x: 0, y: 0, w: 6, h: 7, content: '{"showLegend":true}',
  }],
}).ok, true);
assert.equal(frontendBlocksToDocument({
  ...report,
  blocks: [{
    id: "mismatched-chart", title: "잘못된 차트", type: "chart", artifactId: "artifact-a",
    columns: 6, x: 0, y: 0, w: 6, h: 7, content: '{"visibleViews":["table"]}',
  }],
}).ok, false);
assert.throws(() => toReportBlockRequest({
  id: "legacy-bundle-request", title: "합본", type: "artifact", artifactId: "artifact-a",
  columns: 12, x: 0, y: 0, w: 12, h: 12,
  content: '{"visibleViews":["summary","kpi"]}',
}), /visibleViews 하나/);

const side = insertFrontendArtifact(first.blocks, {
  ...sourceB,
  blockId: "whole-b",
  visibleViews: ["summary"],
  placement: { type: "side", targetBlockId: "whole-a", edge: "right" },
}, report);
assert.equal(side.ok, true, side.errors?.join("; "));
assert.deepEqual(side.blocks.filter((block) => block.id.startsWith("whole-")).map(({ id, x, w, h }) => [id, x, w, h]), [
  ["whole-a", 0, 6, 5],
  ["whole-b", 6, 6, 5],
]);

const beforeMove = structuredClone(side.blocks);
const moved = moveFrontendBlock(side.blocks, "whole-b", { type: "before", targetBlockId: "summary" }, report);
assert.equal(moved.ok, true);
assert.equal(moved.blocks[0].id, "whole-b");
assert.equal(moved.blocks[0].artifactId, sourceB.artifactId);
assert.equal(moved.blocks[0].queryId, sourceB.queryId);
assert.equal(moved.blocks.find((block) => block.id === "whole-a").w, 12);
assert.deepEqual(side.blocks, beforeMove, "valid operations must not mutate their input");
const resizedArtifact = resizeDraftBlocks(moved.blocks, "whole-b", 8, 12, "portrait");
assert.equal(resizedArtifact.blocks.find((block) => block.id === "whole-b").artifactId, sourceB.artifactId);
assert.equal(resizedArtifact.blocks.find((block) => block.id === "whole-b").queryId, sourceB.queryId);

const deleted = deleteFrontendBlock(moved.blocks, "whole-a", report);
assert.equal(deleted.ok, true);
assert.equal(deleted.blocks.some((block) => block.id === "whole-a"), false);
const documentResult = frontendBlocksToDocument({ ...report, blocks: deleted.blocks });
assert.equal(documentResult.ok, true);
for (const page of documentResult.document.pages) {
  const rows = [...new Map(page.blocks.map((block) => [block.y, block.h])).entries()].sort((a, b) => a[0] - b[0]);
  assert.equal(rows[0]?.[0] ?? 0, 0);
  for (let index = 1; index < rows.length; index += 1) assert.equal(rows[index][0], rows[index - 1][0] + rows[index - 1][1]);
}

const landscape = orientFrontendBlocks(side.blocks, "landscape", report);
assert.equal(landscape.ok, true);
assert.equal(landscape.document.orientation, "landscape");
assert.equal(landscape.document.pages.every((page) => page.orientation === "landscape"), true);

const undoPast = [beforeMove];
const afterOneMove = moved.blocks;
const undone = undoPast.at(-1);
assert.notDeepEqual(afterOneMove, undone);
assert.deepEqual(undone, side.blocks, "one move is restored by one history snapshot");

const currencyPolicy = {
  currencyCode: "KRW", displayUnit: "million", unitPlacement: "header", maximumFractionDigits: 1,
};
const snapshotResult = createFrontendDraftSnapshot({ ...report, currencyPolicy, blocks: side.blocks });
assert.equal(snapshotResult.ok, true);
assert.equal(snapshotResult.snapshot.schemaVersion, FRONTEND_REPORT_DRAFT_VERSION);
const memory = new Map();
const storage = { setItem: (key, value) => memory.set(key, value), getItem: (key) => memory.get(key) ?? null };
saveFrontendDraft(storage, snapshotResult.snapshot);
const restored = loadFrontendDraft(storage, report.definitionId, report.version);
assert.equal(restored.orientation, "portrait");
assert.deepEqual(restored.currencyPolicy, currencyPolicy);
assert.deepEqual(restored.blocks, snapshotResult.snapshot.blocks);

const summary = { ...textBlock, w: 6, columns: 6, content: "긴 한국어 요약 문장입니다. ".repeat(18) };
const summaryBefore = structuredClone(summary);
const summaryLayout = frontendTextBlockLayout(summary, "portrait");
assert.equal(summaryLayout.height > summary.h, true);
assert.deepEqual(summary, summaryBefore, "content sizing must not mutate the block");
assert.deepEqual(frontendTextBlockLayout({ ...summary, content: "매우 긴 문장 ".repeat(800) }, "portrait"), {
  minimumHeight: 14, height: 14, overflow: true,
});

const keyboardDrop = keyboardEndDropPosition(side.blocks, {
  pageId: "report-1:page:1", width: 12, height: 16,
});
const sideBottom = side.blocks.reduce((bottom, block) => Math.max(bottom, block.y + block.h), 0);
assert.deepEqual(keyboardDrop, {
  pageId: "report-1:page:1", x: 0, requestedX: 0, y: sideBottom, w: 12, h: 16,
  placement: { type: "end", pageId: "report-1:page:1" },
});

const definitions = [
  { definitionId: "report-1", version: 3, title: "현재 보고서", blocks: [{ ...sourceA, id: "legacy-a" }] },
  { definitionId: "report-2", version: 1, title: "채널 보고서", blocks: [{ ...sourceA, id: "duplicate-a" }, { ...sourceB, id: "legacy-b" }] },
];
assert.deepEqual(
  reportArtifactLibrarySources(definitions[0], definitions).map(({ artifactId, definitionId }) => [artifactId, definitionId]),
  [["artifact-a", "report-1"], ["artifact-b", "report-2"]],
);

const analysisLibraryFixture = fixture("analysis-report-library.json");
const analysisSources = analysisRunArtifactSources(
  analysisLibraryFixture.runs,
  analysisLibraryFixture.definitions,
);
assert.deepEqual(analysisSources.map(({ artifactId, requestId, title }) => [artifactId, requestId, title]), [
  ["artifact-occupancy", "request-occupancy", "2026년 6월 1일부터 30일까지 주요 지표 분석"],
  ["artifact-revenue", "request-revenue-new", "월간 객실 매출 추이"],
]);
assert.equal(analysisSources.some((source) => Object.hasOwn(source, "question")), false);
assert.equal(analysisSources[0].completedAt, "2026-07-03T00:00:02Z");
assert.equal(
  analysisTimeLabel({}, { periodStart: "2026-03-01", periodEndExclusive: "2026-08-30" }),
  "2026년 3월 1일부터 8월 29일까지",
);

const manyAssistantOptions = Array.from({ length: 222 }, (_, index) => ({
  artifactId: `artifact-${index + 1}`,
  title: `Artifact ${index + 1}`,
}));
assert.deepEqual(
  reportAssistantArtifactOptions(
    manyAssistantOptions,
    "artifact-120",
    [],
    ["artifact-222", "artifact-221", "artifact-220", "artifact-219", "artifact-218", "artifact-217", "artifact-216"],
  ).map(({ artifactId }) => artifactId),
  ["artifact-120", "artifact-222", "artifact-221", "artifact-220", "artifact-219", "artifact-218", "artifact-217"],
);
assert.deepEqual(
  reportAssistantArtifactOptions(
    manyAssistantOptions,
    "artifact-120",
    ["artifact-8", "artifact-9"],
    ["artifact-222", "artifact-221", "artifact-220", "artifact-219", "artifact-218"],
  ).map(({ artifactId }) => artifactId),
  ["artifact-120", "artifact-8", "artifact-9", "artifact-222", "artifact-221", "artifact-220", "artifact-219"],
  "explicitly selected evidence must stay visible before recent candidates fill the seven slots",
);
assert.deepEqual(reportAssistantArtifactOptions([manyAssistantOptions[0]], "artifact-1"), [manyAssistantOptions[0]]);

const assistantBlocks = [
  { id: "summary", type: "text", content: "요약" },
  { id: "revenue-chart", type: "chart", artifactId: "artifact-revenue" },
  { id: "occupancy-table", type: "table", artifactId: "artifact-occupancy" },
];
assert.equal(
  reportAssistantRepresentativeBlock(assistantBlocks, "occupancy-table")?.artifactId,
  "artifact-occupancy",
  "선택한 Artifact 블록의 실제 근거가 대표 Artifact여야 한다",
);
assert.equal(
  reportAssistantRepresentativeBlock(assistantBlocks, "summary")?.artifactId,
  "artifact-revenue",
  "텍스트 블록 선택 시 보고서에 배치된 첫 Artifact를 대표 근거로 사용해야 한다",
);
assert.equal(reportAssistantRepresentativeBlock([{ id: "summary", type: "text" }], "summary"), null);

const analysisArtifactBefore = structuredClone(analysisLibraryFixture.artifact);
const adaptedAnalysisArtifact = adaptAnalysisRunArtifact(analysisLibraryFixture.artifact);
assert.equal(adaptedAnalysisArtifact.artifact_id, "artifact-revenue");
assert.equal(Object.hasOwn(adaptedAnalysisArtifact, "query_id"), false);
assert.equal(adaptedAnalysisArtifact.evidence.artifact_id, "artifact-revenue");
assert.equal(Object.hasOwn(adaptedAnalysisArtifact.evidence, "query_id"), false);
assert.equal(adaptedAnalysisArtifact.evidence.product_release_id, "walkerhill-v4-synthetic");
assert.equal(adaptedAnalysisArtifact.evidence.evidence_cutoff, "2026-07-02");
assert.equal(adaptedAnalysisArtifact.evidence.period.end_exclusive, "2026-07-01");
assert.equal(adaptedAnalysisArtifact.evidence.sources[0].urn, "urn:answervice:pms:room-revenue");
assert.equal(adaptedAnalysisArtifact.evidence.sources[0].synthetic, true);
assert.equal(adaptedAnalysisArtifact.metrics[0].result_field, "room_revenue");
assert.equal(Object.hasOwn(adaptedAnalysisArtifact, "question"), false);
assert.deepEqual(analysisLibraryFixture.artifact, analysisArtifactBefore, "analysis adaptation must not mutate the API result");
assert.equal(analysisArtifactTitle(adaptedAnalysisArtifact), "2026년 1월 1일부터 6월 30일까지 객실 매출 분석");
assert.equal(adaptAnalysisRunArtifact({ ...analysisLibraryFixture.artifact, evidenceReady: false }), null);

const presentationRun = structuredClone(analysisLibraryFixture.artifact);
presentationRun.metrics[0] = {
  ...presentationRun.metrics[0],
  label: "Room Revenue",
  displayLabel: "객실 매출",
  unit: "KRW",
  displayUnit: "원",
};
presentationRun.evidence.metrics[0] = {
  ...presentationRun.evidence.metrics[0],
  label: "Room Revenue",
  displayLabel: "객실 매출",
  unit: "KRW",
  displayUnit: "원",
};
const presentationArtifact = adaptAnalysisRunArtifact(presentationRun);
assert.equal(presentationArtifact.metrics[0].display_label, "객실 매출");
assert.equal(presentationArtifact.metrics[0].display_unit, "원");
assert.equal(presentationArtifact.evidence.metrics[0].display_label, "객실 매출");
assert.equal(presentationArtifact.evidence.metrics[0].display_unit, "원");

const snapshotRun = structuredClone(analysisLibraryFixture.artifact);
delete snapshotRun.evidence.period;
snapshotRun.evidence.snapshot = {
  cutoff: "2026-08-20",
  selection: "max_source_value_lt_as_of",
};
const adaptedSnapshotArtifact = adaptAnalysisRunArtifact(snapshotRun);
assert.deepEqual(adaptedSnapshotArtifact.evidence.snapshot, {
  cutoff: "2026-08-20",
  selection: "max_source_value_lt_as_of",
});
assert.equal(analysisTimeLabel(adaptedSnapshotArtifact.evidence), "2026-08-20 이전 최신 데이터");
assert.equal(
  analysisArtifactTitle(adaptedSnapshotArtifact),
  "2026-08-20 이전 최신 데이터 객실 매출 분석",
);
assert.equal(reportEvidenceReady(adaptedSnapshotArtifact), true);

const insertedAnalysisArtifact = insertFrontendArtifact([], {
  ...analysisSources[1],
  blockId: "analysis-whole",
  sourceKind: "analysisRun",
  requestId: "request-revenue-new",
  visibleViews: ["summary"],
}, report);
assert.equal(insertedAnalysisArtifact.ok, true, insertedAnalysisArtifact.errors?.join("; "));
const persistedAnalysisBlock = toReportBlockRequest(insertedAnalysisArtifact.blocks[0]);
assert.equal(persistedAnalysisBlock.type, "artifact");
assert.equal(Object.hasOwn(persistedAnalysisBlock, "query_id"), false);
assert.equal(persistedAnalysisBlock.content, insertedAnalysisArtifact.blocks[0].content);
assert.doesNotThrow(() => toReportBlockRequest({ ...insertedAnalysisArtifact.blocks[0], queryId: undefined }));
const serverOnlyDefinition = normalizeReportDefinition({
  contract_version: REPORT_CONTRACT_VERSION,
  definition_id: report.definitionId,
  version: report.version,
  draft_revision: 1,
  status: "draft",
  title: report.title,
  blocks: [{ ...persistedAnalysisBlock, view_spec_id: "view-spec-1" }],
  orientation: "landscape",
  currency_display_unit: "million",
  approved_at: null,
  archived_at: null,
  archived_by: null,
});
assert.equal(loadFrontendDraft({ getItem: () => null }, report.definitionId, report.version), null);
assert.equal(serverOnlyDefinition.blocks[0].type, "artifact");
assert.equal(serverOnlyDefinition.blocks[0].artifactId, "artifact-revenue");
assert.equal(serverOnlyDefinition.blocks[0].queryId, undefined);
assert.equal(serverOnlyDefinition.blocks[0].viewSpecId, "view-spec-1");
assert.equal(toReportBlockRequest(serverOnlyDefinition.blocks[0]).view_spec_id, "view-spec-1");
assert.equal(serverOnlyDefinition.orientation, "landscape");
assert.equal(serverOnlyDefinition.currencyDisplayUnit, "million");
assert.equal(reportArtifactLibrarySources(serverOnlyDefinition, [])[0].artifactRequestId, "request-revenue-new");

const monthlyCards = artifactMetricCards(fixture("artifact-monthly-revenue.json"));
assert.deepEqual(
  monthlyCards.map(({ label, value }) => [label, value]),
  [["객실 매출", 1450000000], ["목표 매출", 1440000000]],
);
assert.equal(monthlyCards.some((metric) => Object.hasOwn(metric, "context")), false);
const channelCards = artifactMetricCards(fixture("artifact-channel-mix.json"));
assert.deepEqual(
  channelCards.map(({ label, value }) => [label, value]),
  [["채널 매출", 1080000000], ["매출 비중", 47.2]],
);
const reversedTemporalRows = {
  table: {
    columns: ["month", "room_revenue"],
    rows: [
      { month: "2026-06", room_revenue: 1450000000 },
      { month: "2026-05", room_revenue: 1360000000 },
    ],
  },
  chart: { x_field: "month", y_fields: ["room_revenue"] },
  evidence: {
    metrics: [{
      metric_id: "room_revenue", result_field: "room_revenue", label: "객실 매출",
      definition: "월별 객실 매출", unit: "원", reduction: "sum",
    }],
  },
};
assert.deepEqual(
  artifactMetricCards(reversedTemporalRows),
  [],
  "row order and reduction metadata must never manufacture a representative KPI",
);

const monthlyArtifact = fixture("artifact-monthly-revenue.json");
const monthlyBeforeSizing = structuredClone(monthlyArtifact);
assert.throws(
  () => estimateArtifactBlockLayout(monthlyArtifact, { orientation: "landscape" }),
  /원자 view 하나/,
);
assert.deepEqual(estimateArtifactBlockLayout(monthlyArtifact, { orientation: "landscape", visibleViews: ["chart"] }), { width: 6, height: 8 });
assert.deepEqual(estimateArtifactBlockLayout(monthlyArtifact, { orientation: "landscape", visibleViews: ["table"] }), { width: 6, height: 8 });
const longSummaryLayout = estimateArtifactBlockLayout({ ...monthlyArtifact, summary: "긴 한국어 분석 요약입니다. ".repeat(30) }, {
  orientation: "landscape", visibleViews: ["summary"],
});
assert.equal(longSummaryLayout.width, 6);
assert.equal(longSummaryLayout.height > estimateArtifactBlockLayout(monthlyArtifact, { orientation: "landscape", visibleViews: ["summary"] }).height, true);
const wideTableLayout = estimateArtifactBlockLayout({
  table: { columns: ["a", "b", "c", "d", "e"], rows: [{ a: 1 }] },
}, { orientation: "landscape", visibleViews: ["table"] });
assert.equal(wideTableLayout.width, 12);
assert.equal(wideTableLayout.height <= 18, true);
assert.deepEqual(monthlyArtifact, monthlyBeforeSizing, "Artifact sizing must be pure");
const manualArtifactBlock = {
  id: "manual-size", title: "수동 크기", type: "artifact", artifactId: monthlyArtifact.artifact_id,
  content: JSON.stringify({ presentationMode: "standard", visibleViews: ["summary"], sizeMode: "manual" }),
  columns: 6, x: 0, y: 0, w: 6, h: 8,
};
assert.equal(fitFrontendArtifactBlock(manualArtifactBlock, monthlyArtifact, { orientation: "portrait" }), manualArtifactBlock);
const autoFittedBlock = fitFrontendArtifactBlock(manualArtifactBlock, monthlyArtifact, { orientation: "portrait", force: true });
assert.deepEqual([autoFittedBlock.w, autoFittedBlock.h], [6, 5]);
assert.equal(JSON.parse(autoFittedBlock.content).sizeMode, "auto");
assert.deepEqual(manualArtifactBlock, {
  id: "manual-size", title: "수동 크기", type: "artifact", artifactId: monthlyArtifact.artifact_id,
  content: JSON.stringify({ presentationMode: "standard", visibleViews: ["summary"], sizeMode: "manual" }),
  columns: 6, x: 0, y: 0, w: 6, h: 8,
}, "fit must not mutate manual input");
const legacyBundleBlock = {
  ...manualArtifactBlock,
  content: JSON.stringify({ visibleViews: ["summary", "chart"], sizeMode: "auto" }),
};
assert.equal(
  fitFrontendArtifactBlock(legacyBundleBlock, monthlyArtifact, { orientation: "portrait", force: true }),
  legacyBundleBlock,
  "legacy multi-view blocks must fail closed instead of silently selecting a view",
);

const legacyChart = { id: "legacy-chart", title: "월별 차트", type: "chart", artifactId: monthlyArtifact.artifact_id, content: JSON.stringify({ showLegend: true }), columns: 6, x: 0, y: 0, w: 6, h: 7 };
const legacyMonthlyTable = { id: "legacy-monthly-table", title: "월별 표", type: "table", artifactId: monthlyArtifact.artifact_id, content: JSON.stringify({ density: "compact" }), columns: 6, x: 6, y: 0, w: 6, h: 7 };
const channelArtifact = fixture("artifact-channel-mix.json");
const legacyChannelTable = { ...legacyMonthlyTable, id: "legacy-channel-table", artifactId: channelArtifact.artifact_id, content: JSON.stringify({ density: "comfortable", showRowNumbers: true }) };
assert.equal(artifactViewBlockSettings(legacyChart).sizeMode, "auto");
assert.equal(artifactViewBlockSettings(legacyMonthlyTable).sizeMode, "auto");
assert.deepEqual(estimateArtifactViewBlockLayout(legacyChart, monthlyArtifact, { orientation: "landscape" }), { width: 6, height: 8 });
assert.deepEqual(estimateArtifactViewBlockLayout(legacyMonthlyTable, monthlyArtifact, { orientation: "landscape" }), { width: 6, height: 10 });
assert.deepEqual(estimateArtifactViewBlockLayout({ type: "chart" }, monthlyArtifact, { orientation: "landscape", autoWidth: true }), { width: 8, height: 8 });
assert.deepEqual(estimateArtifactViewBlockLayout({ type: "table" }, monthlyArtifact, { orientation: "landscape", autoWidth: true }), { width: 6, height: 11 });
assert.deepEqual(estimateArtifactViewBlockLayout(legacyChannelTable, channelArtifact, { orientation: "landscape" }), { width: 6, height: 8 });
assert.deepEqual(estimateArtifactViewBlockLayout(legacyMonthlyTable, monthlyArtifact, { orientation: "portrait" }), { width: 6, height: 11 });
assert.deepEqual(estimateArtifactViewBlockLayout({ ...legacyChannelTable, w: 12, columns: 12 }, channelArtifact, { orientation: "portrait" }), { width: 12, height: 9 });
const fittedLegacyChart = fitFrontendArtifactViewBlock(legacyChart, monthlyArtifact, { orientation: "landscape" });
assert.equal(fittedLegacyChart.h, 8);
assert.equal(JSON.parse(fittedLegacyChart.content).sizeMode, "auto");
assert.equal(JSON.parse(fittedLegacyChart.content).showLegend, true);
const fittedMonthlyRow = compactDraftLayout([
  fittedLegacyChart,
  fitFrontendArtifactViewBlock(legacyMonthlyTable, monthlyArtifact, { orientation: "landscape" }),
]);
assert.deepEqual(fittedMonthlyRow.map(({ id, h }) => [id, h]), [["legacy-chart", 8], ["legacy-monthly-table", 10]]);
assert.deepEqual(fitFrontendArtifactViewBlock(structuredClone(fittedLegacyChart), monthlyArtifact, { orientation: "landscape" }), fittedLegacyChart, "saved auto sizing must be idempotent on re-entry");
assert.equal(fitFrontendArtifactViewBlock(structuredClone(fittedLegacyChart), monthlyArtifact, { orientation: "portrait" }).h, 9);
const denseSeriesChart = { ...monthlyArtifact, chart: { ...monthlyArtifact.chart, y_fields: ["a", "b", "c", "d"] } };
assert.equal(estimateArtifactViewBlockLayout(legacyChart, denseSeriesChart, { orientation: "landscape" }).height, 9);
const wideMonthlyTable = { ...monthlyArtifact, table: { ...monthlyArtifact.table, columns: ["a", "b", "c", "d", "e", "f", "g"] } };
assert.equal(estimateArtifactViewBlockLayout(legacyMonthlyTable, wideMonthlyTable, { orientation: "landscape" }).height, 12);
const manuallySizedLegacyTable = { ...legacyMonthlyTable, h: 9, content: JSON.stringify({ density: "comfortable", sizeMode: "manual" }) };
assert.equal(fitFrontendArtifactViewBlock(manuallySizedLegacyTable, monthlyArtifact, { orientation: "portrait" }), manuallySizedLegacyTable);
const compactHotelTable = {
  ...channelArtifact,
  table: {
    ...channelArtifact.table,
    columns: channelArtifact.table.columns.slice(0, 2),
    rows: channelArtifact.table.rows.slice(0, 3),
  },
};
assert.deepEqual(
  estimateArtifactViewBlockLayout({ ...legacyChannelTable, w: 6, columns: 6 }, compactHotelTable, { orientation: "portrait" }),
  { width: 6, height: 6 },
  "three-row tables should fit their content without a clipped row or an oversized block",
);
const undersizedChart = resizeDraftBlocks([legacyChart], legacyChart.id, 6, 5, "portrait");
assert.equal(undersizedChart?.blocks[0].h, 9, "portrait charts must retain enough height for category labels");
const undersizedTable = resizeDraftBlocks([{ ...legacyChannelTable, h: 9 }], legacyChannelTable.id, 6, 5, "portrait");
assert.equal(undersizedTable?.blocks[0].h, 6, "portrait tables must retain enough height for three visible rows");
assert.deepEqual(legacyChart, { id: "legacy-chart", title: "월별 차트", type: "chart", artifactId: monthlyArtifact.artifact_id, content: JSON.stringify({ showLegend: true }), columns: 6, x: 0, y: 0, w: 6, h: 7 }, "legacy sizing must be pure");

assert.match(reportSources.blockControls, /memo\(function ReportCurrencyControl/);
assert.match(reportSources.controller, /currency=\{reportCurrency\}/);
assert.match(reportSources.dragAndDrop, /keyboardEndDropPosition\(blocksRef\.current/);
assert.match(reportSources.dragAndDrop, /유효한 위치가 없어 이동을 취소했습니다/);
assert.match(reportSources.presentation, /safeDataBlockHeight\(block, orientation\)/);
assert.match(
  reportSources.controller,
  /if \(draft\.isDirty\) \{\s*lifecycle\.setError\("저장되지 않은 변경사항을 먼저 저장한 뒤 PDF를 확정해 주세요\."\)/,
);
assert.match(reportSources.lifecycle, /createAnalysisClient\(fetch\)/);
assert.match(reportSources.artifacts, /analysisClient\.listRuns\(\{ limit: 7, approvedOnly: true \}\)/);
assert.match(reportSources.artifacts, /analysisClient\.getRunArtifact\(source\.requestId \|\| source\.artifactRequestId\)/);
assert.match(reportSources.artifacts, /sources\.filter\([\s\S]*hydrationIds\.has\(source\.artifactId\)/);
assert.match(reportSources.artifacts, /const setAssistantArtifacts = useCallback\(async/);
assert.match(reportSources.artifacts, /const primaryArtifactId = representativeArtifactId \|\| artifactSelection \|\| uniqueIds\[0\] \|\| ""/);
assert.match(reportSources.artifacts, /const selectedIds = \[primaryArtifactId, \.\.\.requested\]/);
assert.match(reportSources.artifacts, /filter\(Boolean\)\.slice\(0, 5\)/);
assert.match(reportSources.artifacts, /filter\(\(artifactId\) => artifactId !== primaryArtifactId\)[\s\S]*\.slice\(0, 4\)/);
assert.match(reportSources.artifacts, /setArtifactSelection\(primaryArtifactId\)/);
assert.match(reportSources.controller, /const persistedBlocks = draft\.orderedBlocks/);
assert.doesNotMatch(
  reportFeatureSource,
  /pdfUnsupportedBlocks|orderedBlocks\.filter\(\(block\) => block\.type !== "artifact"\)/,
);
assert.match(reportSources.documentView, /disabled=\{Boolean\(pending\) \|\| isDirty\}/);
assert.doesNotMatch(reportSources.controller, /wholeArtifactTemplateFor|WHOLE_ARTIFACT_TEMPLATE/);
assert.doesNotMatch(reportSources.dragAndDrop, /activeId\.startsWith\("artifact:"\)|addWholeArtifact/);
assert.match(reportSources.draftMutations, /sizeMode: "manual"/);
assert.match(reportSources.blockControls, /내용에 맞춤/);
assert.match(reportSources.controller, /draftBridgeRef\.current\?\.fitHydratedArtifactViews\(artifactMap\)/);
const hydratedFit = reportSources.draftState.match(/const fitHydratedArtifactViews[\s\S]*?const changeOrientation/)?.[0] || "";
assert.match(hydratedFit, /savedBlocksRef\.current = copyDraftBlocks\(fittedSaved\)/);
assert.match(hydratedFit, /setIsDirty\(migrated\.migratedSourceCount > 0 \|\| draftChanged\(blocksRef\.current\)\)/);
assert.doesNotMatch(hydratedFit, /commitBlocks\(/, "artifact hydration must not create user history; only an explicit legacy migration becomes dirty");
assert.match(reportSources.draftState, /fitAutoArtifactViewLayout\(reflowed\.blocks, artifacts, orientation\)/);
assert.match(reportSources.draftMutations, /return resolveDraftLayoutCollisions\(fitted\)/);
assert.match(reportSources.draftMutations, /fitFrontendArtifactViewBlock\(block, artifacts\[block\.artifactId\], \{ orientation \}\)/);
assert.match(reportSources.draftMutations, /block\.type === "artifact"[\s\S]*fitFrontendArtifactBlock\(block, artifacts\[block\.artifactId\], \{ orientation \}\)/);
assert.match(reportSources.draftMutations, /\["artifact", "chart", "table"\]\.includes\(block\.type \?\? ""\)[\s\S]*sizeMode: "manual"/);
assert.match(reportSources.draftState, /density: "comfortable", sizeMode: "auto"/);

const publicMonthlyArtifact = {
  ...monthlyArtifact,
  query_id: undefined,
  evidence: { ...monthlyArtifact.evidence, query_id: undefined },
};
assert.equal(reportEvidenceReady(publicMonthlyArtifact), true);
const snapshotArtifact = structuredClone(publicMonthlyArtifact);
delete snapshotArtifact.evidence.period;
snapshotArtifact.evidence.snapshot = {
  cutoff: "2026-08-20",
  selection: "max_source_value_lt_as_of",
};
assert.equal(reportEvidenceReady(snapshotArtifact), true);
snapshotArtifact.evidence.period = {
  start: "2026-08-01",
  end_exclusive: "2026-08-21",
};
assert.equal(reportEvidenceReady(snapshotArtifact), false);
assert.equal(
  reportEvidenceReady({ ...publicMonthlyArtifact, chart: { ...monthlyArtifact.chart, y_fields: ["unknown_measure"] } }),
  false,
  "an artifact chart must not reference an ungoverned result field",
);

console.log("frontend report draft v2 tests passed");
