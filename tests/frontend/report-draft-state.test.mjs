import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import {
  copyDraftBlocks,
  createTextTemplateBlock,
  mergeDraftCurrencyPolicy,
  readDraftBlockSettings,
  resizeDraftBlocks,
} from "../../app/frontend/src/features/reports/reportDraftMutations.ts";
import { useReportDraftState } from "../../app/frontend/src/features/reports/useReportDraftState.ts";

const requireFromFrontend = createRequire(new URL("../../app/frontend/package.json", import.meta.url));
const { createElement } = requireFromFrontend("react");
const { renderToStaticMarkup } = requireFromFrontend("react-dom/server");

const sourceBlocks = [{
  id: "block-a",
  title: "Section",
  columns: 12,
  type: "text",
  content: "Body",
  x: 0,
  y: 0,
  w: 12,
  h: 4,
}];
const copiedBlocks = copyDraftBlocks(sourceBlocks);
assert.deepEqual(copiedBlocks, sourceBlocks);
assert.notEqual(copiedBlocks, sourceBlocks);
assert.notEqual(copiedBlocks[0], sourceBlocks[0]);

const policy = mergeDraftCurrencyPolicy({ displayUnit: "million" });
assert.equal(policy.currencyCode, "KRW");
assert.equal(policy.displayUnit, "million");

const templateBlock = createTextTemplateBlock({
  id: "section",
  blockTitle: "Section",
  content: "## Heading",
  w: 6,
  h: 4,
}, null, sourceBlocks, "landscape");
assert.equal(templateBlock.y, 4);
assert.equal(templateBlock.w, 6);
assert.equal(templateBlock.type, "text");

const resized = resizeDraftBlocks(sourceBlocks, "block-a", 6, 7, "landscape");
assert.ok(resized);
assert.equal(resized.blocks[0].w, 6);
assert.equal(resized.blocks[0].h, 7);
assert.match(resized.announcement, /높이 7단/);
const boundedResize = resizeDraftBlocks(sourceBlocks, "block-a", 6, 7, "landscape", { x: 6, y: 2 });
assert.equal(boundedResize.blocks[0].x, 6);
assert.equal(boundedResize.blocks[0].y, 2);
assert.equal(boundedResize.blocks[0].w, 6);
assert.deepEqual(readDraftBlockSettings({ ...sourceBlocks[0], type: "chart", content: "{" }), {});

let state;
function HookProbe() {
  state = useReportDraftState({ editable: true, identity: { title: "월간 보고서" }, initialBlocks: sourceBlocks });
  return createElement("span", null, `${state.reportTitle}:${state.saveState}`);
}
assert.equal(renderToStaticMarkup(createElement(HookProbe)), "<span>월간 보고서:saved</span>");
for (const action of [
  "resetDraft", "commitBlocks", "undo", "redo", "updateBlock", "moveBlock",
  "resizeBlock", "setBlockSetting", "addTemplateBlock",
  "deleteBlock", "duplicateBlock", "changeOrientation", "changeCurrencyDisplayUnit",
  "updateReportTitle", "commitReportTitle",
]) assert.equal(typeof state[action], "function", `${action} must be a stable hook action`);

const atomicArtifact = {
  summary: "승인된 분석 요약",
  metrics: [{ metric_id: "room_revenue", label: "객실 매출", value: 123, unit: "KRW" }],
};
const atomicSource = {
  artifactId: "artifact-atomic",
  artifactChecksum: "sha256:atomic",
  queryId: "query-atomic",
  title: "객실 매출 분석",
};
const atomicTemplates = new Map([
  ["artifact-summary", { id: "artifact-summary", view: "summary", w: 6, h: 4 }],
  ["artifact-kpi", { id: "artifact-kpi", view: "kpi", w: 6, h: 5 }],
]);
function renderAtomicDraft(initialBlocks) {
  let atomicState;
  function AtomicHookProbe() {
    atomicState = useReportDraftState({
      editable: true,
      initialBlocks,
      artifacts: { [atomicSource.artifactId]: atomicArtifact },
      artifactSources: [atomicSource],
      selectedArtifactId: atomicSource.artifactId,
      templates: atomicTemplates,
    });
    return createElement("span", null, atomicState.blocks.length);
  }
  renderToStaticMarkup(createElement(AtomicHookProbe));
  return atomicState;
}

