/** 분석 대시보드의 대화형 요약, KPI, 차트, 데이터 테이블, 통합 뷰·액션 툴바 서브 컴포넌트들을 렌더링하는 모듈이다. */
import React from "react";
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, BarChart3, Eye, FilePlus2, Save, Search, TableProperties, Target } from "lucide-react";
import { EnterpriseChart } from "../charts/EnterpriseChart";
import { type AnalysisRun } from "../../contracts/analysis";
import { type AnalysisValueScale, userFacingAnalysisSummary } from "./analysisValueScale";
import { analysisTitle, formatCompactNumber, formatMetricValue, isNumericValue, metricDisplayLabel, metricUnitLabel } from "../../utils/presentation";

const KPI_SPARKLINE_PERIOD = /^\d{4}-\d{2}(?:-\d{2})?$/;
const KPI_SPARKLINE_MAX_POINTS = 30;

/**
 * KPI 카드의 숫자 표기를 결정한다. 1억 이상은 단위 문자열과 무관하게 축약해 카드 안에서 한 줄로 읽히게 하며,
 * 손실 없는 원값은 호출부가 `title` 속성으로 함께 노출한다.
 */
function formatKpiValue(value: unknown, unit?: string | null) {
  const numeric = Number(value);
  if (isNumericValue(value) && Math.abs(numeric) >= 100_000_000) return formatCompactNumber(numeric);
  return formatMetricValue(value, { includeUnit: false, unit });
}

function analysisAsOfLabel(asOf?: string | null) {
  if (!asOf) return "";
  const [year, month, day] = asOf.split("-");
  if (year?.length === 4 && month?.length === 2 && day?.length === 2) {
    return `${year}.${month}.${day}.`;
  }
  return asOf;
}

