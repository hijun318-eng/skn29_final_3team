/** 저장 payload와 분리된 선택·잠금·검색·복원 지점·클립보드 편집 편의를 관리한다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createUuid } from "../../utils/createUuid.ts";
import { compactDraftLayout } from "../../contracts/report.ts";

const SNAPSHOT_LIMIT = 20;

const TEXT_SIZE_PRESETS = [
  ["아주 작게", 4, 4], ["작게", 5, 4], ["좁게", 6, 5], ["반쪽", 7, 5],
  ["넓게", 8, 6], ["크게", 9, 7], ["거의 전체", 10, 8], ["전체", 12, 10],
];
const DATA_SIZE_PRESETS = [
  ["아주 작게", 6, 5], ["작게", 6, 7], ["좁게", 7, 7], ["반쪽", 8, 8],
  ["넓게", 9, 9], ["크게", 10, 10], ["거의 전체", 11, 11], ["전체", 12, 12],
];

/** 12-column 저장 좌표를 유지하면서 사용자에게 8개 정돈 크기를 제공한다. */
export function reportSizePresets(block, orientation = "landscape") {
  if (!block) return [];
  const source = block.type === "text" ? TEXT_SIZE_PRESETS : DATA_SIZE_PRESETS;
  const portraitExtra = orientation === "portrait" ? 1 : 0;
  return source.map(([label, width, height], index) => ({
    index: index + 1,
    label,
    width,
    height: Math.min(block.type === "text" ? 14 : 18, height + portraitExtra),
  }));
}

/** 제목과 실제 text 본문만 검색하고 설정 JSON은 결과에서 제외한다. */
export function searchReportBlocks(blocks, query) {
  const needle = query.trim().toLocaleLowerCase("ko-KR");
  if (!needle) return [];
  return blocks.filter((block) => {
    const title = String(block.title ?? "").toLocaleLowerCase("ko-KR");
    const body = block.type === "text"
      ? String(block.content ?? "").toLocaleLowerCase("ko-KR")
      : "";
    return title.includes(needle) || body.includes(needle);
  });
}

/** 블록의 Artifact lineage 필드를 유지하면서 세션 작업용 독립 배열을 만든다. */
export function copyReportBlocks(blocks) {
  return blocks.map((block) => ({
    ...block,
    ...(Array.isArray(block.sourceUrns) ? { sourceUrns: [...block.sourceUrns] } : {}),
  }));
}

