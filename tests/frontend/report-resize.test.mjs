import assert from "node:assert/strict";

import { resizeReportFrame } from "../../app/frontend/src/features/reports/reportResizeGeometry.ts";

const frame = { x: 2, y: 3, w: 6, h: 6 };
const limits = { minimumWidth: 4, minimumHeight: 4, maximumHeight: 14 };

assert.deepEqual(resizeReportFrame(frame, "n", 0, -2, limits), { x: 2, y: 1, w: 6, h: 8 });
assert.deepEqual(resizeReportFrame(frame, "s", 0, 2, limits), { x: 2, y: 3, w: 6, h: 8 });
assert.deepEqual(resizeReportFrame(frame, "w", -2, 0, limits), { x: 0, y: 3, w: 8, h: 6 });
assert.deepEqual(resizeReportFrame(frame, "e", 2, 0, limits), { x: 2, y: 3, w: 8, h: 6 });
assert.deepEqual(resizeReportFrame(frame, "nw", -2, -2, limits), { x: 0, y: 1, w: 8, h: 8 });
assert.deepEqual(resizeReportFrame(frame, "ne", 2, -2, limits), { x: 2, y: 1, w: 8, h: 8 });
assert.deepEqual(resizeReportFrame(frame, "sw", -2, 2, limits), { x: 0, y: 3, w: 8, h: 8 });
assert.deepEqual(resizeReportFrame(frame, "se", 2, 2, limits), { x: 2, y: 3, w: 8, h: 8 });

assert.deepEqual(resizeReportFrame(frame, "n", 0, 99, limits), { x: 2, y: 5, w: 6, h: 4 });
assert.deepEqual(resizeReportFrame(frame, "w", 99, 0, limits), { x: 4, y: 3, w: 4, h: 6 });
assert.deepEqual(resizeReportFrame(frame, "e", 99, 0, limits), { x: 2, y: 3, w: 10, h: 6 });

console.log("frontend report resize geometry tests passed");