/** 승인된 차트·표 계약에 같은 KPI의 시계열이 있을 때만 미니 추이를 만든다. */
function kpiSparkline(run: AnalysisRun, resultField: string) {
  const table = run.table;
  const chart = run.chart;
  if (!table?.rows?.length || !chart?.xField || !chart.yFields.includes(resultField)) return null;
  const values = table.rows
    .filter((row) => KPI_SPARKLINE_PERIOD.test(String(row[chart.xField] ?? "")) && isNumericValue(row[resultField]))
    .sort((left, right) => String(left[chart.xField]).localeCompare(String(right[chart.xField])))
    .slice(-KPI_SPARKLINE_MAX_POINTS)
    .map((row) => Number(row[resultField]));
  if (values.length < 3) return null;

  const width = 240;
  const height = 54;
  const padding = 3;
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = maximum - minimum;
  const points = values.map((value, index) => {
    const x = padding + (index * (width - padding * 2)) / (values.length - 1);
    const y = range === 0
      ? height / 2
      : padding + ((maximum - value) * (height - padding * 2)) / range;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  return {
    count: values.length,
    line: points,
    area: `${padding},${height - padding} ${points} ${width - padding},${height - padding}`,
    viewBox: `0 0 ${width} ${height}`,
  };
}

/** KPI 카드에는 축·레이블 없이 검증된 최근 시계열의 방향만 보조적으로 표시한다. */
function AnalysisKpiSparkline({ label, sparkline }: {
  label: string;
  sparkline: NonNullable<ReturnType<typeof kpiSparkline>>;
}) {
  return (
    <div className="analysis-kpi-sparkline" role="img" aria-label={`${label} 최근 ${sparkline.count}개 시점 추이`}>
      <svg viewBox={sparkline.viewBox} preserveAspectRatio="none" aria-hidden="true">
        <polygon points={sparkline.area} />
        <polyline points={sparkline.line} />
      </svg>
    </div>
  );
}

/** 결과 섹션의 수량과 데이터 기준일을 제목 옆 보조정보로 묶는다. */
function AnalysisSectionMeta({ run, children, showAsOf = true }: {
  run: AnalysisRun; children?: React.ReactNode; showAsOf?: boolean;
}) {
  const asOf = showAsOf ? run.meta?.asOf : "";
  if (!children && !asOf) return null;
  return (
    <div className="analysis-section-meta">
      {children}
      {asOf && <time dateTime={asOf}>데이터 기준 {analysisAsOfLabel(asOf)}</time>}
    </div>
  );
}

/** 대화형 AI 내러티브 요약을 렌더링한다. 데이터 출처 고지는 보고서 artifact 화면이 담당한다. */
export function AnalysisConversationalSummary({ run, valueScale }: { run: AnalysisRun; valueScale: AnalysisValueScale }) {
  return (
    <div className="agent-conversational-bubble" aria-label="AI 분석 요약">
      <header className="analysis-summary-heading">
        <div>
          <h3>{analysisTitle(run)}</h3>
        </div>
        <AnalysisSectionMeta run={run} />
      </header>
      <div className="analysis-summary-answer">
        <p className="agent-narrative-text">{userFacingAnalysisSummary(run, valueScale)}</p>
      </div>
    </div>
  );
}

/** 요청한 표현에 필요한 승인 데이터가 없을 때 임의 생성 없이 다음 행동을 안내한다. */
export function AnalysisUnavailableView({ view }: { view: "KPI" | "CHART" | "TABLE" }) {
  const label = { KPI: "KPI", CHART: "그래프", TABLE: "상세 표" }[view];
  const Icon = { KPI: Target, CHART: BarChart3, TABLE: TableProperties }[view];
  return (
    <section className="analysis-view-unavailable" role="status" data-view={view.toLowerCase()}>
      <Icon size={17} aria-hidden="true" />
      <div>
        <b>현재 분석 결과로는 {label} 보기를 만들 수 없습니다.</b>
        <p>현재 결과에 필요한 데이터가 없어 값을 임의로 만들지 않았습니다.</p>
      </div>
    </section>
  );
}

/**
 * Artifact가 명시한 승인 KPI만 카드로 렌더링하며 상세 행을 새 KPI처럼 파생하지 않는다.
 * 금액은 `valueScale`이 결과 한 건 단위로 확정한 통화 배율만 사용하고, 손실 없는 원값은 `title`로 노출한다.
 */
export function AnalysisKpiSection({ run, valueScale, showAsOf = true }: {
  run: AnalysisRun; valueScale: AnalysisValueScale; showAsOf?: boolean;
}) {
  const headingId = React.useId().replaceAll(":", "");
  if (!run.metrics || run.metrics.length === 0) return null;
  const isSingleMetric = run.metrics.length === 1;

  return (
    <section className={`analysis-kpi-section${isSingleMetric ? " is-single-metric" : ""}`} aria-labelledby={headingId}>
      {/* 차트·표 섹션과 같은 (eyebrow + 제목 + 우측 메타) 헤더 구조를 공유해 시선 이동을 단순화한다. */}
      <header>
        <div><small>수치 근거</small><h3 id={headingId}>핵심 지표</h3></div>
        <AnalysisSectionMeta run={run} showAsOf={showAsOf}><span>{run.metrics.length}개 지표</span></AnalysisSectionMeta>
      </header>
      <div className={`analysis-metrics${isSingleMetric ? " is-single-metric" : ""}`}>
        {run.metrics.map((metric) => {
          const sparkline = isSingleMetric ? kpiSparkline(run, metric.resultField) : null;
          return (
          <article key={`total-${metric.metricId}`} className={`analysis-metric-card--total${isSingleMetric ? " is-hero-metric" : ""}${sparkline ? " has-sparkline" : ""}`}>
            {/* 배지와 지표명을 세로로 쌓아, 지표명이 길어도 배지 위로 겹치지 않게 한다. */}
            <div className="metric-header-strip">
              <small>{metricDisplayLabel(metric)}</small>
            </div>
            <strong title={valueScale.exact(metric.value, metric.unit)}>
              {valueScale.isCurrency(metric.unit) ? valueScale.format(metric.value, metric.unit, metric.resultField) : formatKpiValue(metric.value, metric.unit)}
              {metric.unit && metric.value !== null && metric.value !== undefined && metric.value !== "" && <em>{valueScale.unitLabel(metric.unit, metric.resultField)}</em>}
            </strong>
            {sparkline && <AnalysisKpiSparkline label={metricDisplayLabel(metric)} sparkline={sparkline} />}
          </article>
          );
        })}
      </div>
    </section>
  );
}

/** 차트 시각화 및 실패 시의 fallback 섹션을 렌더링한다. */
export function AnalysisVisualSection({
  run, chart, table, canRenderChart, supportedChartType, hasTableColumns, chartTitle, chartDisplayOptions,
  chartDisplayType, showDisplayControls = false, setChartDisplayOverride, chartLines, chartHeight, chartDescription, columnLabel,
  valueScale, chartCurrencyField, showAsOf = true,
}: {
  run: AnalysisRun; chart: NonNullable<AnalysisRun["chart"]> | null; table: NonNullable<AnalysisRun["table"]> | null;
  canRenderChart: boolean; supportedChartType: boolean; hasTableColumns: boolean; chartTitle: string;
  chartDisplayOptions: Array<{ type: string; label: string }>; chartDisplayType: string;
  showDisplayControls?: boolean;
  setChartDisplayOverride: React.Dispatch<React.SetStateAction<string>>;
  chartLines: Array<{ key: string; label: string; color: string; unit?: string }>;
  chartHeight: number; chartDescription: string; columnLabel: (col: string, r: AnalysisRun) => string;
  valueScale: AnalysisValueScale; chartCurrencyField: string | null; showAsOf?: boolean;
}) {
  if (chart && table && canRenderChart) {
    return (
      <section className="analysis-result-section analysis-visual-section">
        <header>
          <div><small>차트 시각화</small><h3>{chartTitle}</h3></div>
          <div className="analysis-chart-actions">
            <AnalysisSectionMeta run={run} showAsOf={showAsOf}><span>{(table?.rows?.length ?? 0).toLocaleString("ko-KR")}개 항목</span></AnalysisSectionMeta>
            {showDisplayControls && chartDisplayOptions.length > 0 && (
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
            interactiveLegend
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
  if (chart && !canRenderChart) {
    const hasTableRows = Boolean(table?.rows?.length);
    const missingData = !hasTableColumns || !hasTableRows;
    return (
      <section className="analysis-chart-fallback" role="status">
        <AlertTriangle size={16} aria-hidden="true" />
        <div>
          <b>{!supportedChartType
            ? "현재 지원하지 않는 그래프 형식입니다."
            : missingData
              ? "그래프로 표시할 데이터가 없습니다."
              : "그래프 구성 정보를 확인할 수 없습니다."}</b>
          <p>
            {!supportedChartType
              ? "데이터를 임의로 바꾸지 않고 아래 표로 표시합니다."
              : missingData
                ? "현재 결과에 상세 데이터가 없어 값을 임의로 만들지 않았습니다."
                : "그래프 구성과 상세 데이터가 일치하지 않아 임의로 해석하지 않았습니다. 제공된 데이터는 아래 표에서 확인할 수 있습니다."}
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
  valueScale, showAsOf = true,
}: {
  run: AnalysisRun; table: NonNullable<AnalysisRun["table"]> | null; resultTitle: string;
  tableSort: { column: string; direction: "" | "asc" | "desc" };
  setTableSort: React.Dispatch<React.SetStateAction<{ column: string; direction: "" | "asc" | "desc" }>>;
  nextTableSort: (curr: { column: string; direction: "" | "asc" | "desc" }, col: string) => { column: string; direction: "" | "asc" | "desc" };
  numericColumns: Set<string>; visibleRows: Array<Record<string, unknown>>;
  columnLabel: (col: string, r: AnalysisRun) => string; columnUnit: (col: string, r: AnalysisRun) => string | null;
  valueScale: AnalysisValueScale; showAsOf?: boolean;
}) {
  if (!table?.columns?.length) return null;
  const isCompactResult = table.columns.length <= 3 && visibleRows.length <= 8;
  const isSingleValueResult = table.columns.length === 1 && visibleRows.length === 1;
  const isWideResult = table.columns.length > 3;
  const showRowNumbers = visibleRows.length > 1;
  const canSort = visibleRows.length > 1;
  const sortedColumnLabel = tableSort.column ? columnLabel(tableSort.column, run) : "";
  const sortDescription = canSort
    ? tableSort.direction
      ? `${sortedColumnLabel} ${tableSort.direction === "asc" ? "오름차순" : "내림차순"}`
      : "열 제목을 눌러 정렬"
    : "단일 결과";
  return (
    <section
      className={`analysis-result-section analysis-data-section${isCompactResult ? " is-compact-result" : ""}${isSingleValueResult ? " is-single-value-result" : ""}${isWideResult ? " is-wide-result" : ""}`}
      data-table-density={isSingleValueResult ? "single" : isWideResult ? "wide" : "regular"}
      style={isWideResult ? { "--analysis-table-min-width": `${Math.max(760, table.columns.length * 156)}px` } as React.CSSProperties : undefined}
    >
      <header>
        <div><small>데이터</small><h3>상세 데이터</h3></div>
        <div className="analysis-data-meta">
          <span>{(table?.rows?.length ?? 0).toLocaleString("ko-KR")}행 · {(table?.columns?.length ?? 0).toLocaleString("ko-KR")}열</span>
          <small>{sortDescription}</small>
          {showAsOf && run.meta?.asOf && <time dateTime={run.meta.asOf}>데이터 기준 {analysisAsOfLabel(run.meta.asOf)}</time>}
        </div>
      </header>
      <div className="analysis-table" tabIndex={0} aria-label="상세 데이터 표">
        <table>
          <caption className="sr-only">{resultTitle} 상세 데이터</caption>
          <thead>
            <tr>
              {showRowNumbers && <th scope="col" className="row-number">#</th>}
              {table.columns.map((column) => {
                const unit = valueScale.unitLabel(columnUnit(column, run), column);
                const label = columnLabel(column, run);
                const sortDirection = tableSort.column === column ? tableSort.direction : "";
                const SortIcon = sortDirection === "asc" ? ArrowUp : sortDirection === "desc" ? ArrowDown : ArrowUpDown;
                return (
                  <th scope="col" aria-sort={canSort ? (tableSort.column === column ? (tableSort.direction === "asc" ? "ascending" : "descending") : "none") : undefined} className={numericColumns.has(column) ? "is-numeric" : ""} key={column}>
                    {canSort ? (
                      <button type="button" className={`analysis-table-sort ${sortDirection ? "is-sorted" : ""}`} aria-label={`${metricUnitLabel(label, unit)} 열 정렬`} onClick={() => setTableSort((current) => nextTableSort(current, column))}>
                        <span>{label}{unit && <small className="analysis-column-unit">{unit}</small>}</span>
                        <SortIcon size={12} aria-hidden="true" />
                      </button>
                    ) : (
                      <span className="analysis-table-label">{label}{unit && <small className="analysis-column-unit">{unit}</small>}</span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <tr key={`${run.requestId}-${index}`}>
                {showRowNumbers && <th scope="row" className="row-number">{index + 1}</th>}
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

/** 분석 결과의 저장·보고서·근거 액션만 렌더링한다. 보기 변경은 후속 대화 요청으로 수행한다. */
export function AnalysisUnifiedToolbar({
  onSave, onCreateReportDraft, onOpenEvidence, onPreview, saveDisabled = false,
}: {
  onSave?: () => void; onCreateReportDraft?: () => void; onOpenEvidence?: () => void; onPreview?: () => void;
  saveDisabled?: boolean;
}) {
  const hasActions = Boolean(onSave || onCreateReportDraft || onOpenEvidence || onPreview);
  if (!hasActions) return null;
  return (
    <div className="analysis-unified-toolbar" aria-label="분석 결과 액션">
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
          <button type="button" className="unified-action-btn" onClick={onOpenEvidence} title="승인된 데이터와 계산 근거 확인">
            <Search size={13} /><span>분석 근거</span>
          </button>
        )}
      </div>
    </div>
  );
}
