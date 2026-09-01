import assert from "node:assert/strict";
import test from "node:test";

import { computeReportAlignmentGuides, parseArtifactViewDragId } from "../../app/frontend/src/features/reports/useReportDragAndDrop.js";
import { copyReportBlocks, reportSizePresets, searchReportBlocks } from "../../app/frontend/src/features/reports/useReportEditorTools.js";

const blocks = [
  { id: "text-1", type: "text", title: "경영 요약", content: "객실 매출이 증가했습니다.", x: 0, y: 0, w: 6, h: 4 },
  { id: "chart-1", type: "chart", title: "월별 매출", content: "{\"chartType\":\"line\"}", x: 6, y: 0, w: 6, h: 8 },
];

test("report search matches titles and text bodies but does not expose settings JSON", () => {
  assert.deepEqual(searchReportBlocks(blocks, "객실").map((block) => block.id), ["text-1"]);
  assert.deepEqual(searchReportBlocks(blocks, "월별").map((block) => block.id), ["chart-1"]);
  assert.deepEqual(searchReportBlocks(blocks, "chartType"), []);
});

test("report size presets expose exactly eight snapped sizes for each orientation", () => {
  const landscape = reportSizePresets(blocks[1], "landscape");
  const portrait = reportSizePresets(blocks[1], "portrait");
  assert.equal(landscape.length, 8);
  assert.deepEqual(landscape.map((preset) => preset.index), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.equal(landscape.at(-1).width, 12);
  assert.equal(portrait[0].height, landscape[0].height + 1);
});

test("alignment guides compare 12-column edges and centers", () => {
  const guides = computeReportAlignmentGuides(
    { pageId: "page-1", x: 0, y: 8, w: 6, h: 4 },
    blocks,
    "moving",
  );
  assert.equal(guides.pageId, "page-1");
  assert.deepEqual(guides.vertical, [0, 3, 6]);
  assert.ok(guides.horizontal.includes(8));
});

test("artifact library view drag IDs preserve the selected analysis result", () => {
  assert.deepEqual(
    parseArtifactViewDragId("artifact-view:artifact-a:artifact-chart"),
    { artifactId: "artifact-a", templateId: "artifact-chart" },
  );
  assert.equal(parseArtifactViewDragId("artifact:artifact-a"), null);
  assert.equal(parseArtifactViewDragId("artifact-view::artifact-table"), null);
});

test("session copies preserve artifact lineage without sharing source arrays", () => {
  const source = [{
    id: "artifact-1", artifactId: "artifact-a", queryId: "query-a",
    artifactChecksum: "sha256:a", sourceUrns: ["urn:rooms"],
  }];
  const copied = copyReportBlocks(source);
  assert.deepEqual(copied[0], source[0]);
  assert.notEqual(copied[0], source[0]);
  assert.notEqual(copied[0].sourceUrns, source[0].sourceUrns);
});
