/** 분석 대시보드의 대화형 요약, KPI, 차트, 데이터 테이블, 통합 뷰·액션 툴바 서브 컴포넌트들을 렌더링하는 모듈이다. */
import React from "react";
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, BarChart3, Eye, FilePlus2, Save, Search, TableProperties, Target } from "lucide-react";
import { EnterpriseChart } from "../charts/EnterpriseChart";
import { type AnalysisRun } from "../../contracts/analysis";
import { type AnalysisValueScale, userFacingAnalysisSummary } from "./analysisValueScale";
import { analysisTitle, formatCompactNumber, formatMetricValue, isNumericValue, localizeMetricDefinition, metricDisplayLabel, metricUnitLabel } from "../../utils/presentation";

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
export function AnalysisConversationalSummary({ run, valueScale }: { run: AnalysisRun; valueScale: AnalysisValueScale }) {
  return (
    <div className="agent-conversational-bubble" aria-label="AI 분석 요약">
      <header className="analysis-summary-heading">
        <div>
          <small>분석 결과</small>
          <h3>{analysisTitle(run)}</h3>
        </div>
        <span className="analysis-summary-verified">근거 검증 완료</span>
      </header>
      <div className="analysis-summary-answer">
        <small>핵심 답변</small>
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
        <p>기존 Artifact에 필요한 데이터가 없어 값을 임의로 생성하지 않았습니다.</p>
      </div>
    </section>
  );
}

/**
 * Artifact가 명시한 승인 KPI만 카드로 렌더링하며 상세 행을 새 KPI처럼 파생하지 않는다.
 * 금액은 `valueScale`이 결과 한 건 단위로 확정한 통화 배율만 사용하고, 손실 없는 원값은 `title`로 노출한다.
 */
export function AnalysisKpiSection({ run, valueScale }: { run: AnalysisRun; valueScale: AnalysisValueScale }) {
  if (!run.metrics || run.metrics.length === 0) return null;

  return (
    <section className="analysis-kpi-section" aria-labelledby="analysis-kpi-title">
      {/* 차트·표 섹션과 같은 (eyebrow + 제목 + 우측 메타) 헤더 구조를 공유해 시선 이동을 단순화한다. */}
      <header>
        <div><small>수치 근거</small><h3 id="analysis-kpi-title">핵심 지표</h3></div>
        <span>{run.metrics.length}개 지표</span>
      </header>
      <div className="analysis-metrics">
        {run.metrics.map((metric) => (
          <article key={`total-${metric.metricId}`} className="analysis-metric-card--total">
            {/* 배지와 지표명을 세로로 쌓아, 지표명이 길어도 배지 위로 겹치지 않게 한다. */}
            <div className="metric-header-strip">
              <small>{metricDisplayLabel(metric)}</small>
            </div>
            <strong title={valueScale.exact(metric.value, metric.unit)}>
              {valueScale.isCurrency(metric.unit) ? valueScale.format(metric.value, metric.unit, metric.resultField) : formatKpiValue(metric.value, metric.unit)}
              {metric.unit && metric.value !== null && metric.value !== undefined && metric.value !== "" && <em>{valueScale.unitLabel(metric.unit, metric.resultField)}</em>}
            </strong>
            {metric.definition && <p>{localizeMetricDefinition(metric.definition)}</p>}
          </article>
        ))}
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
  const isCompactResult = table.columns.length <= 3 && visibleRows.length <= 8;
  const isSingleValueResult = table.columns.length === 1 && visibleRows.length === 1;
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
      className={`analysis-result-section analysis-data-section${isCompactResult ? " is-compact-result" : ""}${isSingleValueResult ? " is-single-value-result" : ""}`}
      data-table-density={isSingleValueResult ? "single" : isCompactResult ? "compact" : "full"}
    >
      <header>
        <div><small>데이터</small><h3>상세 데이터</h3></div>
        <div className="analysis-data-meta">
          <span>{(table?.rows?.length ?? 0).toLocaleString("ko-KR")}행 · {(table?.columns?.length ?? 0).toLocaleString("ko-KR")}열</span>
          <small>{sortDescription}</small>
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
          <button type="button" className="unified-action-btn" onClick={onOpenEvidence} title="DataHub 거버넌스 및 AST SQL 검증 근거">
            <Search size={13} /><span>분석 근거</span>
          </button>
        )}
      </div>
    </div>
  );
}
