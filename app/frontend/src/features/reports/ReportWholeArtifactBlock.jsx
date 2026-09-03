/** artifact 원본 선택 tile과 레거시 전체 artifact block UI를 제공하는 모듈이다. */
import { AlertTriangle, Inbox, Layers3, RotateCcw } from "lucide-react";

import {
  formatMetricDisplayValue,
  localizeAnalysisPeriod,
  localizeAnalysisSummary,
  metricDisplayLabel,
} from "../../utils/presentation";
import { formatCurrencyAmount, isCurrencyMetricUnit } from "./reportCurrency";
import {
  ARTIFACT_VIEW_LABELS,
  artifactMetricCards,
  availableArtifactViews,
  wholeArtifactSettings,
} from "./reportDraftV2";
import { analysisTimeLabel } from "./reportAnalysisArtifacts";
import { reportTimeRangeLabel } from "./reportTimePresentation.js";

function shortSummary(summary) {
  const value = String(summary || "").trim();
  if (!value) return "이 분석에는 별도 요약이 제공되지 않았습니다.";
  return value.length > 240 ? `${value.slice(0, 239).trimEnd()}…` : value;
}

/** 승인된 소규모 그룹 결과를 값 재집계 없이 한 행 비교 카드로 표시한다. */
export function artifactComparisonCards(artifact, metrics) {
  if (metrics.length !== 1) return null;
  const metric = metrics[0];
  const resultField = metric.result_field || metric.resultField;
  const columns = artifact?.table?.columns || [];
  const rows = artifact?.table?.rows || [];
  if (!resultField || !columns.includes(resultField) || rows.length < 2 || rows.length > 4) return null;
  const dimension = columns.find((column) => column !== resultField);
  if (!dimension || !rows.every((row) => (
    row[dimension] !== null && row[dimension] !== undefined && String(row[dimension]).trim()
    && Number.isFinite(Number(row[resultField]))
  ))) return null;
  return { dimension, metric, resultField, rows };
}

/** governed artifact source의 근거 준비 상태를 표시하고 삽입 원본만 선택한다. */
export function ReportArtifactLibraryTile({ source, artifact, disabled = false, selected = false, onSelect }) {
  const metrics = artifactMetricCards(artifact);
  const metricLabels = [...new Set(metrics.map((metric) => metricDisplayLabel(metric)).filter(Boolean))];
  const metricLabel = metricLabels.length > 1
    ? `${metricLabels[0]} 외 ${metricLabels.length - 1}개 지표`
    : metricLabels[0] || "지표 확인 중";
  const sourceLabel = source.title || source.question || source.definitionTitle || "분석 결과";
  const periodLabel = analysisTimeLabel(artifact?.evidence, source);
  const availableViews = availableArtifactViews(artifact);
  return <article className={`report-artifact-library-tile ${selected ? "is-selected" : ""}`}>
    <button type="button" className="report-artifact-library-add" disabled={disabled} aria-pressed={selected} onClick={() => onSelect(source.artifactId)}>
      <span className="report-artifact-library-icon"><Layers3 size={16} aria-hidden="true" /></span>
      <span>
        <b title={sourceLabel}>{sourceLabel}</b>
        {periodLabel && <small className="report-artifact-library-period">{periodLabel}</small>}
        <small>{metricLabel}{availableViews.length ? ` · ${availableViews.map((view) => ARTIFACT_VIEW_LABELS[view]).join(" · ")}` : ""}</small>
      </span>
    </button>
  </article>;
}

