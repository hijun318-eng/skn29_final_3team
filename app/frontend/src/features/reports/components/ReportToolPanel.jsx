/** text template·artifact library·assistant 지시 입력을 제공하는 editor 도구 모듈이다. */
import { memo, useDeferredValue, useMemo, useState } from "react";
import { BarChart3, PanelLeftClose, Plus, Search, Sparkles, X } from "lucide-react";

import { ReportArtifactLibraryTile } from "../ReportWholeArtifactBlock";
import { analysisTimeLabel } from "../reportAnalysisArtifacts";
import { ARTIFACT_VIEW_LABELS, availableArtifactViews } from "../reportDraftV2";
import { REPORT_CHART_OPTIONS } from "./reportPresentation";

function outlineEqual(previous, next) {
  return previous.length === next.length && previous.every((block, index) => (
    block.id === next[index].id
    && block.title === next[index].title
    && block.artifactId === next[index].artifactId
  ));
}

function toolPanelPropsEqual(previous, next) {
  const keys = Object.keys(next).filter((key) => key !== "orderedBlocks");
  return keys.length === Object.keys(previous).filter((key) => key !== "orderedBlocks").length
    && keys.every((key) => Object.is(previous[key], next[key]))
    && outlineEqual(previous.orderedBlocks, next.orderedBlocks);
}

/** 임의의 library 항목에서 사용자에게 보이는 동적 문자열만 검색하고 식별자 분기를 만들지 않는다. */
export function matchesReportLibraryQuery(item, query) {
  const normalized = String(query ?? "").trim().toLocaleLowerCase("ko-KR");
  if (!normalized) return true;
  return [item?.title, item?.description, item?.blockTitle, item?.content, item?.question]
    .filter((value) => typeof value === "string")
    .some((value) => value.toLocaleLowerCase("ko-KR").includes(normalized));
}

