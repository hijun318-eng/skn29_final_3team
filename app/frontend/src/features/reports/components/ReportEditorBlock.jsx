/** 단일 A4 editor block의 내용·선택·resize·명령을 격리하는 모듈이다. */
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { Columns2, GripVertical, Lock } from "lucide-react";
import { useDraggable } from "@dnd-kit/core";

import { dataProvenanceLabel } from "../../../utils/presentation";
import { ReportWholeArtifactBlock } from "../ReportWholeArtifactBlock";
import { DataProvenanceBadge, ReportArtifactContent } from "./ReportArtifactContent";
import { ReportBlockMenu } from "./ReportBlockControls";
import { MarkdownBlockEditor } from "./MarkdownBlockEditor";

function blockMinimumHeight(type) {
  if (type === "artifact") return 5;
  if (type === "chart") return 7;
  if (type === "table") return 5;
  return 4;
}

function shallowBlockEqual(previous, next) {
  if (previous === next) return true;
  if (!previous || !next) return false;
  const keys = Object.keys(previous);
  return keys.length === Object.keys(next).length
    && keys.every((key) => Object.is(previous[key], next[key]));
}

function editorBlockPropsEqual(previous, next) {
  return shallowBlockEqual(previous.block, next.block)
    && previous.rowOffset === next.rowOffset
    && previous.artifact === next.artifact
    && previous.artifactState === next.artifactState
    && previous.currency === next.currency
    && previous.isDraft === next.isDraft
    && previous.selected === next.selected
    && previous.primary === next.primary
    && previous.dragging === next.dragging
    && previous.groupTransform === next.groupTransform
    && previous.locked === next.locked;
}

const RESIZE_DIRECTIONS = [
  ["nw", "왼쪽 위"], ["n", "위"], ["ne", "오른쪽 위"], ["e", "오른쪽"],
  ["se", "오른쪽 아래"], ["s", "아래"], ["sw", "왼쪽 아래"], ["w", "왼쪽"],
];

