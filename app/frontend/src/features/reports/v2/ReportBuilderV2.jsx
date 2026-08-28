/** 기존 보고서 상태와 명령을 V2 전용 3단 편집 화면에 배치하는 프레젠테이션 어댑터다. */
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { Expand, HelpCircle, Keyboard, PanelRightClose, Settings2, Shrink, Sparkles } from "lucide-react";

import { ReportShortcutHelp } from "./ReportShortcutHelp";
import "./report-builder-v2.css";

/** 파생된 A4 페이지를 별도 저장 상태 없이 탐색하고 V2 로컬 화면 상태만 관리한다. */
export const ReportBuilderV2 = memo(function ReportBuilderV2({
  assistant,
  canvas,
  library,
  libraryOpen,
  onKeyDown,
  onPointerMove,
  orientation,
  pages,
  presentation,
  properties,
  reportTitle,
  toolbar,
}) {
  const rootRef = useRef(null);
  const shortcutTriggerRef = useRef(null);
  const workspaceRef = useRef(null);
  const [activePageIndex, setActivePageIndex] = useState(0);
  const [propertiesOpen, setPropertiesOpen] = useState(() => (
    typeof window === "undefined"
    || typeof window.matchMedia !== "function"
    || window.matchMedia("(min-width: 1180px)").matches
  ));
  const [rightPanel, setRightPanel] = useState(assistant ? "assistant" : "properties");
  const [fullscreen, setFullscreen] = useState(false);
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  const fullscreenSupported = typeof document !== "undefined" && Boolean(document.fullscreenEnabled);

  useEffect(() => {
    const syncFullscreen = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  useEffect(() => {
    if (activePageIndex >= pages.length) setActivePageIndex(Math.max(0, pages.length - 1));
  }, [activePageIndex, pages.length]);

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
  const closeShortcutHelp = useCallback(() => {
    setShortcutHelpOpen(false);
    window.requestAnimationFrame(() => shortcutTriggerRef.current?.focus());
  }, []);
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
      {libraryOpen && <div className="builder-library-column">
        {library}
        <nav className="builder-page-navigator" aria-label="보고서 페이지">
          <header><span>페이지</span><small>{pages.length} PAGES</small></header>
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
      <main ref={workspaceRef} className="builder-workspace" onScroll={trackVisiblePage}>
        <div className="builder-workspace-toolbar" data-report-editor-chrome="true">
          <div><b>{reportTitle || "보고서 초안"}</b><span>{orientation === "landscape" ? "A4 가로 297 × 210mm" : "A4 세로 210 × 297mm"}</span><small>12 COLUMN · GRID SNAP</small></div>
          <nav aria-label="작업 화면 설정">
            <span title="입력 중에는 편집 단축키가 동작하지 않습니다."><Keyboard size={14} />Shift+클릭 다중 선택</span>
            <button ref={shortcutTriggerRef} type="button" onClick={() => setShortcutHelpOpen(true)} aria-haspopup="dialog"><HelpCircle size={14} />단축키</button>
            {presentation}
            {assistant && <button type="button" onClick={() => toggleRightPanel("assistant")} aria-pressed={propertiesOpen && rightPanel === "assistant"}><Sparkles size={14} />AI Assistant</button>}
            <button type="button" onClick={() => toggleRightPanel("properties")} aria-pressed={propertiesOpen && rightPanel === "properties"}>{propertiesOpen && rightPanel === "properties" ? <PanelRightClose size={14} /> : <Settings2 size={14} />}속성</button>
            {fullscreenSupported && <button type="button" onClick={toggleFullscreen} aria-pressed={fullscreen}>{fullscreen ? <Shrink size={14} /> : <Expand size={14} />}{fullscreen ? "축소" : "전체화면"}</button>}
          </nav>
        </div>
        {canvas}
      </main>
      {(assistant || properties) && <div className="builder-inspector" hidden={!propertiesOpen}>
        <button type="button" className="builder-inspector-dismiss" onClick={() => setPropertiesOpen(false)} aria-label="오른쪽 패널 닫기"><PanelRightClose size={16} /></button>
        <div className="builder-inspector-view" hidden={rightPanel !== "assistant"}>{assistant}</div>
        <div className="builder-inspector-view" hidden={rightPanel !== "properties"}>{properties}</div>
      </div>}
    </div>
    <ReportShortcutHelp open={shortcutHelpOpen} onClose={closeShortcutHelp} />
  </div>;
});
