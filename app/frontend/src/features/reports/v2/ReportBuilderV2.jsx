/** 기존 보고서 상태와 명령을 캔버스 중심 편집 화면과 온디맨드 패널에 배치하는 어댑터다. */
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { HelpCircle, PanelRightClose, Settings2, Sparkles } from "lucide-react";

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
  properties,
  toolbar,
}) {
  const rootRef = useRef(null);
  const assistantTriggerRef = useRef(null);
  const inspectorDismissRef = useRef(null);
  const inspectorRef = useRef(null);
  const propertiesTriggerRef = useRef(null);
  const rightPanelTriggerRef = useRef(null);
  const shortcutTriggerRef = useRef(null);
  const workspaceRef = useRef(null);
  const [activePageIndex, setActivePageIndex] = useState(0);
  const [compactInspector, setCompactInspector] = useState(false);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [rightPanel, setRightPanel] = useState("properties");
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);

  useEffect(() => {
    if (activePageIndex >= pages.length) setActivePageIndex(Math.max(0, pages.length - 1));
  }, [activePageIndex, pages.length]);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 1180px)");
    const update = () => setCompactInspector(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

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

  const closeShortcutHelp = useCallback(() => {
    setShortcutHelpOpen(false);
    window.requestAnimationFrame(() => shortcutTriggerRef.current?.focus());
  }, []);
  const closeRightPanel = useCallback(() => {
    setPropertiesOpen(false);
    window.requestAnimationFrame(() => rightPanelTriggerRef.current?.focus());
  }, []);
  const toggleRightPanel = useCallback((panel, trigger) => {
    if (propertiesOpen && panel === rightPanel) {
      closeRightPanel();
      return;
    }
    rightPanelTriggerRef.current = trigger.current;
    setRightPanel(panel);
    setPropertiesOpen(true);
  }, [closeRightPanel, propertiesOpen, rightPanel]);

  useEffect(() => {
    if (!propertiesOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key !== "Escape" || document.querySelector("dialog[open]")) return;
      event.preventDefault();
      closeRightPanel();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [closeRightPanel, propertiesOpen]);

  const inspectorModal = propertiesOpen && compactInspector;
  const inspectorLabel = rightPanel === "assistant" ? "보고서 AI 도우미" : "보고서 속성";
  useEffect(() => {
    if (!inspectorModal) return;
    window.requestAnimationFrame(() => inspectorDismissRef.current?.focus());
  }, [inspectorModal, rightPanel]);

  const keepInspectorFocus = useCallback((event) => {
    if (!inspectorModal || event.key !== "Tab") return;
    const controls = [...(inspectorRef.current?.querySelectorAll(
      'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])',
    ) || [])].filter((element) => {
      const closedDetails = element.closest("details:not([open])");
      return !element.closest("[hidden]") && (!closedDetails || element.tagName === "SUMMARY");
    });
    if (!controls.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }, [inspectorModal]);

  return <div
    ref={rootRef}
    className={`${libraryOpen ? "library-open" : "library-collapsed"} ${propertiesOpen ? "inspector-open" : "properties-collapsed"}`.trim()}
    data-report-builder="v2"
    onKeyDown={inspectorModal ? undefined : onKeyDown}
    onPointerMoveCapture={inspectorModal ? undefined : onPointerMove}
  >
    {toolbar}
    <div className="report-builder-v2-layout">
      {libraryOpen && <div className="builder-library-column" inert={inspectorModal || undefined}>
        {library}
        {pages.length > 1 && <nav className="builder-page-navigator" aria-label="보고서 페이지">
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
        </nav>}
      </div>}
      <main ref={workspaceRef} className="builder-workspace" onScroll={trackVisiblePage} inert={inspectorModal || undefined}>
        <div className="builder-workspace-toolbar" data-report-editor-chrome="true">
          <div className="builder-workspace-context"><b>{String(activePageIndex + 1).padStart(2, "0")} / {String(pages.length).padStart(2, "0")}</b><span>{orientation === "landscape" ? "가로" : "세로"}</span></div>
          <nav aria-label="작업 화면 설정">
            <button ref={shortcutTriggerRef} type="button" onClick={() => setShortcutHelpOpen(true)} aria-haspopup="dialog" aria-label="편집 단축키"><HelpCircle size={14} /><span>도움말</span></button>
            {assistant && <button ref={assistantTriggerRef} type="button" onClick={() => toggleRightPanel("assistant", assistantTriggerRef)} aria-label={propertiesOpen && rightPanel === "assistant" ? "AI 도우미 닫기" : "AI 도우미 열기"} aria-pressed={propertiesOpen && rightPanel === "assistant"} aria-haspopup={compactInspector ? "dialog" : undefined}><Sparkles size={14} /><span>AI 도우미</span></button>}
            <button ref={propertiesTriggerRef} type="button" onClick={() => toggleRightPanel("properties", propertiesTriggerRef)} aria-label={propertiesOpen && rightPanel === "properties" ? "속성 닫기" : "속성 열기"} aria-pressed={propertiesOpen && rightPanel === "properties"} aria-haspopup={compactInspector ? "dialog" : undefined}>{propertiesOpen && rightPanel === "properties" ? <PanelRightClose size={14} /> : <Settings2 size={14} />}<span>속성</span></button>
          </nav>
        </div>
        {canvas}
      </main>
      {inspectorModal && <button type="button" className="builder-inspector-scrim" onClick={closeRightPanel} aria-label={`${inspectorLabel} 닫기`} />}
      {(assistant || properties) && <div
        ref={inspectorRef}
        className="builder-inspector"
        hidden={!propertiesOpen}
        role={compactInspector ? "dialog" : "complementary"}
        aria-modal={compactInspector && propertiesOpen ? "true" : undefined}
        aria-label={inspectorLabel}
        onKeyDown={keepInspectorFocus}
      >
        <button ref={inspectorDismissRef} type="button" className="builder-inspector-dismiss" onClick={closeRightPanel} aria-label={`${inspectorLabel} 닫기`}><PanelRightClose size={16} /></button>
        <div className="builder-inspector-view" hidden={rightPanel !== "assistant"}>{assistant}</div>
        <div className="builder-inspector-view" hidden={rightPanel !== "properties"}>{properties}</div>
      </div>}
    </div>
    <ReportShortcutHelp open={shortcutHelpOpen} onClose={closeShortcutHelp} />
  </div>;
});
