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
  artifactViewBlockSettings,
  artifactMetricCards,
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
  saveFrontendDraft,
} from "../../app/frontend/src/features/reports/reportDraftV2.js";
import { reportEvidenceReady } from "../../app/frontend/src/features/reports/reportArtifactEvidence.ts";
import { resizeDraftBlocks } from "../../app/frontend/src/features/reports/reportDraftMutations.ts";
import { reportFeatureSource, reportSources } from "./report-source-contract.mjs";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));

const report = { definitionId: "report-1", version: 3, title: "월간 영업 성과 보고서", orientation: "portrait" };
const textBlock = {
  id: "summary", title: "경영진 요약", type: "text", content: "핵심 변화", columns: 12,
  x: 0, y: 0, w: 12, h: 4,
};
const sourceA = {
  artifactId: "artifact-a", queryId: "query-a", title: "객실 매출 분석",
  artifactChecksum: "sha256:a", sourceUrns: ["urn:rooms"],
};
const sourceB = { artifactId: "artifact-b", queryId: "query-b", title: "채널 구성 분석" };

const first = insertFrontendArtifact([textBlock], { ...sourceA, blockId: "whole-a" }, report);
assert.equal(first.ok, true, first.errors?.join("; "));
assert.equal(first.blocks.find((block) => block.id === "whole-a").type, "artifact");
assert.equal(first.blocks.find((block) => block.id === "whole-a").artifactId, "artifact-a");
assert.equal(JSON.parse(first.blocks.find((block) => block.id === "whole-a").content).sizeMode, "auto");