/** template·artifact library를 표시하며 custom comparator가 관련 ID/제목/상태 변경만 다시 그린다. */
export const ReportToolPanel = memo(function ReportToolPanel({
  analysisLibraryState,
  artifactOptions,
  artifactSelection,
  artifactStates,
  artifactTemplates,
  artifacts,
  assistantInstruction,
  canEdit,
  isDraft,
  onAddTemplate,
  onAddChart,
  onClose,
  onCreateAssistantDraft,
  onSelectArtifact,
  orderedBlocks,
  panelRef,
  pending,
  reportTemplates,
  selectedArtifact,
  selectedArtifactPeriod,
  selectedArtifactSource,
  selectedDefinition,
  selectedBlockId,
  showAssistant = true,
  setAssistantInstruction,
  setSelectedBlockId,
  TemplateTile,
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const deferredQuery = useDeferredValue(searchQuery);
  const visibleQuickTemplates = useMemo(
    () => reportTemplates.slice(0, 2).filter((item) => matchesReportLibraryQuery(item, deferredQuery)),
    [deferredQuery, reportTemplates],
  );
  const visibleReportTemplates = useMemo(
    () => reportTemplates.slice(2).filter((item) => matchesReportLibraryQuery(item, deferredQuery)),
    [deferredQuery, reportTemplates],
  );
  const visibleArtifacts = useMemo(
    () => artifactOptions.filter((item) => matchesReportLibraryQuery(item, deferredQuery)),
    [artifactOptions, deferredQuery],
  );
  const visibleArtifactTemplates = useMemo(
    () => artifactTemplates.filter((item) => matchesReportLibraryQuery(item, deferredQuery)),
    [artifactTemplates, deferredQuery],
  );
  const visibleOutline = useMemo(
    () => orderedBlocks.filter((item) => matchesReportLibraryQuery(item, deferredQuery)),
    [deferredQuery, orderedBlocks],
  );
  const hasSearchResults = visibleQuickTemplates.length || visibleReportTemplates.length
    || visibleArtifacts.length || visibleArtifactTemplates.length || visibleOutline.length;
  const selectedTimeDescription = analysisTimeLabel(
    selectedArtifact?.evidence,
    selectedArtifactPeriod || {},
  );
  const selectedAvailableViews = availableArtifactViews(selectedArtifact);

  return <aside ref={panelRef} tabIndex={-1} className="editor-library notion-editor-sidebar" aria-label="블록 도구">
    <header><div><p>보고서 구성</p><h2>블록 추가</h2><span>필요한 항목만 열어 클릭하거나 캔버스로 끌어 놓으세요.</span></div><button type="button" className="editor-library-close" aria-label="블록 도구 닫기" onClick={onClose}><PanelLeftClose size={16} aria-hidden="true" /></button></header>
    <label className="report-library-search"><Search size={14} aria-hidden="true" /><input type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="블록·본문·분석 결과 검색" aria-label="보고서 블록 검색" />{searchQuery && <button type="button" aria-label="검색어 지우기" onClick={() => setSearchQuery("")}><X size={13} /></button>}</label>
    {isDraft && <section className="notion-insert">
      <h3><Plus size={14} />추가할 항목</h3>
      {visibleQuickTemplates.length > 0 && <details className="report-library-group" open><summary>기본 블록 <span>{visibleQuickTemplates.length}</span></summary><div className="report-insert-grid">{visibleQuickTemplates.map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit} key={template.id} />)}</div></details>}
      {visibleReportTemplates.length > 0 && <details className="report-library-group" open={deferredQuery ? true : undefined}><summary>보고서 템플릿 <span>{visibleReportTemplates.length}</span></summary><div className="report-insert-grid report-template-grid">{visibleReportTemplates.map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit} key={template.id} />)}</div></details>}
      <details className="report-library-group" open>
        <summary>1. 분석 원본 <span>{visibleArtifacts.length}</span></summary>
        {visibleArtifacts.length > 0 && <div className="report-artifact-library" aria-label="분석 원본 라이브러리">{visibleArtifacts.map((source) => <ReportArtifactLibraryTile source={source} artifact={artifacts[source.artifactId]} disabled={!canEdit || artifactStates[source.artifactId]?.status === "loading"} selected={source.artifactId === artifactSelection} onSelect={onSelectArtifact} key={source.artifactId} />)}</div>}
        {!deferredQuery && !artifactOptions.length && <p className="report-artifact-library-empty">{analysisLibraryState.status === "loading" ? "저장된 분석 결과를 확인하는 중입니다." : "연결할 수 있는 승인 분석 결과가 없습니다."}</p>}
        {analysisLibraryState.status !== "loading" && analysisLibraryState.message && <small className="report-insert-help" role={analysisLibraryState.status === "error" ? "alert" : "status"}>{analysisLibraryState.message}</small>}
        {artifactOptions.length > 0 && <details className="report-library-subgroup" open><summary>2. 추가할 분석 요소 <span>{selectedAvailableViews.length}/{artifactTemplates.length}</span></summary><p className="report-artifact-selection-summary" aria-live="polite"><span>선택한 원본</span><b title={selectedArtifactSource?.title || "분석 원본을 선택해 주세요."}>{selectedArtifactSource?.title || "분석 원본을 선택해 주세요."}</b></p>{visibleArtifactTemplates.length > 0 && <div className="report-insert-grid">{visibleArtifactTemplates.map((template) => { const unavailable = !selectedAvailableViews.includes(template.view); return <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit || unavailable} disabledReason={unavailable ? `선택한 원본에는 ${ARTIFACT_VIEW_LABELS[template.view]} 데이터가 없습니다.` : ""} key={template.id} />; })}</div>}<small className="report-artifact-availability-help">선택한 원본에서 제공되는 요소만 추가할 수 있습니다.</small></details>}
      </details>
      {selectedArtifact?.chart && <details className="report-library-group" open={deferredQuery ? true : undefined}><summary>차트 유형으로 바로 추가 <span>{REPORT_CHART_OPTIONS.length}</span></summary><div className="report-chart-gallery">{REPORT_CHART_OPTIONS.map(([chartType, label]) => <button type="button" onClick={() => onAddChart(chartType)} disabled={!canEdit} title={`${label} 차트 추가`} key={chartType}><BarChart3 size={13} aria-hidden="true" /><span>{label}</span></button>)}</div></details>}
      {deferredQuery && !hasSearchResults && <p className="report-library-empty-search">“{deferredQuery}”와 일치하는 블록이나 분석 결과가 없습니다.</p>}
    </section>}
    {orderedBlocks.length > 1 && <nav className="notion-outline" aria-label="보고서 목차"><p>{deferredQuery ? "검색된 목차" : "목차"}</p>{visibleOutline.map((block) => <button type="button" onClick={() => setSelectedBlockId(block.id)} aria-pressed={selectedBlockId === block.id} title={block.title || "제목 없음"} key={block.id}><span>{String(orderedBlocks.findIndex((item) => item.id === block.id) + 1).padStart(2, "0")}</span><b>{block.title || "제목 없음"}</b></button>)}</nav>}
    {showAssistant && orderedBlocks.some((block) => block.artifactId) && <details className="notion-assistant"><summary><Sparkles size={14} />AI 초안 만들기</summary><div className="assistant-source-preview"><b>선택한 원본</b><span>{selectedArtifact?.title || selectedArtifactSource?.title || "분석 결과를 선택해 주세요."}</span><small>{selectedTimeDescription || "시간 기준 정보 없음"}</small><small>{selectedArtifact?.evidence?.sources?.length ? `출처 ${selectedArtifact.evidence.sources.map((source) => source.name).join("·")}` : "출처 정보 없음"}</small></div><textarea aria-label="AI 초안 지시" value={assistantInstruction} onChange={(event) => setAssistantInstruction(event.target.value)} maxLength={500} placeholder="초안의 목적과 구성 원칙을 입력하세요." /><button onClick={onCreateAssistantDraft} disabled={Boolean(pending) || !selectedArtifact || !assistantInstruction.trim()}><Sparkles size={14} />선택한 원본으로 AI 초안 생성</button><small>생성 결과는 AI 초안이며 확정 전에 검토가 필요합니다.</small></details>}
  </aside>;
}, toolPanelPropsEqual);
