import assert from "node:assert/strict";
import {
  closeReportPatchSelection,
  groupReportPatchItemsByPage,
  removeReportPatchSelection,
} from "../../app/frontend/src/features/reports/reportAssistantPatchSelection.js";

const items = [
  { index: 0, page_index: null, depends_on_indexes: [] },
  { index: 1, page_index: 2, depends_on_indexes: [] },
  { index: 2, page_index: 2, depends_on_indexes: [1] },
  { index: 3, page_index: 3, depends_on_indexes: [1, 2] },
];

assert.deepEqual(closeReportPatchSelection(items, [3]), [1, 2, 3]);
assert.deepEqual(closeReportPatchSelection(items, [0, 2]), [0, 1, 2]);
assert.deepEqual(removeReportPatchSelection(items, [0, 1, 2, 3], 1), [0]);
assert.deepEqual(removeReportPatchSelection(items, [0, 1, 2, 3], 2), [0, 1]);

assert.deepEqual(
  groupReportPatchItemsByPage([items[3], items[0], items[2], items[1]]).map((group) => ({
    key: group.key,
    indexes: group.items.map((item) => item.index),
  })),
  [
    { key: "report", indexes: [0] },
    { key: "page-2", indexes: [1, 2] },
    { key: "page-3", indexes: [3] },
  ],
);

console.log("Report Assistant dependency selection tests passed.");
