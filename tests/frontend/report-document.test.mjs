import assert from "node:assert/strict";

import {
  A4_PAGE_LAYOUT,
  REPORT_DOCUMENT_SCHEMA_VERSION,
  compactReportDocument,
  createReportDocument,
  deleteReportBlock,
  insertArtifactBlock,
  moveReportBlock,
  parseReportDocument,
  serializeReportDocument,
  setReportOrientation,
  validateReportDocument,
} from "../../app/frontend/src/features/reports/reportDocument.ts";

function insert(document, id, options = {}) {
  const result = insertArtifactBlock(document, {
    blockId: id,
    title: `${id} 성과 분석`,
    artifactRef: { artifactId: `artifact-${id}`, version: 2, checksum: `sha256:${id}` },
    presentationMode: options.mode ?? "standard",
    visibleViews: options.visibleViews ?? ["summary", "kpi", "charts", "table"],
    width: options.width,
    height: options.height,
    placement: options.placement,
  });
  assert.equal(result.ok, true, result.errors?.join("; "));
  return result.document;
}

function assertNoOverlap(document) {
  for (const page of document.pages) {
    for (let left = 0; left < page.blocks.length; left += 1) {
      for (let right = left + 1; right < page.blocks.length; right += 1) {
        const a = page.blocks[left];
        const b = page.blocks[right];
        assert.equal(a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y, false);
      }
    }
  }
}

let document = createReportDocument({
  id: "report-july-sales",
  title: "7월 영업 실적 보고서",
  currencyPolicy: { displayUnit: "hundredMillion", unitPlacement: "header" },
});
assert.equal(document.schemaVersion, REPORT_DOCUMENT_SCHEMA_VERSION);
assert.deepEqual(A4_PAGE_LAYOUT.portrait, { widthMm: 210, heightMm: 297, contentRows: 30 });
assert.deepEqual(A4_PAGE_LAYOUT.landscape, { widthMm: 297, heightMm: 210, contentRows: 18 });
assert.equal(validateReportDocument(document).valid, true);

const halfWidth = insert(createReportDocument({ id: "half-width", title: "단일 보기" }), "single-chart", {
  width: 6, height: 9, visibleViews: ["chart"],
});
assert.deepEqual(halfWidth.pages[0].blocks.map(({ w, h }) => [w, h]), [[6, 9]]);

const independentDocumentRows = createReportDocument({ id: "independent-rows", title: "독립 높이" });
independentDocumentRows.pages[0].blocks = [
  { id: "short", kind: "markdown", title: "짧은 요약", markdown: "요약", x: 0, y: 0, w: 6, h: 4 },
  { id: "tall", kind: "markdown", title: "긴 설명", markdown: "설명", x: 6, y: 0, w: 6, h: 7 },
  { id: "following", kind: "markdown", title: "다음 행", markdown: "다음", x: 0, y: 7, w: 12, h: 5 },
];
const compactIndependentRows = compactReportDocument(independentDocumentRows);
assert.equal(compactIndependentRows.ok, true);
assert.deepEqual(
  compactIndependentRows.document.pages[0].blocks.map(({ id, x, y, w, h }) => [id, x, y, w, h]),
  [
    ["short", 0, 0, 6, 4],
    ["tall", 6, 0, 6, 7],
    ["following", 0, 7, 12, 5],
  ],
);
assertNoOverlap(compactIndependentRows.document);

const beforeInvalidWidth = JSON.stringify(halfWidth);
const invalidWidth = insertArtifactBlock(halfWidth, {
  blockId: "invalid-width",
  title: "잘못된 너비",
  artifactRef: { artifactId: "artifact-invalid-width" },
  visibleViews: ["chart"],
  width: 7,
});
assert.equal(invalidWidth.ok, false);
assert.equal(JSON.stringify(halfWidth), beforeInvalidWidth);

document = insert(document, "revenue");
document = insert(document, "channel", {
  placement: { type: "side", targetBlockId: "revenue", edge: "right" },
});
assert.deepEqual(
  document.pages[0].blocks.map(({ id, x, y, w, h }) => [id, x, y, w, h]),
  [
    ["revenue", 0, 0, 6, 12],
    ["channel", 6, 0, 6, 12],
  ],
);
assertNoOverlap(document);

const beforeInvalidSide = JSON.stringify(document);
const invalidSide = insertArtifactBlock(document, {
  blockId: "invalid-side",
  title: "잘못된 옆 배치",
  artifactRef: { artifactId: "artifact-invalid" },
  visibleViews: ["summary"],
  placement: { type: "side", targetBlockId: "revenue", edge: "left" },
});
assert.equal(invalidSide.ok, false);
assert.equal(invalidSide.document, document);
assert.equal(JSON.stringify(document), beforeInvalidSide);

