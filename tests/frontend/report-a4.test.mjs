import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(
  new URL("../../app/frontend/src/features/reports/ReportPageCanvas.jsx", import.meta.url),
  "utf8",
);
const styles = readFileSync(
  new URL("../../app/frontend/src/features/reports/report-a4.css", import.meta.url),
  "utf8",
);

assert.match(component, /import "\.\/report-a4\.css"/);
assert.match(component, /new ResizeObserver\(resize\)/);
assert.match(component, /pages\.map\(\(page, pageIndex\)/);
assert.match(component, /renderBlock\(block, \{ \.\.\.context, blockIndex \}\)/);
assert.match(component, /role="region"/);
assert.match(component, /aria-label=\{pageLabel\}/);
assert.match(component, /data-report-mode=\{mode\}/);
assert.match(component, /data-report-editor-chrome="true"/);
assert.match(component, /getGridRef\?\.\(element, context\)/);
assert.match(component, /renderGridOverlay\?\.\(context\)/);
assert.match(component, /gridColumn: `\$\{column \+ 1\} \/ span \$\{width\}`/);
assert.match(component, /gridRow: `\$\{row \+ 1\} \/ span \$\{height\}`/);

assert.match(styles, /\.answer-report-page--portrait\s*\{[\s\S]*inline-size: 210mm;[\s\S]*block-size: 297mm;/);
assert.match(styles, /\.answer-report-page--landscape\s*\{[\s\S]*inline-size: 297mm;[\s\S]*block-size: 210mm;/);
assert.match(styles, /grid-template-columns: repeat\(12, minmax\(0, 1fr\)\)/);
assert.match(styles, /color-scheme: light/);
assert.match(styles, /\.ppt-theme \.answer-report-page \.report-table-sort\s*\{[\s\S]*background: transparent !important/);
assert.match(styles, /\.ppt-theme \.answer-report-page \.report-table-sort > span\s*\{[\s\S]*color: #253b59 !important/);
assert.match(styles, /\.ppt-theme \.answer-report-page \.generated-report-copy[\s\S]*color: #33465f !important/);
assert.match(styles, /overflow-x: clip/);
assert.match(styles, /@page answer-report-portrait\s*\{[\s\S]*size: A4 portrait/);
assert.match(styles, /@page answer-report-landscape\s*\{[\s\S]*size: A4 landscape/);
assert.match(styles, /@media print\s*\{/);
assert.match(styles, /\[data-report-editor-chrome="true"\][\s\S]*display: none !important/);
assert.match(styles, /break-after: page/);
assert.match(styles, /break-inside: avoid/);
assert.doesNotMatch(styles, /@media\s*\(max-width:/);

console.log("frontend A4 report canvas tests passed");
