/** 보고서 block의 pointer·touch·keyboard drag와 접근성 안내를 조정하는 hook 모듈이다. */
import { useCallback, useRef, useState } from "react";
import { KeyboardSensor, PointerSensor, TouchSensor, useSensor, useSensors } from "@dnd-kit/core";

import { isDraftLayoutValid, placeDraftBlock } from "../../contracts/report.ts";
import { keyboardEndDropPosition, moveFrontendBlock } from "./reportDraftV2.js";

const ARTIFACT_VIEW_DRAG_PREFIX = "artifact-view:";

/** 분석 결과 ID와 보기 template을 결합한 library drag ID를 안전하게 분리한다. */
export function parseArtifactViewDragId(value) {
  const id = String(value || "");
  if (!id.startsWith(ARTIFACT_VIEW_DRAG_PREFIX)) return null;
  const encoded = id.slice(ARTIFACT_VIEW_DRAG_PREFIX.length);
  const templateMarker = encoded.lastIndexOf(":artifact-");
  if (templateMarker <= 0) return null;
  return {
    artifactId: encoded.slice(0, templateMarker),
    templateId: encoded.slice(templateMarker + 1),
  };
}

/** 이동 대상과 형제 블록의 좌·중·우 및 상·중·하가 일치하는 12열 guide를 계산한다. */
export function computeReportAlignmentGuides(position, blocks, activeId) {
  if (!position) return null;
  const siblings = blocks.filter((block) => block.id !== activeId);
  const xPoints = [position.x, position.x + position.w / 2, position.x + position.w];
  const yPoints = [position.y, position.y + position.h / 2, position.y + position.h];
  const siblingX = new Set(siblings.flatMap((block) => {
    const x = block.x ?? 0;
    const width = block.w ?? block.columns ?? 12;
    return [x, x + width / 2, x + width];
  }));
  const siblingY = new Set(siblings.flatMap((block) => {
    const y = block.y ?? 0;
    const height = block.h ?? 1;
    return [y, y + height / 2, y + height];
  }));
  const vertical = [...new Set(xPoints.filter((value) => siblingX.has(value)))];
  const horizontal = [...new Set(yPoints.filter((value) => siblingY.has(value)))];
  return vertical.length || horizontal.length
    ? { pageId: position.pageId, vertical, horizontal }
    : null;
}

/** 선택 블록의 상대 배치를 유지하며 빈 12열 좌표로만 그룹을 이동한다. */
export function moveReportBlockGroup(blocks, blockIds, activeId, position) {
  const selectedIds = new Set(blockIds);
  const selected = blocks.filter((block) => selectedIds.has(block.id));
  const active = selected.find((block) => block.id === activeId);
  if (!active || selected.length < 2 || !position) return null;
  const requestedDeltaX = position.x - active.x;
  const requestedDeltaY = position.y - active.y;
  const minimumDeltaX = -Math.min(...selected.map((block) => block.x));
  const maximumDeltaX = Math.min(...selected.map((block) => 12 - block.w - block.x));
  const minimumDeltaY = -Math.min(...selected.map((block) => block.y));
  const deltaX = Math.max(minimumDeltaX, Math.min(maximumDeltaX, requestedDeltaX));
  const deltaY = Math.max(minimumDeltaY, requestedDeltaY);
  if (deltaX === 0 && deltaY === 0) return null;
  const moved = blocks.map((block) => selectedIds.has(block.id)
    ? { ...block, x: block.x + deltaX, y: block.y + deltaY }
    : block);
  return isDraftLayoutValid(moved) ? moved : null;
}

function reportKeyboardCoordinates(event, { currentCoordinates }) {
  const movement = {
    ArrowRight: [80, 0],
    ArrowLeft: [-80, 0],
    ArrowDown: [0, 72],
    ArrowUp: [0, -72],
  }[event.code];
  if (!movement) return undefined;
  event.preventDefault();
  return { x: currentCoordinates.x + movement[0], y: currentCoordinates.y + movement[1] };
}

