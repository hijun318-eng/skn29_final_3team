import assert from "node:assert/strict";

import {
  compactDraftLayout,
  isDraftLayoutValid,
  placeDraftBlock,
  restoreDraftLayout,
} from "../../app/frontend/src/contracts/report.ts";

const validSavedLayout = [
  { id: "summary", title: "요약", columns: 4, type: "text", content: "요약", x: 2, y: 3, w: 4, h: 4 },
  { id: "chart", title: "차트", columns: 6, type: "chart", content: "{}", x: 6, y: 3, w: 6, h: 7 },
  { id: "table", title: "표", columns: 12, type: "table", content: "{}", x: 0, y: 10, w: 12, h: 5 },
];

assert.equal(isDraftLayoutValid(validSavedLayout), true);
assert.deepEqual(restoreDraftLayout(validSavedLayout), validSavedLayout);
assert.deepEqual(restoreDraftLayout(restoreDraftLayout(validSavedLayout)), validSavedLayout);

const overlappingLegacyLayout = [
  { id: "a", title: "A", columns: 12, type: "text", content: "A", x: 0, y: 0, w: 12, h: 4 },
  { id: "b", title: "B", columns: 12, type: "table", content: "{}", x: 0, y: 2, w: 12, h: 5 },
];
assert.equal(isDraftLayoutValid(overlappingLegacyLayout), false);
const repaired = restoreDraftLayout(overlappingLegacyLayout);
assert.equal(isDraftLayoutValid(repaired), true);
assert.deepEqual(repaired.map(({ x, y, w, h }) => [x, y, w, h]), [[0, 0, 12, 4], [0, 4, 12, 5]]);

const split = placeDraftBlock([
  { id: "full", title: "전체", columns: 12, type: "table", content: "{}", x: 0, y: 0, w: 12, h: 5 },
  { id: "incoming", title: "차트", columns: 12, type: "chart", content: "{}", x: 0, y: 5, w: 12, h: 7 },
], "incoming", 6, 2);
assert.deepEqual(split.map(({ x, y, w }) => [x, y, w]), [[0, 0, 6], [6, 0, 6]]);
assert.equal(isDraftLayoutValid(split), true);

const gapless = compactDraftLayout([
  { id: "first", title: "첫째", columns: 12, type: "text", content: "A", x: 0, y: 20, w: 12, h: 4 },
  { id: "second", title: "둘째", columns: 12, type: "text", content: "B", x: 0, y: 80, w: 12, h: 4 },
]);
assert.deepEqual(gapless.map(({ y }) => y), [0, 4]);
assert.equal(isDraftLayoutValid(gapless), true);

console.log("frontend report layout tests passed");
