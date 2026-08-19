/** pagination된 A4 page canvas와 빈 문서 CTA를 렌더링하는 모듈이다. */
import { memo, useCallback } from "react";
import { Plus, Type } from "lucide-react";

import { ReportPageCanvas } from "../ReportPageCanvas";

/** pagination된 A4 editor canvas를 렌더링하고 안정된 render callback으로 page 재렌더를 제한한다. */
export const ReportEditorCanvas = memo(function ReportEditorCanvas({
  activeArtifactTitle,
  activeInsert,
  alignmentGuides,
  canEdit,
  draggedBlockId,
  dropPosition,
  onAddText,
  onRegisterCanvas,
  orientation,
  orderedBlocks,
  pages,
  pending,
  renderBlock,
  renderFooter,
  renderHeader,
  reportTitle,
  zoom,
}) {
  const renderGridOverlay = useCallback((context) => <>
    {alignmentGuides?.pageId === context.page.id && <div className="report-alignment-guides" aria-hidden="true">
      {alignmentGuides.vertical.map((value) => <i className="vertical" style={{ left: `${(value / 12) * 100}%` }} key={`x-${value}`} />)}
      {alignmentGuides.horizontal.map((value) => <i className="horizontal" style={{ "--guide-row": Math.max(0, value - context.page.offsetY) }} key={`y-${value}`} />)}
    </div>}
    {dropPosition?.pageId === context.page.id && <div aria-hidden="true" className="report-drop-preview" style={{ gridColumn: `${dropPosition.x + 1} / span ${dropPosition.w}`, gridRow: `${Math.max(0, dropPosition.y - context.page.offsetY) + 1} / span ${dropPosition.h}` }}><span>{activeInsert ? `${activeArtifactTitle || activeInsert.title} 놓기` : "여기에 이동"}</span></div>}
    {!orderedBlocks.length && context.pageIndex === 0 && <div className="report-empty-canvas"><span><Plus size={19} aria-hidden="true" /></span><h2>첫 블록을 추가하세요</h2><p>왼쪽 편집 도구에서 템플릿을 끌어오거나 클릭해서 시작할 수 있습니다.</p><button type="button" onClick={onAddText} disabled={!canEdit}><Type size={14} aria-hidden="true" />텍스트 블록 추가</button></div>}
  </>, [activeArtifactTitle, activeInsert, alignmentGuides, canEdit, dropPosition, onAddText, orderedBlocks.length]);

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
      renderGridOverlay={renderGridOverlay}
      renderBlock={renderBlock}
      zoom={zoom}
    />
  </section>;
});
