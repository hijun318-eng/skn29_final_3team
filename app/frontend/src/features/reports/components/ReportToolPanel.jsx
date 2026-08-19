/** text template·artifact library·assistant 지시 입력을 제공하는 editor 도구 모듈이다. */
import { memo } from "react";
import { BarChart3, PanelLeftClose, Plus, Search, Sparkles, X } from "lucide-react";

import { ReportArtifactLibraryTile } from "../ReportWholeArtifactBlock";
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

/** template·artifact library를 표시하며 custom comparator가 관련 ID/제목/상태 변경만 다시 그린다. */
export const ReportToolPanel = memo(function ReportToolPanel({
  analysisLibraryState,
  artifactOptions,
  artifactSelection,
  artifactStates,
  artifactTemplates,
  artifacts,
  assistantInstruction,
  builderV2,
  canEdit,
  isDraft,
  onAddTemplate,
  onAddChart,
  onAddWholeArtifact,
  onClose,
  onCreateAssistantDraft,
  onSearch,
  onSearchResult,
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
  searchQuery,
  searchResults,
  setAssistantInstruction,
  setSelectedBlockId,
  TemplateTile,
}) {
  return <aside ref={panelRef} tabIndex={-1} className="editor-library notion-editor-sidebar" aria-label="블록 도구">
    <header><div><p>REPORT ELEMENTS</p><h2>블록 라이브러리</h2><span>클릭하거나 흰색 A4 위로 끌어 놓으세요.</span></div><button type="button" className="editor-library-close" aria-label="블록 도구 닫기" onClick={onClose}><PanelLeftClose size={16} aria-hidden="true" /></button></header>
    {builderV2 && <section className="builder-library-search"><label><Search size={13} /><input aria-label="보고서 블록 검색" value={searchQuery} onChange={(event) => onSearch(event.target.value)} placeholder="제목 또는 텍스트 검색" />{searchQuery && <button type="button" aria-label="검색 지우기" onClick={() => onSearch("")}><X size={12} /></button>}</label>{searchQuery && <div>{searchResults.length ? searchResults.map((result) => <button type="button" onClick={() => onSearchResult(result.id)} key={result.id}><b>{result.title || "제목 없음"}</b><small>{result.type === "text" ? "텍스트" : result.type}</small></button>) : <p>검색 결과가 없습니다.</p>}</div>}</section>}
    {isDraft && <section className="notion-insert">
      <h3><Plus size={14} />블록 추가</h3>
      <p className="report-template-label">빠른 블록</p><div className="report-insert-grid">{reportTemplates.slice(0, 2).map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit} key={template.id} />)}</div>
      <p className="report-template-label">보고서 템플릿</p><div className="report-insert-grid report-template-grid">{reportTemplates.slice(2).map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit} key={template.id} />)}</div>
      <p className="report-template-label">차트 갤러리 <span>{REPORT_CHART_OPTIONS.length} TYPES</span></p><div className="report-chart-gallery">{REPORT_CHART_OPTIONS.map(([chartType, label]) => <button type="button" onClick={() => onAddChart(chartType)} disabled={!canEdit || !selectedArtifact?.chart} title={`${label} 차트 추가`} key={chartType}><BarChart3 size={13} /><span>{label}</span></button>)}</div>
      <p className="report-template-label">Artifact 전체</p><div className="report-artifact-library" aria-label="분석 Artifact 라이브러리">{artifactOptions.length ? artifactOptions.map((source) => <ReportArtifactLibraryTile source={source} artifact={artifacts[source.artifactId]} disabled={!canEdit || artifactStates[source.artifactId]?.status === "loading"} onAdd={onAddWholeArtifact} key={source.artifactId} />) : <p className="report-artifact-library-empty">{analysisLibraryState.status === "loading" ? "저장된 분석 결과를 확인하는 중입니다." : "보고서에 사용할 분석 결과가 없습니다."}</p>}</div>
      {analysisLibraryState.status !== "loading" && analysisLibraryState.message && <small className="report-insert-help" role={analysisLibraryState.status === "error" ? "alert" : "status"}>{analysisLibraryState.message}</small>}
      <small className="report-insert-help">Artifact 전체는 요약·KPI·차트·표를 한 블록으로 유지합니다. 원하는 위치로 끌어다 놓으세요. 행은 빈 공간 없이 자동 정렬됩니다.</small>
      <label className="report-artifact-picker"><span>개별 보기용 Artifact</span><select aria-label="표 또는 차트로 삽입할 분석 결과" value={artifactSelection} onChange={(event) => onSelectArtifact(event.target.value)} disabled={!canEdit || !artifactOptions.length}>{artifactOptions.length ? artifactOptions.map((block) => <option value={block.artifactId} key={block.artifactId}>{block.title}</option>) : <option value="">연결된 결과 없음</option>}</select></label>
      <div className="report-insert-grid">{artifactTemplates.map((template) => <TemplateTile template={template} onAdd={onAddTemplate} disabled={!canEdit || !artifactOptions.length || (template.id === "artifact-chart" && !selectedArtifact?.chart)} key={template.id} />)}</div>
      <small className="report-insert-help">표 보기만·차트 보기만은 기존 보고서 호환을 위한 개별 보기입니다. 클릭하거나 끌어 원하는 위치에 추가하세요.</small>
    </section>}
    <nav className="notion-outline" aria-label="보고서 목차"><p>목차</p>{orderedBlocks.map((block, index) => <button type="button" onClick={() => setSelectedBlockId(block.id)} aria-pressed={selectedBlockId === block.id} key={block.id}><span>{String(index + 1).padStart(2, "0")}</span><b>{block.title || "제목 없음"}</b></button>)}</nav>
    {orderedBlocks.some((block) => block.artifactId) && <details className="notion-assistant"><summary><Sparkles size={14} />AI 초안 만들기</summary><div className="assistant-source-preview"><b>선택한 원본</b><span>{selectedArtifact?.title || selectedArtifactSource?.title || "분석 결과를 선택해 주세요."}</span><small>{selectedArtifactPeriod ? `${selectedArtifactPeriod.start} ~ ${selectedArtifactPeriod.end_exclusive} 미포함` : "기간 정보 없음"}</small><small>{selectedArtifact?.evidence?.sources?.length ? `출처 ${selectedArtifact.evidence.sources.map((source) => source.name).join("·")}` : "출처 정보 없음"}</small></div><textarea aria-label="AI 초안 지시" value={assistantInstruction} onChange={(event) => setAssistantInstruction(event.target.value)} maxLength={500} placeholder="초안의 목적과 구성 원칙을 입력하세요." /><button onClick={onCreateAssistantDraft} disabled={Boolean(pending) || !selectedArtifact || !assistantInstruction.trim()}><Sparkles size={14} />선택한 원본으로 AI 초안 생성</button><small>생성 결과는 AI 초안이며 확정 전에 검토가 필요합니다.</small></details>}
  </aside>;
}, toolPanelPropsEqual);
