import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../../app/frontend/src/App.jsx", import.meta.url), "utf8");
const controller = readFileSync(new URL("../../app/frontend/src/features/reports/useReportsPageController.jsx", import.meta.url), "utf8");
const review = readFileSync(new URL("../../app/frontend/src/features/reports/reportReviewMode.js", import.meta.url), "utf8");

assert.match(app, /VITE_REPORT_REVIEW_MODE === "true"/);
assert.match(app, /REPORT_REVIEW_MODE \? \{ role: "report_admin" \} : undefined/);
assert.match(controller, /REPORT_REVIEW_LIFECYCLE_OPTIONS/);
assert.match(review, /report-review/);
assert.match(review, /async replaceDraftBlocks/);

console.log("frontend report review mode tests passed");
