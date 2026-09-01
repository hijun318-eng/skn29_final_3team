/** 보고서 draft·history·selection·layout·통화 정책을 한 도메인 상태로 관리하는 hook 모듈이다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  compactDraftLayout,
  placeDraftBlock,
  resolveDraftLayoutCollisions,
} from "../../contracts/report.ts";
import { createUuid } from "../../utils/createUuid.ts";
import {
  ARTIFACT_VIEW_LABELS,
  artifactViewBlockSettings,
  artifactViewTitle,
  availableArtifactViews,
  deleteFrontendBlock,
  estimateArtifactBlockLayout,
  estimateArtifactViewBlockLayout,
  fitFrontendArtifactBlock,
  fitFrontendArtifactViewBlock,
  frontendTextBlockLayout,
  insertFrontendArtifact,
  orientFrontendBlocks,
  wholeArtifactSettings,
} from "./reportDraftV2.js";
import {
  copyDraftBlocks,
  createTextTemplateBlock,
  fitAutoArtifactViewLayout,
  mergeDraftCurrencyPolicy,
  readDraftBlockSettings,
  resizeDraftBlocks,
  splitLegacyCompositeArtifactBlocks,
} from "./reportDraftMutations.ts";
import {
  normalizeGeneratedArtifactViewTitle,
} from "./reportTimePresentation.js";
import type {
  DraftCurrencyPolicy,
  DraftArtifactData,
  DraftInsertPosition,
  DraftReportBlock,
  ReportDraftHistory,
  ReportDraftHistorySnapshot,
  ResetReportDraftInput,
  UseReportDraftStateOptions,
  UseReportDraftStateResult,
} from "./reportDraftStateTypes.ts";
import type { ReportOrientation } from "../../contracts/report.ts";

const EMPTY_HISTORY: ReportDraftHistory = { past: [], future: [] };
const HISTORY_LIMIT = 40;

function createHistorySnapshot(
  title: string,
  blocks: readonly DraftReportBlock[],
  orientation: ReportOrientation,
  currencyPolicy: DraftCurrencyPolicy,
): ReportDraftHistorySnapshot {
  return {
    title,
    blocks: copyDraftBlocks(blocks),
    orientation,
    currencyPolicy: { ...currencyPolicy },
  };
}

/** draft·history·layout·표시 정책을 불변 갱신하고 memo 소비자가 사용할 안정된 callback을 반환한다. */
export function useReportDraftState(
  options: UseReportDraftStateOptions,
): UseReportDraftStateResult {
  const initialOrientation = options.initialOrientation ?? "landscape";
  const initialPolicy = mergeDraftCurrencyPolicy(options.initialCurrencyPolicy);
  const initialBlocks = copyDraftBlocks(options.initialBlocks ?? []);
  const initialTitle = options.identity?.title ?? "보고서 초안";
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const [blocks, setBlocks] = useState<readonly DraftReportBlock[]>(initialBlocks);
  const [reportTitle, setReportTitle] = useState(initialTitle);
  const [history, setHistory] = useState<ReportDraftHistory>(EMPTY_HISTORY);
  const [selectedBlockId, setSelectedBlockId] = useState("");
  const [isDirty, setIsDirty] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editorAnnouncement, setEditorAnnouncement] = useState("");
  const [reportOrientation, setReportOrientation] = useState(initialOrientation);
  const [reportCurrencyPolicy, setReportCurrencyPolicy] = useState(initialPolicy);

  const blocksRef = useRef<readonly DraftReportBlock[]>(initialBlocks);
  const savedBlocksRef = useRef<readonly DraftReportBlock[]>(initialBlocks);
  const titleRef = useRef(initialTitle);
  const savedTitleRef = useRef(initialTitle);
  const orientationRef = useRef(initialOrientation);
  const savedOrientationRef = useRef(initialOrientation);
  const currencyPolicyRef = useRef(initialPolicy);
  const savedCurrencyPolicyRef = useRef(initialPolicy);

  const draftChanged = useCallback((
    nextBlocks: readonly DraftReportBlock[],
    nextPolicy = currencyPolicyRef.current,
    nextOrientation = orientationRef.current,
    nextTitle = titleRef.current,
  ) => (
    JSON.stringify(nextBlocks) !== JSON.stringify(savedBlocksRef.current)
    || JSON.stringify(nextPolicy) !== JSON.stringify(savedCurrencyPolicyRef.current)
    || nextOrientation !== savedOrientationRef.current
    || nextTitle !== savedTitleRef.current
  ), []);

  const announce = useCallback((message: string) => setEditorAnnouncement(message), []);
  const selectBlock = useCallback((blockId: string) => setSelectedBlockId(blockId), []);

  const resetDraft = useCallback((input: ResetReportDraftInput) => {
    const nextBlocks = copyDraftBlocks(input.blocks);
    const nextSavedBlocks = copyDraftBlocks(input.savedBlocks ?? input.blocks);
    const nextTitle = input.title ?? optionsRef.current.identity?.title ?? "보고서 초안";
    const nextSavedTitle = input.savedTitle ?? nextTitle;
    const nextOrientation = input.orientation ?? "landscape";
    const nextSavedOrientation = input.savedOrientation ?? nextOrientation;
    const nextPolicy = mergeDraftCurrencyPolicy(input.currencyPolicy);
    const nextSavedPolicy = mergeDraftCurrencyPolicy(input.savedCurrencyPolicy ?? input.currencyPolicy);
    blocksRef.current = nextBlocks;
    savedBlocksRef.current = nextSavedBlocks;
    titleRef.current = nextTitle;
    savedTitleRef.current = nextSavedTitle;
    orientationRef.current = nextOrientation;
    savedOrientationRef.current = nextSavedOrientation;
    currencyPolicyRef.current = nextPolicy;
    savedCurrencyPolicyRef.current = nextSavedPolicy;
    setBlocks(nextBlocks);
    setReportTitle(nextTitle);
    setHistory(EMPTY_HISTORY);
    setSelectedBlockId(input.selectedBlockId ?? nextBlocks[0]?.id ?? "");
    setReportOrientation(nextOrientation);
    setReportCurrencyPolicy(nextPolicy);
    setIsDirty(input.dirty ?? (
      JSON.stringify(nextBlocks) !== JSON.stringify(nextSavedBlocks)
      || JSON.stringify(nextPolicy) !== JSON.stringify(nextSavedPolicy)
      || nextOrientation !== nextSavedOrientation
      || nextTitle !== nextSavedTitle
    ));
    setSaveFailed(false);
    setSaving(false);
  }, []);

  const resetBlocks = useCallback((nextBlocks: readonly DraftReportBlock[], dirty = false) => {
    const next = copyDraftBlocks(nextBlocks);
    blocksRef.current = next;
    if (!dirty) savedBlocksRef.current = next;
    setBlocks(next);
    setHistory(EMPTY_HISTORY);
    setIsDirty(dirty || draftChanged(next));
    setSaveFailed(false);
    setSaving(false);
  }, [draftChanged]);

  const updateReportTitle = useCallback((title: string) => {
    if (!optionsRef.current.editable || title === titleRef.current) return;
    titleRef.current = title;
    setReportTitle(title);
    setIsDirty(draftChanged(blocksRef.current, currencyPolicyRef.current, orientationRef.current, title));
  }, [draftChanged]);

  const commitReportTitle = useCallback((previousTitle: string): boolean => {
    if (!optionsRef.current.editable || previousTitle === titleRef.current) return false;
    setHistory((value) => ({
      past: [...value.past.slice(-(HISTORY_LIMIT - 1)), createHistorySnapshot(
        previousTitle,
        blocksRef.current,
        orientationRef.current,
        currencyPolicyRef.current,
      )],
      future: [],
    }));
    return true;
  }, []);

  const commitBlocks = useCallback((updater, record = true): boolean => {
    if (!optionsRef.current.editable) return false;
    const current = blocksRef.current;
    const resolved = typeof updater === "function" ? updater(current) : updater;
    if (!resolved || resolved === current) return false;
    const next = copyDraftBlocks(resolved);
    if (record) {
      setHistory((value) => ({
        past: [...value.past.slice(-(HISTORY_LIMIT - 1)), createHistorySnapshot(
          titleRef.current,
          current,
          orientationRef.current,
          currencyPolicyRef.current,
        )],
        future: [],
      }));
    }
    blocksRef.current = next;
    setBlocks(next);
    setIsDirty(draftChanged(next));
    return true;
  }, [draftChanged]);

  const undo = useCallback(() => {
    if (!optionsRef.current.editable) return;
    setHistory((value) => {
      if (!value.past.length) return value;
      const current = createHistorySnapshot(
        titleRef.current,
        blocksRef.current,
        orientationRef.current,
        currencyPolicyRef.current,
      );
      const previous = value.past.at(-1);
      if (!previous) return value;
      const previousBlocks = copyDraftBlocks(previous.blocks);
      const previousPolicy = { ...previous.currencyPolicy };
      titleRef.current = previous.title;
      blocksRef.current = previousBlocks;
      orientationRef.current = previous.orientation;
      currencyPolicyRef.current = previousPolicy;
      setReportTitle(previous.title);
      setBlocks(previousBlocks);
      setReportOrientation(previous.orientation);
      setReportCurrencyPolicy(previousPolicy);
      setIsDirty(draftChanged(previousBlocks, previousPolicy, previous.orientation, previous.title));
      return {
        past: value.past.slice(0, -1),
        future: [current, ...value.future].slice(0, HISTORY_LIMIT),
      };
    });
  }, [draftChanged]);

  const redo = useCallback(() => {
    if (!optionsRef.current.editable) return;
    setHistory((value) => {
      if (!value.future.length) return value;
      const current = createHistorySnapshot(
        titleRef.current,
        blocksRef.current,
        orientationRef.current,
        currencyPolicyRef.current,
      );
      const [nextSnapshot, ...future] = value.future;
      const next = copyDraftBlocks(nextSnapshot.blocks);
      const nextPolicy = { ...nextSnapshot.currencyPolicy };
      titleRef.current = nextSnapshot.title;
      blocksRef.current = next;
      orientationRef.current = nextSnapshot.orientation;
      currencyPolicyRef.current = nextPolicy;
      setReportTitle(nextSnapshot.title);
      setBlocks(next);
      setReportOrientation(nextSnapshot.orientation);
      setReportCurrencyPolicy(nextPolicy);
      setIsDirty(draftChanged(next, nextPolicy, nextSnapshot.orientation, nextSnapshot.title));
      return { past: [...value.past, current].slice(-HISTORY_LIMIT), future };
    });
  }, [draftChanged]);

  const updateBlock = useCallback((blockId: string, change: Partial<DraftReportBlock>, record = true) => {
    commitBlocks((current) => {
      const next = current.map((block) => block.id === blockId
        ? {
            ...block,
            ...change,
            ...(Object.hasOwn(change, "content") && change.content !== block.content
              && !Object.hasOwn(change, "evidenceRefs") ? { evidenceRefs: [] } : {}),
          }
        : block);
      if (!Object.hasOwn(change, "content")) return next;
      return resolveDraftLayoutCollisions(next.map((block) => (
        block.id === blockId && block.type === "text"
          ? { ...block, h: frontendTextBlockLayout(block, orientationRef.current).height }
          : block
      )), blockId) as readonly DraftReportBlock[];
    }, record);
  }, [commitBlocks]);

  const moveBlock = useCallback((blockId: string, deltaX: number, deltaY: number) => {
    const source = blocksRef.current.find((block) => block.id === blockId);
    if (!source) return;
    const x = Math.min(12 - source.w, Math.max(0, source.x + deltaX));
    const y = Math.max(0, source.y + deltaY);
    if (x === source.x && y === source.y) return;
    if (commitBlocks((current) => placeDraftBlock(current, blockId, x, y) as readonly DraftReportBlock[])) {
      announce(`${source.title || "제목 없음"} 블록을 ${y + 1}행 ${x + 1}열로 이동했습니다.`);
    }
  }, [announce, commitBlocks]);

  const resizeBlock = useCallback((
    blockId: string,
    requestedWidth: number,
    requestedHeight?: number,
    requestedPosition?: { readonly x: number; readonly y: number },
  ) => {
    const result = resizeDraftBlocks(
      blocksRef.current,
      blockId,
      requestedWidth,
      requestedHeight,
      orientationRef.current,
      requestedPosition,
    );
    if (result && commitBlocks(result.blocks)) announce(result.announcement);
  }, [announce, commitBlocks]);

  const compactLayout = useCallback((): boolean => {
    const current = blocksRef.current;
    const compacted = compactDraftLayout(current) as readonly DraftReportBlock[];
    if (JSON.stringify(compacted) === JSON.stringify(current)) { announce("블록이 이미 읽는 순서대로 정리되어 있습니다."); return false; }
    const committed = commitBlocks(compacted);
    if (committed) announce("겹친 블록을 읽는 순서대로 정리했습니다.");
    return committed;
  }, [announce, commitBlocks]);

  const setBlockSetting = useCallback((blockId: string, name: string, value: unknown) => {
    const source = blocksRef.current.find((block) => block.id === blockId);
    if (!source) return;
    const settings = { ...readDraftBlockSettings(source), [name]: value };
    const wholeAuto = source.type === "artifact"
      && (name === "sizeMode" ? value === "auto" : wholeArtifactSettings(source)?.sizeMode === "auto");
    const viewAuto = ["chart", "table"].includes(source.type ?? "")
      && (name === "sizeMode" ? value === "auto" : artifactViewBlockSettings(source)?.sizeMode === "auto");
    if (!wholeAuto && !viewAuto) {
      updateBlock(blockId, { content: JSON.stringify(settings) });
      return;
    }
    const artifact = source.artifactId ? optionsRef.current.artifacts?.[source.artifactId] : undefined;
    if (commitBlocks((current) => resolveDraftLayoutCollisions(current.map((block) => {
      if (block.id !== blockId) return block;
      return wholeAuto
        ? fitFrontendArtifactBlock(block, artifact, { orientation: orientationRef.current, force: true, settings })
        : fitFrontendArtifactViewBlock(block, artifact, { orientation: orientationRef.current, force: true, settings });
    }), blockId) as readonly DraftReportBlock[])) {
      announce(`${source.title || "분석 결과"} 블록 크기를 내용에 맞췄습니다.`);
    }
  }, [announce, commitBlocks, updateBlock]);

  const reportContext = useCallback((orientation = orientationRef.current) => ({
    definitionId: optionsRef.current.identity?.definitionId || "report-draft",
    version: optionsRef.current.identity?.version || 1,
    title: titleRef.current || "보고서 초안",
    orientation,
    currencyPolicy: currencyPolicyRef.current,
  }), []);

  const addTemplateBlock = useCallback((templateId: string, position: DraftInsertPosition | null = null, settings: { readonly chartType?: string } = {}): boolean => {
    if (!optionsRef.current.editable) return false;
    const template = optionsRef.current.templates?.get(templateId);
    if (!template) return false;
    const current = blocksRef.current;
    let block: DraftReportBlock;
    if (!templateId.startsWith("artifact-")) {
      block = createTextTemplateBlock(template, position, current, orientationRef.current);
    } else {
      const view = template.view;
      if (!view || !["summary", "kpi", "chart", "table"].includes(view)) return false;
      const sources = optionsRef.current.artifactSources ?? [];
      const source = sources.find((item) => item.artifactId === settings.artifactId)
        ?? sources.find((item) => item.artifactId === optionsRef.current.selectedArtifactId)
        ?? sources[0];
      if (!source?.artifactId) {
        optionsRef.current.onNotice?.("먼저 사용할 분석 원본을 선택해 주세요.");
        return false;
      }
      const artifact = optionsRef.current.artifacts?.[source.artifactId];
      if (!availableArtifactViews(artifact).includes(view)) {
        optionsRef.current.onNotice?.(`선택한 분석 결과에는 ${ARTIFACT_VIEW_LABELS[view]} 데이터가 없습니다.`);
        return false;
      }
      const sourceTitle = source.title || source.definitionTitle || "분석 결과";
      const title = artifactViewTitle(sourceTitle, view);
      const analysisSource = source.sourceKind === "analysisRun" || source.artifactSourceKind === "analysisRun";
      if (["summary", "kpi"].includes(view)) {
        const blockId = createUuid();
        const layout = estimateArtifactBlockLayout(artifact, {
          orientation: orientationRef.current,
          visibleViews: [view],
          ...(position?.w ? { width: position.w } : {}),
        });
        const result = insertFrontendArtifact(current, {
          blockId,
          title,
          artifactId: source.artifactId,
          artifactChecksum: source.artifactChecksum,
          queryId: source.queryId,
          ...(!analysisSource ? {
            artifactDefinitionId: source.definitionId,
            artifactDefinitionVersion: source.definitionVersion,
          } : {
            sourceKind: "analysisRun",
            requestId: source.requestId || source.artifactRequestId,
            analysisDefinitionId: source.analysisDefinitionId,
            analysisDefinitionVersion: source.analysisDefinitionVersion,
          }),
          question: source.question,
          sourceUrns: source.sourceUrns,
          artifact,
          visibleViews: [view],
          sizeMode: "auto",
          width: position?.w ?? layout.width,
          height: layout.height,
          placement: position?.placement || { type: "end", pageId: position?.pageId },
        }, reportContext());
        if (!result.ok) {
          optionsRef.current.onError?.(result.errors?.[0] || `${ARTIFACT_VIEW_LABELS[view]} 요소를 추가하지 못했습니다.`);
          return false;
        }
        const inserted = result.blocks.find((item) => item.id === blockId);
        const positioned = position && (position.x !== undefined || position.y !== undefined)
          ? placeDraftBlock(
              result.blocks,
              blockId,
              position.requestedX ?? position.x ?? inserted?.x ?? 0,
              position.y ?? inserted?.y ?? 0,
            ) as readonly DraftReportBlock[]
          : result.blocks;
        if (!commitBlocks(positioned)) return false;
        selectBlock(blockId);
        optionsRef.current.onNotice?.(`${ARTIFACT_VIEW_LABELS[view]} 요소를 독립 블록으로 추가했습니다.`);
        return true;
      }
      const type = view === "chart" ? "chart" : "table";
      const defaultY = current.reduce((bottom, item) => Math.max(bottom, item.y + item.h), 0);
      const adaptiveLayout = estimateArtifactViewBlockLayout(
        { type, ...(position?.w ? { w: position.w, columns: position.w } : {}) },
        artifact,
        { orientation: orientationRef.current, autoWidth: !position?.w },
      );
      const width = position?.w ?? adaptiveLayout.width;
      block = fitFrontendArtifactViewBlock({
        ...source,
        id: createUuid(),
        type,
        title,
        content: type === "chart"
          ? JSON.stringify({ showLegend: true, sizeMode: "auto", ...(settings.chartType ? { chartType: settings.chartType } : {}) })
          : JSON.stringify({ density: "comfortable", sizeMode: "auto" }),
        x: Math.min(position?.x ?? 0, 12 - width),
        y: position?.y ?? defaultY,
        w: width,
        columns: width,
        h: template.h,
      }, artifact, { orientation: orientationRef.current, force: true });
    }
    const requestedX = position?.requestedX ?? block.x;
    const committed = commitBlocks((existing) => {
      const placed = placeDraftBlock([...existing, block], block.id, requestedX, block.y) as readonly DraftReportBlock[];
      return templateId.startsWith("artifact-")
        ? fitAutoArtifactViewLayout(placed, optionsRef.current.artifacts ?? {}, orientationRef.current)
        : placed;
    });
    if (!committed) return false;
    selectBlock(block.id);
    if (template.view) optionsRef.current.onNotice?.(`${ARTIFACT_VIEW_LABELS[template.view]} 요소를 독립 블록으로 추가했습니다.`);
    return true;
  }, [commitBlocks, reportContext, selectBlock]);

  const duplicateBlock = useCallback((blockId: string) => {
    const current = blocksRef.current;
    const source = current.find((block) => block.id === blockId);
    if (!source) return;
    const duplicate = {
      ...source,
      id: createUuid(),
      title: source.type === "text" ? `${source.title} 복사본` : source.title,
      y: source.y + source.h,
    };
    if (commitBlocks(placeDraftBlock([...current, duplicate], duplicate.id, duplicate.x, duplicate.y) as readonly DraftReportBlock[])) {
      selectBlock(duplicate.id);
    }
  }, [commitBlocks, selectBlock]);

  const deleteBlock = useCallback((blockId: string) => {
    const ordered = [...blocksRef.current].sort((left, right) => left.y - right.y || left.x - right.x);
    const index = ordered.findIndex((block) => block.id === blockId);
    const nextFocusId = ordered[index + 1]?.id || ordered[index - 1]?.id || "";
    const deleted = deleteFrontendBlock(blocksRef.current, blockId, reportContext());
    const next = deleted.ok
      ? deleted.blocks
      : blocksRef.current.filter((block) => block.id !== blockId);
    if (!commitBlocks(next as readonly DraftReportBlock[])) return;
    selectBlock(nextFocusId);
    optionsRef.current.onNotice?.("블록을 삭제했습니다. 실행 취소로 되돌릴 수 있습니다.");
    optionsRef.current.onFocusRequest?.(nextFocusId);
  }, [commitBlocks, reportContext, selectBlock]);

  const fitHydratedArtifactViews = useCallback((artifactMap = optionsRef.current.artifacts ?? {}): boolean => {
    if (!optionsRef.current.editable) return false;
    const current = blocksRef.current;
    const normalizeTitles = (items: readonly DraftReportBlock[]) => items.map((block) => {
      const artifact = block.artifactId ? artifactMap[block.artifactId] : undefined;
      if (!artifact) return block;
      const title = normalizeGeneratedArtifactViewTitle(block.title, artifact, block.type);
      return title === block.title ? block : { ...block, title };
    });
    const migrated = splitLegacyCompositeArtifactBlocks(
      current,
      artifactMap,
      optionsRef.current.artifactSources ?? [],
      orientationRef.current,
      createUuid,
    );
    const fitted = fitAutoArtifactViewLayout(
      normalizeTitles(migrated.blocks),
      artifactMap,
      orientationRef.current,
    );
    if (JSON.stringify(fitted) === JSON.stringify(current)) return false;
    const fittedSaved = fitAutoArtifactViewLayout(
      normalizeTitles(savedBlocksRef.current),
      artifactMap,
      savedOrientationRef.current,
    );
    blocksRef.current = copyDraftBlocks(fitted);
    savedBlocksRef.current = copyDraftBlocks(fittedSaved);
    setBlocks(blocksRef.current);
    setIsDirty(migrated.migratedSourceCount > 0 || draftChanged(blocksRef.current));
    announce(migrated.migratedSourceCount > 0
      ? `이전 합본 분석 요소 ${migrated.migratedSourceCount}개를 독립 블록으로 정리했습니다. 검토한 뒤 저장해 주세요.`
      : "차트와 표 높이를 실제 데이터에 맞춰 조정했습니다.");
    return true;
  }, [announce, draftChanged]);

  const changeOrientation = useCallback((orientation: "portrait" | "landscape"): boolean => {
    if (!optionsRef.current.editable || orientation === orientationRef.current) return false;
    const previousSnapshot = createHistorySnapshot(
      titleRef.current,
      blocksRef.current,
      orientationRef.current,
      currencyPolicyRef.current,
    );
    const artifacts = optionsRef.current.artifacts ?? {};
    const contentSized = compactDraftLayout(blocksRef.current.map((block) => (
      block.type === "text"
        ? { ...block, h: frontendTextBlockLayout(block, orientation).height }
        : block.type === "artifact" && wholeArtifactSettings(block)?.sizeMode === "auto"
          ? fitFrontendArtifactBlock(block, block.artifactId ? artifacts[block.artifactId] : undefined, { orientation })
          : ["chart", "table"].includes(block.type ?? "") && artifactViewBlockSettings(block)?.sizeMode === "auto"
            ? fitFrontendArtifactViewBlock(block, block.artifactId ? artifacts[block.artifactId] : undefined, { orientation })
            : block
    ))) as readonly DraftReportBlock[];
    const reflowed = orientFrontendBlocks(contentSized, orientation, reportContext(orientation));
    if (!reflowed.ok) {
      optionsRef.current.onError?.(reflowed.errors?.[0] || "A4 방향에 맞게 보고서를 재배치하지 못했습니다.");
      return false;
    }
    setHistory((value) => ({
      past: [...value.past.slice(-(HISTORY_LIMIT - 1)), previousSnapshot],
      future: [],
    }));
    orientationRef.current = orientation;
    setReportOrientation(orientation);
    commitBlocks(fitAutoArtifactViewLayout(reflowed.blocks, artifacts, orientation), false);
    setIsDirty(draftChanged(blocksRef.current, currencyPolicyRef.current, orientation));
    return true;
  }, [commitBlocks, draftChanged, reportContext]);

  const changeCurrencyDisplayUnit = useCallback((displayUnit) => {
    if (!optionsRef.current.editable || displayUnit === currencyPolicyRef.current.displayUnit) return;
    const previousSnapshot = createHistorySnapshot(
      titleRef.current,
      blocksRef.current,
      orientationRef.current,
      currencyPolicyRef.current,
    );
    const next = { ...currencyPolicyRef.current, displayUnit };
    setHistory((value) => ({
      past: [...value.past.slice(-(HISTORY_LIMIT - 1)), previousSnapshot],
      future: [],
    }));
    currencyPolicyRef.current = next;
    setReportCurrencyPolicy(next);
    setIsDirty(draftChanged(blocksRef.current, next));
  }, [draftChanged]);

  const beginSave = useCallback(() => {
    setSaving(true);
    setSaveFailed(false);
  }, []);
  const markSaved = useCallback(() => {
    savedBlocksRef.current = copyDraftBlocks(blocksRef.current);
    savedTitleRef.current = titleRef.current;
    savedOrientationRef.current = orientationRef.current;
    savedCurrencyPolicyRef.current = { ...currencyPolicyRef.current };
    setSaving(false);
    setSaveFailed(false);
    setIsDirty(false);
  }, []);
  const markSaveFailed = useCallback(() => {
    setSaving(false);
    setSaveFailed(true);
  }, []);
  const clearSaveFailure = useCallback(() => setSaveFailed(false), []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    window.dispatchEvent(new CustomEvent("answervice:report-dirty", { detail: isDirty }));
    if (!isDirty) return () => {
      window.dispatchEvent(new CustomEvent("answervice:report-dirty", { detail: false }));
    };
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", warnBeforeUnload);
      window.dispatchEvent(new CustomEvent("answervice:report-dirty", { detail: false }));
    };
  }, [isDirty]);

  const orderedBlocks = useMemo(
    () => [...blocks].sort((left, right) => left.y - right.y || left.x - right.x),
    [blocks],
  );
  const selectedBlock = useMemo(
    () => blocks.find((block) => block.id === selectedBlockId) ?? null,
    [blocks, selectedBlockId],
  );
  const saveState = saving ? "saving" : saveFailed ? "error" : isDirty ? "unsaved" : "saved";

  return useMemo(() => ({
    blocks,
    orderedBlocks,
    blocksRef,
    savedBlocksRef,
    reportTitle,
    titleRef,
    savedTitleRef,
    selectedBlockId,
    selectedBlock,
    history,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    isDirty,
    saveFailed,
    saveState,
    editorAnnouncement,
    reportOrientation,
    reportCurrencyPolicy,
    savedOrientationRef,
    currencyPolicyRef,
    savedCurrencyPolicyRef,
    selectBlock,
    announce,
    resetDraft,
    resetBlocks,
    updateReportTitle,
    commitReportTitle,
    commitBlocks,
    beginSave,
    markSaved,
    markSaveFailed,
    clearSaveFailure,
    undo,
    redo,
    updateBlock,
    moveBlock,
    resizeBlock,
    compactLayout,
    setBlockSetting,
    addTemplateBlock,
    duplicateBlock,
    deleteBlock,
    fitHydratedArtifactViews,
    changeOrientation,
    changeCurrencyDisplayUnit,
  }), [
    addTemplateBlock, announce, beginSave, blocks, changeCurrencyDisplayUnit, changeOrientation,
    clearSaveFailure, commitBlocks, commitReportTitle, deleteBlock, duplicateBlock, editorAnnouncement,
    fitHydratedArtifactViews, history, isDirty, markSaveFailed, markSaved,
    compactLayout, moveBlock, orderedBlocks, redo, reportCurrencyPolicy, reportOrientation, reportTitle, resetBlocks,
    resetDraft, resizeBlock, saveFailed, saveState, selectBlock, selectedBlock,
    selectedBlockId, setBlockSetting, undo, updateBlock, updateReportTitle,
  ]);
}
