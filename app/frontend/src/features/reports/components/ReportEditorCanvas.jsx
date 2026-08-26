/** 서버 draft에서 파생된 A4 page와 저장 payload 밖의 marquee 선택 상태를 렌더링한다. */
import { memo, useCallback, useRef, useState } from "react";
import { Plus, Type } from "lucide-react";

import { ReportPageCanvas } from "../ReportPageCanvas";

/** pagination된 A4를 렌더링하고 빈 영역 pointer 범위에 교차하는 실제 block ID만 선택한다. */
export const ReportEditorCanvas = memo(function ReportEditorCanvas({
  activeArtifactTitle,
  activeInsert,
  alignmentGuides,
  canEdit,
  draggedBlockId,
  dropPosition,
  onAddText,
  onRegisterCanvas,
  onSelectBlocks,
  orientation,
  orderedBlocks,
  pages,
  pending,
  renderBlock,
  renderFooter,
  renderHeader,
  reportTitle,
  viewScale,
}) {
  const marqueeStartRef = useRef(null);
  const [marquee, setMarquee] = useState(null);

  const pointInCanvas = useCallback((canvas, event) => {
    const bounds = canvas.getBoundingClientRect();
    const scale = canvas.offsetWidth ? bounds.width / canvas.offsetWidth : 1;
    return {
      x: (event.clientX - bounds.left) / Math.max(scale, 0.01),
      y: (event.clientY - bounds.top) / Math.max(scale, 0.01),
    };
  }, []);
  const handleMarqueeStart = useCallback((event, context) => {
    if (!canEdit || event.button !== 0 || event.target.closest?.("[data-report-block-id], button, input, textarea, select, a")) return;
    const canvas = event.currentTarget;
    const point = pointInCanvas(canvas, event);
    marqueeStartRef.current = {
      additive: event.shiftKey,
      canvas,
      clientX: event.clientX,
      clientY: event.clientY,
      pageId: context.page.id,
      pointerId: event.pointerId,
      x: point.x,
      y: point.y,
    };
    setMarquee({ pageId: context.page.id, x: point.x, y: point.y, width: 0, height: 0 });
    canvas.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }, [canEdit, pointInCanvas]);
  const handleMarqueeMove = useCallback((event) => {
    const start = marqueeStartRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    const point = pointInCanvas(start.canvas, event);
    setMarquee({
      pageId: start.pageId,
      x: Math.min(start.x, point.x),
      y: Math.min(start.y, point.y),
      width: Math.abs(point.x - start.x),
      height: Math.abs(point.y - start.y),
    });
  }, [pointInCanvas]);
  const finishMarquee = useCallback((event, cancelled = false) => {
    const start = marqueeStartRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    marqueeStartRef.current = null;
    if (start.canvas.hasPointerCapture?.(event.pointerId)) {
      start.canvas.releasePointerCapture(event.pointerId);
    }
    setMarquee(null);
    if (cancelled) return;
    const left = Math.min(start.clientX, event.clientX);
    const top = Math.min(start.clientY, event.clientY);
    const right = Math.max(start.clientX, event.clientX);
    const bottom = Math.max(start.clientY, event.clientY);
    if (right - left < 4 && bottom - top < 4) {
      onSelectBlocks([], { additive: start.additive });
      return;
    }
    const blockIds = [...start.canvas.querySelectorAll("[data-report-block-id]")]
      .filter((element) => {
        const bounds = element.getBoundingClientRect();
        return bounds.left < right && bounds.right > left && bounds.top < bottom && bounds.bottom > top;
      })
      .map((element) => element.dataset.reportBlockId)
      .filter(Boolean);
    onSelectBlocks(blockIds, { additive: start.additive });
  }, [onSelectBlocks]);
  const handleMarqueeEnd = useCallback((event) => finishMarquee(event), [finishMarquee]);
  const handleMarqueeCancel = useCallback((event) => finishMarquee(event, true), [finishMarquee]);

  const renderGridOverlay = useCallback((context) => <>
    {alignmentGuides?.pageId === context.page.id && <div className="report-alignment-guides" aria-hidden="true">
      {alignmentGuides.vertical.map((value) => <i className="vertical" style={{ left: `${(value / 12) * 100}%` }} key={`x-${value}`} />)}
      {alignmentGuides.horizontal.map((value) => <i className="horizontal" style={{ "--guide-row": Math.max(0, value - context.page.offsetY) }} key={`y-${value}`} />)}
    </div>}
    {dropPosition?.pageId === context.page.id && <div aria-hidden="true" className="report-drop-preview" style={{ gridColumn: `${dropPosition.x + 1} / span ${dropPosition.w}`, gridRow: `${Math.max(0, dropPosition.y - context.page.offsetY) + 1} / span ${dropPosition.h}` }}><span>{activeInsert ? `${activeArtifactTitle || activeInsert.title} 놓기` : "여기에 이동"}</span></div>}
    {marquee?.pageId === context.page.id && <div aria-hidden="true" className="report-marquee-selection" style={{ left: marquee.x, top: marquee.y, width: marquee.width, height: marquee.height }} />}
    {!orderedBlocks.length && context.pageIndex === 0 && <div className="report-empty-canvas"><span><Plus size={19} aria-hidden="true" /></span><h2>첫 블록을 추가하세요</h2><p>왼쪽 편집 도구에서 템플릿을 끌어오거나 클릭해서 시작할 수 있습니다.</p><button type="button" onClick={onAddText} disabled={!canEdit}><Type size={14} aria-hidden="true" />텍스트 블록 추가</button></div>}
  </>, [activeArtifactTitle, activeInsert, alignmentGuides, canEdit, dropPosition, marquee, onAddText, orderedBlocks.length]);

  return <section className="report-a4-editor-shell report-screen-render-root" data-report-render-root="screen-editor" aria-label="A4 보고서 편집" aria-busy={pending === "save"}>
    <ReportPageCanvas
      pages={pages}
      orientation={orientation}
      mode="editor"
      ariaLabel={`${reportTitle || "보고서"} A4 편집 영역`}
      renderHeader={renderHeader}
      renderFooter={renderFooter}
      gridClassName={`editor-canvas report-api-blocks notion-canvas ${draggedBlockId ? "drop-ready is-drop-ready" : ""}`}
      getGridRef={onRegisterCanvas}
      onGridPointerDown={handleMarqueeStart}
      onGridPointerMove={handleMarqueeMove}
      onGridPointerUp={handleMarqueeEnd}
      onGridPointerCancel={handleMarqueeCancel}
      renderGridOverlay={renderGridOverlay}
      renderBlock={renderBlock}
      viewScale={viewScale}
    />
  </section>;
});
