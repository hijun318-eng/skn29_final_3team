/** 분석 대시보드의 대화형 요약, KPI, 차트, 데이터 테이블, 통합 뷰·액션 툴바 서브 컴포넌트들을 렌더링하는 모듈이다. */
import React from "react";
import { AlertTriangle, ArrowUpDown, BarChart3, Eye, FilePlus2, LayoutGrid, MessageSquare, Save, Search, TableProperties, Target } from "lucide-react";
import { EnterpriseChart } from "../charts/EnterpriseChart";
import { type AnalysisRun } from "../../contracts/analysis";
import { type AnalysisValueScale } from "./analysisValueScale";
import { formatCompactNumber, formatMetricValue, isNumericValue, metricUnitLabel } from "../../utils/presentation";

/**
 * KPI 카드의 숫자 표기를 결정한다. 1억 이상은 단위 문자열과 무관하게 축약해 카드 안에서 한 줄로 읽히게 하며,
 * 손실 없는 원값은 호출부가 `title` 속성으로 함께 노출한다.
 */
function formatKpiValue(value: unknown, unit?: string | null) {
  const numeric = Number(value);
  if (isNumericValue(value) && Math.abs(numeric) >= 100_000_000) return formatCompactNumber(numeric);
  return formatMetricValue(value, { includeUnit: false, unit });
}

/** 대화형 AI 내러티브 요약을 렌더링한다. 데이터 출처 고지는 보고서 artifact 화면이 담당한다. */
export function AnalysisConversationalSummary({ run }: { run: AnalysisRun }) {
  return (
    <div className="agent-conversational-bubble" aria-label="AI 분석 요약">
      <p className="agent-narrative-text">{run.summary || "선택한 조건의 지표 계산이 완료되었습니다."}</p>
    </div>
  );
}

/**
 * 핵심 KPI 지표 카드 목록 및 차원 세부 분해(Breakdown: 전체 합계 + 항목별 개별 지표)를 렌더링한다.
 * 금액은 `valueScale`이 결과 한 건 단위로 확정한 통화 배율만 사용하고, 손실 없는 원값은 `title`로 노출한다.
 */
export function AnalysisKpiSection({ run, valueScale }: { run: AnalysisRun; valueScale: AnalysisValueScale }) {
  if (!run.metrics || run.metrics.length === 0) return null;
  const rows = run.table?.rows ?? [];
  const columns = run.table?.columns ?? [];
  const chartX = run.chart?.xField;
  const dimensionCol = chartX && columns.includes(chartX)
    ? chartX
    : columns.find((c) => rows.some((r) => typeof r[c] === "string" && !isNumericValue(r[c])));
  const hasBreakdown = Boolean(dimensionCol && rows.length > 1 && rows.length <= 16);

  return (
    <section className="analysis-kpi-section" aria-labelledby="analysis-kpi-title">
      {/* 차트·표 섹션과 같은 (eyebrow + 제목 + 우측 메타) 헤더 구조를 공유해 시선 이동을 단순화한다. */}
      <header>
        <div><small>핵심 지표</small><h3 id="analysis-kpi-title">주요 KPI</h3></div>
        <span>{hasBreakdown ? `전체 · ${rows.length}개 항목별 상세` : `${run.metrics?.length ?? 0}개 지표`}</span>
      </header>
      <div className="analysis-metrics">
        {run.metrics.map((metric) => (
          <article key={`total-${metric.metricId}`} className="analysis-metric-card--total">
            {/* 배지와 지표명을 세로로 쌓아, 지표명이 길어도 배지 위로 겹치지 않게 한다. */}
            <div className="metric-header-strip">
              {hasBreakdown && <span className="metric-badge-total">전체</span>}
              <small>{metric.label}</small>
            </div>
            <strong title={valueScale.exact(metric.value, metric.unit)}>
              {valueScale.isCurrency(metric.unit) ? valueScale.format(metric.value, metric.unit, metric.resultField) : formatKpiValue(metric.value, metric.unit)}
              {metric.unit && metric.value !== null && metric.value !== undefined && metric.value !== "" && <em>{valueScale.unitLabel(metric.unit, metric.resultField)}</em>}
            </strong>
            {metric.definition && <p>{metric.definition}</p>}
          </article>
        ))}
        {hasBreakdown && dimensionCol && rows.flatMap((row, idx) => {
          const dimVal = String(row[dimensionCol] ?? `항목 ${idx + 1}`);
          return run.metrics.map((metric) => {
            const rowVal = row[metric.resultField] ?? row[metric.metricId];
            if (rowVal === undefined || rowVal === null) return null;
            const numericTotal = Number(metric.value);
            const numericRow = Number(rowVal);
            const sharePercent = metric.unit?.trim().toLowerCase() !== "ratio" && !Number.isNaN(numericTotal) && !Number.isNaN(numericRow) && numericTotal > 0
              ? ((numericRow / numericTotal) * 100).toFixed(1)
              : null;
            return (
              <article key={`item-${dimVal}-${metric.metricId}`} className="analysis-metric-card--item">
                <div className="metric-header-strip">
                  <span className="metric-dim-badge">{dimVal}</span>
                  <small>{metric.label}</small>
                </div>
                <strong title={valueScale.exact(rowVal, metric.unit)}>
                  {valueScale.isCurrency(metric.unit) ? valueScale.format(rowVal, metric.unit, metric.resultField) : formatKpiValue(rowVal, metric.unit)}
                  {metric.unit && rowVal !== "" && <em>{valueScale.unitLabel(metric.unit, metric.resultField)}</em>}
                </strong>
                {sharePercent && <p className="metric-share-text">전체의 <b>{sharePercent}%</b> 비중</p>}
              </article>
            );
          });
        })}
      </div>
    </section>
  );
}

