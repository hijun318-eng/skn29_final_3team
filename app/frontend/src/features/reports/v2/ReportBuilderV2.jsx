/** 기존 보고서 상태와 명령을 V2 전용 3단 편집 화면에 배치하는 프레젠테이션 어댑터다. */
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { Expand, HelpCircle, Keyboard, PanelRightClose, Settings2, Shrink, Sparkles } from "lucide-react";

import { ReportShortcutHelp } from "./ReportShortcutHelp";
import "./report-builder-v2.css";

function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => (
    typeof window !== "undefined" && window.matchMedia(query).matches
  ));

  useEffect(() => {
    const media = window.matchMedia(query);
    const sync = () => setMatches(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, [query]);

  return matches;
}

/** 파생된 A4 페이지를 별도 저장 상태 없이 탐색하고 V2 로컬 화면 상태만 관리한다. */
export const ReportBuilderV2 = memo(function ReportBuilderV2({
  assistant,
  canvas,
  library,
  libraryOpen,
  onCloseLibrary,
  onKeyDown,
  onPointerMove,
  orientation,
  pages,
  presentation,
  properties,
  reportTitle,
  theme,
  toolbar,
}) {
  const rootRef = useRef(null);
  const workspaceRef = useRef(null);
  const inspectorRef = useRef(null);
  const inspectorCloseRef = useRef(null);
  const assistantTriggerRef = useRef(null);
  const propertiesTriggerRef = useRef(null);
  const [activePageIndex, setActivePageIndex] = useState(0);
  const [propertiesOpen, setPropertiesOpen] = useState(true);
  const [rightPanel, setRightPanel] = useState(assistant ? "assistant" : "properties");
  const [fullscreen, setFullscreen] = useState(false);
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  const libraryDrawer = useMediaQuery("(max-width: 1179px)");
  const libraryModalOpen = libraryDrawer && libraryOpen;
  const inspectorModalOpen = libraryDrawer && propertiesOpen && !libraryModalOpen;
  const editorModalOpen = libraryModalOpen || inspectorModalOpen;
  const fullscreenSupported = typeof document !== "undefined" && Boolean(document.fullscreenEnabled);

  useEffect(() => {
    const syncFullscreen = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  useEffect(() => {
    if (activePageIndex >= pages.length) setActivePageIndex(Math.max(0, pages.length - 1));
  }, [activePageIndex, pages.length]);

  useEffect(() => {
    if (libraryDrawer) setPropertiesOpen(false);
  }, [libraryDrawer]);

  useEffect(() => {
    const toolbarElement = rootRef.current?.querySelector(":scope > .notion-editor-topbar");
    if (!toolbarElement) return undefined;
    toolbarElement.inert = editorModalOpen;
    if (editorModalOpen) toolbarElement.setAttribute("aria-hidden", "true");
    else toolbarElement.removeAttribute("aria-hidden");
    return () => {
      toolbarElement.inert = false;
      toolbarElement.removeAttribute("aria-hidden");
    };
  }, [editorModalOpen]);

  useEffect(() => {
    if (!inspectorModalOpen) return undefined;
    const inspector = inspectorRef.current;
    const returnTarget = rightPanel === "assistant" ? assistantTriggerRef.current : propertiesTriggerRef.current;
    const frame = window.requestAnimationFrame(() => inspectorCloseRef.current?.focus());
    const containFocus = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setPropertiesOpen(false);
        return;
      }
      if (event.key !== "Tab" || !inspector) return;
      const controls = [...inspector.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [href], [tabindex]:not([tabindex='-1'])")]
        .filter((element) => !element.hidden && element.getClientRects().length > 0);
      if (!controls.length) {
        event.preventDefault();
        inspectorCloseRef.current?.focus();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || !inspector.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !inspector.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", containFocus);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", containFocus);
      window.requestAnimationFrame(() => returnTarget?.focus?.());
    };
  }, [inspectorModalOpen, rightPanel]);

  const navigatePage = useCallback((pageIndex) => {
    const target = rootRef.current?.querySelector(`[data-report-page-index="${pageIndex}"]`);
    setActivePageIndex(pageIndex);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const trackVisiblePage = useCallback(() => {
    const workspace = workspaceRef.current;
    if (!workspace) return;
    const top = workspace.getBoundingClientRect().top + 72;
    const candidates = [...workspace.querySelectorAll("[data-report-page-index]")];
    if (!candidates.length) return;
    const nearest = candidates.reduce((best, element) => (
      Math.abs(element.getBoundingClientRect().top - top) < Math.abs(best.getBoundingClientRect().top - top)
        ? element
        : best
    ));
    setActivePageIndex(Number(nearest.dataset.reportPageIndex || 0));
  }, []);

  const toggleFullscreen = useCallback(async () => {
    if (!fullscreenSupported || !rootRef.current) return;
    try {
      if (document.fullscreenElement === rootRef.current) await document.exitFullscreen();
      else await rootRef.current.requestFullscreen();
    } catch {
      setFullscreen(false);
    }
  }, [fullscreenSupported]);
  const closeShortcutHelp = useCallback(() => setShortcutHelpOpen(false), []);
  const toggleRightPanel = useCallback((panel) => {
    setPropertiesOpen((open) => panel === rightPanel ? !open : true);
    setRightPanel(panel);
  }, [rightPanel]);

  return <div
    ref={rootRef}
    className={`${libraryOpen ? "" : "library-collapsed"} ${propertiesOpen ? "" : "properties-collapsed"}`.trim()}
    data-report-builder="v2"
    onKeyDown={onKeyDown}
    onPointerMoveCapture={onPointerMove}
  >
    {toolbar}
    <div className="report-builder-v2-layout">
      {editorModalOpen && <button
        type="button"
        className="builder-modal-scrim"
        aria-label={libraryModalOpen ? "블록 추가 패널 닫기" : `${rightPanel === "assistant" ? "보고서 도우미" : "속성"} 패널 닫기`}
        onClick={libraryModalOpen ? onCloseLibrary : () => setPropertiesOpen(false)}
      />}
      {libraryOpen && <div
        className="builder-library-column"
        role={libraryModalOpen ? "dialog" : undefined}
        aria-modal={libraryModalOpen ? "true" : undefined}
        aria-label={libraryModalOpen ? "블록 추가" : undefined}
      >
        {library}
        <nav className="builder-page-navigator" aria-label="보고서 페이지">
          <header><span>페이지</span><small>{pages.length}쪽</small></header>
          <div>{pages.map((page, index) => <button
            type="button"
            className={activePageIndex === index ? "active" : ""}
            onClick={() => navigatePage(index)}
            aria-current={activePageIndex === index ? "page" : undefined}
            key={page.id || index}
          >
            <i className={page.orientation || orientation} aria-hidden="true" />
            <span><b>{String(index + 1).padStart(2, "0")} 페이지</b><small>{page.blocks?.length || 0}개 블록</small></span>
            <em>{(page.orientation || orientation) === "landscape" ? "가로" : "세로"}</em>
          </button>)}</div>
        </nav>
      </div>}
      <main
        ref={workspaceRef}
        className="builder-workspace"
        inert={editorModalOpen || undefined}
        aria-hidden={editorModalOpen ? "true" : undefined}
        onScroll={trackVisiblePage}
      >
        <div className="builder-workspace-toolbar" data-report-editor-chrome="true">
          <div><b>{reportTitle || "보고서 초안"}</b><span>{orientation === "landscape" ? "A4 가로 297 × 210mm" : "A4 세로 210 × 297mm"}</span></div>
          <nav aria-label="작업 화면 설정">
            <span title="입력 중에는 편집 단축키가 동작하지 않습니다."><Keyboard size={14} />Shift+클릭 다중 선택</span>
            <button type="button" onClick={() => setShortcutHelpOpen(true)} aria-haspopup="dialog"><HelpCircle size={14} />단축키</button>
            {presentation}
            {assistant && <button ref={assistantTriggerRef} type="button" onClick={() => toggleRightPanel("assistant")} aria-pressed={propertiesOpen && rightPanel === "assistant"}><Sparkles size={14} />도우미</button>}
            <button ref={propertiesTriggerRef} type="button" onClick={() => toggleRightPanel("properties")} aria-pressed={propertiesOpen && rightPanel === "properties"}>{propertiesOpen && rightPanel === "properties" ? <PanelRightClose size={14} /> : <Settings2 size={14} />}속성</button>
            {fullscreenSupported && <button type="button" onClick={toggleFullscreen} aria-pressed={fullscreen}>{fullscreen ? <Shrink size={14} /> : <Expand size={14} />}{fullscreen ? "축소" : "전체화면"}</button>}
          </nav>
        </div>
        {canvas}
      </main>
      {(assistant || properties) && <div
        ref={inspectorRef}
        className="builder-inspector"
        role={inspectorModalOpen ? "dialog" : undefined}
        aria-modal={inspectorModalOpen ? "true" : undefined}
        aria-label={inspectorModalOpen ? (rightPanel === "assistant" ? "보고서 도우미" : "속성") : undefined}
        inert={libraryModalOpen || undefined}
        aria-hidden={libraryModalOpen ? "true" : undefined}
        hidden={!propertiesOpen}
      >
        <header className="builder-inspector-drawer-header"><b>{rightPanel === "assistant" ? "보고서 도우미" : "속성"}</b><button ref={inspectorCloseRef} type="button" aria-label={`${rightPanel === "assistant" ? "보고서 도우미" : "속성"} 패널 닫기`} onClick={() => setPropertiesOpen(false)}><PanelRightClose size={16} /></button></header>
        <div className="builder-inspector-view" hidden={rightPanel !== "assistant"}>{assistant}</div>
        <div className="builder-inspector-view" hidden={rightPanel !== "properties"}>{properties}</div>
      </div>}
    </div>
    <ReportShortcutHelp open={shortcutHelpOpen} onClose={closeShortcutHelp} theme={theme} />
  </div>;
});
