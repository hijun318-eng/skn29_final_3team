/** text template·artifact library·assistant 지시 입력을 제공하는 editor 도구 모듈이다. */
import { memo, useDeferredValue, useMemo, useState } from "react";
import { BarChart3, PanelLeftClose, Search, Sparkles, X } from "lucide-react";

import { ReportArtifactLibraryTile } from "../ReportWholeArtifactBlock";
import { compactReportArtifactOptions } from "../reportArtifactLibrary";
import { analysisTimeLabel } from "../reportAnalysisArtifacts";
import {
  normalizeGeneratedArtifactViewTitle,
  reportTimeRangeLabel,
} from "../reportTimePresentation";
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
  artifacts,
  assistantInstruction,
  canEdit,
  isDraft,
  onAddTemplate,
  onAddChart,
  onAddView,
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
  const compactArtifacts = useMemo(
    () => compactReportArtifactOptions(visibleArtifacts, artifacts, artifactSelection),
    [artifactSelection, artifacts, visibleArtifacts],
  );
  const hiddenDuplicateCount = visibleArtifacts.length - compactArtifacts.length;
  const visibleOutline = useMemo(
    () => orderedBlocks.filter((item) => matchesReportLibraryQuery(item, deferredQuery)),
    [deferredQuery, orderedBlocks],
  );
  const hasSearchResults = visibleQuickTemplates.length || visibleReportTemplates.length
    || visibleArtifacts.length || visibleOutline.length;
  const selectedTimeLabel = analysisTimeLabel(
    selectedArtifact?.evidence,
    selectedArtifactPeriod || {},
  );
  const selectedTimeDescription = reportTimeRangeLabel(selectedArtifact) || selectedTimeLabel;

  return <aside id="report-block-library" ref={panelRef} tabIndex={-1} className="editor-library notion-editor-sidebar" aria-label="블록 추가">
    <header><div><h2>블록 추가</h2><span>클릭하거나 끌어 원하는 위치에 추가하세요.</span></div><button type="button" className="editor-library-close" aria-label="블록 추가 패널 닫기" onClick={onClose}><PanelLeftClose size={16} aria-hidden="true" /></button></header>
    <label className="report-library-search"><Search size={14} aria-hidden="true" /><input type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="추가할 블록 검색" aria-label="추가할 블록 검색" />{searchQuery && <button type="button" aria-label="검색어 지우기" onClick={() => setSearchQuery("")}><X size={13} /></button>}</label>
    {isDraft && <section className="notion-insert">
      {visibleQuickTemplates.length > 0 && <><p className="report-template-label">빠른 블록</p><div className="report-insert-grid">{visibleQuickTemplates.map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit} key={template.id} />)}</div></>}
      {visibleReportTemplates.length > 0 && <><p className="report-template-label">보고서 템플릿</p><div className="report-insert-grid report-template-grid">{visibleReportTemplates.map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit} key={template.id} />)}</div></>}
      {compactArtifacts.length > 0 && <><p className="report-template-label">분석 결과 <span>{hiddenDuplicateCount ? `동일 결과 ${hiddenDuplicateCount}개 정리` : "펼쳐서 추가"}</span></p><div className="report-artifact-library" aria-label="분석 결과 라이브러리">{compactArtifacts.map((source) => <ReportArtifactLibraryTile source={source} artifact={artifacts[source.artifactId]} disabled={!canEdit || artifactStates[source.artifactId]?.status === "loading"} onAdd={onAddWholeArtifact} onAddView={onAddView} onSelect={onSelectArtifact} selected={artifactSelection === source.artifactId} key={source.artifactId} />)}</div></>}
      {!deferredQuery && !artifactOptions.length && <p className="report-artifact-library-empty">{analysisLibraryState.status === "loading" ? "저장된 분석 결과를 확인하는 중입니다." : "보고서에 사용할 분석 결과가 없습니다."}</p>}
      {analysisLibraryState.status !== "loading" && analysisLibraryState.message && <small className="report-insert-help" role={analysisLibraryState.status === "error" ? "alert" : "status"}>{analysisLibraryState.message}</small>}
      {selectedArtifact?.chart && <details className="report-chart-style-picker"><summary>다른 차트 형태로 추가</summary><div className="report-chart-gallery">{REPORT_CHART_OPTIONS.map(([chartType, label]) => <button type="button" onClick={() => onAddChart(chartType)} disabled={!canEdit} title={`${label} 차트 추가`} key={chartType}><BarChart3 size={13} /><span>{label}</span></button>)}</div></details>}
      {deferredQuery && !hasSearchResults && <p className="report-library-empty-search">“{deferredQuery}”와 일치하는 블록이나 분석 결과가 없습니다.</p>}
    </section>}
    <nav className="notion-outline" aria-label="보고서 목차"><p>{deferredQuery ? "검색된 목차" : "목차"}</p>{visibleOutline.map((block) => { const title = normalizeGeneratedArtifactViewTitle(block.title, block.artifactId ? artifacts[block.artifactId] : null, block.type); return <button type="button" onClick={() => setSelectedBlockId(block.id)} aria-pressed={selectedBlockId === block.id} key={block.id}><span>{String(orderedBlocks.findIndex((item) => item.id === block.id) + 1).padStart(2, "0")}</span><b>{title || "제목 없음"}</b></button>; })}</nav>
    {showAssistant && orderedBlocks.some((block) => block.artifactId) && <details className="notion-assistant"><summary><Sparkles size={14} />초안 만들기</summary><div className="assistant-source-preview"><b>사용할 분석 결과</b><span>{selectedArtifact?.title || selectedArtifactSource?.title || "분석 결과를 선택해 주세요."}</span><small>{selectedTimeDescription || "시간 기준 정보 없음"}</small><details><summary>출처 정보</summary><small>{selectedArtifact?.evidence?.sources?.length ? selectedArtifact.evidence.sources.map((source) => source.name).join(" · ") : "확인 가능한 출처 정보가 없습니다."}</small></details></div><textarea aria-label="작성 요청" value={assistantInstruction} onChange={(event) => setAssistantInstruction(event.target.value)} maxLength={500} placeholder="초안의 목적과 구성 원칙을 입력하세요." /><button onClick={onCreateAssistantDraft} disabled={Boolean(pending) || !selectedArtifact || !assistantInstruction.trim()}><Sparkles size={14} />초안 만들기</button><small>확정 전 변경 내용을 확인하세요.</small></details>}
  </aside>;
}, toolPanelPropsEqual);