/** 단일 편집 블록과 제어기를 렌더링하며 custom comparator가 변경된 block field만 다시 그린다. */
export const ReportEditorBlock = memo(function ReportEditorBlock({
  block,
  rowOffset,
  artifact,
  artifactState,
  currency,
  isDraft,
  selected,
  primary,
  dragging,
  groupTransform,
  locked = false,
  onSelect,
  onUpdate,
  onMove,
  onResize,
  onSetting,
  onDuplicate,
  onDelete,
  onToggleLock,
  onRetryArtifact,
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
  } = useDraggable({ id: block.id, disabled: !isDraft || locked });
  const blockNodeRef = useRef(null);
  const resizeStart = useRef(null);
  const resizePreviewRef = useRef(null);
  const [resizePreview, setResizePreview] = useState(null);
  const titleTimerRef = useRef(null);
  const titleTransactionRef = useRef(false);

  useEffect(() => () => window.clearTimeout(titleTimerRef.current), []);

  const setBlockNodeRef = useCallback((node) => {
    blockNodeRef.current = node;
    setNodeRef(node);
  }, [setNodeRef]);

  const selectBlock = useCallback((event) => onSelect(block.id, event), [block.id, onSelect]);
  const selectBlockFromKeyboard = useCallback((event) => {
    if (event.target.matches?.(":focus-visible")) onSelect(block.id);
  }, [block.id, onSelect]);
  const updateBlock = useCallback(
    (change, record) => onUpdate(block.id, change, record),
    [block.id, onUpdate],
  );
  const moveBlock = useCallback(
    (deltaX, deltaY) => onMove(block.id, deltaX, deltaY),
    [block.id, onMove],
  );
  const resizeBlock = useCallback(
    (width, height, position) => onResize(block.id, width, height, position),
    [block.id, onResize],
  );
  const setBlockSetting = useCallback(
    (name, value) => onSetting(block.id, name, value),
    [block.id, onSetting],
  );
  const duplicateBlock = useCallback(() => onDuplicate(block.id), [block.id, onDuplicate]);
  const deleteBlock = useCallback(() => onDelete(block.id), [block.id, onDelete]);
  const toggleLock = useCallback(() => onToggleLock?.(block.id), [block.id, onToggleLock]);
  const retryArtifact = useCallback(
    () => onRetryArtifact?.(block.artifactId),
    [block.artifactId, onRetryArtifact],
  );

  const startResize = (event) => {
    event.stopPropagation();
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    const canvas = event.currentTarget.closest(".notion-canvas");
    const styles = canvas ? window.getComputedStyle(canvas) : null;
    const bounds = canvas?.getBoundingClientRect();
    const gap = Number.parseFloat(styles?.columnGap || "0") || 0;
    const padding = (Number.parseFloat(styles?.paddingLeft || "0") || 0)
      + (Number.parseFloat(styles?.paddingRight || "0") || 0);
    resizeStart.current = {
      clientX: event.clientX,
      clientY: event.clientY,
      blockX: block.x ?? 0,
      blockY: block.y ?? 0,
      w: block.w ?? block.columns,
      h: block.h ?? 4,
      direction: event.currentTarget.dataset.direction,
      scale: bounds && canvas?.offsetWidth ? bounds.width / canvas.offsetWidth : 1,
      columnStep: canvas
        ? Math.max(1, (canvas.offsetWidth - padding - gap * 11) / 12 + gap)
        : 72,
      rowStep: (Number.parseFloat(
        styles?.getPropertyValue("--report-grid-row") || "56",
      ) || 56) + (Number.parseFloat(styles?.rowGap || "0") || 0),
    };
    resizePreviewRef.current = {
      x: block.x ?? 0,
      y: block.y ?? 0,
      w: block.w ?? block.columns,
      h: block.h ?? 4,
    };
    setResizePreview(resizePreviewRef.current);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const resizeWithPointer = (event) => {
    if (!resizeStart.current || (event.buttons & 1) === 0) return;
    const start = resizeStart.current;
    const minimumWidth = block.type === "text" ? 4 : 6;
    const maximumHeight = ["artifact", "chart", "table"].includes(block.type) ? 18 : 14;
    const deltaX = Math.round((event.clientX - start.clientX) / (start.columnStep * start.scale));
    const deltaY = Math.round((event.clientY - start.clientY) / (start.rowStep * start.scale));
    const initialRight = start.blockX + start.w;
    const initialBottom = start.blockY + start.h;
    const left = start.direction.includes("w")
      ? Math.max(0, Math.min(initialRight - minimumWidth, start.blockX + deltaX))
      : start.blockX;
    const right = start.direction.includes("e")
      ? Math.max(start.blockX + minimumWidth, Math.min(12, initialRight + deltaX))
      : initialRight;
    const top = start.direction.includes("n")
      ? Math.max(0, initialBottom - maximumHeight, Math.min(initialBottom - blockMinimumHeight(block.type), start.blockY + deltaY))
      : start.blockY;
    const bottom = start.direction.includes("s")
      ? Math.max(start.blockY + blockMinimumHeight(block.type), Math.min(start.blockY + maximumHeight, initialBottom + deltaY))
      : initialBottom;
    const next = {
      x: left,
      y: top,
      w: right - left,
      h: bottom - top,
    };
    resizePreviewRef.current = next;
    setResizePreview(next);
  };

  const finishResize = () => {
    const next = resizePreviewRef.current;
    const start = resizeStart.current;
    resizeStart.current = null;
    resizePreviewRef.current = null;
    setResizePreview(null);
    if (next && start && (next.w !== start.w || next.h !== start.h)) {
      resizeBlock(next.w, next.h, { x: next.x, y: next.y });
    }
  };

  const cancelResize = () => {
    resizeStart.current = null;
    resizePreviewRef.current = null;
    setResizePreview(null);
  };

  const resizeWithKeyboard = (event, direction) => {
    const movement = {
      ArrowRight: [1, 0],
      ArrowLeft: [-1, 0],
      ArrowDown: [0, 1],
      ArrowUp: [0, -1],
    }[event.key];
    if (!movement) return;
    event.preventDefault();
    event.stopPropagation();
    const horizontal = direction.includes("w") ? -movement[0] : direction.includes("e") ? movement[0] : 0;
    const vertical = direction.includes("n") ? -movement[1] : direction.includes("s") ? movement[1] : 0;
    resizeBlock(
      (block.w ?? block.columns) + horizontal,
      (block.h ?? 4) + vertical,
      {
        x: (block.x ?? 0) + (direction.includes("w") ? movement[0] : 0),
        y: (block.y ?? 0) + (direction.includes("n") ? movement[1] : 0),
      },
    );
  };

  const resizeTableWithWheel = useCallback((event) => {
    if (!event.altKey || event.deltaY === 0 || block.type !== "table" || !isDraft || locked) return;
    event.preventDefault();
    event.stopPropagation();
    const step = event.deltaY < 0 ? 1 : -1;
    resizeBlock((block.w ?? block.columns) + step, (block.h ?? 5) + step);
  }, [block.columns, block.h, block.type, block.w, isDraft, locked, resizeBlock]);

  useEffect(() => {
    const node = blockNodeRef.current;
    if (!node || block.type !== "table" || !isDraft || locked) return undefined;
    node.addEventListener("wheel", resizeTableWithWheel, { passive: false });
    return () => node.removeEventListener("wheel", resizeTableWithWheel);
  }, [block.type, isDraft, locked, resizeTableWithWheel]);

  const displayY = Math.max(0, (block.y ?? 0) - rowOffset);
  const previewX = resizePreview?.x ?? block.x ?? 0;
  const previewY = resizePreview?.y ?? block.y ?? 0;
  const displayWidth = resizePreview?.w ?? block.w ?? block.columns;
  const displayHeight = resizePreview?.h ?? block.h ?? 1;
  const dragTransform = transform || groupTransform;
  const style = {
    "--block-x": previewX + 1,
    "--block-y": Math.max(0, previewY - rowOffset) + 1,
    "--block-w": displayWidth,
    "--block-h": displayHeight,
    "--block-order": displayY * 12 + (block.x ?? 0),
    gridRow: `${displayY + 1} / span ${displayHeight}`,
    ...(resizePreview ? {
      inlineSize: `calc(100% + ${(displayWidth - (block.w ?? block.columns)) * resizeStart.current.columnStep}px)`,
      blockSize: `calc(100% + ${(displayHeight - (block.h ?? 1)) * resizeStart.current.rowStep}px)`,
    } : {}),
    transform: resizePreview
      ? `translate3d(${(previewX - (block.x ?? 0)) * resizeStart.current.columnStep}px, ${(previewY - (block.y ?? 0)) * resizeStart.current.rowStep}px, 0)`
      : dragTransform
        ? `translate3d(${Math.round(dragTransform.x)}px, ${Math.round(dragTransform.y)}px, 0)`
        : undefined,
  };

  let body;
  if (block.type === "text") {
    body = <MarkdownBlockEditor block={block} disabled={!isDraft || locked} onUpdate={updateBlock} />;
  } else if (block.type === "artifact") {
    body = (
      <ReportWholeArtifactBlock
        block={block}
        artifact={artifact}
        artifactState={artifactState}
        currency={currency}
        renderView={(type, options = {}) => (
          <ReportArtifactContent
            block={{ ...block, type, h: options.height ?? block.h }}
            artifact={options.artifact || artifact}
            artifactState={artifactState}
            currency={currency}
            editor
            paper
            onRetry={block.artifactId ? retryArtifact : undefined}
          />
        )}
      />
    );
  } else {
    body = (
      <div className="notion-data-embed notion-data-embed-live">
        <div className="notion-data-status">
          <Columns2 size={19} aria-hidden="true" />
          <div>
            <small>{dataProvenanceLabel(artifact?.evidence?.sources ?? []) ?? "분석 데이터"}</small>
            <b>{block.type === "chart" ? "분석 차트 보기" : "분석 데이터 표 보기"}</b>
            <span>Artifact에서 선택한 하나의 보기입니다.</span>
          </div>
        </div>
        <ReportArtifactContent
          block={block}
          artifact={artifact}
          artifactState={artifactState}
          currency={currency}
          editor
          paper
          onRetry={block.artifactId ? retryArtifact : undefined}
        />
      </div>
    );
  }

  return (
    <article
      ref={setBlockNodeRef}
      data-block-id={block.id}
      tabIndex={-1}
      className={`editor-block notion-block ${selected ? "selected" : ""} ${dragging ? "dragging is-dragging" : ""} ${locked ? "locked" : ""}`}
      aria-label={`${block.title || "제목 없음"} 블록${selected ? ", 선택됨" : ""}${locked ? ", 잠김" : ""}`}
      onClick={selectBlock}
      onFocusCapture={selectBlockFromKeyboard}
      style={style}
    >
      <header className="report-block-chrome">
        <div className="report-block-title">
          {isDraft && !locked && (
            <button
              ref={setActivatorNodeRef}
              type="button"
              className="report-drag-handle"
              {...listeners}
              {...attributes}
              aria-label={`${block.title} 블록 이동`}
              title="끌어서 이동 · Space 또는 Enter로 키보드 이동"
            >
              <GripVertical size={17} />
            </button>
          )}
          {isDraft && locked && <Lock className="report-block-locked-icon" size={15} aria-hidden="true" />}
          <span>{block.type === "text" ? "텍스트" : block.type === "artifact" ? "Artifact 전체" : block.type === "chart" ? "차트 보기" : "표 보기"}</span>
          {block.type !== "text" && <DataProvenanceBadge artifact={artifact} />}
        </div>
        {isDraft && (
          <ReportBlockMenu
            block={block}
            artifact={artifact}
            locked={locked}
            onMove={moveBlock}
            onResize={resizeBlock}
            onSetting={setBlockSetting}
            onDuplicate={duplicateBlock}
            onDelete={deleteBlock}
            onToggleLock={toggleLock}
          />
        )}
      </header>
      {isDraft ? (
        <input
          className="notion-block-title"
          aria-label={`${block.title || "제목 없음"} 제목`}
          value={block.title}
          disabled={locked}
          onChange={(event) => {
            const record = !titleTransactionRef.current;
            titleTransactionRef.current = true;
            window.clearTimeout(titleTimerRef.current);
            titleTimerRef.current = window.setTimeout(() => {
              titleTransactionRef.current = false;
            }, 700);
            updateBlock({ title: event.target.value }, record);
          }}
          placeholder="블록 제목을 입력하세요"
        />
      ) : <h2>{block.title}</h2>}
      {body}
      {isDraft && !locked && primary && RESIZE_DIRECTIONS.map(([direction, label]) => (
        <button
          type="button"
          className="report-resize-handle"
          data-direction={direction}
          aria-label={`${block.title} 블록 ${label} 크기 조절`}
          title={`${label} 방향 크기 조절 · 방향키로 미세 조절`}
          onPointerDown={startResize}
          onPointerMove={resizeWithPointer}
          onPointerUp={finishResize}
          onPointerCancel={cancelResize}
          onLostPointerCapture={() => {
            if (resizeStart.current) cancelResize();
          }}
          onKeyDown={(event) => resizeWithKeyboard(event, direction)}
          key={direction}
        ><span /></button>
      ))}
    </article>
  );
}, editorBlockPropsEqual);
