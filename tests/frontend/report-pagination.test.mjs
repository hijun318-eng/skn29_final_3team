import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const server = await createServer({
  appType: "custom",
  cacheDir: "node_modules/.vite-report-pagination-test",
  logLevel: "error",
  root: frontendRoot,
  server: { middlewareMode: true, hmr: false },
});
const { paginateReportBlocks } = await server.ssrLoadModule(
  "/src/features/reports/components/reportPresentation.js",
);
after(() => server.close());

function assertNoOverlap(pages) {
  for (const page of pages) {
    for (let leftIndex = 0; leftIndex < page.blocks.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < page.blocks.length; rightIndex += 1) {
        const left = page.blocks[leftIndex];
        const right = page.blocks[rightIndex];
        const overlaps = left.x < right.x + right.w
          && left.x + left.w > right.x
          && left.y < right.y + right.h
          && left.y + left.h > right.y;
        assert.equal(overlaps, false, `${left.id} and ${right.id} must not overlap`);
      }
    }
  }
}

test("production paginator applies portrait and landscape row limits deterministically", () => {
  const blocks = [
    { id: "third", type: "text", x: 0, y: 20, w: 12, h: 10 },
    { id: "first-left", type: "text", x: 0, y: 0, w: 6, h: 8 },
    { id: "second", type: "text", x: 0, y: 10, w: 12, h: 10 },
    { id: "first-right", type: "text", x: 6, y: 0, w: 6, h: 10 },
  ];

  const portrait = paginateReportBlocks(blocks, "portrait", "monthly");
  const landscape = paginateReportBlocks(blocks, "landscape", "monthly");

  assert.equal(portrait.length, 1);
  assert.deepEqual(portrait[0].blocks.map(({ id, y, h }) => [id, y, h]), [
    ["first-left", 0, 10],
    ["first-right", 0, 10],
    ["second", 10, 10],
    ["third", 20, 10],
  ]);
  assert.deepEqual(landscape.map((page) => page.blocks.map(({ id }) => id)), [
    ["first-left", "first-right"],
    ["second"],
    ["third"],
  ]);
  assert.deepEqual(landscape.map(({ id, index }) => [id, index]), [
    ["monthly:page:1", 0],
    ["monthly:page:2", 1],
    ["monthly:page:3", 2],
  ]);
  assertNoOverlap(portrait);
  assertNoOverlap(landscape);
});

test("production paginator preserves stable visual order and explicit page breaks", () => {
  const blocks = [
    { id: "same-position-a", type: "text", x: 0, y: 0, w: 6, h: 4 },
    { id: "same-position-b", type: "text", x: 6, y: 0, w: 6, h: 4 },
    { id: "before-break", type: "text", x: 0, y: 5, w: 12, h: 4 },
    { id: "page-break", type: "page_break", x: 0, y: 9, w: 12, h: 1 },
    { id: "after-break", type: "text", x: 0, y: 10, w: 12, h: 5 },
  ];

  const first = paginateReportBlocks(blocks, "landscape", "stable");
  const second = paginateReportBlocks(structuredClone(blocks), "landscape", "stable");

  assert.deepEqual(first, second);
  assert.deepEqual(first.map((page) => page.blocks.map(({ id }) => id)), [
    ["same-position-a", "same-position-b", "before-break"],
    ["after-break"],
  ]);
  assert.deepEqual(first[1].blocks.map(({ y, h }) => [y, h]), [[0, 5]]);
  assertNoOverlap(first);
});