/** pointer·touch·keyboard drag를 동일 배치 계약으로 조정하고 실패 시 기존 draft를 보존한다. */
export function useReportDragAndDrop({
  addTemplateBlock,
  blocksRef,
  commitBlocks,
  frontendReportContext,
  reportPages,
  reportTemplateMap,
  selectedBlockIds,
  lockedBlockIds,
  setEditorAnnouncement,
  selectDraggedBlock,
  viewArtifactTemplateFor,
}) {
  const [draggedBlockId, setDraggedBlockId] = useState("");
  const [draggedBlockIds, setDraggedBlockIds] = useState(() => new Set());
  const [dragDelta, setDragDelta] = useState(null);
  const [dropPosition, setDropPosition] = useState(null);
  const [alignmentGuides, setAlignmentGuides] = useState(null);
  const lastDropOutcomeRef = useRef({ success: false, message: "" });
  const pageCanvasRefs = useRef(new Map());
  const dragPointerRef = useRef(null);
  const pointerDragRef = useRef(false);
  const dropPositionRef = useRef(null);
  const draggedBlockIdsRef = useRef(new Set());
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: reportKeyboardCoordinates }),
  );

  const registerPageCanvas = useCallback((element, context) => {
    if (element) pageCanvasRefs.current.set(context.page.id, { element, page: context.page });
    else pageCanvasRefs.current.delete(context.page.id);
  }, []);

  const dragLabel = useCallback((activeId) => {
    const id = String(activeId);
    const artifactView = parseArtifactViewDragId(id);
    if (artifactView) {
      const source = artifactOptions.find((item) => item.artifactId === artifactView.artifactId);
      const view = artifactView.templateId === "artifact-chart" ? "차트" : "표";
      return `${source?.title || "분석 결과"} ${view} 블록`;
    }
    if (id.startsWith("template:")) return `${reportTemplateMap.get(id.slice("template:".length))?.title || "새"} 블록`;
    const block = blocksRef.current.find((item) => item.id === id);
    const type = block?.type === "artifact" ? "분석 결과" : block?.type === "chart" ? "차트" : block?.type === "table" ? "표" : "텍스트";
    return `${block?.title || "제목 없음"} ${type} 블록`;
  }, [blocksRef, reportTemplateMap]);

  const dragDestination = useCallback((active, delta) => {
    const activeId = String(active.id);
    const source = blocksRef.current.find((block) => block.id === activeId);
    const artifactView = parseArtifactViewDragId(activeId);
    const templateId = activeId.startsWith("template:")
      ? activeId.slice("template:".length)
      : artifactView?.templateId;
    const template = templateId
      ? viewArtifactTemplateFor(reportTemplateMap.get(templateId))
      : null;
    const dragTemplate = template;
    if (!source && !dragTemplate) return null;
    const initial = active.rect.current.initial;
    const center = pointerDragRef.current && dragPointerRef.current
      ? dragPointerRef.current
      : initial
        ? { x: initial.left + initial.width / 2 + delta.x, y: initial.top + initial.height / 2 + delta.y }
        : null;
    if (!center) return null;
    const targetCanvas = [...pageCanvasRefs.current.values()].find(({ element }) => {
      const bounds = element.getBoundingClientRect();
      return center.x >= bounds.left && center.x <= bounds.right && center.y >= bounds.top && center.y <= bounds.bottom;
    });
    if (!targetCanvas) return null;
    const { element: canvas, page } = targetCanvas;
    const styles = window.getComputedStyle(canvas);
    const bounds = canvas.getBoundingClientRect();
    const scale = canvas.offsetWidth ? bounds.width / canvas.offsetWidth : 1;
    const paddingLeft = (Number.parseFloat(styles.paddingLeft) || 0) * scale;
    const paddingRight = (Number.parseFloat(styles.paddingRight) || 0) * scale;
    const paddingTop = (Number.parseFloat(styles.paddingTop) || 0) * scale;
    const columnGap = (Number.parseFloat(styles.columnGap) || 0) * scale;
    const contentWidth = Math.max(1, bounds.width - paddingLeft - paddingRight);
    const columnStep = Math.max(1, (contentWidth - columnGap * 11) / 12 + columnGap);
    const rowHeight = (Number.parseFloat(styles.getPropertyValue("--report-grid-row")) || 56) * scale;
    const rowStep = rowHeight + (Number.parseFloat(styles.rowGap) || 0) * scale;
    const width = source ? source.w ?? source.columns : dragTemplate.w;
    const height = source ? source.h ?? 1 : dragTemplate.h;
    const pointerColumn = Math.min(11, Math.max(0, Math.floor((center.x - bounds.left - paddingLeft) / columnStep)));
    const pointerRow = Math.max(0, Math.floor((center.y - bounds.top - paddingTop) / rowStep)) + page.offsetY;
    const fullRowTarget = blocksRef.current.find((block) => (
      block.id !== activeId && (block.w ?? block.columns) === 12
      && pointerRow >= (block.y ?? 0) && pointerRow < (block.y ?? 0) + (block.h ?? 1)
    ));
    const contentTarget = fullRowTarget || blocksRef.current
      .filter((block) => block.id !== activeId)
      .sort((left, right) => Math.abs((left.y ?? 0) + (left.h ?? 1) / 2 - pointerRow) - Math.abs((right.y ?? 0) + (right.h ?? 1) / 2 - pointerRow))[0];
    const rawX = Math.round((center.x - bounds.left - paddingLeft) / columnStep - width / 2);
    const requestedX = fullRowTarget ? (pointerColumn < 6 ? 0 : 6) : Math.max(0, rawX);
    const dropWidth = fullRowTarget ? 6 : width;
    const dropHeight = !source && template?.id?.startsWith("artifact-")
      ? viewArtifactTemplateFor(template, dropWidth).h
      : height;
    const y = fullRowTarget
      ? fullRowTarget.y ?? 0
      : Math.max(page.offsetY, Math.round((center.y - bounds.top - paddingTop) / rowStep - dropHeight / 2) + page.offsetY);
    return {
      pageId: page.id,
      x: fullRowTarget ? (pointerColumn < 6 ? 0 : 6) : Math.min(12 - width, Math.max(0, rawX)),
      requestedX,
      y,
      w: dropWidth,
      h: dropHeight,
      placement: fullRowTarget
        ? { type: "side", targetBlockId: fullRowTarget.id, edge: pointerColumn < 6 ? "left" : "right" }
        : contentTarget
          ? { type: pointerRow < (contentTarget.y ?? 0) + (contentTarget.h ?? 1) / 2 ? "before" : "after", targetBlockId: contentTarget.id }
          : { type: "end", pageId: page.id },
    };
  }, [blocksRef, reportTemplateMap, viewArtifactTemplateFor]);

  const resetDrag = useCallback(() => {
    pointerDragRef.current = false;
    dragPointerRef.current = null;
    dropPositionRef.current = null;
    setDraggedBlockId("");
    setDraggedBlockIds(new Set());
    draggedBlockIdsRef.current = new Set();
    setDragDelta(null);
    setDropPosition(null);
    setAlignmentGuides(null);
  }, []);

  const handleDragStart = useCallback(({ active, activatorEvent }) => {
    const activeId = String(active.id);
    pointerDragRef.current = Number.isFinite(activatorEvent?.clientX) && Number.isFinite(activatorEvent?.clientY);
    dragPointerRef.current = pointerDragRef.current ? { x: activatorEvent.clientX, y: activatorEvent.clientY } : null;
    dropPositionRef.current = null;
    lastDropOutcomeRef.current = { success: false, message: "" };
    setDraggedBlockId(activeId);
    if (!activeId.startsWith("template:")) {
      const group = selectedBlockIds.has(activeId) ? new Set(selectedBlockIds) : new Set([activeId]);
      draggedBlockIdsRef.current = group;
      setDraggedBlockIds(group);
      selectDraggedBlock(activeId);
    }
  }, [selectDraggedBlock, selectedBlockIds]);

  const handleDragMove = useCallback(({ active, delta }) => {
    const position = dragDestination(active, delta);
    dropPositionRef.current = position;
    setDropPosition(position);
    setDragDelta(delta);
    const group = draggedBlockIdsRef.current;
    setAlignmentGuides(computeReportAlignmentGuides(
      position,
      blocksRef.current.filter((block) => !group.has(block.id) || block.id === String(active.id)),
      String(active.id),
    ));
  }, [blocksRef, dragDestination]);

  const handleDragEnd = useCallback(({ active, delta }) => {
    const activeId = String(active.id);
    const artifactView = parseArtifactViewDragId(activeId);
    const libraryTemplate = activeId.startsWith("template:")
      ? viewArtifactTemplateFor(reportTemplateMap.get(activeId.slice("template:".length)))
      : null;
    const keyboardPosition = !pointerDragRef.current && libraryTemplate
      ? keyboardEndDropPosition(blocksRef.current, { pageId: reportPages.at(-1)?.id, width: libraryTemplate.w, height: libraryTemplate.h })
      : null;
    const position = dropPositionRef.current ?? dragDestination(active, delta) ?? keyboardPosition;
    let succeeded = false;
    if (activeId.startsWith("template:")) {
      if (position) succeeded = addTemplateBlock(activeId.slice("template:".length), position);
    } else {
      const source = blocksRef.current.find((block) => block.id === activeId);
      if (position && source && (position.x !== source.x || position.y !== source.y)) {
        const groupIds = draggedBlockIdsRef.current;
        if (groupIds.size > 1) {
          const groupUnlocked = [...groupIds].every((id) => !lockedBlockIds.has(id));
          const moved = groupUnlocked
            ? moveReportBlockGroup(blocksRef.current, groupIds, activeId, position)
            : null;
          succeeded = Boolean(moved && commitBlocks(moved));
        } else {
          succeeded = commitBlocks((current) => {
            const moved = moveFrontendBlock(current, activeId, position.placement, frontendReportContext());
            return moved.ok ? moved.blocks : placeDraftBlock(current, activeId, position.requestedX, position.y);
          });
        }
      }
    }
    const pageNumber = position
      ? Math.max(1, reportPages.findIndex((page) => page.id === position.pageId) + 1)
      : 1;
    const message = succeeded
      ? `${dragLabel(activeId)}을 ${pageNumber}페이지 ${position.y + 1}번째 줄에 놓았습니다.`
      : `${dragLabel(activeId)}은 유효한 위치가 없어 이동을 취소했습니다. 원래 구성을 유지합니다.`;
    lastDropOutcomeRef.current = { success: succeeded, message };
    setEditorAnnouncement(message);
    resetDrag();
  }, [addTemplateBlock, blocksRef, commitBlocks, dragDestination, dragLabel, frontendReportContext, lockedBlockIds, reportPages, reportTemplateMap, resetDrag, setEditorAnnouncement, viewArtifactTemplateFor]);

  const handleDragCancel = useCallback(({ active }) => {
    const message = `${dragLabel(active.id)} 이동을 취소했습니다. 원래 위치를 유지합니다.`;
    lastDropOutcomeRef.current = { success: false, message };
    setEditorAnnouncement(message);
    resetDrag();
  }, [dragLabel, resetDrag, setEditorAnnouncement]);

  const handlePointerMove = useCallback((event) => {
    if (pointerDragRef.current) dragPointerRef.current = { x: event.clientX, y: event.clientY };
  }, []);

  const dragPositionMessage = useCallback((activeId) => {
    const position = dropPositionRef.current;
    if (position) {
      const pageNumber = Math.max(1, reportPages.findIndex((page) => page.id === position.pageId) + 1);
      return `${dragLabel(activeId)}, ${pageNumber}페이지 ${position.y + 1}번째 줄, 가로 위치 ${position.x + 1}`;
    }
    const block = blocksRef.current.find((item) => item.id === String(activeId));
    return block ? `${dragLabel(activeId)}, ${Number(block.y ?? 0) + 1}번째 줄, 가로 위치 ${Number(block.x ?? 0) + 1}` : dragLabel(activeId);
  }, [blocksRef, dragLabel, reportPages]);

  return {
    alignmentGuides,
    accessibility: {
      screenReaderInstructions: { draggable: "블록을 이동하려면 Enter 또는 Space를 누르세요. 방향키로 위치를 바꾸고 Enter 또는 Space로 놓습니다. Escape를 누르면 취소합니다." },
      announcements: {
        onDragStart: ({ active }) => `${dragLabel(active.id)} 이동을 시작했습니다. 방향키로 위치를 선택하세요.`,
        onDragMove: ({ active }) => dragPositionMessage(active.id),
        onDragEnd: ({ active }) => lastDropOutcomeRef.current.message || `${dragLabel(active.id)} 이동을 종료했습니다. 문서 구성을 확인해 주세요.`,
        onDragCancel: ({ active }) => `${dragLabel(active.id)} 이동을 취소했습니다. 원래 위치를 유지합니다.`,
      },
    },
    draggedBlockId,
    draggedBlockIds,
    dragDelta,
    dropPosition,
    handleDragCancel,
    handleDragEnd,
    handleDragMove,
    handleDragStart,
    handlePointerMove,
    pageCanvasRefs,
    registerPageCanvas,
    sensors,
  };
}
