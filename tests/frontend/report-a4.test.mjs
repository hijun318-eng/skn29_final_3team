import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (path) => readFileSync(
  new URL(`../../app/frontend/src/features/reports/${path}`, import.meta.url),
  "utf8",
);

const component = source("ReportPageCanvas.jsx");
const styleFiles = [
  "report-a4-paper.css",
  "report-a4-content.css",
  "report-a4-artifact.css",
  "report-a4-print.css",
];
const styleSources = Object.fromEntries(styleFiles.map((file) => [file, source(file)]));
const styles = styleFiles.map((file) => styleSources[file]).join("\n");

assert.match(component, /import "\.\/report-a4-paper\.css";\s*import "\.\/report-a4-content\.css";\s*import "\.\/report-a4-artifact\.css";\s*import "\.\/report-a4-print\.css";/);
assert.match(styleSources["report-a4-artifact.css"], /\.notion-block:has\(> \.report-whole-artifact > \.report-whole-artifact-kpis\.is-comparison\) > \.notion-block-title--readonly\s*\{[\s\S]*margin-block-end: 3mm;/);
assert.doesNotMatch(component, /report-a4\.css/);
assert.match(component, /new ResizeObserver\(resize\)/);
assert.match(component, /pages\.map\(\(page, pageIndex\)/);
assert.match(component, /renderBlock\(block, \{ \.\.\.context, blockIndex \}\)/);
assert.match(component, /role="region"/);
assert.match(component, /aria-label=\{pageLabel\}/);
assert.match(component, /data-report-mode=\{mode\}/);
assert.match(component, /mode === "presentation"/);
assert.match(component, /pageCountOverride/);
assert.match(component, /aria-label=\{`\$\{pageNumber\}\/\$\{resolvedPageCount\}페이지`\}/);
assert.doesNotMatch(component, /answer-report-page-chrome/);
assert.match(component, /getGridRef\?\.\(element, context\)/);
assert.match(component, /renderGridOverlay\?\.\(context\)/);
assert.match(component, /gridColumn: `\$\{column \+ 1\} \/ span \$\{width\}`/);
assert.match(component, /gridRow: `\$\{row \+ 1\} \/ span \$\{height\}`/);

assert.match(styleSources["report-a4-paper.css"], /\.answer-report-page--portrait\s*\{[\s\S]*inline-size: 210mm;[\s\S]*block-size: 297mm;/);
assert.match(styleSources["report-a4-paper.css"], /\.answer-report-page--landscape\s*\{[\s\S]*inline-size: 297mm;[\s\S]*block-size: 210mm;/);
assert.match(styleSources["report-a4-paper.css"], /grid-template-columns: repeat\(12, minmax\(0, 1fr\)\)/);
assert.match(styleSources["report-a4-paper.css"], /color-scheme: light/);
assert.match(styleSources["report-a4-content.css"], /\.ppt-theme \.answer-report-page \.report-table-sort\s*\{[\s\S]*background: transparent !important/);
assert.match(styleSources["report-a4-content.css"], /\.ppt-theme \.answer-report-page \.report-table-sort > span\s*\{[\s\S]*color: #253b59 !important/);
assert.match(styleSources["report-a4-content.css"], /\.ppt-theme \.answer-report-page \.generated-report-copy[\s\S]*color: #33465f !important/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page__block > \.notion-block\s*\{[\s\S]*min-inline-size: 0;[\s\S]*display: flex;[\s\S]*flex-direction: column;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.notion-data-embed\s*\{[\s\S]*min-inline-size: 0;[\s\S]*min-block-size: 0;[\s\S]*flex: 1;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.notion-data-embed:has\(> \.generated-report-table\)\s*\{[\s\S]*overflow: hidden;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.generated-report-table table\s*\{[\s\S]*inline-size: 100%;[\s\S]*table-layout: fixed;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.generated-report-table th,[\s\S]*text-overflow: ellipsis;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.generated-report-table thead th\s*\{[\s\S]*background: #eef3f8 !important;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.generated-report-table \.report-table-sort-label\s*\{[\s\S]*display: inline-flex;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.generated-report-table \.analysis-column-unit\s*\{[\s\S]*display: inline-flex;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.generated-report-table th\.is-numeric \.report-table-sort\s*\{[\s\S]*justify-content: flex-end;/);
assert.match(styleSources["report-a4-content.css"], /\.answer-report-page \.markdown-copy table\s*\{[\s\S]*table-layout: fixed;/);
assert.match(styles, /overflow-x: clip/);

const print = styleSources["report-a4-print.css"];
assert.match(print, /@page answer-report-portrait\s*\{[\s\S]*size: A4 portrait/);
assert.match(print, /@page answer-report-landscape\s*\{[\s\S]*size: A4 landscape/);
assert.match(print, /@media print\s*\{/);
assert.match(print, /body:has\(\[data-report-render-root\^="screen-"\] \.answer-report-canvas\[data-report-mode\]\)[\s\S]*#root/);
assert.match(print, /\.answer-report-page\s*\{[\s\S]*overflow: hidden;[\s\S]*break-after: page/);
assert.match(print, /\.answer-report-canvas\[data-report-mode\] \.answer-report-page__grid,[\s\S]*\.report-whole-artifact-views > section,[\s\S]*\.analysis-table\s*\{\s*overflow: visible !important/);
assert.match(print, /\.analysis-table table\s*\{[\s\S]*table-layout: fixed !important/);
assert.match(print, /\.analysis-table td\s*\{[\s\S]*white-space: normal !important/);
assert.match(print, /\[data-report-editor-chrome="true"\][\s\S]*display: none !important/);
assert.match(print, /break-inside: avoid/);
assert.doesNotMatch(styles, /@media\s*\(max-width:/);

console.log("frontend A4 report canvas tests passed");
