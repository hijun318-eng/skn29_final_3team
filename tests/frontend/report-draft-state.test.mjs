import assert from "node:assert/strict";
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
assert.match(resized.announcement, /너비 6, 높이 7/);
assert.doesNotMatch(resized.announcement, /\/12|12열/);

const sameRowBlocks = [
  { id: "row-text", title: "요약", columns: 6, type: "text", content: "요약", x: 0, y: 0, w: 6, h: 4 },
  { id: "row-chart", title: "차트", columns: 6, type: "chart", content: "{}", x: 6, y: 0, w: 6, h: 7 },
  { id: "row-table", title: "표", columns: 12, type: "table", content: "{}", x: 0, y: 7, w: 12, h: 5 },
];
const independentlyResized = resizeDraftBlocks(sameRowBlocks, "row-chart", 6, 10, "landscape");
assert.ok(independentlyResized);
assert.equal(independentlyResized.blocks.find((block) => block.id === "row-text").h, 4);
assert.equal(independentlyResized.blocks.find((block) => block.id === "row-chart").h, 10);
assert.equal(independentlyResized.blocks.find((block) => block.id === "row-table").y, 10);

const edgeResizeBlocks = [
  { id: "edge-above", title: "위", columns: 6, type: "text", content: "위", x: 6, y: 0, w: 6, h: 2 },
  { id: "edge-left", title: "왼쪽", columns: 6, type: "text", content: "왼쪽", x: 0, y: 4, w: 6, h: 4 },
  { id: "edge-target", title: "대상", columns: 6, type: "chart", content: "{}", x: 6, y: 4, w: 6, h: 7 },
  { id: "edge-below", title: "아래", columns: 6, type: "table", content: "{}", x: 6, y: 11, w: 6, h: 5 },
];
const topResized = resizeDraftBlocks(
  edgeResizeBlocks,
  "edge-target",
  6,
  10,
  "landscape",
  { x: 6, y: 1 },
);
assert.ok(topResized);
assert.deepEqual(
  topResized.blocks.map(({ id, x, y, w, h }) => [id, x, y, w, h]),
  [
    ["edge-above", 6, 0, 6, 2],
    ["edge-left", 0, 4, 6, 4],
    ["edge-target", 6, 2, 6, 9],
    ["edge-below", 6, 11, 6, 5],
  ],
);
const bottomResized = resizeDraftBlocks(edgeResizeBlocks, "edge-target", 6, 10, "landscape");
assert.ok(bottomResized);
assert.equal(bottomResized.blocks.find((block) => block.id === "edge-left").h, 4);
assert.equal(bottomResized.blocks.find((block) => block.id === "edge-below").y, 14);
assert.deepEqual(readDraftBlockSettings({ ...sourceBlocks[0], type: "chart", content: "{" }), {});

let state;
function HookProbe() {
  state = useReportDraftState({ editable: true, initialBlocks: sourceBlocks });
  return createElement("span", null, state.saveState);
}
assert.equal(renderToStaticMarkup(createElement(HookProbe)), "<span>saved</span>");
for (const action of [
  "resetDraft", "commitBlocks", "undo", "redo", "updateBlock", "moveBlock",
  "resizeBlock", "setBlockSetting", "addTemplateBlock", "insertArtifact",
  "deleteBlock", "duplicateBlock", "changeOrientation", "changeCurrencyDisplayUnit",
]) assert.equal(typeof state[action], "function", `${action} must be a stable hook action`);

console.log("frontend report draft state tests passed");
