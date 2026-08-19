/** 보고서 block의 pointer·touch·keyboard drag와 접근성 안내를 조정하는 hook 모듈이다. */
import { useCallback, useRef, useState } from "react";
import { KeyboardSensor, PointerSensor, TouchSensor, useSensor, useSensors } from "@dnd-kit/core";

import { placeDraftBlock } from "../../contracts/report";
import { keyboardEndDropPosition, moveFrontendBlock } from "./reportDraftV2";

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
  addWholeArtifact,
  artifactOptions,
  blocksRef,
  commitBlocks,
  frontendReportContext,
  reportPages,
  reportTemplateMap,
  setEditorAnnouncement,
  setSelectedBlockId,
  viewArtifactTemplateFor,
  wholeArtifactTemplateFor,
}) {
  const [draggedBlockId, setDraggedBlockId] = useState("");
  const [dropPosition, setDropPosition] = useState(null);
  const lastDropOutcomeRef = useRef({ success: false, message: "" });
  const pageCanvasRefs = useRef(new Map());
  const dragPointerRef = useRef(null);
  const pointerDragRef = useRef(false);
  const dropPositionRef = useRef(null);
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
    if (id.startsWith("template:")) return `${reportTemplateMap.get(id.slice("template:".length))?.title || "새"} 블록`;
    if (id.startsWith("artifact:")) return `${artifactOptions.find((item) => item.artifactId === id.slice("artifact:".length))?.title || "분석 결과"} Artifact 전체 블록`;
    const block = blocksRef.current.find((item) => item.id === id);
    const type = block?.type === "artifact" ? "Artifact 전체" : block?.type === "chart" ? "차트" : block?.type === "table" ? "표" : "텍스트";
    return `${block?.title || "제목 없음"} ${type} 블록`;
  }, [artifactOptions, blocksRef, reportTemplateMap]);

  const dragDestination = useCallback((active, delta) => {
    const activeId = String(active.id);
    const source = blocksRef.current.find((block) => block.id === activeId);
    const template = activeId.startsWith("template:")
      ? viewArtifactTemplateFor(reportTemplateMap.get(activeId.slice("template:".length)))
      : null;
    const libraryArtifact = activeId.startsWith("artifact:")
      ? artifactOptions.find((item) => item.artifactId === activeId.slice("artifact:".length))
      : null;
    const dragTemplate = template || (libraryArtifact ? wholeArtifactTemplateFor(libraryArtifact) : null);
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
      : !source && libraryArtifact
        ? wholeArtifactTemplateFor(libraryArtifact, dropWidth).h
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
  }, [artifactOptions, blocksRef, reportTemplateMap, viewArtifactTemplateFor, wholeArtifactTemplateFor]);

  const resetDrag = useCallback(() => {
    pointerDragRef.current = false;
    dragPointerRef.current = null;
    dropPositionRef.current = null;
    setDraggedBlockId("");
    setDropPosition(null);
  }, []);

  const handleDragStart = useCallback(({ active, activatorEvent }) => {
    const activeId = String(active.id);
    pointerDragRef.current = Number.isFinite(activatorEvent?.clientX) && Number.isFinite(activatorEvent?.clientY);
    dragPointerRef.current = pointerDragRef.current ? { x: activatorEvent.clientX, y: activatorEvent.clientY } : null;
    dropPositionRef.current = null;
    lastDropOutcomeRef.current = { success: false, message: "" };
    setDraggedBlockId(activeId);
    if (!activeId.startsWith("template:") && !activeId.startsWith("artifact:")) setSelectedBlockId(activeId);
  }, [setSelectedBlockId]);

  const handleDragMove = useCallback(({ active, delta }) => {
    const position = dragDestination(active, delta);
    dropPositionRef.current = position;
    setDropPosition(position);
  }, [dragDestination]);

  const handleDragEnd = useCallback(({ active, delta }) => {
    const activeId = String(active.id);
    const libraryTemplate = activeId.startsWith("template:")
      ? viewArtifactTemplateFor(reportTemplateMap.get(activeId.slice("template:".length)))
      : activeId.startsWith("artifact:")
        ? wholeArtifactTemplateFor(artifactOptions.find((item) => item.artifactId === activeId.slice("artifact:".length)))
        : null;
    const keyboardPosition = !pointerDragRef.current && libraryTemplate
      ? keyboardEndDropPosition(blocksRef.current, { pageId: reportPages.at(-1)?.id, width: libraryTemplate.w, height: libraryTemplate.h })
      : null;
    const position = dropPositionRef.current ?? dragDestination(active, delta) ?? keyboardPosition;
    let succeeded = false;
    if (activeId.startsWith("artifact:")) {
      if (position) succeeded = addWholeArtifact(activeId.slice("artifact:".length), position);
    } else if (activeId.startsWith("template:")) {
      if (position) succeeded = addTemplateBlock(activeId.slice("template:".length), position);
    } else {
      const source = blocksRef.current.find((block) => block.id === activeId);
      if (position && source && (position.x !== source.x || position.y !== source.y)) {
        commitBlocks((current) => {
          const moved = moveFrontendBlock(current, activeId, position.placement, frontendReportContext());
          return moved.ok ? moved.blocks : placeDraftBlock(current, activeId, position.requestedX, position.y);
        });
        succeeded = true;
      }
    }
    const message = succeeded
      ? `${dragLabel(activeId)}을 문서에 놓았습니다.`
      : `${dragLabel(activeId)}은 유효한 위치가 없어 이동을 취소했습니다. 원래 구성을 유지합니다.`;
    lastDropOutcomeRef.current = { success: succeeded, message };
    setEditorAnnouncement(message);
    resetDrag();
  }, [addTemplateBlock, addWholeArtifact, artifactOptions, blocksRef, commitBlocks, dragDestination, dragLabel, frontendReportContext, reportPages, reportTemplateMap, resetDrag, setEditorAnnouncement, viewArtifactTemplateFor, wholeArtifactTemplateFor]);

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
    if (position) return `${dragLabel(activeId)}, ${position.y + 1}행 ${position.x + 1}열, 너비 ${position.w}/12 위치`;
    const block = blocksRef.current.find((item) => item.id === String(activeId));
    return block ? `${dragLabel(activeId)}, ${Number(block.y ?? 0) + 1}행 ${Number(block.x ?? 0) + 1}열` : dragLabel(activeId);
  }, [blocksRef, dragLabel]);

  return {
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
