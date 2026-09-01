/** artifact library tile과 전체 artifact block 조합 UI를 제공하는 모듈이다. */
import { BarChart3, Check, ChevronDown, GripVertical, Layers3, Table2 } from "lucide-react";
import { useDraggable } from "@dnd-kit/core";

import { formatMetricValue } from "../../utils/presentation";
import { formatCurrencyAmount, isCurrencyMetricUnit } from "./reportCurrency";
import { WHOLE_ARTIFACT_VIEWS, artifactMetricCards, wholeArtifactSettings } from "./reportDraftV2";
import { analysisTimeLabel } from "./reportAnalysisArtifacts";
import { reportTimeRangeLabel } from "./reportTimePresentation.js";

function shortSummary(summary) {
  const value = String(summary || "").trim();
  if (!value) return "이 분석에는 별도 요약이 제공되지 않았습니다.";
  return value.length > 240 ? `${value.slice(0, 239).trimEnd()}…` : value;
}

function libraryMetricTitle(source, artifact) {
  const labels = [...new Set((artifact?.evidence?.metrics ?? artifact?.metrics ?? [])
    .map((metric) => String(metric?.label || "").trim())
    .filter(Boolean))];
  if (labels.length > 1) return `${labels[0]} 외 ${labels.length - 1}개 지표`;
  return labels[0] || source.definitionTitle || source.title || "분석 결과";
}

function libraryRunLabel(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return "";
  return `실행 ${new Intl.DateTimeFormat("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)}`;
}

function ArtifactLibraryAction({ description, disabled, dragId, icon: Icon, label, onAdd }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging } = useDraggable({
    id: dragId,
    disabled,
    data: { kind: "artifact-library-action" },
  });
  return <div ref={setNodeRef} className={`report-artifact-library-action ${isDragging ? "is-dragging" : ""}`}>
    <button type="button" disabled={disabled} onClick={onAdd}>
      <Icon size={14} aria-hidden="true" />
      <span><b>{label}</b><small>{description}</small></span>
    </button>
    <button ref={setActivatorNodeRef} type="button" className="report-artifact-library-drag" disabled={disabled} aria-label={`${label} 끌어서 추가`} title="끌어서 원하는 위치에 추가" {...listeners} {...attributes}><GripVertical size={14} aria-hidden="true" /></button>
  </div>;
}

/** 분석 결과와 그 아래 추가 가능한 보기를 한 계층으로 묶어 표시한다. */
export function ReportArtifactLibraryTile({
  source,
  artifact,
  disabled = false,
  onAdd,
  onAddView,
  onSelect,
  selected = false,
}) {
  const availableViews = [
    artifact?.summary && "요약",
    artifactMetricCards(artifact).length && "핵심 지표",
    artifact?.chart && "차트",
    artifact?.table && "표",
  ].filter(Boolean);
  const title = libraryMetricTitle(source, artifact);
  const time = reportTimeRangeLabel(artifact) || analysisTimeLabel(artifact?.evidence, {
    start: source.periodStart,
    end_exclusive: source.periodEndExclusive,
    cutoff: source.snapshotCutoff,
    selection: source.snapshotSelection,
  });
  const qualifiers = [time, libraryRunLabel(source.completedAt)].filter(Boolean);
  return <article className={`report-artifact-library-tile ${selected ? "is-selected" : ""}`}>
    <button type="button" className="report-artifact-library-summary" disabled={disabled} aria-expanded={selected} onClick={() => onSelect(selected ? "" : source.artifactId)}>
      <span className="report-artifact-library-icon"><Layers3 size={16} aria-hidden="true" /></span>
      <span><b>{title}</b>{qualifiers.length > 0 && <small>{qualifiers.join(" · ")}</small>}<em>{availableViews.length ? availableViews.join(" · ") : "분석 보기 확인 중"}</em></span>
      {selected && <span className="report-artifact-library-selected"><Check size={12} aria-hidden="true" />선택됨</span>}
      <ChevronDown className="report-artifact-library-chevron" size={15} aria-hidden="true" />
    </button>
    {selected && <div className="report-artifact-library-views" aria-label={`${title}에 추가할 내용`}>
      <ArtifactLibraryAction label="전체 구성" description="요약·지표·차트·표" icon={Layers3} dragId={`artifact:${source.artifactId}`} disabled={disabled} onAdd={() => onAdd(source.artifactId)} />
      {artifact?.table && <ArtifactLibraryAction label="표" description="상세 데이터" icon={Table2} dragId={`artifact-view:${source.artifactId}:artifact-table`} disabled={disabled} onAdd={() => onAddView(source.artifactId, "artifact-table")} />}
      {artifact?.chart && <ArtifactLibraryAction label="차트" description="기본 차트" icon={BarChart3} dragId={`artifact-view:${source.artifactId}:artifact-chart`} disabled={disabled} onAdd={() => onAddView(source.artifactId, "artifact-chart")} />}
    </div>}
  </article>;
}

