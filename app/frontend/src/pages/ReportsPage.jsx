/** 보고서 controller를 목록·문서·A4 편집기 컴포넌트에 배선하는 얇은 화면 모듈이다. */
import { AlertTriangle, Check, Layers3 } from "lucide-react";
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
  const documentCurrencyControl = useMemo(() => (
    <ReportCurrencyControl
      value={draft.reportCurrencyPolicy.displayUnit}
      onChange={draft.changeCurrencyDisplayUnit}
      disabled
    />
  ), [draft.changeCurrencyDisplayUnit, draft.reportCurrencyPolicy.displayUnit]);
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
      definitionCollection={lifecycle.definitionCollection}
      definitionState={lifecycle.definitionState}
      error={lifecycle.error}
      errorRef={page.errorRef}
      newContent={lifecycle.newContent}
      newTitle={lifecycle.newTitle}
      notice={lifecycle.notice}
      onArchive={lifecycle.archiveDefinition}
      onCollectionChange={lifecycle.setDefinitionCollection}
      onCreate={page.createDefinition}
      onEdit={page.openEditor}
      onOpen={page.openPreview}
      onPermanentDelete={lifecycle.permanentlyDeleteDefinition}
      onRefresh={lifecycle.loadDefinitions}
      onRestore={lifecycle.restoreDefinition}
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
      presentation={<ReportPresentation
        orientation={draft.reportOrientation}
        pages={page.reportPages}
        renderBlock={page.renderPreviewBlock}
        renderFooter={page.renderFooter}
        renderHeader={page.renderHeader}
        reportTitle={lifecycle.selectedDefinition?.title}
        theme={theme}
      />}
      renderBlock={page.renderPreviewBlock}
      renderFooter={page.renderFooter}
      renderHeader={page.renderHeader}
      reportBlockCount={draft.blocks.length}
      selectedDefinition={lifecycle.selectedDefinition}
    />;
  }

  const ActiveInsertIcon = page.activeInsert?.icon;
  const activeDraggedBlock = page.activeInsert
    ? null
    : draft.orderedBlocks.find((block) => block.id === dnd.draggedBlockId);
  const draggedBlockCount = dnd.draggedBlockIds.size;
  const dragPlacementClass = dnd.dragDelta
    ? dnd.dropPosition ? "is-valid" : "is-invalid"
    : "";
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
    onReportTitleChange={draft.updateReportTitle}
    onReportTitleCommit={draft.commitReportTitle}
    onRun={page.runDefinition}
    onSave={page.saveDraft}
    onToggleTools={page.toggleToolPanel}
    onToggleTheme={onToggleTheme}
    onUndo={draft.undo}
    orientation={draft.reportOrientation}
    pending={lifecycle.pending}
    reportTitle={draft.reportTitle}
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
    artifactTemplates={page.artifactTemplates}
    artifacts={artifacts.artifacts}
    assistantInstruction={lifecycle.assistantInstruction}
    canEdit={page.canEdit}
    evaluation={lifecycle.assistantEvaluation}
    isDraft={page.isDraft}
    onAddChart={addChartBlock}
    onAddView={addArtifactView}
    onAddTemplate={draft.addTemplateBlock}
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
    {lifecycle.error && <p ref={page.errorRef} tabIndex={-1} className="report-api-state report-notice-shell error" role="alert"><AlertTriangle size={17} />{lifecycle.error}</p>}
    {lifecycle.notice && <p className="report-api-state report-notice-shell notion-editor-notice" role="status"><Check size={17} />{lifecycle.notice}</p>}
    <ReportEditorCanvas
      activeArtifactTitle={page.activeArtifactSource ? `${page.activeArtifactSource.title} · ${page.activeInsert?.title}` : undefined}
      activeInsert={page.activeInsert}
      alignmentGuides={dnd.alignmentGuides}
      canEdit={page.canEdit}
      draggedBlockId={dnd.draggedBlockId}
      dropPosition={dnd.dropPosition}
      onAddText={page.addTextBlock}
      onRegisterCanvas={dnd.registerPageCanvas}
      onSelectBlocks={page.editorTools.selectBlocks}
      orientation={draft.reportOrientation}
      orderedBlocks={draft.orderedBlocks}
      pages={page.reportPages}
      pending={lifecycle.pending}
      renderBlock={page.renderEditorBlock}
      renderFooter={page.renderFooter}
      renderHeader={page.renderHeader}
      reportTitle={draft.reportTitle}
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
    key={`${lifecycle.selectedDefinition?.definitionId || ""}:${lifecycle.selectedDefinition?.version || ""}:${page.assistantArtifactIds.join(":")}:${lifecycle.assistantSession?.assistant_request_id || ""}`}
    approvalRequest={["waiting_approval", "running_data_agent", "waiting_artifact"].includes(lifecycle.assistantSession?.phase)
      ? lifecycle.assistantSession?.analysis_plan && {
          ...lifecycle.assistantSession.analysis_plan,
          scope: [
            lifecycle.assistantSession.analysis_plan.scope.period,
            ...lifecycle.assistantSession.analysis_plan.scope.metrics,
            ...lifecycle.assistantSession.analysis_plan.scope.dimensions,
          ].join(" · "),
        }
      : null}
    artifact={page.assistantArtifact}
    artifactOptions={page.assistantArtifactOptions}
    assistantArtifactIds={page.assistantArtifactIds}
    artifactTitle={page.assistantArtifactSource?.title}
    canEdit={page.canEdit}
    externalTransferDisclosure={lifecycle.assistantExternalTransferDisclosure}
    externalTransferConsentPending={lifecycle.assistantExternalTransferConsentPending}
    hasUnsavedChanges={draft.isDirty}
    instruction={lifecycle.assistantInstruction}
    onInstructionChange={lifecycle.setAssistantInstruction}
    onApproveDataRequest={page.approveAssistantDataRequest}
    onApprovePatch={page.approveAssistantPatch}
    onAcceptExternalTransfer={lifecycle.acceptAssistantExternalTransferConsent}
    onCancel={lifecycle.cancelAssistantSession}
    onDeclineExternalTransfer={lifecycle.declineAssistantExternalTransferConsent}
    onRejectDataRequest={page.rejectAssistantDataRequest}
    onRejectPatch={page.rejectAssistantPatch}
    onReview={page.reviewAssistantReport}
    onSelectArtifacts={page.setAssistantArtifacts}
    onSuggestTitle={page.suggestAssistantTitle}
    onRetry={lifecycle.retryAssistantSession}
    onSubmit={page.createAssistantDraft}
    patchPreview={lifecycle.assistantSession?.patch_request_id
      && ["waiting_patch_approval", "saving_revision"].includes(lifecycle.assistantSession.phase)
      ? {
          requestId: lifecycle.assistantSession.patch_request_id,
          summary: lifecycle.assistantSession.patch_summary,
          operations: lifecycle.assistantSession.patch_operations,
          evidenceRefs: lifecycle.assistantSession.patch_evidence_refs,
          items: lifecycle.assistantSession.patch_preview,
          approvedIndexes: lifecycle.assistantSession.approved_operation_indexes,
          exactPageCount: lifecycle.assistantSession.exact_page_count,
          verifiedPageCount: lifecycle.assistantSession.verified_page_count,
        }
      : null}
    review={lifecycle.assistantReview}
    pending={lifecycle.pending}
    sessionId={lifecycle.assistantSession?.assistant_request_id || ""}
    sessionOperationScope={lifecycle.assistantSession?.operation_scope || "full_report"}
    sessionTurnHistory={lifecycle.assistantSession?.turn_history || []}
    selectedBlock={page.editorTools.primaryBlock}
    suggestions={lifecycle.assistantSuggestionSet?.selectedBlockId === (page.editorTools.primaryBlock?.id || null)
      ? lifecycle.assistantSuggestionSet.suggestions
      : []}
    trace={lifecycle.assistantTrace}
    workflowStatus={lifecycle.assistantSession?.phase || ""}
    workflowError={lifecycle.assistantActionError || lifecycle.assistantSession?.error_code || ""}
    workflowErrorPageCounts={lifecycle.assistantActionPageCounts}
    workflowRequiredAction={lifecycle.assistantSession?.required_action || "NONE"}
    workflowRetryable={Boolean(lifecycle.assistantSession?.retryable)}
  />;
  const editor = page.builderV2 ? <ReportBuilderV2
    assistant={assistant}
    canvas={workspace}
    library={library}
    libraryOpen={page.toolPanelOpen}
    libraryTriggerRef={page.toolToggleRef}
    onCloseLibrary={page.closeToolPanel}
    onKeyDown={page.handleEditorKeyDown}
    onPointerMove={dnd.handlePointerMove}
    orientation={draft.reportOrientation}
    pages={page.reportPages}
    properties={properties}
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
      {page.activeInsert && <div className={`report-template-overlay ${dragPlacementClass}`.trim()}>{ActiveInsertIcon && <ActiveInsertIcon size={16} />}<span><b>{page.activeInsert.title}</b><small>{dragPlacementClass === "is-invalid" ? "보고서 안의 빈 위치로 이동하세요" : page.activeArtifactSource ? `${page.activeArtifactSource.title}에서 독립 요소로 추가` : "캔버스에 놓아 추가"}</small></span></div>}
      {activeDraggedBlock && <div className={`report-block-drag-overlay ${draggedBlockCount > 1 ? "is-group" : ""} ${dragPlacementClass}`.trim()}>
        <Layers3 size={15} aria-hidden="true" />
        <span>
          <b>{draggedBlockCount > 1 ? `${draggedBlockCount}개 블록 이동` : activeDraggedBlock.title || "제목 없음"}</b>
          <small>{dragPlacementClass === "is-invalid" ? "보고서 안의 빈 위치로 이동하세요" : draggedBlockCount > 1 ? activeDraggedBlock.title || "선택한 블록" : "놓을 위치를 선택하세요"}</small>
        </span>
      </div>}
    </DragOverlay>
  </DndContext>;
}
