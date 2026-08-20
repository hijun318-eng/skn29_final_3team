/** 저장 대상과 분리된 화면 상태로 실제 보고서 페이지를 한 장씩 발표하는 overlay 모듈이다. */
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, MonitorPlay, X } from "lucide-react";

import { ReportPageCanvas } from "../ReportPageCanvas";

/** 실제 pagination과 renderer를 재사용하고 방향키·PageUp/PageDown으로 페이지를 탐색한다. */
export function ReportPresentation({ orientation, pages, renderBlock, renderFooter, renderHeader, reportTitle }) {
  const [open, setOpen] = useState(false);
  const [pageIndex, setPageIndex] = useState(0);
  const closeRef = useRef(null);
  const pageCount = pages.length;
  const move = useCallback((delta) => setPageIndex((current) => (
    Math.min(Math.max(0, pageCount - 1), Math.max(0, current + delta))
  )), [pageCount]);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (pageIndex >= pageCount) setPageIndex(Math.max(0, pageCount - 1));
  }, [pageCount, pageIndex]);
  useEffect(() => {
    if (!open) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    const navigate = (event) => {
      if (["ArrowRight", "PageDown", " "].includes(event.key)) { event.preventDefault(); move(1); }
      else if (["ArrowLeft", "PageUp"].includes(event.key)) { event.preventDefault(); move(-1); }
      else if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", navigate);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", navigate);
      document.body.style.overflow = previousOverflow;
    };
  }, [close, move, open]);

  const overlay = open && <div className="report-presentation" role="dialog" aria-modal="true" aria-label={`${reportTitle || "보고서"} 발표`}>
      <header><div><small>ANSWERVICE · GOVERNED REPORT</small><b>{reportTitle || "보고서"}</b></div><nav><span>{pageIndex + 1} / {pageCount}</span><button type="button" onClick={() => move(-1)} disabled={pageIndex === 0} aria-label="이전 페이지"><ChevronLeft size={18} /></button><button type="button" onClick={() => move(1)} disabled={pageIndex >= pageCount - 1} aria-label="다음 페이지"><ChevronRight size={18} /></button><button ref={closeRef} type="button" onClick={close} aria-label="발표 닫기"><X size={18} /></button></nav></header>
      <main>
        <ReportPageCanvas
          pages={pages[pageIndex] ? [pages[pageIndex]] : []}
          orientation={orientation}
          mode="presentation"
          pageNumberOffset={pageIndex}
          pageCountOverride={pageCount}
          ariaLabel={`${reportTitle || "보고서"} ${pageIndex + 1}페이지 발표`}
          renderHeader={renderHeader}
          renderFooter={renderFooter}
          renderBlock={renderBlock}
        />
      </main>
      <footer><span>← → · PageUp PageDown</span><button type="button" onClick={() => move(-1)} disabled={pageIndex === 0}>이전</button><button type="button" onClick={() => move(1)} disabled={pageIndex >= pageCount - 1}>다음</button></footer>
    </div>;

  return <>
    <button type="button" onClick={() => { setPageIndex(0); setOpen(true); }} disabled={!pageCount}><MonitorPlay size={14} />발표</button>
    {overlay && createPortal(overlay, document.body)}
  </>;
}
