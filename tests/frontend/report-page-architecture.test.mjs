import assert from "node:assert/strict";

import {
  TOP_LEVEL_REPORT_COMPONENTS,
  frontendSource,
  reportFeatureSource,
  reportSources,
} from "./report-source-contract.mjs";

assert.match(reportSources.page, /useReportsPageController\(\{ role, isAdmin, onEditorMode \}\)/);
assert.doesNotMatch(reportSources.page, /\buseState\s*\(/, "the page must delegate domain state to hooks");

for (const [componentName, path] of Object.entries(TOP_LEVEL_REPORT_COMPONENTS)) {
  const componentSource = frontendSource(path);
  assert.match(reportSources.page, new RegExp(`<${componentName}\\b`), `${componentName} must be composed by ReportsPage`);
  assert.match(
    componentSource,
    new RegExp(`export const ${componentName} = memo\\(function ${componentName}`),
    `${componentName} must isolate rerenders with React.memo`,
  );
}

for (const hook of ["useReportLifecycleState", "useReportDraftState", "useReportDragAndDrop", "useReportArtifacts"]) {
  assert.match(reportSources.controller, new RegExp(`${hook}\\(`), `${hook} must own its report domain state`);
}
for (const hookSource of [
  reportSources.controller,
  reportSources.lifecycle,
  reportSources.draftState,
  reportSources.dragAndDrop,
  reportSources.artifacts,
]) assert.match(hookSource, /useCallback\(/, "callbacks passed to memoized children must be stable");

const componentSource = Object.values(TOP_LEVEL_REPORT_COMPONENTS).map(frontendSource).join("\n");
assert.doesNotMatch(
  componentSource,
  /createAnalysisClient|createReportClient|loadFrontendDraft|saveFrontendDraft|localStorage|sessionStorage/,
  "presentational components must not own transport or browser persistence",
);
assert.doesNotMatch(reportFeatureSource, /REPORT_DIMENSION_LABELS/);
assert.doesNotMatch(
  reportSources.presentation,
  /["'](?:month|business_date|stay_date|room_revenue|total_guest_revenue|recognized_room_revenue)["']/,
  "column labels must not be a scenario-specific identifier map",
);
assert.match(reportSources.presentation, /artifactMetric\(artifact, column\)\?\.label/);
assert.match(reportSources.presentation, /humanizeColumnIdentifier\(column\)/);

console.log("frontend report page architecture tests passed");