/** 차트 시각화 및 실패 시의 fallback 섹션을 렌더링한다. */
export function AnalysisVisualSection({
  run, chart, table, canRenderChart, supportedChartType, hasTableColumns, chartTitle, chartDisplayOptions,
  chartDisplayType, setChartDisplayOverride, chartLines, chartHeight, chartDescription, columnLabel,
  valueScale, chartCurrencyField,
}: {
  run: AnalysisRun; chart: NonNullable<AnalysisRun["chart"]> | null; table: NonNullable<AnalysisRun["table"]> | null;
  canRenderChart: boolean; supportedChartType: boolean; hasTableColumns: boolean; chartTitle: string;
  chartDisplayOptions: Array<{ type: string; label: string }>; chartDisplayType: string;
  setChartDisplayOverride: React.Dispatch<React.SetStateAction<string>>;
  chartLines: Array<{ key: string; label: string; color: string; unit?: string }>;
  chartHeight: number; chartDescription: string; columnLabel: (col: string, r: AnalysisRun) => string;
  valueScale: AnalysisValueScale; chartCurrencyField: string | null;
}) {
  if (chart && table && canRenderChart) {
    return (
      <section className="analysis-result-section analysis-visual-section">
        <header>
          <div><small>차트 시각화</small><h3>{chartTitle}</h3></div>
          <div className="analysis-chart-actions">
            <span>{(table?.rows?.length ?? 0).toLocaleString("ko-KR")}개 항목</span>
            {chartDisplayOptions.length > 0 && (
              <div role="group" aria-label="차트 표현 방식">
                {chartDisplayOptions.map((option) => (
                  <button type="button" key={option.type} aria-pressed={chartDisplayType === option.type} onClick={() => setChartDisplayOverride(option.type)}>
                    {option.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </header>
        <figure className="analysis-chart">
          <EnterpriseChart
            data={table.rows ?? []} xKey={chart.xField} xLabel={columnLabel(chart.xField, run)} series={chartLines}
            type={chartDisplayType} height={chartHeight}
            valueFormatter={(value, item) => (chartCurrencyField
              ? `${valueScale.format(value, "KRW", chartCurrencyField)}${item?.unit ? ` ${item.unit}` : ""}`
              : formatMetricValue(value, { unit: item?.unit }))}
            axisFormatter={chartCurrencyField ? (value) => valueScale.format(value, "KRW", chartCurrencyField) : formatCompactNumber}
            ariaLabel={`${chartTitle} 차트`} description={chartDescription}
          />
          <figcaption>{chartDescription}</figcaption>
        </figure>
      </section>
    );
  }
  if (chart && (!hasTableColumns || (Boolean(table?.rows?.length) && !canRenderChart))) {
    return (
      <section className="analysis-chart-fallback" role="status">
        <AlertTriangle size={16} aria-hidden="true" />
        <div>
          <b>{supportedChartType ? "차트 메타데이터를 확인할 수 없습니다." : "지원하지 않는 차트 형식입니다."}</b>
          <p>
            {supportedChartType
              ? hasTableColumns ? "차트 필드와 상세 데이터 열이 일치하지 않아 임의로 해석하지 않았습니다. 제공된 데이터는 아래 표에서 확인할 수 있습니다." : "차트와 연결된 상세 데이터가 없어 임의로 시각화하지 않았습니다."
              : <>데이터를 임의의 차트로 바꾸지 않고 아래 표로 표시합니다. 차트 형식 <code>{chart.chartType || "없음"}</code></>}
          </p>
        </div>
      </section>
    );
  }
  return null;
}

/** 상세 데이터 표 섹션을 렌더링한다. 금액 열은 KPI·차트와 같은 통화 배율(`valueScale`)로 표시한다. */
export function AnalysisDataSection({
  run, table, resultTitle, tableSort, setTableSort, nextTableSort, numericColumns, visibleRows, columnLabel, columnUnit,
  valueScale,
}: {
  run: AnalysisRun; table: NonNullable<AnalysisRun["table"]> | null; resultTitle: string;
  tableSort: { column: string; direction: "" | "asc" | "desc" };
  setTableSort: React.Dispatch<React.SetStateAction<{ column: string; direction: "" | "asc" | "desc" }>>;
  nextTableSort: (curr: { column: string; direction: "" | "asc" | "desc" }, col: string) => { column: string; direction: "" | "asc" | "desc" };
  numericColumns: Set<string>; visibleRows: Array<Record<string, unknown>>;
  columnLabel: (col: string, r: AnalysisRun) => string; columnUnit: (col: string, r: AnalysisRun) => string | null;
  valueScale: AnalysisValueScale;
}) {
  if (!table?.columns?.length) return null;
  return (
    <section className="analysis-result-section analysis-data-section">
      <header>
        <div><small>데이터</small><h3>상세 데이터</h3></div>
        <span>{(table?.rows?.length ?? 0).toLocaleString("ko-KR")}행 · {(table?.columns?.length ?? 0).toLocaleString("ko-KR")}열</span>
      </header>
      <div className="analysis-table" tabIndex={0} aria-label="상세 데이터 표">
        <table>
          <caption className="sr-only">{resultTitle} 상세 데이터</caption>
          <thead>
            <tr>
              <th scope="col" className="row-number">#</th>
              {table.columns.map((column) => {
                const unit = valueScale.unitLabel(columnUnit(column, run), column);
                const label = columnLabel(column, run);
                return (
                  <th scope="col" aria-sort={tableSort.column === column ? (tableSort.direction === "asc" ? "ascending" : "descending") : "none"} className={numericColumns.has(column) ? "is-numeric" : ""} key={column}>
                    <button type="button" className="analysis-table-sort" aria-label={`${metricUnitLabel(label, unit)} 열 정렬`} onClick={() => setTableSort((current) => nextTableSort(current, column))}>
                      <span>{label}{unit && <small className="analysis-column-unit">{unit}</small>}</span>
                      <ArrowUpDown size={12} aria-hidden="true" />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <tr key={`${run.requestId}-${index}`}>
                <th scope="row" className="row-number">{index + 1}</th>
                {table.columns.map((column) => (
                  <td className={numericColumns.has(column) ? "is-numeric" : ""} key={column} title={valueScale.exact(row[column], columnUnit(column, run))}>
                    {valueScale.format(row[column], columnUnit(column, run), column)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** 점진적 뷰 전환 세그먼트 탭과 액션 버튼들을 하나의 일체형 툴바로 렌더링한다. */
export function AnalysisUnifiedToolbar({
  activeView, onViewChange, onSave, onCreateReportDraft, onOpenEvidence, onPreview,
  saveDisabled = false, hasMetrics = false, hasChart = false, hasTable = false,
}: {
  activeView: string; onViewChange?: (view: "SUMMARY" | "KPI" | "CHART" | "TABLE" | "FULL") => void;
  onSave?: () => void; onCreateReportDraft?: () => void; onOpenEvidence?: () => void; onPreview?: () => void;
  saveDisabled?: boolean; hasMetrics?: boolean; hasChart?: boolean; hasTable?: boolean;
}) {
  const norm = activeView.toUpperCase();
  return (
    <div className="analysis-unified-toolbar" aria-label="뷰 전환 및 분석 액션">
      <div className="view-segment-group" role="tablist" aria-label="시각화 모드">
        <button type="button" role="tab" aria-selected={norm === "SUMMARY"} className={`segment-btn ${norm === "SUMMARY" ? "active" : ""}`} onClick={() => onViewChange?.("SUMMARY")}>
          <MessageSquare size={13} /><span>대화 요약</span>
        </button>
        {hasMetrics && (
          <button type="button" role="tab" aria-selected={norm === "KPI"} className={`segment-btn ${norm === "KPI" ? "active" : ""}`} onClick={() => onViewChange?.("KPI")}>
            <Target size={13} /><span>주요 지표</span>
          </button>
        )}
        {hasChart && (
          <button type="button" role="tab" aria-selected={["CHART", "BAR", "LINE", "AREA", "HORIZONTAL_BAR"].includes(norm)} className={`segment-btn ${["CHART", "BAR", "LINE", "AREA", "HORIZONTAL_BAR"].includes(norm) ? "active" : ""}`} onClick={() => onViewChange?.("CHART")}>
            <BarChart3 size={13} /><span>그래프</span>
          </button>
        )}
        {hasTable && (
          <button type="button" role="tab" aria-selected={norm === "TABLE"} className={`segment-btn ${norm === "TABLE" ? "active" : ""}`} onClick={() => onViewChange?.("TABLE")}>
            <TableProperties size={13} /><span>상세 표</span>
          </button>
        )}
        <button type="button" role="tab" aria-selected={norm === "FULL"} className={`segment-btn ${norm === "FULL" ? "active" : ""}`} onClick={() => onViewChange?.("FULL")}>
          <LayoutGrid size={13} /><span>전체</span>
        </button>
      </div>

      <div className="action-button-group">
        {onSave && (
          <button type="button" className="unified-action-btn" disabled={saveDisabled} onClick={onSave} title="분석 저장하여 KPI 및 대시보드에서 활용">
            <Save size={13} /><span>분석 저장</span>
          </button>
        )}
        {onCreateReportDraft && (
          <button type="button" className="unified-action-btn unified-action-btn--primary" onClick={onCreateReportDraft} title="보고서 초안 블록으로 연결">
            <FilePlus2 size={13} /><span>보고서에 담기</span>
          </button>
        )}
        {onPreview && (
          <button type="button" className="unified-action-btn" onClick={onPreview} title="결과 전체 미리보기">
            <Eye size={13} /><span>미리보기</span>
          </button>
        )}
        {onOpenEvidence && (
          <button type="button" className="unified-action-btn" onClick={onOpenEvidence} title="DataHub 거버넌스 및 AST SQL 검증 근거">
            <Search size={13} /><span>분석 근거</span>
          </button>
        )}
      </div>
    </div>
  );
}

/** 하위 호환성을 위한 레거시 별칭 */
export const AnalysisViewSwitcherBar = AnalysisUnifiedToolbar;
