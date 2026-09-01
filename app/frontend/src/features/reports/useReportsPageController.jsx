/** 보고서 하위 hook과 memo renderer를 목록·문서·editor 화면 계약으로 합성하는 controller 모듈이다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { compactDraftLayout, toReportBlockRequest } from "../../contracts/report";
import { createUuid } from "../../utils/createUuid.ts";
import {
  DEFAULT_FRONTEND_CURRENCY_POLICY,
  createFrontendDraftSnapshot,
  loadFrontendDraft,
  reportAssistantRepresentativeBlock,
  saveFrontendDraft,
} from "./reportDraftV2";
import { useReportArtifacts } from "./useReportArtifacts";
import { useReportDraftState } from "./useReportDraftState";
import { parseArtifactViewDragId, useReportDragAndDrop } from "./useReportDragAndDrop";
import { useReportEditorTools } from "./useReportEditorTools";
import { useReportLifecycleState } from "./useReportLifecycleState";
import { REPORT_BUILDER_V2 } from "./reportBuilderFlags";
import {
  ARTIFACT_TEMPLATES,
  GeneratedReportBlock,
  REPORT_TEMPLATE_MAP,
  REPORT_TEMPLATES,
  ReportEditorBlock,
  draftLayoutSignature,
  paginateReportBlocks,
} from "./components";
import {
  artifactViewTemplate,
  definitionDraftState,
  focusReportBlock,
  reportCurrencyState,
} from "./reportPageControllerSupport";
import { normalizeReportEditorScale } from "./reportEditorViewport";
import { reportStatusLabel } from "./reportPageLabels";
import {
  reportAssistantSessionMatchesDefinition,
  reportAssistantSessionStorageKey,
} from "./reportAssistantSessionRecovery";

const ASSISTANT_SAVE_FIRST_MESSAGE = "AI로 보고서를 변경하기 전에 현재 편집 내용을 먼저 저장해 주세요.";

/** 보고서 lifecycle·artifact·draft·DND를 화면 계약으로 합성하고 stale open generation을 폐기한다. */
export function useReportsPageController({ role, isAdmin: suppliedIsAdmin, onEditorMode }) {
  const isAdmin = suppliedIsAdmin ?? role === "admin";
  const lifecycle = useReportLifecycleState({ role, isAdmin });
  const [view, setView] = useState("list");
  const [toolPanelOpen, setToolPanelOpen] = useState(false);
  const [editorViewScale, setEditorViewScale] = useState("fit-width");
  const toolPanelRef = useRef(null);
  const toolToggleRef = useRef(null);
  const errorRef = useRef(null);
  const draftBridgeRef = useRef(null);
  const dndBridgeRef = useRef(null);
  const openRequestRef = useRef(0);
  const assistantRecoveryRef = useRef("");
  const assistantRevisionResumeRef = useRef("");

  const handleHydratedArtifacts = useCallback((artifactMap) => {
    draftBridgeRef.current?.fitHydratedArtifactViews(artifactMap);
  }, []);
  const artifacts = useReportArtifacts({
    analysisClient: lifecycle.analysisClient,
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
  const isArchived = Boolean(lifecycle.selectedDefinition?.archivedAt);
  const canEdit = Boolean(isDraft && !isArchived && !lifecycle.pending);
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
  const assistantRepresentativeBlock = useMemo(() => reportAssistantRepresentativeBlock(
    draft.orderedBlocks,
    editorTools.primaryBlock?.id || "",
  ), [draft.orderedBlocks, editorTools.primaryBlock?.id]);
  const assistantArtifact = assistantRepresentativeBlock?.artifactId
    ? artifacts.artifacts[assistantRepresentativeBlock.artifactId]
    : null;
  const assistantArtifactSource = artifacts.artifactOptions.find(
    (source) => source.artifactId === assistantRepresentativeBlock?.artifactId,
  );
  const assistantArtifactIds = useMemo(() => assistantArtifactSource?.artifactId
    ? [
        assistantArtifactSource.artifactId,
        ...artifacts.assistantAdditionalArtifactIds.filter(
          (artifactId) => artifactId !== assistantArtifactSource.artifactId,
        ).slice(0, 4),
      ]
    : [], [artifacts.assistantAdditionalArtifactIds, assistantArtifactSource]);
  const assistantArtifactOptions = useMemo(
    () => artifacts.assistantArtifactOptionsFor(assistantArtifactSource?.artifactId || ""),
    [artifacts.assistantArtifactOptionsFor, assistantArtifactSource?.artifactId],
  );
  const setAssistantArtifacts = useCallback(
    (artifactIds) => artifacts.setAssistantArtifacts(
      artifactIds,
      assistantArtifactSource?.artifactId || "",
    ),
    [artifacts.setAssistantArtifacts, assistantArtifactSource?.artifactId],
  );

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
    title: draft.titleRef.current || "보고서 초안",
    orientation,
    currencyPolicy: draft.currencyPolicyRef.current,
  }), [draft.currencyPolicyRef, draft.reportOrientation, draft.titleRef, lifecycle.selectedDefinition]);
  const dnd = useReportDragAndDrop({
    addTemplateBlock: draft.addTemplateBlock,
    blocksRef: draft.blocksRef,
    commitBlocks: draft.commitBlocks,
    frontendReportContext,
    selectedBlockIds: editorTools.selectedBlockIds,
    lockedBlockIds: editorTools.lockedBlockIds,
    reportPages,
    reportTemplateMap: REPORT_TEMPLATE_MAP,
    setEditorAnnouncement: draft.announce,
    selectDraggedBlock: editorTools.selectDraggedBlock,
    viewArtifactTemplateFor,
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
      const initialBlockId = createUuid();
      draft.resetDraft({
        blocks: [{ id: initialBlockId, title: "운영 요약", columns: 12, type: "text", content: "", x: 0, y: 0, w: 12, h: 4 }],
        savedBlocks: [],
        title: result.definition.title,
        savedTitle: result.definition.title,
        orientation: result.definition.orientation,
        currencyPolicy: DEFAULT_FRONTEND_CURRENCY_POLICY,
        selectedBlockId: initialBlockId,
        dirty: true,
      });
    }
    setView("editor");
  }, [applyDefinition, draft.resetDraft, lifecycle.createDefinition]);

  const openPreview = useCallback(async (definition) => {
    if (definition.archivedAt && definition.status !== "approved") {
      lifecycle.setError("삭제된 초안은 복원한 뒤 확인할 수 있습니다. 휴지통에서는 확정 문서만 열람할 수 있습니다.");
      return;
    }
    const requestId = openRequestRef.current + 1;
    openRequestRef.current = requestId;
    const isCurrentRequest = () => openRequestRef.current === requestId;
    artifacts.invalidateLoads();
    void lifecycle.loadFinalDocument(null);
    const current = await lifecycle.fetchDefinition(definition);
    if (!current || !isCurrentRequest()) return;
    if (current.archivedAt && current.status !== "approved") {
      lifecycle.setError("삭제된 초안은 복원한 뒤 확인할 수 있습니다. 휴지통에서는 확정 문서만 열람할 수 있습니다.");
      return;
    }
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
    if (definition.archivedAt) {
      lifecycle.setError("삭제된 보고서는 읽기 전용입니다. 휴지통에서 복원한 뒤 편집해 주세요.");
      return;
    }
    const requestId = openRequestRef.current + 1;
    openRequestRef.current = requestId;
    const isCurrentRequest = () => openRequestRef.current === requestId;
    artifacts.invalidateLoads();
    void lifecycle.loadFinalDocument(null);
    let current = await lifecycle.fetchDefinition(definition);
    if (!current || !isCurrentRequest()) return;
    if (current.archivedAt) {
      lifecycle.setError("삭제된 보고서는 읽기 전용입니다. 휴지통에서 복원한 뒤 편집해 주세요.");
      return;
    }
    if (current.status === "approved") {
      const existingDraft = lifecycle.findLatestDraft(current.definitionId);
      if (existingDraft) {
        current = await lifecycle.fetchDefinition(existingDraft);
        if (!current || !isCurrentRequest()) return;
        lifecycle.setNotice(`기존 버전 ${current.version} 초안을 이어서 편집합니다.`);
      } else {
        if (!window.confirm(`확정본 v${current.version}을 기준으로 새 편집 버전을 만들까요?`)) return;
        const nextDraft = await lifecycle.mutate("next-draft", () => lifecycle.reportClient.createNextDraft(
          current.definitionId,
          current.version,
        ));
        if (!nextDraft || !isCurrentRequest()) return;
        current = lifecycle.upsertDefinition(nextDraft);
        lifecycle.setNotice(`버전 ${current.version} 초안을 만들었습니다.`);
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
    const editable = recoverLocalDraft
      ? { ...current, blocks: localDraft.blocks }
      : current;
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
    if (!definition || !isDraft || isArchived || lifecycle.pending) return;
    const title = draft.titleRef.current.trim();
    if (!title || title.length > 255 || /[\u0000-\u001f\u007f]/.test(title)) {
      draft.markSaveFailed();
      lifecycle.setError("보고서 제목을 줄바꿈·제어문자 없이 1~255자로 입력한 뒤 저장해 주세요.");
      window.requestAnimationFrame(() => document.querySelector(".report-builder-title-input")?.focus());
      return;
    }
    if (title !== draft.titleRef.current) draft.updateReportTitle(title);
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
    const persistedBlocks = compactDraftLayout(draft.orderedBlocks);
    const snapshot = createFrontendDraftSnapshot({
      definitionId: definition.definitionId,
      version: definition.version,
      title,
      orientation: draft.reportOrientation,
      currencyPolicy: draft.reportCurrencyPolicy,
      blocks: persistedBlocks,
    });
    if (!snapshot.ok) {
      draft.markSaveFailed();
      lifecycle.setError(snapshot.errors?.[0] || "보고서 초안을 구성하지 못했습니다.");
      return;
    }
    draft.beginSave();
    const saved = await lifecycle.mutate("save", () => lifecycle.reportClient.replaceDraftBlocks(
      definition.definitionId,
      definition.version,
      persistedBlocks.map(toReportBlockRequest),
      {
        title,
        expectedDraftRevision: definition.draftRevision,
        orientation: draft.reportOrientation,
        currencyDisplayUnit: draft.reportCurrencyPolicy.displayUnit,
      },
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
  }, [applyDefinition, draft, isArchived, isDraft, lifecycle]);

  const approveDefinition = useCallback(async () => {
    const definition = lifecycle.selectedDefinition;
    if (!definition || !isDraft || isArchived) return;
    if (draft.isDirty) {
      lifecycle.setError("저장되지 않은 변경사항을 먼저 저장한 뒤 PDF를 확정해 주세요.");
      return;
    }
    if (!window.confirm(`저장된 보고서 버전 ${definition.version}을 확정할까요? 확정하면 PDF가 생성되며 이 버전은 수정할 수 없습니다.`)) return;
    const approved = await lifecycle.approveDefinition(definition, {
      orientation: draft.reportOrientation,
      blocks: draft.blocksRef.current,
    });
    if (!approved) return;
    applyDefinition(approved);
    setView("document");
    await lifecycle.loadFinalDocument(approved);
  }, [applyDefinition, draft.blocksRef, draft.isDirty, draft.reportOrientation, isArchived, isDraft, lifecycle]);

  const requireSavedAssistantDraft = useCallback(() => {
    if (lifecycle.selectedDefinition?.archivedAt) {
      lifecycle.setError("삭제된 보고서에서는 AI 도우미를 사용할 수 없습니다. 먼저 보고서를 복원해 주세요.");
      return false;
    }
    if (!draft.isDirty) return true;
    lifecycle.setError(ASSISTANT_SAVE_FIRST_MESSAGE);
    return false;
  }, [draft.isDirty, lifecycle]);

  const createAssistantDraft = useCallback(async (
    instruction = lifecycle.assistantInstruction,
    operationScope = "full_report",
  ) => {
    if (!requireSavedAssistantDraft()) return null;
    const definition = lifecycle.selectedDefinition;
    if (!definition || !instruction.trim()) return null;
    if (!assistantRepresentativeBlock?.artifactId) {
      lifecycle.setError("보고서에 검증된 분석 결과 블록을 먼저 추가해 주세요.");
      return null;
    }
    if (!assistantArtifactSource?.artifactId || !assistantArtifact) {
      lifecycle.setError("선택한 보고서 블록의 분석 근거를 확인할 수 없습니다. 근거를 다시 불러온 뒤 시도해 주세요.");
      return null;
    }
    const result = await lifecycle.submitAssistantInstruction(
      definition,
      assistantArtifactSource.artifactId,
      instruction,
      assistantArtifactIds,
      operationScope === "report_title" ? null : editorTools.primaryBlock?.id || null,
      operationScope,
    );
    if (!result?.definition) return result;
    applyDefinition(result.definition);
    await artifacts.loadArtifacts(result.definition, true);
    return result;
  }, [
    applyDefinition, artifacts, assistantArtifact, assistantArtifactIds,
    assistantArtifactSource, assistantRepresentativeBlock?.artifactId,
    editorTools.primaryBlock?.id, lifecycle, requireSavedAssistantDraft,
  ]);

  const suggestAssistantTitle = useCallback(
    (instruction) => createAssistantDraft(instruction, "report_title"),
    [createAssistantDraft],
  );

  const reviewAssistantReport = useCallback(async () => {
    if (!requireSavedAssistantDraft()) return null;
    const definition = lifecycle.selectedDefinition;
    if (!definition) return null;
    if (!assistantRepresentativeBlock?.artifactId) {
      lifecycle.setError("보고서에 검증된 분석 결과 블록을 먼저 추가해 주세요.");
      return null;
    }
    if (!assistantArtifactSource?.artifactId || !assistantArtifact) {
      lifecycle.setError("선택한 보고서 블록의 분석 근거를 확인할 수 없습니다. 근거를 다시 불러온 뒤 시도해 주세요.");
      return null;
    }
    return lifecycle.reviewAssistantReport(
      definition,
      assistantArtifactSource.artifactId,
      assistantArtifactIds,
      editorTools.primaryBlock?.id || null,
    );
  }, [
    assistantArtifact, assistantArtifactIds, assistantArtifactSource,
    assistantRepresentativeBlock?.artifactId, editorTools.primaryBlock?.id,
    lifecycle, requireSavedAssistantDraft,
  ]);

  const approveAssistantDataRequest = useCallback(async () => {
    if (!requireSavedAssistantDraft()) return null;
    const result = await lifecycle.approveAssistantRequest();
    if (!result?.definition) return result;
    applyDefinition(result.definition);
    await artifacts.loadArtifacts(result.definition, true);
    return result;
  }, [applyDefinition, artifacts, lifecycle, requireSavedAssistantDraft]);

  const rejectAssistantDataRequest = useCallback(
    () => lifecycle.rejectAssistantRequest(),
    [lifecycle],
  );

  const approveAssistantPatch = useCallback(async (operationIndexes) => {
    if (!requireSavedAssistantDraft()) return null;
    const result = await lifecycle.approveAssistantPatch(operationIndexes);
    if (!result?.definition) return result;
    applyDefinition(result.definition);
    await artifacts.loadArtifacts(result.definition, true);
    return result;
  }, [applyDefinition, artifacts, lifecycle, requireSavedAssistantDraft]);

  const rejectAssistantPatch = useCallback(
    () => lifecycle.rejectAssistantPatch(),
    [lifecycle],
  );

  const resumeAssistantRevision = useCallback((session) => {
    if (session?.phase !== "saving_revision") return null;
    if (session.patch_request_id) {
      return approveAssistantPatch(session.approved_operation_indexes);
    }
    if (session.analysis_plan?.request_id) return approveAssistantDataRequest();
    return null;
  }, [approveAssistantDataRequest, approveAssistantPatch]);

  const assistantStorageKey = reportAssistantSessionStorageKey(lifecycle.selectedDefinition);

  useEffect(() => {
    if (!assistantStorageKey) return;
    const current = lifecycle.assistantSession;
    const currentMatches = reportAssistantSessionMatchesDefinition(
      current,
      lifecycle.selectedDefinition,
    );
    if (currentMatches) return;
    if (current) lifecycle.clearAssistantTrace();
    let stored = "";
    try { stored = window.sessionStorage.getItem(assistantStorageKey) || ""; } catch { return; }
    const recoveryToken = `${assistantStorageKey}:${stored}`;
    if (!stored || assistantRecoveryRef.current === recoveryToken) return;
    assistantRecoveryRef.current = recoveryToken;
    void lifecycle.restoreAssistantSession(stored, lifecycle.selectedDefinition);
  }, [assistantStorageKey, lifecycle.assistantSession, lifecycle.clearAssistantTrace, lifecycle.restoreAssistantSession, lifecycle.selectedDefinition]);
  useEffect(() => {
    const session = lifecycle.assistantSession;
    if (session?.phase !== "saving_revision") return;
    const resumeKey = `${session.assistant_request_id}:${session.patch_request_id || session.analysis_plan?.request_id || ""}`;
    if (assistantRevisionResumeRef.current === resumeKey) return;
    assistantRevisionResumeRef.current = resumeKey;
    void resumeAssistantRevision(session);
  }, [lifecycle.assistantSession, resumeAssistantRevision]);
  useEffect(() => {
    if (!assistantStorageKey || !lifecycle.assistantSession) return;
    const session = lifecycle.assistantSession;
    if (!reportAssistantSessionMatchesDefinition(session, lifecycle.selectedDefinition)) return;
    try { window.sessionStorage.setItem(assistantStorageKey, session.assistant_request_id); } catch { /* 서버 상태는 유지한다. */ }
  }, [assistantStorageKey, lifecycle.assistantSession, lifecycle.selectedDefinition]);

  const leaveEditor = useCallback(() => {
    if (draft.isDirty && !window.confirm("저장하지 않은 변경사항이 있습니다. 편집을 종료할까요?")) return;
    openRequestRef.current += 1;
    artifacts.invalidateLoads();
    void lifecycle.loadFinalDocument(null);
    lifecycle.clearFeedback();
    setView("list");
  }, [artifacts.invalidateLoads, draft.isDirty, lifecycle.clearFeedback, lifecycle.loadFinalDocument]);
  const previewEditor = useCallback(() => {
    if (draft.isDirty) {
      lifecycle.setError("변경사항을 저장한 뒤 보고서 미리보기를 확인해 주세요.");
      return;
    }
    const definition = lifecycle.selectedDefinition;
    if (!definition) return;
    lifecycle.selectDefinition({ ...definition, blocks: [...draft.blocks] });
    setView("document");
    void artifacts.loadArtifacts({ ...definition, blocks: [...draft.blocks] });
  }, [artifacts.loadArtifacts, draft.blocks, draft.isDirty, lifecycle]);
  const returnToEditor = useCallback(() => {
    if (lifecycle.selectedDefinition?.archivedAt) {
      lifecycle.setError("삭제된 보고서는 읽기 전용입니다. 복원한 뒤 편집해 주세요.");
      return;
    }
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
    if (textField) return;
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
    const drawer = window.matchMedia("(max-width: 1179px)");
    const collapse = (event) => { if (event.matches) setToolPanelOpen(false); };
    if (drawer.matches) setToolPanelOpen(false);
    drawer.addEventListener("change", collapse);
    return () => drawer.removeEventListener("change", collapse);
  }, []);
  useEffect(() => {
    if (!toolPanelOpen || !window.matchMedia("(max-width: 1179px)").matches) return undefined;
    const panel = toolPanelRef.current;
    const frame = window.requestAnimationFrame(() => {
      const target = panel?.querySelector(".editor-library-close") || panel;
      target?.focus();
    });
    const containFocus = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setToolPanelOpen(false);
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const controls = [...panel.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [href], [tabindex]:not([tabindex='-1'])")]
        .filter((element) => !element.hidden && element.getClientRects().length > 0);
      if (!controls.length) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel || !panel.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", containFocus);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", containFocus);
      window.requestAnimationFrame(() => toolToggleRef.current?.focus?.());
    };
  }, [toolPanelOpen]);

  const artifactStateFor = useCallback((artifactId) => artifactId
    ? artifacts.artifactStates[artifactId] || { status: "loading", message: "" }
    : null, [artifacts.artifactStates]);
  const renderHeader = useCallback(({ pageNumber, pageCount }) => <><div className="answer-report-page-title"><small>ANSWERVICE · 분석 보고서</small><h1>{draft.reportTitle || "보고서"}</h1><p>{lifecycle.assistantTrace ? "AI 초안 · 검토 필요" : reportStatusLabel(lifecycle.selectedDefinition?.status)} · v{lifecycle.selectedDefinition?.version} · {pageNumber}/{pageCount}페이지</p></div>{lifecycle.selectedDefinition?.status === "approved" && <span className="answer-report-draft-mark">확정본</span>}</>, [draft.reportTitle, lifecycle.assistantTrace, lifecycle.selectedDefinition]);
  const renderFooter = useCallback(() => null, []);
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
    return <ReportEditorBlock block={block} rowOffset={context.page.offsetY} artifact={block.artifactId ? artifacts.artifacts[block.artifactId] : null} artifactState={artifactStateFor(block.artifactId)} currency={reportCurrency} isDraft={canEdit} selected={editorTools.selectedBlockIds.has(block.id)} primary={draft.selectedBlockId === block.id} dragging={dnd.draggedBlockIds.has(block.id)} groupTransform={dnd.draggedBlockId !== block.id && dnd.draggedBlockIds.has(block.id) ? dnd.dragDelta : null} locked={editorTools.lockedBlockIds.has(block.id)} onSelect={editorTools.selectBlock} onUpdate={updateDraftBlock} onMove={moveDraftBlock} onResize={resizeDraftBlock} onSetting={setDraftBlockSetting} onDuplicate={duplicateDraftBlock} onDelete={editorTools.deleteBlock} onToggleLock={editorTools.toggleBlockLock} onRetryArtifact={artifacts.retryArtifact} />;
  }, [
    artifactStateFor, artifacts.artifacts, artifacts.retryArtifact, canEdit,
    dnd.dragDelta, dnd.draggedBlockId, dnd.draggedBlockIds, draft.selectedBlockId,
    duplicateDraftBlock, editorTools, moveDraftBlock, reportCurrency,
    resizeDraftBlock, setDraftBlockSetting, updateDraftBlock,
  ]);

  const activeTemplate = dnd.draggedBlockId.startsWith("template:")
    ? viewArtifactTemplateFor(REPORT_TEMPLATE_MAP.get(dnd.draggedBlockId.slice("template:".length)))
    : null;
  const activeArtifactSource = activeTemplate?.view ? selectedArtifactSource : null;
  const activeInsert = activeTemplate;

  return {
    activeArtifactSource,
    assistantArtifact,
    assistantArtifactIds,
    assistantArtifactOptions,
    assistantArtifactSource,
    activeInsert,
    approveDefinition,
    approveAssistantDataRequest,
    approveAssistantPatch,
    artifacts,
    builderV2: REPORT_BUILDER_V2, canEdit,
    createAssistantDraft,
    suggestAssistantTitle,
    reviewAssistantReport,
    createSchedule,
    createDefinition,
    dnd,
    draft,
    editorTools,
    errorRef,
    handleEditorKeyDown,
    isAdmin,
    isArchived,
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
    setAssistantArtifacts,
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
