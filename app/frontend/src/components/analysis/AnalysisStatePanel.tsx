/** 분석 실행 상태와 governed 결과·근거를 사용자 화면으로 표현하는 모듈이다. */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleX,
  Clock3,
  FileWarning,
  Lightbulb,
  LoaderCircle,
  RotateCcw,
  SearchX,
  StopCircle,
} from "lucide-react";
import { resolveViewState, type AnalysisRun, type AnalysisViewState } from "../../contracts/analysis";
import { createAnalysisValueScale } from "./analysisValueScale";
import {
  analysisTitle,
  isNumericValue,
  seriesColor,
} from "../../utils/presentation";
import {
  AnalysisProgress,
  REQUIRED_ACTION_COPY,
  VIEW_COPY,
  columnLabel,
  columnUnit,
  compareTableValues,
  errorStateTitle,
  nextTableSort,
  tidyAnalysisTitle,
  type TableSort,
} from "./AnalysisStatePanelParts";
import {
  AnalysisConversationalSummary,
  AnalysisDataSection,
  AnalysisKpiSection,
  AnalysisUnifiedToolbar,
  AnalysisVisualSection,
} from "./AnalysisDashboardViews";

/** 상태 패널이 표시할 수 있는 뷰 모드. 서버가 확정한 target_chart_type을 그대로 받는다. */
export type ViewTypeMode = "SUMMARY" | "KPI" | "CHART" | "TABLE" | "FULL" | string;

