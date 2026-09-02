import assert from "node:assert/strict";

import {
  compactDraftLayout,
  isDraftLayoutValid,
  placeDraftBlock,
  resolveDraftLayoutCollisions,
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

const collisionOnly = resolveDraftLayoutCollisions([
  { id: "grown", title: "커진 요약", columns: 12, type: "text", content: "요약", x: 0, y: 3, w: 12, h: 8 },
  { id: "colliding", title: "충돌 표", columns: 12, type: "table", content: "{}", x: 0, y: 10, w: 12, h: 5 },
  { id: "gapped", title: "의도한 간격", columns: 12, type: "chart", content: "{}", x: 0, y: 30, w: 12, h: 7 },
], "grown");
assert.deepEqual(collisionOnly.map(({ id, y }) => [id, y]), [
  ["grown", 3],
  ["colliding", 11],
  ["gapped", 30],
]);

const independentRowHeights = compactDraftLayout([
  { id: "row-summary", title: "요약", columns: 6, type: "text", content: "요약", x: 0, y: 9, w: 6, h: 4 },
  { id: "row-chart", title: "차트", columns: 6, type: "chart", content: "{}", x: 6, y: 9, w: 6, h: 8 },
  { id: "next-row", title: "다음", columns: 12, type: "table", content: "{}", x: 0, y: 30, w: 12, h: 5 },
]);
assert.deepEqual(
  independentRowHeights.map(({ id, x, y, w, h }) => [id, x, y, w, h]),
  [
    ["row-summary", 0, 0, 6, 4],
    ["row-chart", 6, 0, 6, 8],
    ["next-row", 0, 8, 12, 5],
  ],
);
assert.equal(isDraftLayoutValid(independentRowHeights), true);

const overlappingLegacyLayout = [
  { id: "a", title: "A", columns: 12, type: "text", content: "A", x: 0, y: 0, w: 12, h: 4 },
  { id: "b", title: "B", columns: 12, type: "table", content: "{}", x: 0, y: 2, w: 12, h: 5 },
];
assert.equal(isDraftLayoutValid(overlappingLegacyLayout), false);
const repaired = restoreDraftLayout(overlappingLegacyLayout);
assert.equal(isDraftLayoutValid(repaired), true);
assert.deepEqual(repaired.map(({ x, y, w, h }) => [x, y, w, h]), [[0, 0, 12, 4], [0, 4, 12, 5]]);

const compactLegacyArtifact = restoreDraftLayout([
  { id: "legacy", title: "이전 합본", columns: 12, type: "artifact", artifactId: "artifact-1", x: 0, y: 0, w: 12, h: 1 },
  { id: "overlap", title: "본문", columns: 12, type: "text", content: "본문", x: 0, y: 0, w: 12, h: 4 },
]);
assert.equal(compactLegacyArtifact[0].h, 5, "legacy Artifact layout recovery must not recreate a 12-row empty block");

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

const intentionalHalfWidth = compactDraftLayout([
  { id: "half", title: "절반 표", columns: 6, type: "table", content: "{}", x: 0, y: 0, w: 6, h: 5 },
  { id: "full", title: "전체 표", columns: 12, type: "table", content: "{}", x: 0, y: 5, w: 12, h: 5 },
]);
assert.deepEqual(intentionalHalfWidth.map(({ x, y, w }) => [x, y, w]), [[0, 0, 6], [0, 5, 12]]);

console.log("frontend report layout tests passed");
