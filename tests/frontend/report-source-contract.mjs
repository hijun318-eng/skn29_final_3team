import { readFileSync } from "node:fs";

export const frontendSource = (path) => readFileSync(
  new URL(`../../app/frontend/src/${path}`, import.meta.url),
  "utf8",
);

export const TOP_LEVEL_REPORT_COMPONENTS = Object.freeze({
  ReportListView: "features/reports/components/ReportListView.jsx",
  ReportDocumentView: "features/reports/components/ReportDocumentView.jsx",
  ReportEditorToolbar: "features/reports/components/ReportEditorToolbar.jsx",
  ReportToolPanel: "features/reports/components/ReportToolPanel.jsx",
  ReportEditorCanvas: "features/reports/components/ReportEditorCanvas.jsx",
  ReportOperationsPanel: "features/reports/components/ReportOperationsPanel.jsx",
});

export const reportSources = Object.freeze({
  page: frontendSource("pages/ReportsPage.jsx"),
  controller: frontendSource("features/reports/useReportsPageController.jsx"),
  lifecycle: frontendSource("features/reports/useReportLifecycleState.ts"),
  finalDocument: frontendSource("features/reports/useFinalReportDocument.ts"),
  reportClient: frontendSource("api/reportClient.ts"),
  draftState: frontendSource("features/reports/useReportDraftState.ts"),
  draftMutations: frontendSource("features/reports/reportDraftMutations.ts"),
  dragAndDrop: frontendSource("features/reports/useReportDragAndDrop.js"),
  artifacts: frontendSource("features/reports/useReportArtifacts.ts"),
  presentation: frontendSource("features/reports/components/reportPresentation.js"),
  controllerSupport: frontendSource("features/reports/reportPageControllerSupport.js"),
  evidence: frontendSource("features/reports/reportArtifactEvidence.ts"),
  tableRows: frontendSource("features/reports/reportTableRows.js"),
  artifactContent: frontendSource("features/reports/components/ReportArtifactContent.jsx"),
  blockControls: frontendSource("features/reports/components/ReportBlockControls.jsx"),
  markdownEditor: frontendSource("features/reports/components/MarkdownBlockEditor.jsx"),
  editorBlock: frontendSource("features/reports/components/ReportEditorBlock.jsx"),
  listView: frontendSource(TOP_LEVEL_REPORT_COMPONENTS.ReportListView),
  documentView: frontendSource(TOP_LEVEL_REPORT_COMPONENTS.ReportDocumentView),
  editorToolbar: frontendSource(TOP_LEVEL_REPORT_COMPONENTS.ReportEditorToolbar),
  toolPanel: frontendSource(TOP_LEVEL_REPORT_COMPONENTS.ReportToolPanel),
  editorCanvas: frontendSource(TOP_LEVEL_REPORT_COMPONENTS.ReportEditorCanvas),
  operationsPanel: frontendSource(TOP_LEVEL_REPORT_COMPONENTS.ReportOperationsPanel),
});

export const reportFeatureSource = Object.values(reportSources).join("\n");

export function sourceSection(source, start, end) {
  const startIndex = source.indexOf(start);
  const endIndex = source.indexOf(end, startIndex + start.length);
  if (startIndex < 0 || endIndex < 0) {
    throw new Error(`Source section not found: ${start} -> ${end}`);
  }
  return source.slice(startIndex, endIndex);
}
