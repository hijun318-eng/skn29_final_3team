import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

function source(relativePath) {
  return readFileSync(new URL(`../../${relativePath}`, import.meta.url), "utf8");
}

const app = source("app/frontend/src/App.jsx");
const flags = source("app/frontend/src/features/reports/reportBuilderFlags.js");
const controller = source("app/frontend/src/features/reports/useReportsPageController.jsx");
const page = source("app/frontend/src/pages/ReportsPage.jsx");
const toolbar = source("app/frontend/src/features/reports/components/ReportEditorToolbar.jsx");
const toolPanel = source("app/frontend/src/features/reports/components/ReportToolPanel.jsx");
const builder = source("app/frontend/src/features/reports/v2/ReportBuilderV2.jsx");
const builderStyles = source("app/frontend/src/features/reports/v2/report-builder-v2.css");
const canvas = source("app/frontend/src/features/reports/ReportPageCanvas.jsx");
const normalization = source("app/frontend/src/contracts/reportNormalization.ts");

assert.match(flags, /VITE_REPORT_BUILDER_V2 === "true"/);
assert.match(app, /reportEditorMode && REPORT_BUILDER_V2 \? "report-builder-v2-mode"/);
assert.match(controller, /REPORT_REVIEW_MODE \|\| !REPORT_BUILDER_V2/);
assert.match(controller, /void openEditor\(reviewDefinition\)/);
assert.match(page, /page\.builderV2 \? <ReportBuilderV2/);
assert.match(builder, /data-report-builder="v2"/);
assert.match(builder, /report-builder-v2-layout/);
assert.match(builder, /builder-library-column/);
assert.match(builder, /builder-workspace/);
assert.match(builder, /requestFullscreen/);
assert.match(builder, /pages\.map/);
assert.match(builderStyles, /\[data-report-builder="v2"\] \.report-builder-v2-layout/);
assert.match(builderStyles, /grid-template-columns:var\(--builder-library\) minmax\(620px,1fr\) var\(--builder-properties\)/);
assert.match(builderStyles, /@media\(max-width:1179px\)/);
assert.match(builderStyles, /@media\(max-width:900px\)/);
assert.match(builderStyles, /\.answer-report-canvas--editor\{padding:0/);
assert.match(builderStyles, /\.answer-report-page__block:has\(>\.selected\)/);
assert.match(builderStyles, /\.notion-block>\.report-block-chrome/);
assert.doesNotMatch(builderStyles, /^\.notion-report-editor/m);
assert.match(canvas, /data-report-page-index=\{pageIndex\}/);
assert.match(page, /draft\.addTemplateBlock\("artifact-chart", null, \{ chartType \}\)/);
assert.match(toolbar, /보고서 확대 축소/);
assert.match(toolbar, /builderV2 \? "Preview" : "HTML 초안 확인"/);
assert.match(toolPanel, /REPORT ELEMENTS/);
assert.match(toolPanel, /보고서 블록 검색/);
assert.match(toolPanel, /REPORT_CHART_OPTIONS\.map/);
assert.match(normalization, /artifact_id: block\.artifactId/);
assert.match(normalization, /query_id: block\.queryId/);
assert.doesNotMatch(normalization, /locked|selectedBlockIds|snapshots|clipboard|zoom/);

console.log("frontend Report Builder V2 shell tests passed");