/** API/undo payload에 섞이지 않는 편집기 세션 상태와 일괄 명령을 제공한다. */
export function useReportEditorTools({
  blocks,
  commitBlocks,
  orientation,
  primaryBlockId,
  reportKey,
  requestFocus,
  resizeBlock,
  selectPrimary,
}) {
  const [selectedBlockIds, setSelectedBlockIds] = useState(() => new Set());
  const [lockedBlockIds, setLockedBlockIds] = useState(() => new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [snapshots, setSnapshots] = useState([]);
  const clipboardRef = useRef([]);

  useEffect(() => {
    setSelectedBlockIds(primaryBlockId ? new Set([primaryBlockId]) : new Set());
    setLockedBlockIds(new Set());
    setSearchQuery("");
    setSnapshots([]);
    clipboardRef.current = [];
  }, [reportKey]);

  useEffect(() => {
    const validIds = new Set(blocks.map((block) => block.id));
    setSelectedBlockIds((current) => {
      const next = new Set([...current].filter((id) => validIds.has(id)));
      if (primaryBlockId && !next.has(primaryBlockId)) next.add(primaryBlockId);
      return next;
    });
    setLockedBlockIds((current) => new Set([...current].filter((id) => validIds.has(id))));
  }, [blocks, primaryBlockId]);

  const selectBlock = useCallback((blockId, event) => {
    const additive = Boolean(event?.shiftKey);
    if (!additive) {
      setSelectedBlockIds(new Set([blockId]));
      selectPrimary(blockId);
      return;
    }
    const next = new Set(selectedBlockIds);
    if (next.has(blockId)) next.delete(blockId); else next.add(blockId);
    setSelectedBlockIds(next);
    if (!next.has(primaryBlockId)) selectPrimary([...next][0] ?? "");
  }, [primaryBlockId, selectPrimary, selectedBlockIds]);
  const clearSelection = useCallback(() => {
    setSelectedBlockIds(new Set());
    selectPrimary("");
  }, [selectPrimary]);

  const toggleBlockLock = useCallback((blockId) => {
    setLockedBlockIds((current) => {
      const next = new Set(current);
      if (next.has(blockId)) next.delete(blockId); else next.add(blockId);
      return next;
    });
  }, []);

  const setSelectedLocks = useCallback((locked) => {
    setLockedBlockIds((current) => {
      const next = new Set(current);
      selectedBlockIds.forEach((id) => locked ? next.add(id) : next.delete(id));
      return next;
    });
  }, [selectedBlockIds]);

  const deleteBlocks = useCallback((ids) => {
    if ([...ids].some((id) => lockedBlockIds.has(id))) return false;
    const deletable = new Set(ids);
    if (!deletable.size) return false;
    const ordered = compactDraftLayout(blocks.filter((block) => !deletable.has(block.id)));
    if (!commitBlocks(ordered)) return false;
    const nextId = ordered[0]?.id ?? "";
    setSelectedBlockIds(nextId ? new Set([nextId]) : new Set());
    selectPrimary(nextId);
    if (nextId) requestFocus(nextId);
    return true;
  }, [blocks, commitBlocks, lockedBlockIds, requestFocus, selectPrimary]);

  const deleteSelected = useCallback(
    () => deleteBlocks(selectedBlockIds),
    [deleteBlocks, selectedBlockIds],
  );
  const deleteBlock = useCallback(
    (blockId) => deleteBlocks(new Set([blockId])),
    [deleteBlocks],
  );

  const copySelected = useCallback(() => {
    clipboardRef.current = copyReportBlocks(blocks.filter((block) => selectedBlockIds.has(block.id)));
    return clipboardRef.current.length;
  }, [blocks, selectedBlockIds]);

  const pasteBlocks = useCallback(() => {
    if (!clipboardRef.current.length) return false;
    const source = copyReportBlocks(clipboardRef.current);
    const minY = Math.min(...source.map((block) => block.y ?? 0));
    const startY = blocks.reduce((bottom, block) => Math.max(bottom, (block.y ?? 0) + (block.h ?? 1)), 0);
    const pasted = source.map((block) => ({
      ...block,
      id: createUuid(),
      title: `${block.title || "제목 없음"} 복사본`,
      y: startY + (block.y ?? 0) - minY,
    }));
    if (!commitBlocks(compactDraftLayout([...blocks, ...pasted]))) return false;
    const ids = new Set(pasted.map((block) => block.id));
    const primary = pasted[0]?.id ?? "";
    setSelectedBlockIds(ids);
    selectPrimary(primary);
    if (primary) requestFocus(primary);
    return true;
  }, [blocks, commitBlocks, requestFocus, selectPrimary]);

  const searchResults = useMemo(
    () => searchReportBlocks(blocks, searchQuery),
    [blocks, searchQuery],
  );
  const focusSearchResult = useCallback((blockId) => {
    setSelectedBlockIds(new Set([blockId]));
    selectPrimary(blockId);
    requestFocus(blockId);
  }, [requestFocus, selectPrimary]);

  const createSnapshot = useCallback((name) => {
    const snapshot = {
      id: createUuid(),
      name: name.trim() || `복원 지점 ${snapshots.length + 1}`,
      createdAt: new Date().toISOString(),
      blocks: copyReportBlocks(blocks),
    };
    setSnapshots((current) => [snapshot, ...current].slice(0, SNAPSHOT_LIMIT));
    return snapshot;
  }, [blocks, snapshots.length]);

  const restoreSnapshot = useCallback((snapshotId) => {
    const snapshot = snapshots.find((item) => item.id === snapshotId);
    if (!snapshot || !commitBlocks(copyReportBlocks(snapshot.blocks))) return false;
    const primary = snapshot.blocks[0]?.id ?? "";
    setSelectedBlockIds(primary ? new Set([primary]) : new Set());
    setLockedBlockIds(new Set());
    selectPrimary(primary);
    if (primary) requestFocus(primary);
    return true;
  }, [commitBlocks, requestFocus, selectPrimary, snapshots]);

  const removeSnapshot = useCallback((snapshotId) => {
    setSnapshots((current) => current.filter((item) => item.id !== snapshotId));
  }, []);

  const primaryBlock = useMemo(
    () => blocks.find((block) => block.id === primaryBlockId) ?? null,
    [blocks, primaryBlockId],
  );
  const sizePresets = useMemo(
    () => reportSizePresets(primaryBlock, orientation),
    [orientation, primaryBlock],
  );
  const resizePrimary = useCallback(
    (preset) => primaryBlock && resizeBlock(primaryBlock.id, preset.width, preset.height),
    [primaryBlock, resizeBlock],
  );

  return {
    clearSelection,
    copySelected,
    createSnapshot,
    deleteBlock,
    deleteSelected,
    focusSearchResult,
    lockedBlockIds,
    pasteBlocks,
    primaryBlock,
    removeSnapshot,
    restoreSnapshot,
    searchQuery,
    searchResults,
    selectBlock,
    selectedBlockIds,
    setSearchQuery,
    setSelectedLocks,
    sizePresets,
    snapshots,
    toggleBlockLock,
    resizePrimary,
  };
}
