/** 분석 실행 상태와 governed 결과·근거를 사용자 화면으로 표현하는 모듈이다. */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  LoaderCircle,
  StopCircle,
} from "lucide-react";
import {
  resolveViewState,
  type AnalysisProcessViewModel,
  type AnalysisRun,
} from "../../contracts/analysis";
import { createAnalysisValueScale } from "./analysisValueScale";
import { AnalysisFailureState } from "./AnalysisFailureState";
import {
  analysisTitle,
  isNumericValue,
  seriesColor,
} from "../../utils/presentation";
import {
  AnalysisProgress,
  VIEW_COPY,
  columnLabel,
  columnUnit,
  compareTableValues,
  createAnalysisProcessViewModel,
  nextTableSort,
  tidyAnalysisTitle,
  type TableSort,
} from "./AnalysisStatePanelParts";
import {
  AnalysisConversationalSummary,
  AnalysisDataSection,
  AnalysisKpiSection,
  AnalysisUnifiedToolbar,
  AnalysisUnavailableView,
  AnalysisVisualSection,
} from "./AnalysisDashboardViews";

/** 상태 패널이 표시할 수 있는 뷰 모드. 서버가 확정한 target_chart_type을 그대로 받는다. */
export type ViewTypeMode = "SUMMARY" | "KPI" | "CHART" | "TABLE" | "FULL" | string;

/** 렌더링할 구조화 결과의 개수와 형태만으로 대화 결과 폭을 결정한다. */
export function analysisResultDensity(run: AnalysisRun, viewType: ViewTypeMode = "SUMMARY") {
  const mode = (viewType || "SUMMARY").toUpperCase();
  const showsMetrics = mode === "SUMMARY" || mode === "KPI" || mode === "FULL";
  const showsTable = mode === "TABLE" || mode === "FULL";
  const showsChart = mode === "CHART" || mode === "FULL"
    || ["BAR", "LINE", "AREA", "HORIZONTAL_BAR", "PIE", "DONUT"].includes(mode);
  const metricCount = showsMetrics ? (run.metrics?.length ?? 0) : 0;
  const columnCount = showsTable ? (run.table?.columns?.length ?? 0) : 0;
  const rowCount = showsTable ? (run.table?.rows?.length ?? 0) : 0;

  // 열 수는 가로 폭을, 행 수는 표 내부의 세로 스크롤을 결정한다.
  // 행이 많다는 이유만으로 대화 말풍선 전체를 넓히지 않는다.
  if (showsTable && columnCount > 3) return "wide";
  if (showsChart && run.chart) return "regular";
  if (showsTable) return columnCount === 1 && rowCount === 1 && metricCount <= 1 ? "compact" : "regular";
  if (showsMetrics) {
    if (metricCount <= 1) return "compact";
    if (metricCount <= 3) return "regular";
    return "wide";
  }
  return "regular";
}