/** 전체 artifact의 선택 view를 근거 상태·통화 정책과 함께 한 블록으로 렌더링한다. */
export function ReportWholeArtifactBlock({ block, artifact, artifactState, currency, renderView }) {
  if (!artifact || artifactState?.status !== "success") return renderView("table", { height: 5 });
  const settings = wholeArtifactSettings(block) || { visibleViews: WHOLE_ARTIFACT_VIEWS };
  const metrics = artifactMetricCards(artifact);
  const visibleViewIds = settings.visibleViews.filter((view) => ({
    summary: Boolean(String(artifact.summary || "").trim()),
    kpi: metrics.length > 0,
    chart: Boolean(artifact.chart),
    table: Boolean(artifact.table),
  })[view]);
  const views = new Set(visibleViewIds.length ? visibleViewIds : ["summary"]);
  const visibleMetrics = metrics.slice(0, block.w <= 6 ? 2 : 4);
  const rows = artifact.table?.rows || [];
  const rowLimit = block.w <= 6 ? 3 : 4;
  const visibleRows = rows.slice(0, rowLimit);
  const tableArtifact = artifact.table ? { ...artifact, table: { ...artifact.table, rows: visibleRows } } : artifact;
  const timeDescription = reportTimeRangeLabel(artifact) || analysisTimeLabel(artifact.evidence);
  const titleHasTime = Boolean(
    timeDescription
    && String(block.title || "").includes(String(artifact.evidence?.period?.start || "").slice(0, 4)),
  );
  const showTimeContext = Boolean(timeDescription && !titleHasTime);
  const gridRows = [showTimeContext && "auto", views.has("summary") && "auto", views.has("kpi") && "auto", (views.has("chart") || views.has("table")) && "minmax(0, 1fr)"].filter(Boolean).join(" ");
  return <section className={`report-whole-artifact ${block.w <= 6 ? "is-half" : ""}`} style={{ gridTemplateRows: gridRows }} aria-label={`${block.title} 분석 결과`}>
    {showTimeContext && <p className="report-whole-artifact-context">{timeDescription}</p>}
    {views.has("summary") && <p className="report-whole-artifact-summary">{shortSummary(artifact.summary)}</p>}
    {views.has("kpi") && <div className="report-whole-artifact-kpis" aria-label="핵심 지표">{visibleMetrics.length ? visibleMetrics.map((metric) => { const currencyMetric = isCurrencyMetricUnit(metric.unit); const meta = metric.context || ""; return <dl key={metric.metric_id || metric.metricId || metric.label}><dt>{metric.label}{meta && <small>{meta}</small>}</dt><dd>{currencyMetric ? formatCurrencyAmount(metric.value, currency.unit, currency.policy, true) : formatMetricValue(metric.value, { unit: metric.unit })}</dd></dl>; }) : <p>별도 핵심 지표가 제공되지 않았습니다.</p>}{metrics.length > visibleMetrics.length && <small>외 {metrics.length - visibleMetrics.length}개 지표</small>}</div>}
    <div className="report-whole-artifact-views">
      {views.has("chart") && artifact.chart && <section><h3>변화와 구성</h3>{renderView("chart", { height: 6 })}</section>}
      {views.has("table") && artifact.table && <section><h3>상세 데이터</h3>{renderView("table", { height: 5, artifact: tableArtifact })}{rows.length > visibleRows.length && <p className="report-whole-artifact-more">현재 {visibleRows.length}행 표시 · 나머지 {rows.length - visibleRows.length}행은 원본 분석 결과에서 확인</p>}</section>}
    </div>
  </section>;
}
