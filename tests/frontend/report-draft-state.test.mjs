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
assert.equal(resized.blocks[0].w, 12);
assert.equal(resized.blocks[0].h, 7);
assert.match(resized.announcement, /높이 7단/);
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