/** 정확히 하나의 summary/KPI view를 근거 상태·통화 정책과 함께 렌더링한다. */
export function ReportWholeArtifactBlock({ block, artifact, artifactState, currency, onRetry }) {
  const settings = wholeArtifactSettings(block);
  if (!settings) {
    return <section className="report-whole-artifact report-artifact-state is-legacy" role="status">
      <AlertTriangle size={17} aria-hidden="true" />
      <div>
        <b>이전 형식의 합본 분석 요소입니다.</b>
        <p>편집 화면에서 열면 제공 가능한 요약·핵심 지표·차트·표가 각각 독립 블록으로 정리됩니다.</p>
      </div>
    </section>;
  }
  const view = settings.visibleViews[0];
  if (!artifactState || artifactState.status === "loading") {
    return <section className="report-whole-artifact report-api-state" role="status">
      <b>{ARTIFACT_VIEW_LABELS[view]} 요소를 불러오고 있습니다.</b>
    </section>;
  }
  if (artifactState.status === "error") {
    return <section className="report-whole-artifact report-artifact-state is-error" role="alert">
      <AlertTriangle size={17} aria-hidden="true" />
      <div><b>이 블록의 분석 데이터를 불러오지 못했습니다.</b>
        <p>{artifactState.message || "다른 블록은 계속 확인할 수 있습니다."}</p>
        {onRetry && artifactState.requiredAction === "RETRY" && <button type="button" onClick={onRetry}><RotateCcw size={13} aria-hidden="true" />다시 불러오기</button>}
      </div>
    </section>;
  }
  if (artifactState.status === "empty") {
    return <section className="report-whole-artifact report-artifact-state is-empty" role="status">
      <Inbox size={17} aria-hidden="true" />
      <div><b>조건에 맞는 데이터가 없습니다.</b><p>오류가 아니라 유효한 빈 분석 결과입니다.</p></div>
    </section>;
  }
  if (!artifact) {
    return <section className="report-whole-artifact report-api-state" role="alert">
      <b>{ARTIFACT_VIEW_LABELS[view]} 데이터를 표시할 수 없습니다.</b>
    </section>;
  }
  const metrics = artifactMetricCards(artifact);
  const available = ({
    summary: Boolean(String(artifact.summary || "").trim()),
    kpi: metrics.length > 0,
  })[view];
  if (!available) {
    return <section className="report-whole-artifact report-api-state" role="alert">
      <b>{ARTIFACT_VIEW_LABELS[view]} 데이터를 표시할 수 없습니다.</b>
    </section>;
  }
  const visibleViewLabel = ARTIFACT_VIEW_LABELS[view];
  const visibleMetrics = metrics.slice(0, block.w <= 6 ? 2 : 4);
  const comparison = view === "kpi" ? artifactComparisonCards(artifact, metrics) : null;
  const summaryMetrics = artifact.evidence?.metrics?.length
    ? artifact.evidence.metrics
    : metrics;
  const localizedSummary = localizeAnalysisPeriod(
    localizeAnalysisSummary(artifact.summary || "", summaryMetrics),
    artifact.evidence?.period?.start,
    artifact.evidence?.period?.end_exclusive,
  );
  const timeDescription = analysisTimeLabel(artifact.evidence);
  return <section className={`report-whole-artifact ${block.w <= 6 ? "is-half" : ""}`} aria-label={`${block.title} ${visibleViewLabel} 분석 요소`}>
    {!comparison && <header className="report-whole-artifact-heading"><div><small>분석 결과</small><b>{timeDescription || "분석 결과"}</b></div><span>{visibleViewLabel}</span></header>}
    {view === "summary" && <p className="report-whole-artifact-summary">{shortSummary(localizedSummary)}</p>}
    {view === "kpi" && <div className={`report-whole-artifact-kpis${comparison ? " is-comparison" : ""}`} style={comparison ? { "--report-kpi-columns": comparison.rows.length } : undefined} aria-label={comparison ? "항목별 주요 지표 비교" : "주요 지표"}>{comparison ? comparison.rows.map((row) => { const currencyMetric = isCurrencyMetricUnit(comparison.metric.unit); return <dl className="report-comparison-kpi" key={String(row[comparison.dimension])}><dt>{String(row[comparison.dimension])}</dt><dd>{currencyMetric ? formatCurrencyAmount(row[comparison.resultField], currency.unit, currency.policy) : formatMetricDisplayValue(row[comparison.resultField], comparison.metric)}</dd><small>{metricDisplayLabel(comparison.metric)}</small></dl>; }) : visibleMetrics.map((metric) => { const currencyMetric = isCurrencyMetricUnit(metric.unit); const meta = [metric.context, currencyMetric ? currency.label : ""].filter(Boolean).join(" · "); return <dl key={metric.metric_id || metric.metricId || metric.label}><dt>{metricDisplayLabel(metric)}{meta && <small>{meta}</small>}</dt><dd>{currencyMetric ? formatCurrencyAmount(metric.value, currency.unit, currency.policy) : formatMetricDisplayValue(metric.value, metric)}</dd></dl>; })}{!comparison && metrics.length > visibleMetrics.length && <small>외 {metrics.length - visibleMetrics.length}개 지표</small>}</div>}
  </section>;
}
