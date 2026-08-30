/** artifact library tile과 전체 artifact block 조합 UI를 제공하는 모듈이다. */
import { GripVertical, Layers3 } from "lucide-react";
import { useDraggable } from "@dnd-kit/core";

import {
  formatMetricDisplayValue,
  localizeAnalysisPeriod,
  localizeAnalysisSummary,
  metricDisplayLabel,
} from "../../utils/presentation";
import { formatCurrencyAmount, isCurrencyMetricUnit } from "./reportCurrency";
import { WHOLE_ARTIFACT_VIEWS, artifactMetricCards, wholeArtifactSettings } from "./reportDraftV2";
import { analysisTimeLabel } from "./reportAnalysisArtifacts";

function shortSummary(summary) {
  const value = String(summary || "").trim();
  if (!value) return "이 분석에는 별도 요약이 제공되지 않았습니다.";
  return value.length > 240 ? `${value.slice(0, 239).trimEnd()}…` : value;
}

/** governed artifact source의 근거 준비 상태를 표시하고 준비된 항목만 삽입하게 한다. */
export function ReportArtifactLibraryTile({ source, artifact, disabled = false, onAdd }) {
  const dragId = `artifact:${source.artifactId}`;
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging } = useDraggable({
    id: dragId,
    disabled,
    data: { kind: "artifact", artifactId: source.artifactId },
  });
  const metrics = artifactMetricCards(artifact);
  const metricLabels = [...new Set(metrics.map((metric) => metricDisplayLabel(metric)).filter(Boolean))];
  const primaryLabel = metricLabels.length > 1
    ? `${metricLabels[0]} 외 ${metricLabels.length - 1}개 지표`
    : metricLabels[0] || source.title || source.definitionTitle || "분석 결과";
  const periodLabel = analysisTimeLabel(artifact?.evidence, source);
  const availableViews = [
    artifact?.summary && "요약",
    metrics.length && "핵심 지표",
    artifact?.chart && "차트",
    artifact?.table && "표",
  ].filter(Boolean);
  return <article ref={setNodeRef} className={`report-artifact-library-tile ${isDragging ? "is-dragging" : ""}`}>
    <button type="button" className="report-artifact-library-add" disabled={disabled} onClick={() => onAdd(source.artifactId)}>
      <span className="report-artifact-library-icon"><Layers3 size={16} aria-hidden="true" /></span>
      <span>
        <b>{primaryLabel}</b>
        {periodLabel && <small className="report-artifact-library-period">{periodLabel}</small>}
        <small>{availableViews.length ? availableViews.join(" · ") : "분석 보기 확인 중"}</small>
      </span>
    </button>
    <button ref={setActivatorNodeRef} type="button" className="report-artifact-library-drag" disabled={disabled} aria-label={`${source.title || "분석 결과"} 전체 끌어서 추가`} title="분석 결과 전체를 캔버스에 끌어서 추가" {...listeners} {...attributes}><GripVertical size={15} aria-hidden="true" /></button>
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
  const viewLabels = { summary: "요약", kpi: "핵심 지표", chart: "차트", table: "표" };
  const visibleMetrics = metrics.slice(0, block.w <= 6 ? 2 : 4);
  const summaryMetrics = artifact.evidence?.metrics?.length
    ? artifact.evidence.metrics
    : metrics;
  const localizedSummary = localizeAnalysisPeriod(
    localizeAnalysisSummary(artifact.summary || "", summaryMetrics),
    artifact.evidence?.period?.start,
    artifact.evidence?.period?.end_exclusive,
  );
  const rows = artifact.table?.rows || [];
  const rowLimit = block.w <= 6 ? 3 : 4;
  const visibleRows = rows.slice(0, rowLimit);
  const tableArtifact = artifact.table ? { ...artifact, table: { ...artifact.table, rows: visibleRows } } : artifact;
  const timeDescription = analysisTimeLabel(artifact.evidence);
  const gridRows = ["auto", views.has("summary") && "auto", views.has("kpi") && "auto", (views.has("chart") || views.has("table")) && "minmax(0, 1fr)"].filter(Boolean).join(" ");
  return <section className={`report-whole-artifact ${block.w <= 6 ? "is-half" : ""}`} style={{ gridTemplateRows: gridRows }} aria-label={`${block.title} 분석 결과 전체`}>
    <header className="report-whole-artifact-heading"><div><small>분석 결과</small><b>{timeDescription || "분석 결과"}</b></div><span>{[...views].map((view) => viewLabels[view]).join(" · ")}</span></header>
    {views.has("summary") && <p className="report-whole-artifact-summary">{shortSummary(localizedSummary)}</p>}
    {views.has("kpi") && <div className="report-whole-artifact-kpis" aria-label="주요 지표">{visibleMetrics.length ? visibleMetrics.map((metric) => { const currencyMetric = isCurrencyMetricUnit(metric.unit); const meta = [metric.context, currencyMetric ? currency.label : ""].filter(Boolean).join(" · "); return <dl key={metric.metric_id || metric.metricId || metric.label}><dt>{metricDisplayLabel(metric)}{meta && <small>{meta}</small>}</dt><dd>{currencyMetric ? formatCurrencyAmount(metric.value, currency.unit, currency.policy) : formatMetricDisplayValue(metric.value, metric)}</dd></dl>; }) : <p>별도 대표 지표가 제공되지 않았습니다.</p>}{metrics.length > visibleMetrics.length && <small>외 {metrics.length - visibleMetrics.length}개 지표</small>}</div>}
    <div className="report-whole-artifact-views">
      {views.has("chart") && artifact.chart && <section><h3>변화와 구성</h3>{renderView("chart", { height: 6 })}</section>}
      {views.has("table") && artifact.table && <section><h3>상세 데이터</h3>{renderView("table", { height: 5, artifact: tableArtifact })}{rows.length > visibleRows.length && <p className="report-whole-artifact-more">현재 {visibleRows.length}행 표시 · 외 {rows.length - visibleRows.length}행은 원본 Artifact에서 확인</p>}</section>}
    </div>
  </section>;
}
