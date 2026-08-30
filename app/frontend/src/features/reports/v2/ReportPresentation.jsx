/** 저장 대상과 분리된 화면 상태로 실제 보고서 페이지를 현재 앱 테마에 맞춰 한 장씩 발표하는 overlay 모듈이다. */
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, MonitorPlay, X } from "lucide-react";

import { ReportPageCanvas } from "../ReportPageCanvas";

const FOCUSABLE_SELECTOR = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

/** 실제 pagination과 renderer를 재사용하고 포털에도 테마를 전달해 방향키·PageUp/PageDown으로 탐색한다. */
export function ReportPresentation({ orientation, pages, renderBlock, renderFooter, renderHeader, reportTitle, theme }) {
  const [open, setOpen] = useState(false);
  const [pageIndex, setPageIndex] = useState(0);
  const closeRef = useRef(null);
  const overlayRef = useRef(null);
  const returnFocusRef = useRef(null);
  const triggerRef = useRef(null);
  const pageCount = pages.length;
  const move = useCallback((delta) => setPageIndex((current) => (
    Math.min(Math.max(0, pageCount - 1), Math.max(0, current + delta))
  )), [pageCount]);
  const close = useCallback(() => {
    setOpen(false);
    const focusTarget = returnFocusRef.current || triggerRef.current;
    window.requestAnimationFrame(() => focusTarget?.focus());
  }, []);
  const navigate = useCallback((event) => {
    event.stopPropagation();
    if (event.key === "Tab") {
      const controls = [...(overlayRef.current?.querySelectorAll(FOCUSABLE_SELECTOR) || [])];
      if (!controls.length) {
        event.preventDefault();
        overlayRef.current?.focus();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === overlayRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
      return;
    }
    if (event.key === " " && event.target.closest?.("button, a, input, textarea, select, [role='button']")) return;
    if (["ArrowRight", "PageDown", " "].includes(event.key)) { event.preventDefault(); move(1); }
    else if (["ArrowLeft", "PageUp"].includes(event.key)) { event.preventDefault(); move(-1); }
    else if (event.key === "Escape") close();
  }, [close, move]);

  useEffect(() => {
    if (pageIndex >= pageCount) setPageIndex(Math.max(0, pageCount - 1));
  }, [pageCount, pageIndex]);
  useEffect(() => {
    if (!open) return undefined;
    const previousOverflow = document.body.style.overflow;
    const background = [...document.body.children]
      .filter((element) => element !== overlayRef.current)
      .map((element) => ({ element, inert: element.inert }));
    background.forEach(({ element }) => { element.inert = true; });
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      background.forEach(({ element, inert }) => { element.inert = inert; });
    };
  }, [open]);

  const overlayThemeClass = theme === "dark" ? "ppt-theme theme-dark" : "theme-light";
  const overlay = open && <div ref={overlayRef} className={`report-presentation ${overlayThemeClass}`} role="dialog" aria-modal="true" aria-label={`${reportTitle || "보고서"} 발표`} tabIndex={-1} onKeyDown={navigate}>
      <header><div><small>ANSWERVICE · 분석 보고서</small><b>{reportTitle || "보고서"}</b></div><nav><span>{pageIndex + 1} / {pageCount}</span><button type="button" onClick={() => move(-1)} disabled={pageIndex === 0} aria-label="이전 페이지"><ChevronLeft size={18} /></button><button type="button" onClick={() => move(1)} disabled={pageIndex >= pageCount - 1} aria-label="다음 페이지"><ChevronRight size={18} /></button><button ref={closeRef} type="button" onClick={close} aria-label="발표 닫기"><X size={18} /></button></nav></header>
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
    <button ref={triggerRef} type="button" onClick={() => { returnFocusRef.current = document.activeElement; setPageIndex(0); setOpen(true); }} disabled={!pageCount}><MonitorPlay size={14} />발표</button>
    {overlay && createPortal(overlay, document.body)}
  </>;
}