/** 서버가 정규화한 분석 상태와 근거를 렌더링하며, 대화형 내러티브와 유연한 뷰 전환 툴바를 제공한다. */
export function AnalysisStatePanel({
  run,
  viewType = "SUMMARY",
  onSuggestion,
  onQuickView,
  onRetry,
  onCancel,
  onSave,
  onCreateReportDraft,
  onOpenEvidence,
  onPreview,
  saveDisabled = false,
  cancelRequested = false,
  suggestionsDisabled = false,
}: {
  run: AnalysisRun;
  viewType?: ViewTypeMode;
  onSuggestion?: (suggestion: string) => void;
  onQuickView?: (view: "SUMMARY" | "KPI" | "CHART" | "TABLE" | "REPORT" | "FULL") => void;
  onRetry?: () => void;
  onCancel?: () => void;
  onSave?: () => void;
  onCreateReportDraft?: () => void;
  onOpenEvidence?: () => void;
  onPreview?: () => void;
  saveDisabled?: boolean;
  cancelRequested?: boolean;
  suggestionsDisabled?: boolean;
}) {
  const viewState = resolveViewState(run);
  const copy = VIEW_COPY[viewState];
  const Icon = copy.icon;
  const showResult = viewState === "READY" || viewState === "PARTIAL";
  const chart = showResult ? run.chart : null;
  const table = showResult ? run.table : null;
  const disambiguationOptions = run.disambiguationOptions || run.error?.disambiguation_options || [];
  const suggestions = run.error?.suggestions ?? [];
  const requiredAction = run.error?.required_action ?? "NONE";
  const nextAction = REQUIRED_ACTION_COPY[requiredAction];
  const failureTitle = errorStateTitle(run.error?.code);
  const [elapsed, setElapsed] = useState(0);
  const terminalStateRef = useRef<HTMLElement | null>(null);
  const [tableSort, setTableSort] = useState<TableSort>({ column: "", direction: "" });
  const [chartDisplayOverride, setChartDisplayOverride] = useState("");
  const [localView, setLocalView] = useState<string>(viewType);

  useEffect(() => {
    setLocalView(viewType);
  }, [viewType]);

  const normalizedViewType = (localView || "SUMMARY").toUpperCase();
  const isSummaryMode = normalizedViewType === "SUMMARY";
  const isKpiMode = normalizedViewType === "KPI";
  const isChartMode = ["CHART", "BAR", "LINE", "AREA", "HORIZONTAL_BAR", "PIE"].includes(normalizedViewType);
  const isTableMode = normalizedViewType === "TABLE";
  const isFullMode = normalizedViewType === "FULL";

  const chartType = (
    ["BAR", "LINE", "AREA", "HORIZONTAL_BAR", "PIE"].includes(normalizedViewType)
      ? normalizedViewType.toLowerCase().replace("_", "-")
      : chart?.chartType?.toLocaleLowerCase("en-US") || "bar"
  );

  const supportedChartType = ["bar", "line", "area", "horizontal_bar", "horizontal-bar", "pie"].includes(chartType);
  const hasTableColumns = Boolean(table?.columns?.length);
  const chartColumns = new Set(table?.columns ?? []);
  const chartFieldsMatchTable = Boolean(
    chart
    && chart.yFields
    && chart.yFields.length > 0
    && chartColumns.has(chart.xField)
    && chart.yFields.every((field) => chartColumns.has(field)),
  );
  const canRenderChart = supportedChartType && (chartFieldsMatchTable || (table?.rows?.length ?? 0) > 0);
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
  // 모든 y 계열이 통화일 때만 축·툴팁을 확정 배율로 바꾼다. 단위가 섞이면 계열별 원래 표기를 유지한다.
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
    if (viewState !== "LOADING") return undefined;
    const startedAt = Date.now() - serverElapsed * 1000;
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [run.traceId, viewState]);

  useEffect(() => {
    setChartDisplayOverride("");
  }, [chartType, run.traceId]);

  useEffect(() => {
    if (!run.error || viewState === "LOADING" || viewState === "DELAYED") return undefined;
    const frame = window.requestAnimationFrame(() => {
      const action = terminalStateRef.current?.querySelector<HTMLElement>(".analysis-suggestions button:not([disabled]), .analysis-retry:not([disabled])");
      (action ?? terminalStateRef.current)?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [run.error?.code, run.traceId, viewState]);

  const handleViewChange = (newView: "SUMMARY" | "KPI" | "CHART" | "TABLE" | "FULL") => {
    setLocalView(newView);
    onQuickView?.(newView);
  };

  if (viewState === "LOADING" || viewState === "DELAYED") {
    return (
      <section className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite" aria-busy="true">
        <header>
          <LoaderCircle className="spin" size={18} aria-hidden="true" />
          <div><b>{copy.title}</b></div>
        </header>
        <p>{copy.description}</p>
        <button type="button" className="analysis-cancel" disabled={cancelRequested} onClick={onCancel}>
          <StopCircle size={15} aria-hidden="true" />
          {cancelRequested ? "취소 요청 중" : "분석 취소"}
        </button>
        <AnalysisProgress elapsed={elapsed} />
      </section>
    );
  }

  return (
    <section ref={terminalStateRef} tabIndex={-1} className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite">
      {!showResult && (
        <header>
          <Icon size={18} aria-hidden="true" />
          <div>
            <b>
              {suggestions.length
                ? run.error?.clarification_type === "period"
                  ? "어떤 기간으로 분석할까요?"
                  : "어떤 지표로 분석할까요?"
                : run.error?.code === "CONTEXT_INCOMPLETE"
                  ? "추가 정보 필요"
                  : failureTitle || copy.title}
            </b>
          </div>
        </header>
      )}
      {!showResult && <p>{run.error?.message ?? run.summary ?? copy.description}</p>}
      {disambiguationOptions.length > 0 ? (
        <div className="analysis-disambiguation-options" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "8px", marginTop: "10px" }} aria-label={run.error?.clarification_type === "period" ? "분석 기간 선택" : "분석 지표 선택"}>
          {disambiguationOptions.map((opt, idx) => {
            const label = opt.label || opt.value || opt.metric_id || "";
            return (
              <button
                type="button"
                key={opt.value || opt.metric_id || label || idx}
                className="disambiguation-chip-btn"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  padding: "10px 12px",
                  borderRadius: "8px",
                  border: "1px solid var(--color-border, #d1d5db)",
                  background: "var(--color-surface, #ffffff)",
                  cursor: suggestionsDisabled ? "not-allowed" : "pointer",
                  textAlign: "left",
                }}
                disabled={suggestionsDisabled}
                onClick={() => onSuggestion?.(label)}
              >
                <div style={{ display: "flex", justifyContent: "space-between", width: "100%", alignItems: "center" }}>
                  <strong style={{ fontSize: "13px", color: "var(--color-text-primary, #111827)" }}>{label}</strong>
                  <span style={{ fontSize: "11px", color: "var(--color-primary, #2563eb)", background: "#eff6ff", padding: "1px 5px", borderRadius: "4px" }}>
                    {opt.clarification_type === "period" ? "기간" : "지표"}
                  </span>
                </div>
                {opt.description && (
                  <span style={{ fontSize: "11px", color: "var(--color-text-secondary, #6b7280)", marginTop: "3px", lineHeight: "1.3" }}>
                    {opt.description}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      ) : suggestions.length > 0 ? (
        <div className="analysis-suggestions" aria-label={run.error?.clarification_type === "period" ? "분석 기간 선택" : "분석 지표 선택"}>
          {suggestions.map((suggestion) => (
            <button type="button" key={suggestion} disabled={suggestionsDisabled} onClick={() => onSuggestion?.(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}
      {!showResult && requiredAction === "RETRY" && suggestions.length === 0 && disambiguationOptions.length === 0 && (
        <button type="button" className="analysis-retry" onClick={onRetry}>
          <RotateCcw size={14} />같은 질문 다시 분석
        </button>
      )}
      {!showResult && run.error && suggestions.length === 0 && disambiguationOptions.length === 0 && (
        <div className="friendly-error-card" style={{ marginTop: "14px", padding: "16px 18px", borderRadius: "10px", background: "var(--color-surface-subtle, #f9fafb)", border: "1px solid var(--color-border, #e5e7eb)", boxShadow: "0 1px 3px rgba(0,0,0,0.03)" }}>
          {nextAction && (
            <div
              className="analysis-next-action"
              style={{
                margin: "0 0 12px 0",
                padding: "10px 14px",
                borderRadius: "8px",
                background: "rgba(37, 99, 235, 0.06)",
                border: "1px solid rgba(37, 99, 235, 0.15)",
                borderLeft: "3px solid #2563eb",
                color: "#1e3a8a",
                fontSize: "13px",
                display: "flex",
                alignItems: "flex-start",
                gap: "10px",
              }}
            >
              <Lightbulb size={17} style={{ color: "#2563eb", flexShrink: 0, marginTop: "2px" }} />
              <div style={{ lineHeight: "1.5" }}>
                <strong style={{ color: "#1d4ed8", fontWeight: 600 }}>안내: </strong>
                <span>{nextAction}</span>
              </div>
            </div>
          )}

          {/* 질문 가이드 및 추천 예시 칩 */}
          {["PROVIDE_CONTEXT", "MODIFY_REQUEST"].includes(requiredAction) && (
            <div style={{ marginTop: "10px", marginBottom: "10px" }}>
              <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary, #4b5563)", display: "block", marginBottom: "8px" }}>
                추천 질문으로 바로 분석하기:
              </span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {[
                  "2026년 7월 호텔별 객실 가동률 비교",
                  "2026년 7월 호텔별 VOC 불만 접수 현황",
                  "2026년 6월 객실 매출 및 점유율",
                ].map((sample) => (
                  <button
                    key={sample}
                    type="button"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "4px",
                      padding: "6px 12px",
                      borderRadius: "6px",
                      background: "#ffffff",
                      border: "1px solid #d1d5db",
                      color: "#1f2937",
                      fontSize: "12px",
                      fontWeight: 500,
                      cursor: suggestionsDisabled ? "not-allowed" : "pointer",
                      boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                      transition: "all 0.15s ease",
                    }}
                    disabled={suggestionsDisabled}
                    onClick={() => onSuggestion?.(sample)}
                  >
                    <span>{sample}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 재시도 버튼 */}
          {run.error.retryable && (
            <div style={{ marginTop: nextAction ? "12px" : "0" }}>
              <button
                type="button"
                className="analysis-retry"
                onClick={onRetry}
                style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "8px 14px", borderRadius: "6px", background: "var(--color-primary, #2563eb)", color: "#fff", border: "none", cursor: "pointer", fontSize: "13px", fontWeight: 500, boxShadow: "0 1px 2px rgba(37,99,235,0.2)" }}
              >
                <RotateCcw size={13} />
                <span>다시 시도하기</span>
              </button>
            </div>
          )}
        </div>
      )}

      {showResult && (
        <div className="analysis-conversational-container">
          {/* 1. 최상단: AI 자연어 대화형 답변 */}
          <AnalysisConversationalSummary run={run} />

          {/* 2. 중간 시각화 영역: 활성화된 뷰에 따라 유연하게 렌더링 */}
          <div className="analysis-visual-body">
            {isSummaryMode && run.metrics?.length > 0 && (
              <AnalysisKpiSection run={run} valueScale={valueScale} />
            )}

            {isKpiMode && (
              <AnalysisKpiSection run={run} valueScale={valueScale} />
            )}

            {isChartMode && (
              <AnalysisVisualSection
                run={run}
                chart={chart}
                table={table}
                canRenderChart={canRenderChart}
                supportedChartType={supportedChartType}
                hasTableColumns={hasTableColumns}
                chartTitle={chartTitle}
                chartDisplayOptions={chartDisplayOptions}
                chartDisplayType={chartDisplayType}
                setChartDisplayOverride={setChartDisplayOverride}
                chartLines={chartLines}
                chartHeight={chartHeight}
                chartDescription={chartDescription}
                columnLabel={columnLabel}
                valueScale={valueScale}
                chartCurrencyField={chartCurrencyField}
              />
            )}

            {isTableMode && (
              <AnalysisDataSection
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
            )}

            {isFullMode && (
              <div className="analysis-full-view-stack">
                <AnalysisKpiSection run={run} valueScale={valueScale} />
                <AnalysisVisualSection
                  run={run}
                  chart={chart}
                  table={table}
                  canRenderChart={canRenderChart}
                  supportedChartType={supportedChartType}
                  hasTableColumns={hasTableColumns}
                  chartTitle={chartTitle}
                  chartDisplayOptions={chartDisplayOptions}
                  chartDisplayType={chartDisplayType}
                  setChartDisplayOverride={setChartDisplayOverride}
                  chartLines={chartLines}
                  chartHeight={chartHeight}
                  chartDescription={chartDescription}
                  columnLabel={columnLabel}
                  valueScale={valueScale}
                  chartCurrencyField={chartCurrencyField}
                />
                <AnalysisDataSection
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
              </div>
            )}
          </div>

          {/* 3. 하단: 일체형 세그먼트 뷰 전환 탭 + 통합 액션 툴바 */}
          <AnalysisUnifiedToolbar
            activeView={localView}
            onViewChange={handleViewChange}
            onSave={onSave}
            onCreateReportDraft={onCreateReportDraft}
            onOpenEvidence={onOpenEvidence}
            onPreview={onPreview}
            saveDisabled={saveDisabled}
            hasMetrics={Boolean(run.metrics?.length)}
            hasChart={Boolean(chart && canRenderChart)}
            hasTable={Boolean(table?.rows?.length)}
          />
        </div>
      )}
    </section>
  );
}