const deleted = deleteReportBlock(document, "channel");
assert.equal(deleted.ok, true);
assert.deepEqual(deleted.document.pages[0].blocks.map(({ id, x, y, w }) => [id, x, y, w]), [["revenue", 0, 0, 12]]);
document = deleted.document;

document = insert(document, "occupancy", { mode: "detail" });
document = insert(document, "adr", { mode: "detail" });
document = insert(document, "revpar", { mode: "detail" });
assert.equal(document.pages.length, 3);
assert.deepEqual(document.pages.map(({ id, index }) => [id, index]), [
  ["report-july-sales:page:1", 0],
  ["report-july-sales:page:2", 1],
  ["report-july-sales:page:3", 2],
]);

const landscape = setReportOrientation(document, "landscape");
assert.equal(landscape.ok, true);
assert.equal(landscape.document.pages.every((page) => page.orientation === "landscape" && page.size === "A4"), true);
assert.equal(landscape.document.pages[0].id, document.pages[0].id);
assertNoOverlap(landscape.document);

const moved = moveReportBlock(landscape.document, "revpar", { type: "before", targetBlockId: "revenue" });
assert.equal(moved.ok, true);
assert.equal(moved.document.pages[0].blocks[0].id, "revpar");
assertNoOverlap(moved.document);

const unchangedJson = JSON.stringify(moved.document);
const invalidMove = moveReportBlock(moved.document, "missing", { type: "end" });
assert.equal(invalidMove.ok, false);
assert.equal(invalidMove.document, moved.document);
assert.equal(JSON.stringify(moved.document), unchangedJson);

let pageEndFixture = createReportDocument({ id: "page-end-fixture", title: "페이지 이동 검증", orientation: "landscape" });
pageEndFixture = insert(pageEndFixture, "first", { mode: "summary" });
pageEndFixture = insert(pageEndFixture, "second", { mode: "summary" });
pageEndFixture = insert(pageEndFixture, "third", { mode: "summary" });
const movedToFirstPageEnd = moveReportBlock(pageEndFixture, "first", {
  type: "end",
  pageId: pageEndFixture.pages[0].id,
});
assert.equal(movedToFirstPageEnd.ok, true);
assert.deepEqual(movedToFirstPageEnd.document.pages[0].blocks.map((block) => block.id), ["second", "first"]);
assertNoOverlap(movedToFirstPageEnd.document);

const gapSource = insert(createReportDocument({ id: "gap-fixture", title: "간격 검증 보고서" }), "gap-block");
const withGap = structuredClone(gapSource);
withGap.pages[0].blocks[0].y = 4;
assert.equal(validateReportDocument(withGap).valid, true);
const compacted = compactReportDocument(withGap);
assert.equal(compacted.ok, true);
assert.equal(compacted.document.pages[0].blocks[0].y, 0);
assertNoOverlap(compacted.document);

const pageBreakFixture = createReportDocument({ id: "page-break-fixture", title: "월간 영업 보고서" });
pageBreakFixture.pages[0].blocks = [
  {
    id: "intro",
    kind: "markdown",
    title: "핵심 요약",
    markdown: "## 핵심 요약\n매출과 점유율을 함께 검토합니다.",
    x: 0,
    y: 0,
    w: 12,
    h: 4,
  },
  { id: "manual-break", kind: "pageBreak", title: "새 페이지", x: 0, y: 4, w: 12, h: 1 },
  {
    id: "detail",
    kind: "markdown",
    title: "상세 분석",
    markdown: "상세 분석 본문",
    x: 0,
    y: 5,
    w: 12,
    h: 6,
  },
];
const pageBreakCompacted = compactReportDocument(pageBreakFixture);
assert.equal(pageBreakCompacted.ok, true);
assert.equal(pageBreakCompacted.document.pages.length, 2);
assert.deepEqual(pageBreakCompacted.document.pages.map((page) => page.blocks.map((block) => block.id)), [
  ["intro", "manual-break"],
  ["detail"],
]);

const serialized = serializeReportDocument(pageBreakCompacted.document);
const parsed = parseReportDocument(serialized);
assert.equal(parsed.ok, true);
assert.equal(serializeReportDocument(parsed.document), serialized);
assert.deepEqual(compactReportDocument(parsed.document).document, parsed.document);

const overlapping = structuredClone(pageBreakFixture);
overlapping.pages[0].blocks[1] = {
  id: "overlap",
  kind: "markdown",
  title: "겹침",
  markdown: "겹침",
  x: 0,
  y: 2,
  w: 12,
  h: 3,
};
const overlapValidation = validateReportDocument(overlapping);
assert.equal(overlapValidation.valid, false);
assert.equal(overlapValidation.errors.some((error) => error.includes("overlap")), true);

assert.deepEqual(parseReportDocument("not-json"), { ok: false, errors: ["document is not valid JSON"] });

console.log("frontend report document tests passed");
