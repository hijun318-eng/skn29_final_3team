/** 보고서 하위 hook과 memo renderer를 목록·문서·editor 화면 계약으로 합성하는 controller 모듈이다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { compactDraftLayout, toReportBlockRequest } from "../../contracts/report";
import { DEFAULT_FRONTEND_CURRENCY_POLICY, createFrontendDraftSnapshot, loadFrontendDraft, saveFrontendDraft } from "./reportDraftV2";
import { useReportArtifacts } from "./useReportArtifacts";
import { useReportDraftState } from "./useReportDraftState";
import { useReportDragAndDrop } from "./useReportDragAndDrop";
import { useReportEditorTools } from "./useReportEditorTools";
import { useReportLifecycleState } from "./useReportLifecycleState";
import { REPORT_BUILDER_V2 } from "./reportBuilderFlags";
import {
  ARTIFACT_TEMPLATES,
  GeneratedReportBlock,
  REPORT_TEMPLATE_MAP,
  REPORT_TEMPLATES,
  ReportEditorBlock,
  WHOLE_ARTIFACT_TEMPLATE,
  draftLayoutSignature,
  paginateReportBlocks,
} from "./components";
import {
  artifactViewTemplate,
  definitionDraftState,
  focusReportBlock,
  reportCurrencyState,
  wholeArtifactTemplate,
} from "./reportPageControllerSupport";
import { reportStatusLabel } from "./reportPageLabels";
import { normalizeReportEditorScale } from "./reportEditorViewport";

/** 보고서 lifecycle·artifact·draft·DND를 화면 계약으로 합성하고 stale open generation을 폐기한다. */
export function useReportsPageController({ role, isAdmin: suppliedIsAdmin, onEditorMode }) {
  const isAdmin = suppliedIsAdmin ?? ["report_admin", "platform_admin"].includes(role);
  const lifecycle = useReportLifecycleState({ role, isAdmin });
  const [view, setView] = useState("list");
  const [toolPanelOpen, setToolPanelOpen] = useState(true);
  const [editorViewScale, setEditorViewScale] = useState("fit-width");
  const toolPanelRef = useRef(null);
  const toolToggleRef = useRef(null);
  const errorRef = useRef(null);
  const draftBridgeRef = useRef(null);
  const dndBridgeRef = useRef(null);
  const openRequestRef = useRef(0);
  const assistantRecoveryRef = useRef("");

  const handleHydratedArtifacts = useCallback((artifactMap) => {
    draftBridgeRef.current?.fitHydratedArtifactViews(artifactMap);
  }, []);
  const artifacts = useReportArtifacts({
    analysisClient: lifecycle.analysisClient,
    definitions: lifecycle.definitions,
    onHydrated: handleHydratedArtifacts,
    reportClient: lifecycle.reportClient,
    selectedDefinition: lifecycle.selectedDefinition,
    setNotice: lifecycle.setNotice,
  });
  const requestBlockFocus = useCallback((blockId) => {
    if (dndBridgeRef.current?.pageCanvasRefs) {
      focusReportBlock(dndBridgeRef.current.pageCanvasRefs, blockId);
    }
  }, []);
  const isDraft = lifecycle.selectedDefinition?.status === "draft";
  const canEdit = Boolean(isDraft && !lifecycle.pending);
  const draft = useReportDraftState({
    editable: canEdit,
    artifacts: artifacts.artifacts,
    artifactSources: artifacts.artifactOptions,
    selectedArtifactId: artifacts.artifactSelection,
    templates: REPORT_TEMPLATE_MAP,
    identity: lifecycle.selectedDefinition,
    initialCurrencyPolicy: DEFAULT_FRONTEND_CURRENCY_POLICY,
    onError: lifecycle.setError,
    onNotice: lifecycle.setNotice,
    onFocusRequest: requestBlockFocus,
  });
  draftBridgeRef.current = draft;

  const reportCurrency = useMemo(
    () => reportCurrencyState(artifacts.artifacts, draft.reportCurrencyPolicy),
    [artifacts.artifacts, draft.reportCurrencyPolicy],
  );
  const reportPages = useMemo(() => paginateReportBlocks(
    draft.orderedBlocks,
    draft.reportOrientation,
    lifecycle.selectedDefinition?.definitionId || "report-draft",
  ), [draft.orderedBlocks, draft.reportOrientation, lifecycle.selectedDefinition?.definitionId]);
  const reportBlockNumbers = useMemo(
    () => new Map(draft.orderedBlocks.map((block, index) => [block.id, index + 1])),
    [draft.orderedBlocks],
  );
  const editorTools = useReportEditorTools({
    blocks: draft.blocks,
    commitBlocks: draft.commitBlocks,
    orientation: draft.reportOrientation,
    primaryBlockId: draft.selectedBlockId,
    reportKey: lifecycle.selectedDefinition
      ? `${lifecycle.selectedDefinition.definitionId}:${lifecycle.selectedDefinition.version}`
      : "",
    requestFocus: requestBlockFocus,
    resizeBlock: draft.resizeBlock,
    selectPrimary: draft.selectBlock,
  });
  const selectedArtifact = artifacts.artifactSelection
    ? artifacts.artifacts[artifacts.artifactSelection]
    : null;
  const selectedArtifactSource = artifacts.artifactOptions.find(
    (source) => source.artifactId === artifacts.artifactSelection,
  );

  const wholeArtifactTemplateFor = useCallback((source, width = null) => wholeArtifactTemplate(
    source, artifacts.artifacts, draft.reportOrientation, WHOLE_ARTIFACT_TEMPLATE, width,
  ), [artifacts.artifacts, draft.reportOrientation]);
  const viewArtifactTemplateFor = useCallback((template, width = template?.w) => artifactViewTemplate(
    template,
    selectedArtifactSource || artifacts.artifactOptions[0],
    artifacts.artifacts,
    draft.reportOrientation,
    width,
  ), [artifacts.artifactOptions, artifacts.artifacts, draft.reportOrientation, selectedArtifactSource]);
  const frontendReportContext = useCallback((orientation = draft.reportOrientation) => ({
    definitionId: lifecycle.selectedDefinition?.definitionId || "report-draft",
    version: lifecycle.selectedDefinition?.version || 1,
    title: lifecycle.selectedDefinition?.title || "보고서 초안",
    orientation,
    currencyPolicy: draft.currencyPolicyRef.current,
  }), [draft.currencyPolicyRef, draft.reportOrientation, lifecycle.selectedDefinition]);
  const dnd = useReportDragAndDrop({
    addTemplateBlock: draft.addTemplateBlock,
    addWholeArtifact: draft.addWholeArtifact,
    artifactOptions: artifacts.artifactOptions,
    blocksRef: draft.blocksRef,
    commitBlocks: draft.commitBlocks,
    frontendReportContext,
    reportPages,
    reportTemplateMap: REPORT_TEMPLATE_MAP,
    setEditorAnnouncement: draft.announce,
    setSelectedBlockId: editorTools.selectBlock,
    viewArtifactTemplateFor,
    wholeArtifactTemplateFor,
  });
  dndBridgeRef.current = dnd;

  const applyDefinition = useCallback((definition, options = {}) => {
    lifecycle.upsertDefinition(definition);
    draft.resetDraft(definitionDraftState(definition, options));
  }, [draft.resetDraft, lifecycle.upsertDefinition]);

  const createDefinition = useCallback(async (event) => {
    event.preventDefault();
    const result = await lifecycle.createDefinition();
    if (!result) return;
    applyDefinition(result.definition, { currencyPolicy: DEFAULT_FRONTEND_CURRENCY_POLICY });
    if (!result.initialContent) {
      draft.resetDraft({
        blocks: [{ id: result.blockId, title: "운영 요약", columns: 12, type: "text", content: "", x: 0, y: 0, w: 12, h: 4 }],
        savedBlocks: [],
        orientation: result.definition.orientation,
        currencyPolicy: DEFAULT_FRONTEND_CURRENCY_POLICY,
        selectedBlockId: result.blockId,
        dirty: true,
      });
    }
    setView("editor");
  }, [applyDefinition, draft.resetDraft, lifecycle.createDefinition]);

  const openPreview = useCallback(async (definition) => {
    const requestId = openRequestRef.current + 1;
    openRequestRef.current = requestId;
    const isCurrentRequest = () => openRequestRef.current === requestId;
    artifacts.invalidateLoads();
    void lifecycle.loadFinalDocument(null);
    const current = await lifecycle.fetchDefinition(definition);
    if (!current || !isCurrentRequest()) return;
    lifecycle.clearAssistantTrace();
    applyDefinition(current);
    setView("document");
    await artifacts.loadArtifacts(current);
    if (!isCurrentRequest()) return;
    const document = await lifecycle.loadFinalDocument(current);
    if (document && isCurrentRequest()) draft.resetDraft(definitionDraftState(current, {
      orientation: document.orientation,
      currencyPolicy: { ...DEFAULT_FRONTEND_CURRENCY_POLICY, displayUnit: document.currencyDisplayUnit },
    }));
  }, [applyDefinition, artifacts, draft.resetDraft, lifecycle]);

  const openEditor = useCallback(async (definition) => {
    const requestId = openRequestRef.current + 1;
    openRequestRef.current = requestId;
    const isCurrentRequest = () => openRequestRef.current === requestId;
    artifacts.invalidateLoads();
    void lifecycle.loadFinalDocument(null);
    let current = await lifecycle.fetchDefinition(definition);
    if (!current || !isCurrentRequest()) return;
    if (current.status === "approved") {
      const existingDraft = lifecycle.findLatestDraft(current.definitionId);
      if (existingDraft) {
        current = await lifecycle.fetchDefinition(existingDraft);
        if (!current || !isCurrentRequest()) return;
        lifecycle.setNotice(`기존 v${current.version} 초안을 이어서 편집합니다.`);
      } else {
        if (!window.confirm(`확정본 v${current.version}을 기준으로 새 편집 버전을 만들까요?`)) return;
        const nextDraft = await lifecycle.mutate("next-draft", () => lifecycle.reportClient.createNextDraft(
          current.definitionId,
          current.version,
        ));
        if (!nextDraft || !isCurrentRequest()) return;
        current = lifecycle.upsertDefinition(nextDraft);
        lifecycle.setNotice(`v${current.version} 초안을 만들었습니다.`);
      }
    }
    const localDraft = loadFrontendDraft(window.sessionStorage, current.definitionId, current.version);
    const serverCurrencyPolicy = {
      ...DEFAULT_FRONTEND_CURRENCY_POLICY,
      displayUnit: current.currencyDisplayUnit || DEFAULT_FRONTEND_CURRENCY_POLICY.displayUnit,
    };
    const recoverLocalDraft = Boolean(
      localDraft && (
        draftLayoutSignature(localDraft.blocks) !== draftLayoutSignature(current.blocks)
        || localDraft.orientation !== current.orientation
        || JSON.stringify(localDraft.currencyPolicy) !== JSON.stringify(serverCurrencyPolicy)
      ),
    );
    const editable = recoverLocalDraft ? { ...current, blocks: localDraft.blocks } : current;
    lifecycle.clearAssistantTrace();
    applyDefinition(editable, recoverLocalDraft ? {
      serverBlocks: current.blocks,
      forceDirty: true,
      orientation: localDraft.orientation,
      savedOrientation: current.orientation,
      currencyPolicy: localDraft.currencyPolicy,
      savedCurrencyPolicy: serverCurrencyPolicy,
    } : {});
    setView("editor");
    if (recoverLocalDraft) lifecycle.setNotice("이 브라우저에 남아 있던 구성을 복구했습니다. 서버 저장본과 다르므로 검토한 뒤 저장해 주세요.");
    await artifacts.loadArtifacts(editable, true);
  }, [applyDefinition, artifacts, lifecycle]);

  const saveDraft = useCallback(async () => {
    const definition = lifecycle.selectedDefinition;
    if (!definition || !isDraft || lifecycle.pending) return;
    const invalid = draft.orderedBlocks.find((block) => (
      !block.title?.trim() || (block.type === "text" && !block.content?.trim())
    ));
    if (invalid) {
      draft.selectBlock(invalid.id);
      draft.markSaveFailed();
      lifecycle.setError(!invalid.title?.trim()
        ? "블록 제목을 입력한 뒤 저장해 주세요."
        : `“${invalid.title}” 블록의 내용을 입력한 뒤 저장해 주세요.`);
      window.requestAnimationFrame(() => document.querySelector(
        `[data-block-id="${CSS.escape(invalid.id)}"] ${!invalid.title?.trim() ? ".notion-block-title" : ".notion-markdown-input"}`,
      )?.focus());
      return;
    }
    const snapshot = createFrontendDraftSnapshot({
      definitionId: definition.definitionId,
      version: definition.version,
      title: definition.title,
      orientation: draft.reportOrientation,
      currencyPolicy: draft.reportCurrencyPolicy,
      blocks: draft.orderedBlocks,
    });
    if (!snapshot.ok) {
      draft.markSaveFailed();
      lifecycle.setError(snapshot.errors?.[0] || "보고서 초안을 구성하지 못했습니다.");
      return;
    }
    draft.beginSave();
    const persistedBlocks = compactDraftLayout(draft.orderedBlocks);
    const saved = await lifecycle.mutate("save", () => lifecycle.reportClient.replaceDraftBlocks(
      definition.definitionId,
      definition.version,
      persistedBlocks.map(toReportBlockRequest),
      { orientation: draft.reportOrientation, currencyDisplayUnit: draft.reportCurrencyPolicy.displayUnit },
    ));
    if (!saved) {
      draft.markSaveFailed();
      return;
    }
    let localSnapshotSaved = true;
    try {
      saveFrontendDraft(window.sessionStorage, snapshot.snapshot);
    } catch {
      localSnapshotSaved = false;
    }
    applyDefinition({ ...saved, blocks: snapshot.snapshot.blocks });
    lifecycle.setNotice(localSnapshotSaved
      ? "변경사항을 저장했습니다."
      : "서버에는 저장했지만 이 브라우저의 임시 복구본은 갱신하지 못했습니다.");
  }, [applyDefinition, draft, isDraft, lifecycle]);

  const approveDefinition = useCallback(async () => {
    const definition = lifecycle.selectedDefinition;
    if (!definition || !isDraft) return;
    if (draft.isDirty) {
      lifecycle.setError("저장되지 않은 변경사항을 먼저 저장한 뒤 PDF를 확정해 주세요.");
      return;
    }
    if (!window.confirm(`v${definition.version} 저장된 HTML 초안을 확정하고 수정할 수 없는 PDF를 생성할까요?`)) return;
    const approved = await lifecycle.approveDefinition(definition, {
      orientation: draft.reportOrientation,
      blocks: draft.blocksRef.current,
    });
    if (!approved) return;
    applyDefinition(approved);
    setView("document");
    await lifecycle.loadFinalDocument(approved);
  }, [applyDefinition, draft.blocksRef, draft.isDirty, draft.reportOrientation, isDraft, lifecycle]);

  const createAssistantDraft = useCallback(async (instruction = lifecycle.assistantInstruction) => {
    const definition = lifecycle.selectedDefinition;
    if (!definition || !selectedArtifactSource?.artifactId || !selectedArtifact || !instruction.trim()) return null;
    const result = await lifecycle.submitAssistantInstruction(
      definition,
      selectedArtifactSource.artifactId,
      instruction,
    );
    if (!result?.definition) return result;
    applyDefinition(result.definition);
    await artifacts.loadArtifacts(result.definition, true);
    return result;
  }, [applyDefinition, artifacts, lifecycle, selectedArtifact, selectedArtifactSource]);

  const approveAssistantDataRequest = useCallback(async () => {
    const result = await lifecycle.approveAssistantRequest();
    if (!result?.definition) return result;
    applyDefinition(result.definition);
    await artifacts.loadArtifacts(result.definition, true);
    return result;
  }, [applyDefinition, artifacts, lifecycle]);

  const rejectAssistantDataRequest = useCallback(
    () => lifecycle.rejectAssistantRequest(),
    [lifecycle],
  );

  const approveAssistantPatch = useCallback(async () => {
    const result = await lifecycle.approveAssistantPatch();
    if (!result?.definition) return result;
    applyDefinition(result.definition);
    await artifacts.loadArtifacts(result.definition, true);
    return result;
  }, [applyDefinition, artifacts, lifecycle]);

  const rejectAssistantPatch = useCallback(
    () => lifecycle.rejectAssistantPatch(),
    [lifecycle],
  );

  const assistantStorageKey = lifecycle.selectedDefinition && selectedArtifactSource?.artifactId
    ? `answervice.report-assistant:${lifecycle.selectedDefinition.definitionId}:${lifecycle.selectedDefinition.version}:${selectedArtifactSource.artifactId}`
    : "";

  useEffect(() => {
    if (!assistantStorageKey) return;
    const current = lifecycle.assistantSession;
    if (
      current?.definition_id === lifecycle.selectedDefinition?.definitionId
      && current.definition_version === lifecycle.selectedDefinition?.version
      && current.artifact_id === selectedArtifactSource?.artifactId
    ) return;
    let stored = "";
    try { stored = window.sessionStorage.getItem(assistantStorageKey) || ""; } catch { return; }
    const recoveryToken = `${assistantStorageKey}:${stored}`;
    if (!stored || assistantRecoveryRef.current === recoveryToken) return;
    assistantRecoveryRef.current = recoveryToken;
    void lifecycle.restoreAssistantSession(stored).then((session) => {
      if (!session) assistantRecoveryRef.current = "";
    });
  }, [assistantStorageKey, lifecycle.assistantSession, lifecycle.restoreAssistantSession, lifecycle.selectedDefinition, selectedArtifactSource]);
  useEffect(() => {
    if (!assistantStorageKey || !lifecycle.assistantSession) return;
    const session = lifecycle.assistantSession;
    if (
      session.definition_id !== lifecycle.selectedDefinition?.definitionId
      || session.definition_version !== lifecycle.selectedDefinition?.version
      || session.artifact_id !== selectedArtifactSource?.artifactId
    ) return;
    try { window.sessionStorage.setItem(assistantStorageKey, session.assistant_request_id); } catch { /* 서버 상태는 유지한다. */ }
  }, [assistantStorageKey, lifecycle.assistantSession, lifecycle.selectedDefinition, selectedArtifactSource]);

  const leaveEditor = useCallback(() => {
    if (draft.isDirty && !window.confirm("저장하지 않은 변경사항이 있습니다. 편집을 종료할까요?")) return;
    openRequestRef.current += 1;
    artifacts.invalidateLoads();
    void lifecycle.loadFinalDocument(null);
    setView("list");
  }, [artifacts.invalidateLoads, draft.isDirty, lifecycle.loadFinalDocument]);
  const previewEditor = useCallback(() => {
    if (draft.isDirty) {
      lifecycle.setError("변경사항을 저장한 뒤 HTML 초안을 확인해 주세요.");
      return;
    }
    const definition = lifecycle.selectedDefinition;
    if (!definition) return;
    lifecycle.selectDefinition({ ...definition, blocks: [...draft.blocks] });
    setView("document");
    void artifacts.loadArtifacts({ ...definition, blocks: [...draft.blocks] });
  }, [artifacts.loadArtifacts, draft.blocks, draft.isDirty, lifecycle]);
  const returnToEditor = useCallback(() => {
    const focus = () => focusReportBlock(dnd.pageCanvasRefs, draft.selectedBlockId);
    if (lifecycle.selectedDefinition?.status === "draft") {
      setView("editor");
      focus();
    } else if (lifecycle.selectedDefinition) {
      void openEditor(lifecycle.selectedDefinition).then(focus);
    }
  }, [dnd.pageCanvasRefs, draft.selectedBlockId, lifecycle.selectedDefinition, openEditor]);
  const handleEditorKeyDown = useCallback((event) => {
    const textField = ["input", "textarea", "select"].includes(event.target.tagName.toLowerCase());
    if (!textField && canEdit && ["Delete", "Backspace"].includes(event.key)) {
      event.preventDefault();
      editorTools.deleteSelected();
      return;
    }
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === "s" && canEdit) {
      event.preventDefault();
      void saveDraft();
      return;
    }
    if (textField && !event.target.closest?.(".notion-block")) return;
    if (key === "c") { event.preventDefault(); editorTools.copySelected(); }
    else if (key === "v" && canEdit) { event.preventDefault(); editorTools.pasteBlocks(); }
    else if (key === "z" && event.shiftKey) { event.preventDefault(); draft.redo(); }
    else if (key === "z") { event.preventDefault(); draft.undo(); }
    else if (key === "y") { event.preventDefault(); draft.redo(); }
  }, [canEdit, draft.redo, draft.undo, editorTools, saveDraft]);
  const loadRuns = useCallback(() => { void lifecycle.loadRuns(); }, [lifecycle.loadRuns]);
  const runDefinition = useCallback(() => { void lifecycle.runDefinition(); }, [lifecycle.runDefinition]);
  const createSchedule = useCallback(() => { void lifecycle.createSchedule(); }, [lifecycle.createSchedule]);
  const reloadFinalDocument = useCallback(async () => {
    const definition = lifecycle.selectedDefinition;
    if (!definition) return;
    const document = await lifecycle.loadFinalDocument(definition);
    if (!document) return;
    draft.resetDraft(definitionDraftState(definition, {
      orientation: document.orientation,
      currencyPolicy: { ...DEFAULT_FRONTEND_CURRENCY_POLICY, displayUnit: document.currencyDisplayUnit },
    }));
  }, [draft.resetDraft, lifecycle.loadFinalDocument, lifecycle.selectedDefinition]);
  const closeToolPanel = useCallback(() => setToolPanelOpen(false), []);
  const toggleToolPanel = useCallback(() => setToolPanelOpen((open) => !open), []);
  const changeEditorViewScale = useCallback((value) => {
    setEditorViewScale(normalizeReportEditorScale(value));
  }, []);
  const selectOutlineBlock = useCallback((blockId) => {
    editorTools.selectBlock(blockId);
    requestBlockFocus(blockId);
  }, [editorTools.selectBlock, requestBlockFocus]);
  const addTextBlock = useCallback(() => draft.addTemplateBlock("text"), [draft.addTemplateBlock]);

  useEffect(() => { onEditorMode?.(view === "editor"); }, [onEditorMode, view]);
  useEffect(() => () => onEditorMode?.(false), [onEditorMode]);
  useEffect(() => {
    if (!lifecycle.error) return undefined;
    const frame = window.requestAnimationFrame(() => errorRef.current?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(frame);
  }, [lifecycle.error]);
  useEffect(() => {
    const tablet = window.matchMedia("(min-width: 901px) and (max-width: 1100px)");
    const collapse = (event) => { if (event.matches) setToolPanelOpen(false); };
    if (tablet.matches) setToolPanelOpen(false);
    tablet.addEventListener("change", collapse);
    return () => tablet.removeEventListener("change", collapse);
  }, []);
  useEffect(() => {
    if (!toolPanelOpen || !window.matchMedia("(min-width: 901px) and (max-width: 1100px)").matches) return undefined;
    const frame = window.requestAnimationFrame(() => toolPanelRef.current?.focus());
    const close = (event) => { if (event.key === "Escape") setToolPanelOpen(false); };
    document.addEventListener("keydown", close);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", close);
      window.requestAnimationFrame(() => toolToggleRef.current?.focus?.());
    };
  }, [toolPanelOpen]);

  const artifactStateFor = useCallback((artifactId) => artifactId
    ? artifacts.artifactStates[artifactId] || { status: "loading", message: "" }
    : null, [artifacts.artifactStates]);
  const renderHeader = useCallback(({ pageNumber, pageCount }) => <><div className="answer-report-page-title"><small>ANSWERVICE · GOVERNED REPORT</small><h1>{lifecycle.selectedDefinition?.title || "보고서"}</h1><p>{lifecycle.assistantTrace ? "AI 초안 · 검토 필요" : reportStatusLabel(lifecycle.selectedDefinition?.status)} · v{lifecycle.selectedDefinition?.version} · {pageNumber}/{pageCount}페이지</p></div><span className="answer-report-draft-mark">{lifecycle.selectedDefinition?.status === "approved" ? "확정본" : "HTML 편집 초안"}</span></>, [lifecycle.assistantTrace, lifecycle.selectedDefinition]);
  const renderFooter = useCallback(() => <span>분석 근거 연결 · HTML 편집본</span>, []);
  const renderPreviewBlock = useCallback((layoutBlock) => {
    const block = layoutBlock.sourceBlock || layoutBlock;
    return <GeneratedReportBlock block={block} number={reportBlockNumbers.get(block.id)} rowOffset={0} artifact={block.artifactId ? artifacts.artifacts[block.artifactId] : null} artifactState={artifactStateFor(block.artifactId)} currency={reportCurrency} orientation={draft.reportOrientation} onRetry={block.artifactId ? () => artifacts.retryArtifact(block.artifactId) : undefined} />;
  }, [artifactStateFor, artifacts.artifacts, artifacts.retryArtifact, draft.reportOrientation, reportBlockNumbers, reportCurrency]);
  const {
    duplicateBlock: duplicateDraftBlock,
    moveBlock: moveDraftBlock,
    resizeBlock: resizeDraftBlock,
    setBlockSetting: setDraftBlockSetting,
    updateBlock: updateDraftBlock,
  } = draft;
  const renderEditorBlock = useCallback((layoutBlock, context) => {
    const block = layoutBlock.sourceBlock || layoutBlock;
    return <ReportEditorBlock block={block} rowOffset={context.page.offsetY} artifact={block.artifactId ? artifacts.artifacts[block.artifactId] : null} artifactState={artifactStateFor(block.artifactId)} currency={reportCurrency} isDraft={canEdit} selected={editorTools.selectedBlockIds.has(block.id)} dragging={dnd.draggedBlockId === block.id} locked={editorTools.lockedBlockIds.has(block.id)} onSelect={editorTools.selectBlock} onUpdate={updateDraftBlock} onMove={moveDraftBlock} onResize={resizeDraftBlock} onSetting={setDraftBlockSetting} onDuplicate={duplicateDraftBlock} onDelete={editorTools.deleteBlock} onToggleLock={editorTools.toggleBlockLock} onRetryArtifact={artifacts.retryArtifact} />;
  }, [
    artifactStateFor, artifacts.artifacts, artifacts.retryArtifact, canEdit,
    dnd.draggedBlockId, duplicateDraftBlock, editorTools, moveDraftBlock, reportCurrency,
    resizeDraftBlock, setDraftBlockSetting, updateDraftBlock,
  ]);

  const activeTemplate = dnd.draggedBlockId.startsWith("template:")
    ? viewArtifactTemplateFor(REPORT_TEMPLATE_MAP.get(dnd.draggedBlockId.slice("template:".length)))
    : null;
  const activeArtifactSource = dnd.draggedBlockId.startsWith("artifact:")
    ? artifacts.artifactOptions.find((source) => source.artifactId === dnd.draggedBlockId.slice("artifact:".length))
    : null;
  const activeInsert = activeTemplate || (activeArtifactSource ? wholeArtifactTemplateFor(activeArtifactSource) : null);

  return {
    activeArtifactSource,
    activeInsert,
    approveDefinition,
    approveAssistantDataRequest,
    approveAssistantPatch,
    artifacts,
    builderV2: REPORT_BUILDER_V2, canEdit,
    createAssistantDraft,
    createSchedule,
    createDefinition,
    dnd,
    draft,
    editorTools,
    errorRef,
    handleEditorKeyDown,
    isAdmin,
    isDraft,
    leaveEditor,
    loadRuns,
    lifecycle,
    openEditor,
    openPreview,
    previewEditor,
    renderEditorBlock,
    renderFooter,
    renderHeader,
    renderPreviewBlock,
    rejectAssistantDataRequest,
    rejectAssistantPatch,
    reportCurrency,
    reportPages,
    reloadFinalDocument,
    returnToEditor,
    runDefinition,
    saveDraft,
    selectedArtifact,
    selectedArtifactSource,
    setToolPanelOpen,
    closeToolPanel, toggleToolPanel,
    changeEditorViewScale,
    editorViewScale,
    selectOutlineBlock,
    addTextBlock,
    toolPanelOpen,
    toolPanelRef,
    toolToggleRef,
    view,
    setView,
    reportTemplates: REPORT_TEMPLATES,
    artifactTemplates: ARTIFACT_TEMPLATES,
  };
}