/** 서버가 정규화한 분석 상태와 근거를 렌더링하며, 대화형 내러티브와 유연한 뷰 전환 툴바를 제공한다. */
export function AnalysisStatePanel({
  run,
  viewType = "SUMMARY",
  onSuggestion,
  onRetry,
  onCancel,
  onSave,
  onCreateReportDraft,
  onOpenEvidence,
  onPreview,
  artifactReuse = null,
  processViewModel = null,
  saveDisabled = false,
  cancelRequested = false,
  suggestionsDisabled = false,
}: {
  run: AnalysisRun;
  viewType?: ViewTypeMode;
  onSuggestion?: (suggestion: string) => void;
  onRetry?: () => void;
  onCancel?: () => void;
  onSave?: () => void;
  onCreateReportDraft?: () => void;
  onOpenEvidence?: () => void;
  onPreview?: () => void;
  artifactReuse?: { pending?: boolean; viewSpecId?: string | null } | null;
  processViewModel?: AnalysisProcessViewModel | null;
  saveDisabled?: boolean;
  cancelRequested?: boolean;
  suggestionsDisabled?: boolean;
}) {
  const viewState = resolveViewState(run);
  const copy = VIEW_COPY[viewState];
  const showResult = viewState === "READY" || viewState === "PARTIAL";
  const chart = showResult ? run.chart : null;
  const table = showResult ? run.table : null;
  const [elapsed, setElapsed] = useState(0);
  const terminalStateRef = useRef<HTMLElement | null>(null);
  const [tableSort, setTableSort] = useState<TableSort>({ column: "", direction: "" });
  const [chartDisplayOverride, setChartDisplayOverride] = useState("");

  const normalizedViewType = (viewType || "SUMMARY").toUpperCase();
  const isSummaryMode = normalizedViewType === "SUMMARY";
  const isKpiMode = normalizedViewType === "KPI";
  const isChartMode = ["CHART", "BAR", "LINE", "AREA", "HORIZONTAL_BAR", "PIE", "DONUT"].includes(normalizedViewType);
  const isTableMode = normalizedViewType === "TABLE";
  const isFullMode = normalizedViewType === "FULL";
  const hasMetrics = Boolean(run.metrics?.length);
  const hasTableRows = Boolean(table?.columns?.length && table?.rows?.length);
  const isPresentationPending = Boolean(artifactReuse?.pending);
  const resultDensity = !showResult || isPresentationPending
    ? "compact"
    : analysisResultDensity(run, normalizedViewType);
  const widthClass = `analysis-state--${resultDensity}-width`;
  // 차트 표현 전환은 서버가 확정한 차트 보기 요청에서만 제공한다. 기본 요약·KPI·전체 보기에는 노출하지 않는다.
  const showChartDisplayControls = isChartMode;
  const displayedProcessViewModel = processViewModel ?? createAnalysisProcessViewModel({
    kind: isPresentationPending ? "PRESENTATION" : "ANALYSIS",
    status: "running",
    elapsedSeconds: elapsed,
    cancelRequested,
  });

  const chartType = (
    ["BAR", "LINE", "AREA", "HORIZONTAL_BAR", "PIE", "DONUT"].includes(normalizedViewType)
      ? normalizedViewType.toLowerCase().replace("_", "-")
      : chart?.chartType?.toLocaleLowerCase("en-US") || "bar"
  ).replaceAll("_", "-");

  const supportedChartType = ["bar", "line", "area", "horizontal-bar", "pie", "donut"].includes(chartType);
  const hasTableColumns = Boolean(table?.columns?.length);
  const chartColumns = new Set(table?.columns ?? []);
  const chartFieldsMatchTable = Boolean(
    chart
    && chart.yFields
    && chart.yFields.length > 0
    && chartColumns.has(chart.xField)
    && chart.yFields.every((field) => chartColumns.has(field)),
  );
  const canRenderChart = supportedChartType && chartFieldsMatchTable && (table?.rows?.length ?? 0) > 0;
  // KPI·차트·표가 같은 통화 배율을 쓰도록 결과 한 건당 한 번만 배율을 정한다.
  const valueScale = useMemo(
    () => createAnalysisValueScale(run.metrics ?? [], table?.rows ?? []),
    [run.metrics, table?.rows],
  );
  const chartLines = chart?.yFields?.map((field, index) => ({
    key: field,
    label: columnLabel(field, run),
    color: seriesColor(index),
    unit: valueScale.unitLabel(columnUnit(field, run), field) ?? undefined,
  })) ?? [];
  // 모든 y 계열이 같은 통화 배율일 때만 축·툴팁을 그 배율로 통일한다. 배율이 갈리면 계열별 원래 표기를 유지한다.
  const chartCurrencyField = valueScale.sharedCurrencyLabel(chart?.yFields ?? []) ? (chart?.yFields?.[0] ?? null) : null;
  const chartTitle = chart ? `${columnLabel(chart.xField, run)}별 ${chartLines.map((line) => line.label).join("·")}` : "데이터 시각화";
  const resultTitle = tidyAnalysisTitle(analysisTitle(run));
  const hasLongCategories = Boolean(chart && table?.rows?.some((row) => [...String(row[chart.xField] ?? "")].length > 10));
  const defaultChartDisplayType = chartType === "bar" && hasLongCategories ? "horizontal-bar" : chartType;

  const chartDisplayOptions = [
    { type: "bar", label: "세로 막대" },
    { type: "horizontal-bar", label: "가로 막대" },
    { type: "line", label: "선 그래프" },
    { type: "area", label: "영역 차트" },
    ...(["pie", "donut"].includes(chartType)
      ? [{ type: "pie", label: "원형" }, { type: "donut", label: "도넛" }]
      : []),
  ];

  const chartDisplayType = chartDisplayOptions.some((option) => option.type === chartDisplayOverride)
    ? chartDisplayOverride
    : defaultChartDisplayType;
  const chartHeight = chartDisplayType === "horizontal-bar"
    ? Math.max(280, Math.min(420, (table?.rows?.length ?? 0) * 46 + 54))
    : 280;
  const chartDescription = chart
    ? `${columnLabel(chart.xField, run)} 기준으로 ${chartLines.map((line) => line.label).join(", ")}을 비교합니다.`
    : "";
  const numericColumns = new Set(table?.columns?.filter((column) => table?.rows?.some((row) => (
    isNumericValue(row[column])
  ))) ?? []);
  const visibleRows = useMemo(() => {
    if (!table?.rows || !tableSort.column) return table?.rows ?? [];
    return [...table.rows].sort((left, right) => {
      const comparison = compareTableValues(left[tableSort.column], right[tableSort.column]);
      return tableSort.direction === "desc" ? -comparison : comparison;
    });
  }, [table?.rows, tableSort]);

  useEffect(() => {
    const serverElapsed = Math.floor(run.elapsedSeconds ?? 0);
    setElapsed(serverElapsed);
    if (viewState !== "LOADING" && viewState !== "DELAYED" && !isPresentationPending) return undefined;
    const startedAt = Date.now() - serverElapsed * 1000;
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [isPresentationPending, run.elapsedSeconds, run.traceId, viewState]);

  useEffect(() => {
    setChartDisplayOverride("");
  }, [chartType, run.traceId]);

  useEffect(() => {
    if (!run.error || viewState === "LOADING" || viewState === "DELAYED") return undefined;
    const frame = window.requestAnimationFrame(() => {
      const action = terminalStateRef.current?.querySelector<HTMLElement>(".analysis-diagnostic__options button:not([disabled]), .analysis-diagnostic__action:not([disabled])");
      (action ?? terminalStateRef.current)?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [run.error?.code, run.traceId, viewState]);

  if (viewState === "LOADING" || viewState === "DELAYED") {
    return (
      <section className={`analysis-state analysis-state--${viewState.toLowerCase()} ${widthClass}`} data-result-density={resultDensity} aria-live="polite" aria-busy="true">
        <header>
          <LoaderCircle className="spin" size={18} aria-hidden="true" />
          <div><b>{copy.title}</b></div>
        </header>
        <p>{copy.description}</p>
        <button type="button" className="analysis-cancel" disabled={cancelRequested} onClick={onCancel}>
          <StopCircle size={15} aria-hidden="true" />
          {cancelRequested ? "취소 요청 중" : "분석 취소"}
        </button>
        <AnalysisProgress model={displayedProcessViewModel} />
      </section>
    );
  }

  return (
    <section ref={terminalStateRef} tabIndex={-1} className={`analysis-state analysis-state--${viewState.toLowerCase()} ${widthClass}`} data-result-density={resultDensity} aria-live="polite">
      {!showResult && (
        <AnalysisFailureState
          run={run}
          viewState={viewState}
          onSuggestion={onSuggestion}
          onRetry={onRetry}
          suggestionsDisabled={suggestionsDisabled}
        />
      )}

      {showResult && (
        <div className="analysis-conversational-container">
          {isPresentationPending && <AnalysisProgress model={displayedProcessViewModel} />}

          {!isPresentationPending && <div className="analysis-visual-body">
            {isSummaryMode && (
              <div className="analysis-summary-stack">
                <AnalysisConversationalSummary run={run} valueScale={valueScale} />
                {hasMetrics && <AnalysisKpiSection run={run} valueScale={valueScale} showAsOf={false} />}
              </div>
            )}

            {isKpiMode && (
              hasMetrics
                ? <AnalysisKpiSection run={run} valueScale={valueScale} />
                : <AnalysisUnavailableView view="KPI" />
            )}

            {isChartMode && (
              chart
                ? <AnalysisVisualSection
                    run={run}
                    chart={chart}
                    table={table}
                    canRenderChart={canRenderChart}
                    supportedChartType={supportedChartType}
                    hasTableColumns={hasTableColumns}
                    chartTitle={chartTitle}
                    chartDisplayOptions={chartDisplayOptions}
                    chartDisplayType={chartDisplayType}
                    showDisplayControls={showChartDisplayControls}
                    setChartDisplayOverride={setChartDisplayOverride}
                    chartLines={chartLines}
                    chartHeight={chartHeight}
                    chartDescription={chartDescription}
                    columnLabel={columnLabel}
                    valueScale={valueScale}
                    chartCurrencyField={chartCurrencyField}
                  />
                : <AnalysisUnavailableView view="CHART" />
            )}

            {isTableMode && (
              hasTableRows
                ? <AnalysisDataSection
                    run={run}
                    table={table}
                    resultTitle={resultTitle}
                    tableSort={tableSort}
                    setTableSort={setTableSort}
                    nextTableSort={nextTableSort}
                    numericColumns={numericColumns}
                    visibleRows={visibleRows}
                    columnLabel={columnLabel}
                    columnUnit={columnUnit}
                    valueScale={valueScale}
                  />
                : <AnalysisUnavailableView view="TABLE" />
            )}

            {isFullMode && (
              <div className="analysis-full-view-stack">
                <AnalysisConversationalSummary run={run} valueScale={valueScale} />
                {hasMetrics && <AnalysisKpiSection run={run} valueScale={valueScale} showAsOf={false} />}
                {chart && <AnalysisVisualSection
                  run={run}
                  chart={chart}
                  table={table}
                  canRenderChart={canRenderChart}
                  supportedChartType={supportedChartType}
                  hasTableColumns={hasTableColumns}
                  chartTitle={chartTitle}
                  chartDisplayOptions={chartDisplayOptions}
                  chartDisplayType={chartDisplayType}
                  showDisplayControls={false}
                  setChartDisplayOverride={setChartDisplayOverride}
                  chartLines={chartLines}
                  chartHeight={chartHeight}
                  chartDescription={chartDescription}
                  columnLabel={columnLabel}
                  valueScale={valueScale}
                  chartCurrencyField={chartCurrencyField}
                  showAsOf={false}
                />}
                {hasTableRows && <AnalysisDataSection
                  run={run}
                  table={table}
                  resultTitle={resultTitle}
                  tableSort={tableSort}
                  setTableSort={setTableSort}
                  nextTableSort={nextTableSort}
                  numericColumns={numericColumns}
                  visibleRows={visibleRows}
                  columnLabel={columnLabel}
                  columnUnit={columnUnit}
                  valueScale={valueScale}
                  showAsOf={false}
                />}
              </div>
            )}
          </div>}

          {!isPresentationPending && <AnalysisUnifiedToolbar
            onSave={onSave}
            onCreateReportDraft={onCreateReportDraft}
            onOpenEvidence={onOpenEvidence}
            onPreview={onPreview}
            saveDisabled={saveDisabled}
          />}
        </div>
      )}
    </section>
  );
}
