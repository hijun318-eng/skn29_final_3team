/** 보고서 controller를 목록·문서·A4 편집기 컴포넌트에 배선하는 얇은 화면 모듈이다. */
import { AlertTriangle, Check } from "lucide-react";
import { DndContext, DragOverlay } from "@dnd-kit/core";
import { useCallback, useMemo } from "react";

import {
  ReportCurrencyControl,
  ReportDocumentView,
  ReportEditorCanvas,
  ReportEditorToolbar,
  ReportListView,
  ReportOperationsPanel,
  ReportAssistantPanel,
  ReportPropertiesPanel,
  ReportTemplateTile,
  ReportToolPanel,
} from "../features/reports/components";
import { useReportsPageController } from "../features/reports/useReportsPageController";
import { ReportBuilderV2 } from "../features/reports/v2/ReportBuilderV2";
import { ReportPresentation } from "../features/reports/v2/ReportPresentation";

/** 보고서 controller의 상태를 목록·최종본·편집기 뷰에 배선하며 memoized 하위 경계를 유지한다. */
export function ReportsPage({ role, isAdmin, onEditorMode, theme, onToggleTheme }) {
  const page = useReportsPageController({ role, isAdmin, onEditorMode });
  const { artifacts, dnd, draft, lifecycle } = page;
  const editorCurrencyControl = useMemo(() => (
    <ReportCurrencyControl
      value={draft.reportCurrencyPolicy.displayUnit}
      onChange={draft.changeCurrencyDisplayUnit}
      disabled={!page.canEdit}
    />
  ), [draft.changeCurrencyDisplayUnit, draft.reportCurrencyPolicy.displayUnit, page.canEdit]);
  const addChartBlock = useCallback(
    (chartType) => draft.addTemplateBlock("artifact-chart", null, { chartType }),
    [draft.addTemplateBlock],
  );
  const addArtifactView = useCallback(
    (artifactId, templateId) => draft.addTemplateBlock(templateId, null, { artifactId }),
    [draft.addTemplateBlock],
  );

  if (page.view === "list") {
    return <ReportListView
      createOpen={lifecycle.createOpen}
      definitionState={lifecycle.definitionState}
      error={lifecycle.error}
      errorRef={page.errorRef}
      newContent={lifecycle.newContent}
      newTitle={lifecycle.newTitle}
      onCreate={page.createDefinition}
      onEdit={page.openEditor}
      onOpen={page.openPreview}
      onRefresh={lifecycle.loadDefinitions}
      pending={lifecycle.pending}
      query={lifecycle.query}
      setCreateOpen={lifecycle.setCreateOpen}
      setNewContent={lifecycle.setNewContent}
      setNewTitle={lifecycle.setNewTitle}
      setQuery={lifecycle.setQuery}
      setStatusFilter={lifecycle.setStatusFilter}
      statusFilter={lifecycle.statusFilter}
      visibleDefinitions={lifecycle.visibleDefinitions}
    />;
  }

  if (page.view === "document" && lifecycle.selectedDefinition) {
    return <ReportDocumentView
      error={lifecycle.error}
      errorRef={page.errorRef}
      finalDocument={lifecycle.finalDocument}
      finalDocumentState={lifecycle.finalDocumentState}
      isAdmin={page.isAdmin}
      isDirty={draft.isDirty}
      notice={lifecycle.notice}
      onApprove={page.approveDefinition}
      onLeave={page.leaveEditor}
      onOpenFinalAsset={lifecycle.openFinalAsset}
      onReloadFinalDocument={page.reloadFinalDocument}
      onReturnToEditor={page.returnToEditor}
      onRun={page.runDefinition}
      orientation={draft.reportOrientation}
      pages={page.reportPages}
      pending={lifecycle.pending}
      renderBlock={page.renderPreviewBlock}
      renderFooter={page.renderFooter}
      renderHeader={page.renderHeader}
      reportBlockCount={draft.blocks.length}
      selectedDefinition={lifecycle.selectedDefinition}
    />;
  }

  const ActiveInsertIcon = page.activeInsert?.icon;
  const toolbar = <ReportEditorToolbar
    builderV2={page.builderV2}
    currencyControl={editorCurrencyControl}
    history={draft.history}
    isAdmin={page.isAdmin}
    isDraft={page.isDraft}
    isDirty={draft.isDirty}
    onChangeOrientation={draft.changeOrientation}
    onChangeViewScale={page.changeEditorViewScale}
    onCompactLayout={draft.compactLayout}
    onLeave={page.leaveEditor}
    onPreview={page.previewEditor}
    onRedo={draft.redo}
    onRun={page.runDefinition}
    onSave={page.saveDraft}
    onToggleTools={page.toggleToolPanel}
    onToggleTheme={onToggleTheme}
    onUndo={draft.undo}
    orientation={draft.reportOrientation}
    pending={lifecycle.pending}
    reportTitle={page.reportDisplayTitle}
    saveStatus={draft.saveState}
    selectedDefinition={lifecycle.selectedDefinition}
    toolPanelOpen={page.toolPanelOpen}
    toolToggleRef={page.toolToggleRef}
    theme={theme}
    viewScale={page.editorViewScale}
  />;
  const library = page.toolPanelOpen ? <ReportToolPanel
    analysisLibraryState={artifacts.analysisLibraryState}
    artifactOptions={artifacts.artifactOptions}
    artifactSelection={artifacts.artifactSelection}
    artifactStates={artifacts.artifactStates}
    artifacts={artifacts.artifacts}
    assistantInstruction={lifecycle.assistantInstruction}
    canEdit={page.canEdit}
    evaluation={lifecycle.assistantEvaluation}
    isDraft={page.isDraft}
    onAddChart={addChartBlock}
    onAddView={addArtifactView}
    onAddTemplate={draft.addTemplateBlock}
    onAddWholeArtifact={draft.addWholeArtifact}
    onClose={page.closeToolPanel}
    onCreateAssistantDraft={page.createAssistantDraft}
    onSelectArtifact={artifacts.setArtifactSelection}
    orderedBlocks={draft.orderedBlocks}
    panelRef={page.toolPanelRef}
    pending={lifecycle.pending}
    reportTemplates={page.reportTemplates}
    selectedArtifact={page.selectedArtifact}
    selectedArtifactPeriod={page.selectedArtifact?.evidence?.period}
    selectedArtifactSource={page.selectedArtifactSource}
    selectedDefinition={lifecycle.selectedDefinition}
    selectedBlockId={draft.selectedBlockId}
    showAssistant={!page.builderV2}
    setAssistantInstruction={lifecycle.setAssistantInstruction}
    setSelectedBlockId={page.selectOutlineBlock}
    TemplateTile={ReportTemplateTile}
  /> : null;
  const workspace = <>
    {lifecycle.error && <p ref={page.errorRef} tabIndex={-1} className="report-api-state error" role="alert"><AlertTriangle size={17} />{lifecycle.error}</p>}
    {lifecycle.notice && <p className="report-api-state notion-editor-notice" role="status"><Check size={17} />{lifecycle.notice}</p>}
    <ReportEditorCanvas
      activeArtifactTitle={page.activeArtifactSource?.title}
      activeInsert={page.activeInsert}
      alignmentGuides={dnd.alignmentGuides}
      canEdit={page.canEdit}
      draggedBlockId={dnd.draggedBlockId}
      dropPosition={dnd.dropPosition}
      onAddText={page.addTextBlock}
      onRegisterCanvas={dnd.registerPageCanvas}
      orientation={draft.reportOrientation}
      orderedBlocks={draft.orderedBlocks}
      pages={page.reportPages}
      pending={lifecycle.pending}
      renderBlock={page.renderEditorBlock}
      renderFooter={page.renderFooter}
      renderHeader={page.renderHeader}
      reportTitle={page.reportDisplayTitle}
      viewScale={page.editorViewScale}
    />
    {page.isAdmin && lifecycle.selectedDefinition?.status === "approved" && <ReportOperationsPanel
      assistantTrace={lifecycle.assistantTrace}
      cadence={lifecycle.cadence}
      filteredRunCount={lifecycle.filteredRuns.length}
      onCreateSchedule={page.createSchedule}
      onLoadRuns={page.loadRuns}
      onRetryRun={page.runDefinition}
      onSelectRun={lifecycle.setSelectedRun}
      onSetScheduleEnabled={lifecycle.setScheduleEnabled}
      onShowMoreRuns={lifecycle.showMoreRuns}
      pending={lifecycle.pending}
      runQuery={lifecycle.runQuery}
      runs={lifecycle.runs}
      scheduleAt={lifecycle.scheduleAt}
      schedules={lifecycle.selectedSchedules}
      selectedRun={lifecycle.selectedRun}
      setCadence={lifecycle.setCadence}
      setRunQuery={lifecycle.setRunQuery}
      setScheduleAt={lifecycle.setScheduleAt}
      visibleRunCount={lifecycle.visibleRunCount}
      visibleRuns={lifecycle.visibleRuns}
    />}
    {lifecycle.assistantTrace && lifecycle.selectedDefinition?.status !== "approved" && <details className="card editor-advanced"><summary>초안 생성 정보</summary><p>생성 완료 · {(lifecycle.assistantTrace.duration_ms / 1000).toFixed(1)}초</p></details>}
    <p className="sr-only" aria-live="polite">{draft.editorAnnouncement}</p>
  </>;
  const properties = <ReportPropertiesPanel
    artifact={page.editorTools.primaryBlock?.artifactId ? artifacts.artifacts[page.editorTools.primaryBlock.artifactId] : null}
    canEdit={page.canEdit}
    editorTools={page.editorTools}
    onSetting={draft.setBlockSetting}
    onUpdate={draft.updateBlock}
    orientation={draft.reportOrientation}
    pageCount={page.reportPages.length}
  />;
  const assistant = <ReportAssistantPanel
    approvalRequest={["waiting_approval", "running_data_agent", "waiting_artifact", "saving_revision"].includes(lifecycle.assistantSession?.phase)
      ? lifecycle.assistantSession?.analysis_plan && {
          ...lifecycle.assistantSession.analysis_plan,
          scope: [
            lifecycle.assistantSession.analysis_plan.scope.period,
            ...lifecycle.assistantSession.analysis_plan.scope.metrics,
            ...lifecycle.assistantSession.analysis_plan.scope.dimensions,
          ].join(" · "),
        }
      : null}
    artifact={page.selectedArtifact}
    artifactTitle={page.selectedArtifactSource?.title}
    canEdit={page.canEdit}
    instruction={lifecycle.assistantInstruction}
    onInstructionChange={lifecycle.setAssistantInstruction}
    onApproveDataRequest={page.approveAssistantDataRequest}
    onApprovePatch={page.approveAssistantPatch}
    onRejectDataRequest={page.rejectAssistantDataRequest}
    onRejectPatch={page.rejectAssistantPatch}
    onRetry={lifecycle.retryAssistantSession}
    onSubmit={page.createAssistantDraft}
    patchPreview={lifecycle.assistantSession?.patch_request_id
      && ["waiting_patch_approval", "saving_revision"].includes(lifecycle.assistantSession.phase)
      ? {
          summary: lifecycle.assistantSession.patch_summary,
          operations: lifecycle.assistantSession.patch_operations,
        }
      : null}
    pending={lifecycle.pending}
    selectedBlock={page.editorTools.primaryBlock}
    trace={lifecycle.assistantTrace}
    workflowStatus={lifecycle.assistantSession?.phase || ""}
    workflowError={lifecycle.assistantSession?.error_code || ""}
    workflowRequiredAction={lifecycle.assistantSession?.required_action || "NONE"}
    workflowRetryable={Boolean(lifecycle.assistantSession?.retryable)}
  />;
  const editor = page.builderV2 ? <ReportBuilderV2
    assistant={assistant}
    canvas={workspace}
    library={library}
    libraryOpen={page.toolPanelOpen}
    onCloseLibrary={page.closeToolPanel}
    onKeyDown={page.handleEditorKeyDown}
    onPointerMove={dnd.handlePointerMove}
    orientation={draft.reportOrientation}
    pages={page.reportPages}
    presentation={<ReportPresentation
      orientation={draft.reportOrientation}
      pages={page.reportPages}
      renderBlock={page.renderPreviewBlock}
      renderFooter={page.renderFooter}
      renderHeader={page.renderHeader}
      reportTitle={page.reportDisplayTitle}
      theme={theme}
    />}
    properties={properties}
    reportTitle={page.reportDisplayTitle}
    theme={theme}
    toolbar={toolbar}
  /> : <div
    className={`enterprise-report-editor notion-report-editor ${page.toolPanelOpen ? "" : "tools-collapsed"}`}
    onPointerMoveCapture={dnd.handlePointerMove}
    onKeyDown={page.handleEditorKeyDown}
  >
    {page.toolPanelOpen && <button type="button" className="editor-tools-scrim" aria-label="블록 도구 닫기" onClick={page.closeToolPanel} />}
    {library}
    <main className="editor-workspace notion-editor-workspace">{toolbar}{workspace}</main>
  </div>;

  return <DndContext
    sensors={dnd.sensors}
    onDragStart={dnd.handleDragStart}
    onDragMove={dnd.handleDragMove}
    onDragEnd={dnd.handleDragEnd}
    onDragCancel={dnd.handleDragCancel}
    accessibility={dnd.accessibility}
  >
    {editor}
    <DragOverlay dropAnimation={{ duration: 160, easing: "ease-out" }}>
      {page.activeInsert && <div className="report-template-overlay">{ActiveInsertIcon && <ActiveInsertIcon size={16} />}<span><b>{page.activeArtifactSource?.title || page.activeInsert.title}</b><small>{page.activeArtifactView ? `${page.activeInsert.title}로 추가` : page.activeArtifactSource ? "전체 구성으로 추가" : "캔버스에 놓아 추가"}</small></span></div>}
    </DragOverlay>
  </DndContext>;
}