const emptyAtomicDraft = renderAtomicDraft([]);
assert.equal(emptyAtomicDraft.addTemplateBlock("artifact-summary", { x: 0, y: 0, w: 6 }), true);
assert.deepEqual(
  emptyAtomicDraft.blocksRef.current.map(({ type, x, y, w }) => ({ type, x, y, w })),
  [{ type: "artifact", x: 0, y: 0, w: 6 }],
  "an atomic summary dropped on an empty page must commit at the preview coordinates",
);

const adjacentAtomicDraft = renderAtomicDraft(sourceBlocks);
assert.equal(adjacentAtomicDraft.addTemplateBlock("artifact-kpi", { x: 6, y: 0, w: 6, requestedX: 6 }), true);
const adjacentBlocks = adjacentAtomicDraft.blocksRef.current;
assert.deepEqual(
  adjacentBlocks.map(({ type, x, y, w }) => ({ type, x, y, w })),
  [
    { type: "text", x: 0, y: 0, w: 6 },
    { type: "artifact", x: 6, y: 0, w: 6 },
  ],
  "an atomic KPI dropped beside a full-width block must commit at the preview coordinates",
);

const draftStateSource = readFileSync(new URL("../../app/frontend/src/features/reports/useReportDraftState.ts", import.meta.url), "utf8");
const draftStateTypesSource = readFileSync(new URL("../../app/frontend/src/features/reports/reportDraftStateTypes.ts", import.meta.url), "utf8");
assert.match(draftStateSource, /window\.addEventListener\("beforeunload", warnBeforeUnload\)/);
assert.match(draftStateSource, /window\.removeEventListener\("beforeunload", warnBeforeUnload\)/);
assert.match(
  draftStateTypesSource,
  /interface ReportDraftHistorySnapshot\s*\{[\s\S]*title: string;[\s\S]*blocks:[\s\S]*orientation: ReportOrientation;[\s\S]*currencyPolicy: DraftCurrencyPolicy;/,
  "history contract must include every persisted report layout field",
);
assert.match(
  draftStateSource,
  /function createHistorySnapshot\([\s\S]*orientation,[\s\S]*currencyPolicy: \{ \.\.\.currencyPolicy \}/,
  "history snapshots must copy orientation and currency policy with title and blocks",
);
assert.match(
  draftStateSource,
  /orientationRef\.current = previous\.orientation;[\s\S]*currencyPolicyRef\.current = previousPolicy;[\s\S]*setReportOrientation\(previous\.orientation\);[\s\S]*setReportCurrencyPolicy\(previousPolicy\);/,
  "undo must restore orientation and currency policy atomically",
);
assert.match(
  draftStateSource,
  /orientationRef\.current = nextSnapshot\.orientation;[\s\S]*currencyPolicyRef\.current = nextPolicy;[\s\S]*setReportOrientation\(nextSnapshot\.orientation\);[\s\S]*setReportCurrencyPolicy\(nextPolicy\);/,
  "redo must restore orientation and currency policy atomically",
);
assert.match(
  draftStateSource,
  /changeCurrencyDisplayUnit[\s\S]*setHistory\([\s\S]*previousSnapshot[\s\S]*currencyPolicyRef\.current = next;/,
  "currency unit changes must create an undo boundary before mutation",
);
assert.match(
  draftStateSource,
  /changeOrientation[\s\S]*setHistory\([\s\S]*previousSnapshot[\s\S]*orientationRef\.current = orientation;[\s\S]*commitBlocks\([\s\S]*, false\);/,
  "orientation changes must record exactly one complete snapshot before reflow",
);

console.log("frontend report draft state tests passed");