const side = insertFrontendArtifact(first.blocks, {
  ...sourceB,
  blockId: "whole-b",
  placement: { type: "side", targetBlockId: "whole-a", edge: "right" },
}, report);
assert.equal(side.ok, true, side.errors?.join("; "));
assert.deepEqual(side.blocks.filter((block) => block.id.startsWith("whole-")).map(({ id, x, w, h }) => [id, x, w, h]), [
  ["whole-a", 0, 6, 18],
  ["whole-b", 6, 6, 18],
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
assert.deepEqual(keyboardDrop, {
  pageId: "report-1:page:1", x: 0, requestedX: 0, y: 22, w: 12, h: 16,
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
  ["artifact-occupancy", "request-occupancy", "2026-06-01–2026-07-01 주요 지표 분석"],
  ["artifact-revenue", "request-revenue-new", "월간 객실 매출 추이"],
]);
assert.equal(analysisSources.some((source) => Object.hasOwn(source, "question")), false);

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
assert.equal(analysisArtifactTitle(adaptedAnalysisArtifact), "2026-01-01–2026-07-01 객실 매출 분석");
assert.equal(adaptAnalysisRunArtifact({ ...analysisLibraryFixture.artifact, evidenceReady: false }), null);

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
assert.equal(analysisTimeLabel(adaptedSnapshotArtifact.evidence), "2026-08-20 이전 최신 스냅샷");
assert.equal(
  analysisArtifactTitle(adaptedSnapshotArtifact),
  "2026-08-20 이전 최신 스냅샷 객실 매출 분석",
);
assert.equal(reportEvidenceReady(adaptedSnapshotArtifact), true);

const insertedAnalysisArtifact = insertFrontendArtifact([], {
  ...analysisSources[1],
  blockId: "analysis-whole",
  sourceKind: "analysisRun",
  requestId: "request-revenue-new",
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
  status: "draft",
  title: report.title,
  blocks: [{ ...persistedAnalysisBlock, view_spec_id: "view-spec-1" }],
  orientation: "landscape",
  currency_display_unit: "million",
  approved_at: null,
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
assert.deepEqual(estimateArtifactBlockLayout(monthlyArtifact, { orientation: "landscape" }), { width: 12, height: 12 });
assert.deepEqual(estimateArtifactBlockLayout(monthlyArtifact, { orientation: "portrait" }), { width: 12, height: 18 });
assert.deepEqual(estimateArtifactBlockLayout(monthlyArtifact, { orientation: "landscape", width: 6 }), { width: 6, height: 17 });
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
  content: JSON.stringify({ presentationMode: "standard", visibleViews: ["summary", "chart"], sizeMode: "manual" }),
  columns: 6, x: 0, y: 0, w: 6, h: 8,
};
assert.equal(fitFrontendArtifactBlock(manualArtifactBlock, monthlyArtifact, { orientation: "portrait" }), manualArtifactBlock);
const autoFittedBlock = fitFrontendArtifactBlock(manualArtifactBlock, monthlyArtifact, { orientation: "portrait", force: true });
assert.equal(autoFittedBlock.w, 12);
assert.equal(autoFittedBlock.h > manualArtifactBlock.h, true);
assert.equal(JSON.parse(autoFittedBlock.content).sizeMode, "auto");
assert.deepEqual(manualArtifactBlock, {
  id: "manual-size", title: "수동 크기", type: "artifact", artifactId: monthlyArtifact.artifact_id,
  content: JSON.stringify({ presentationMode: "standard", visibleViews: ["summary", "chart"], sizeMode: "manual" }),
  columns: 6, x: 0, y: 0, w: 6, h: 8,
}, "fit must not mutate manual input");

const legacyChart = { id: "legacy-chart", title: "월별 차트", type: "chart", artifactId: monthlyArtifact.artifact_id, content: JSON.stringify({ showLegend: true }), columns: 6, x: 0, y: 0, w: 6, h: 7 };
const legacyMonthlyTable = { id: "legacy-monthly-table", title: "월별 표", type: "table", artifactId: monthlyArtifact.artifact_id, content: JSON.stringify({ density: "compact" }), columns: 6, x: 6, y: 0, w: 6, h: 7 };
const channelArtifact = fixture("artifact-channel-mix.json");
const legacyChannelTable = { ...legacyMonthlyTable, id: "legacy-channel-table", artifactId: channelArtifact.artifact_id, content: JSON.stringify({ density: "comfortable", showRowNumbers: true }) };
assert.equal(artifactViewBlockSettings(legacyChart).sizeMode, "auto");
assert.equal(artifactViewBlockSettings(legacyMonthlyTable).sizeMode, "auto");
assert.deepEqual(estimateArtifactViewBlockLayout(legacyChart, monthlyArtifact, { orientation: "landscape" }), { width: 6, height: 8 });
assert.deepEqual(estimateArtifactViewBlockLayout(legacyMonthlyTable, monthlyArtifact, { orientation: "landscape" }), { width: 6, height: 10 });
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
assert.deepEqual(fittedMonthlyRow.map(({ id, h }) => [id, h]), [["legacy-chart", 10], ["legacy-monthly-table", 10]]);
assert.deepEqual(fitFrontendArtifactViewBlock(structuredClone(fittedLegacyChart), monthlyArtifact, { orientation: "landscape" }), fittedLegacyChart, "saved auto sizing must be idempotent on re-entry");
assert.equal(fitFrontendArtifactViewBlock(structuredClone(fittedLegacyChart), monthlyArtifact, { orientation: "portrait" }).h, 9);
const denseSeriesChart = { ...monthlyArtifact, chart: { ...monthlyArtifact.chart, y_fields: ["a", "b", "c", "d"] } };
assert.equal(estimateArtifactViewBlockLayout(legacyChart, denseSeriesChart, { orientation: "landscape" }).height, 9);
const wideMonthlyTable = { ...monthlyArtifact, table: { ...monthlyArtifact.table, columns: ["a", "b", "c", "d", "e", "f", "g"] } };
assert.equal(estimateArtifactViewBlockLayout(legacyMonthlyTable, wideMonthlyTable, { orientation: "landscape" }).height, 12);
const manuallySizedLegacyTable = { ...legacyMonthlyTable, h: 9, content: JSON.stringify({ density: "comfortable", sizeMode: "manual" }) };
assert.equal(fitFrontendArtifactViewBlock(manuallySizedLegacyTable, monthlyArtifact, { orientation: "portrait" }), manuallySizedLegacyTable);
assert.deepEqual(legacyChart, { id: "legacy-chart", title: "월별 차트", type: "chart", artifactId: monthlyArtifact.artifact_id, content: JSON.stringify({ showLegend: true }), columns: 6, x: 0, y: 0, w: 6, h: 7 }, "legacy sizing must be pure");

assert.match(reportSources.blockControls, /memo\(function ReportCurrencyControl/);
assert.match(reportSources.controller, /currency=\{reportCurrency\}/);
assert.match(reportSources.dragAndDrop, /keyboardEndDropPosition\(blocksRef\.current/);
assert.match(reportSources.dragAndDrop, /유효한 위치가 없어 이동을 취소했습니다/);
assert.match(
  reportSources.controller,
  /if \(draft\.isDirty\) \{\s*lifecycle\.setError\("저장되지 않은 변경사항을 먼저 저장한 뒤 PDF를 확정해 주세요\."\)/,
);
assert.match(reportSources.lifecycle, /createAnalysisClient\(fetch\)/);
assert.match(reportSources.artifacts, /analysisClient\.listRuns\(\{ limit: 7, approvedOnly: true \}\)/);
assert.match(reportSources.artifacts, /analysisClient\.getRunArtifact\(source\.requestId \|\| source\.artifactRequestId\)/);
assert.match(reportSources.artifacts, /sources\.filter\([\s\S]*hydrationIds\.has\(source\.artifactId\)/);
assert.match(reportSources.artifacts, /const setAssistantArtifacts = useCallback\(async/);
assert.match(reportSources.artifacts, /const primaryArtifactId = artifactSelection \|\| uniqueIds\[0\] \|\| ""/);
assert.match(reportSources.artifacts, /const selectedIds = \[primaryArtifactId, \.\.\.requested\]/);
assert.match(reportSources.artifacts, /setArtifactSelection\(primaryArtifactId\)/);
assert.match(reportSources.controller, /const persistedBlocks = compactDraftLayout\(draft\.orderedBlocks\)/);
assert.doesNotMatch(
  reportFeatureSource,
  /pdfUnsupportedBlocks|orderedBlocks\.filter\(\(block\) => block\.type !== "artifact"\)/,
);
assert.match(reportSources.documentView, /disabled=\{Boolean\(pending\) \|\| isDirty\}/);
assert.match(reportSources.controller, /wholeArtifactTemplateFor/);
assert.match(reportSources.dragAndDrop, /wholeArtifactTemplateFor\(libraryArtifact, dropWidth\)\.h/);
assert.match(reportSources.draftMutations, /sizeMode: "manual"/);
assert.match(reportSources.blockControls, /내용에 맞춤/);
assert.match(reportSources.controller, /draftBridgeRef\.current\?\.fitHydratedArtifactViews\(artifactMap\)/);
const hydratedFit = reportSources.draftState.match(/const fitHydratedArtifactViews[\s\S]*?const changeOrientation/)?.[0] || "";
assert.match(hydratedFit, /savedBlocksRef\.current = copyDraftBlocks\(fittedSaved\)/);
assert.match(hydratedFit, /setIsDirty\(draftChanged\(blocksRef\.current\)\)/);
assert.doesNotMatch(hydratedFit, /commitBlocks\(/, "artifact hydration must not create user history or dirty state");
assert.match(reportSources.draftState, /fitAutoArtifactViewLayout\(reflowed\.blocks, artifacts, orientation\)/);
assert.match(reportSources.draftMutations, /const compacted = compactDraftLayout\(inputBlocks\)/);
assert.match(reportSources.draftMutations, /fitFrontendArtifactViewBlock\(block, artifacts\[block\.artifactId\], \{ orientation \}\)/);
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
