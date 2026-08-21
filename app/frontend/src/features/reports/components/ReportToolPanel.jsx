/** text template·artifact library·assistant 지시 입력을 제공하는 editor 도구 모듈이다. */
import { memo, useDeferredValue, useMemo, useState } from "react";
import { BarChart3, PanelLeftClose, Plus, Search, Sparkles, X } from "lucide-react";

import { ReportArtifactLibraryTile } from "../ReportWholeArtifactBlock";
import { analysisTimeLabel } from "../reportAnalysisArtifacts";
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
  onAddWholeArtifact,
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
  const selectedTimeLabel = analysisTimeLabel(
    selectedArtifact?.evidence,
    selectedArtifactPeriod || {},
  );
  const hasPeriodTime = Boolean(
    selectedArtifact?.evidence?.period?.start
      && selectedArtifact?.evidence?.period?.end_exclusive,
  ) || Boolean(
    selectedArtifactPeriod?.start && selectedArtifactPeriod?.end_exclusive,
  );
  const selectedTimeDescription = hasPeriodTime && selectedTimeLabel
    ? `${selectedTimeLabel} 미포함`
    : selectedTimeLabel;

  return <aside ref={panelRef} tabIndex={-1} className="editor-library notion-editor-sidebar" aria-label="블록 도구">
    <header><div><p>REPORT ELEMENTS</p><h2>블록 라이브러리</h2><span>문단과 근거가 연결된 분석 결과를 흰색 A4로 끌어 놓으세요.</span></div><button type="button" className="editor-library-close" aria-label="블록 도구 닫기" onClick={onClose}><PanelLeftClose size={16} aria-hidden="true" /></button></header>
    <label className="report-library-search"><Search size={14} aria-hidden="true" /><input type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="블록·본문·분석 결과 검색" aria-label="보고서 블록 검색" />{searchQuery && <button type="button" aria-label="검색어 지우기" onClick={() => setSearchQuery("")}><X size={13} /></button>}</label>
    {isDraft && <section className="notion-insert">
      <h3><Plus size={14} />블록 추가</h3>
      {visibleQuickTemplates.length > 0 && <><p className="report-template-label">빠른 블록</p><div className="report-insert-grid">{visibleQuickTemplates.map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit} key={template.id} />)}</div></>}
      {visibleReportTemplates.length > 0 && <><p className="report-template-label">보고서 템플릿</p><div className="report-insert-grid report-template-grid">{visibleReportTemplates.map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit} key={template.id} />)}</div></>}
      <p className="report-template-label">차트 갤러리 <span>{REPORT_CHART_OPTIONS.length} TYPES</span></p><div className="report-chart-gallery">{REPORT_CHART_OPTIONS.map(([chartType, label]) => <button type="button" onClick={() => onAddChart(chartType)} disabled={!canEdit || !selectedArtifact?.chart} title={`${label} 차트 추가`} key={chartType}><BarChart3 size={13} /><span>{label}</span></button>)}</div>
      {visibleArtifacts.length > 0 && <><p className="report-template-label">Artifact 전체</p><div className="report-artifact-library" aria-label="분석 Artifact 라이브러리">{visibleArtifacts.map((source) => <ReportArtifactLibraryTile source={source} artifact={artifacts[source.artifactId]} disabled={!canEdit || artifactStates[source.artifactId]?.status === "loading"} onAdd={onAddWholeArtifact} key={source.artifactId} />)}</div></>}
      {!deferredQuery && !artifactOptions.length && <p className="report-artifact-library-empty">{analysisLibraryState.status === "loading" ? "저장된 분석 결과를 확인하는 중입니다." : "보고서에 사용할 분석 결과가 없습니다."}</p>}
      {analysisLibraryState.status !== "loading" && analysisLibraryState.message && <small className="report-insert-help" role={analysisLibraryState.status === "error" ? "alert" : "status"}>{analysisLibraryState.message}</small>}
      <small className="report-insert-help">Artifact 전체는 요약·KPI·차트·표를 한 블록으로 유지합니다. 원하는 위치로 끌어다 놓으세요. 행은 빈 공간 없이 자동 정렬됩니다.</small>
      <label className="report-artifact-picker"><span>개별 보기용 Artifact</span><select aria-label="표 또는 차트로 삽입할 분석 결과" value={artifactSelection} onChange={(event) => onSelectArtifact(event.target.value)} disabled={!canEdit || !artifactOptions.length}>{artifactOptions.length ? artifactOptions.map((block) => <option value={block.artifactId} key={block.artifactId}>{block.title}</option>) : <option value="">연결된 결과 없음</option>}</select></label>
      {visibleArtifactTemplates.length > 0 && <div className="report-insert-grid">{visibleArtifactTemplates.map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit || !artifactOptions.length || (template.id === "artifact-chart" && !selectedArtifact?.chart)} key={template.id} />)}</div>}
      <small className="report-insert-help">표 보기만·차트 보기만은 기존 보고서 호환을 위한 개별 보기입니다. 클릭하거나 끌어 원하는 위치에 추가하세요.</small>
      {deferredQuery && !hasSearchResults && <p className="report-library-empty-search">“{deferredQuery}”와 일치하는 블록이나 분석 결과가 없습니다.</p>}
    </section>}
    <nav className="notion-outline" aria-label="보고서 목차"><p>{deferredQuery ? "검색된 목차" : "목차"}</p>{visibleOutline.map((block) => <button type="button" onClick={() => setSelectedBlockId(block.id)} aria-pressed={selectedBlockId === block.id} key={block.id}><span>{String(orderedBlocks.findIndex((item) => item.id === block.id) + 1).padStart(2, "0")}</span><b>{block.title || "제목 없음"}</b></button>)}</nav>
    {orderedBlocks.some((block) => block.artifactId) && <details className="notion-assistant"><summary><Sparkles size={14} />AI 초안 만들기</summary><div className="assistant-source-preview"><b>선택한 원본</b><span>{selectedArtifact?.title || selectedArtifactSource?.title || "분석 결과를 선택해 주세요."}</span><small>{selectedTimeDescription || "시간 기준 정보 없음"}</small><small>{selectedArtifact?.evidence?.sources?.length ? `출처 ${selectedArtifact.evidence.sources.map((source) => source.name).join("·")}` : "출처 정보 없음"}</small></div><textarea aria-label="AI 초안 지시" value={assistantInstruction} onChange={(event) => setAssistantInstruction(event.target.value)} maxLength={500} placeholder="초안의 목적과 구성 원칙을 입력하세요." /><button onClick={onCreateAssistantDraft} disabled={Boolean(pending) || !selectedArtifact || !assistantInstruction.trim()}><Sparkles size={14} />선택한 원본으로 AI 초안 생성</button><small>생성 결과는 AI 초안이며 확정 전에 검토가 필요합니다.</small></details>}
  </aside>;
}, toolPanelPropsEqual);
