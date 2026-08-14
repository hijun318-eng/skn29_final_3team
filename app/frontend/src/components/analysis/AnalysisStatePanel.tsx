import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowUpDown, Ban, CheckCircle2, CircleX, Clock3, FileWarning, LoaderCircle, RotateCcw, SearchX, StopCircle } from "lucide-react";
import { EnterpriseChart } from "../charts/EnterpriseChart";
import { resolveViewState, type AnalysisRun, type AnalysisViewState } from "../../contracts/analysis";
import {
  analysisTitle, dataProvenanceLabel, formatCompactNumber, formatMetricValue, isNumericValue, metricUnitLabel, seriesColor,
} from "../../utils/presentation";

const VIEW_COPY: Record<AnalysisViewState, { title: string; description: string; icon: typeof CheckCircle2 }> = {
  LOADING: { title: "분석 중", description: "분석 요청을 처리하고 있습니다.", icon: LoaderCircle },
  EMPTY: { title: "결과 없음", description: "조건이나 기간을 바꾸어 다시 요청해 주세요.", icon: SearchX },
  READY: { title: "분석 결과", description: "요청한 조건의 핵심 결과를 표시합니다.", icon: CheckCircle2 },
  DELAYED: { title: "응답 지연", description: "데이터 소스의 응답을 기다리고 있습니다.", icon: Clock3 },
  PARTIAL: { title: "일부 데이터 결과", description: "확인 가능한 결과와 응답하지 않은 소스를 구분해 표시합니다.", icon: AlertTriangle },
  ERROR: { title: "분석 실패", description: "요청을 다시 확인하거나 잠시 후 재시도해 주세요.", icon: CircleX },
  FORBIDDEN: { title: "접근 불가", description: "현재 역할에는 이 분석 범위가 허용되지 않습니다.", icon: Ban },
  INSUFFICIENT_EVIDENCE: { title: "근거 부족", description: "검증 근거를 확보하지 못해 결과를 표시하지 않습니다.", icon: FileWarning },
  CANCELLED: { title: "분석 취소", description: "새 요청으로 다시 시작할 수 있습니다.", icon: CircleX },
};

const SOURCE_STATUS: Record<string, string> = {
  success: "정상", failed: "실패", partial: "일부 응답", delayed: "지연",
  SUCCEEDED: "정상", FAILED: "실패", PARTIAL: "일부 응답",
};

const COLUMN_LABELS: Record<string, string> = {
  month: "월",
  business_date: "일자",
  date: "일자",
  property_id: "호텔",
  membership_grade_code: "회원 등급",
  room_type_code: "객실 유형",
  actual_checkout_at: "체크아웃 시점",
  ordered_at: "주문 시점",
};

const FILTER_LABELS: Record<string, string> = {
  void_flag: "취소 건",
  is_forecast: "예측값",
  property_id: "호텔",
  stay_status: "투숙 상태",
  house_use_flag: "사내 사용",
  complimentary_flag: "무료 제공",
  membership_grade_code: "고객 등급",
  grade_code: "고객 등급",
};

const REQUIRED_ACTION_COPY: Record<string, string> = {
  RETRY: "잠시 후 같은 질문을 다시 분석해 주세요.",
  AUTHENTICATE: "로그인한 뒤 다시 시도해 주세요.",
  REQUEST_ACCESS: "현재 계정에 필요한 데이터 권한을 요청해 주세요.",
  PROVIDE_CONTEXT: "분석할 지표나 기간을 질문에 추가해 주세요.",
  MODIFY_REQUEST: "질문의 범위나 조건을 수정해 다시 전송해 주세요.",
  CONTACT_SUPPORT: "추적 ID와 함께 서비스 관리자에게 문의해 주세요.",
};

function errorStateTitle(code?: string) {
  if (["CONTEXT_SOURCE_FAILED", "TRINO_CONNECTION_FAILED", "QUERY_SOURCE_FAILED", "DEPENDENCY_UNAVAILABLE"].includes(code ?? "")) return "데이터 원천 응답 실패";
  if (["MODEL_CONTRACT_INVALID", "MODEL_OUTPUT_UNGROUNDED"].includes(code ?? "")) return "모델 설명 검증 실패";
  if (["MODEL_TIMEOUT", "MODEL_ENDPOINT_UNAVAILABLE", "CIRCUIT_OPEN"].includes(code ?? "")) return "모델 응답 실패";
  return null;
}

function progressMessage(elapsed: number) {
  if (elapsed >= 60) return "평소보다 오래 걸리고 있지만 요청은 중단되지 않았습니다. 필요하면 분석을 취소할 수 있습니다.";
  if (elapsed >= 30) return "데이터 조회와 결과 검증을 계속 진행하고 있습니다. 완료되는 즉시 결과를 표시합니다.";
  if (elapsed >= 10) return "분석이 계속 진행 중입니다. 현재 단계와 경과 시간을 자동으로 갱신합니다.";
  return "질문은 그대로 보존됩니다. 현재 상태와 경과 시간을 자동으로 갱신합니다.";
}

function AnalysisProgress({ elapsed }: { elapsed: number }) {
  return <section className="analysis-trace analysis-trace--indeterminate" aria-label="분석 진행 상태" aria-live="polite">
    <header><div><small>현재 상태</small><h3>승인된 범위에서 분석하고 있습니다</h3></div><span>{elapsed}초 경과</span></header>
    <p>{progressMessage(elapsed)}</p>
    <p className="analysis-progress-boundary">서버가 확정한 결과와 근거가 준비되면 이 화면에 표시합니다. 내부 처리 순서는 추측해 표시하지 않습니다.</p>
  </section>;
}

function columnLabel(column: string, run: AnalysisRun) {
  return run.metrics.find((item) => item.resultField === column)?.label
    ?? run.evidence?.metrics.find((item) => item.resultField === column)?.label
    ?? COLUMN_LABELS[column]
    ?? "구분";
}

function columnUnit(column: string, run: AnalysisRun) {
  return run.metrics.find((item) => item.resultField === column)?.unit
    ?? run.evidence?.metrics.find((item) => item.resultField === column)?.unit
    ?? null;
}

function formatPeriod(run: AnalysisRun) {
  const period = run.evidence?.period;
  if (!period) return "기간 정보 없음";
  return `${period.start.replaceAll("-", ".")}부터 ${period.endExclusive.replaceAll("-", ".")} 전까지`;
}

function formatFilterValue(field: string, value: unknown) {
  const key = field.split(".").at(-1) ?? field;
  if (["void_flag", "is_forecast", "house_use_flag", "complimentary_flag"].includes(key)) {
    return ["false", "0", "no", "아니요"].includes(String(value).toLocaleLowerCase("ko-KR")) ? "제외" : "포함";
  }
  if (key === "stay_status" && value === "COMPLETED") return "투숙 완료";
  if (value === true) return "예";
  if (value === false) return "아니요";
  return String(value ?? "없음");
}

function filterLabel(field: string) {
  const key = field.split(".").at(-1) ?? field;
  return FILTER_LABELS[key] ?? key.replaceAll("_", " ");
}

function filterEntries(filters: Record<string, unknown>) {
  const seen = new Set<string>();
  const excluded = new Set<string>();
  const entries = Object.entries(filters).flatMap(([key, value]) => {
    const entry = { label: filterLabel(key), value: formatFilterValue(key, value) };
    const normalizedKey = key.split(".").at(-1) ?? key;
    if (["void_flag", "is_forecast", "house_use_flag", "complimentary_flag"].includes(normalizedKey) && entry.value === "제외") {
      excluded.add(entry.label);
      return [];
    }
    const signature = `${entry.label}:${entry.value}`;
    if (seen.has(signature)) return [];
    seen.add(signature);
    return [entry];
  });
  if (excluded.size) entries.push({ label: "기본 제외", value: [...excluded].join("·") });
  return entries;
}

function tidyAnalysisTitle(value: string) {
  const words = value.trim().split(/\s+/);
  return words.filter((word, index) => index === 0 || word !== words[index - 1]).join(" ");
}

function formatKpiValue(value: unknown, unit?: string | null) {
  const numeric = Number(value);
  if (unit === "원" && isNumericValue(value) && Math.abs(numeric) >= 100_000_000) {
    return formatCompactNumber(numeric);
  }
  return formatMetricValue(value, { includeUnit: false });
}

type TableSort = { column: string; direction: "" | "asc" | "desc" };

function nextTableSort(current: TableSort, column: string): TableSort {
  if (current.column !== column) return { column, direction: "asc" };
  if (current.direction === "asc") return { column, direction: "desc" };
  return { column: "", direction: "" };
}

function compareTableValues(left: unknown, right: unknown) {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  return String(left ?? "").localeCompare(String(right ?? ""), "ko", { numeric: true });
}

export function AnalysisStatePanel({
  run,
  onSuggestion,
  onRetry,
  onCancel,
  cancelRequested = false,
  suggestionsDisabled = false,
}: {
  run: AnalysisRun;
  onSuggestion?: (suggestion: string) => void;
  onRetry?: () => void;
  onCancel?: () => void;
  cancelRequested?: boolean;
  suggestionsDisabled?: boolean;
}) {
  const viewState = resolveViewState(run);
  const copy = VIEW_COPY[viewState];
  const Icon = copy.icon;
  const showResult = viewState === "READY" || viewState === "PARTIAL";
  const chart = showResult ? run.chart : null;
  const table = showResult ? run.table : null;
  const suggestions = run.error?.suggestions ?? [];
  const requiredAction = run.error?.required_action ?? "NONE";
  const nextAction = REQUIRED_ACTION_COPY[requiredAction];
  const failureTitle = errorStateTitle(run.error?.code);
  const [elapsed, setElapsed] = useState(0);
  const terminalStateRef = useRef<HTMLElement | null>(null);
  const [tableSort, setTableSort] = useState<TableSort>({ column: "", direction: "" });
  const [chartDisplayOverride, setChartDisplayOverride] = useState("");
  const chartType = chart?.chartType?.toLocaleLowerCase("en-US") ?? "";
  const supportedChartType = chartType === "bar" || chartType === "line";
  const hasTableColumns = Boolean(table?.columns.length);
  const chartColumns = new Set(table?.columns ?? []);
  const chartFieldsMatchTable = Boolean(
    chart
    && chart.yFields.length > 0
    && chartColumns.has(chart.xField)
    && chart.yFields.every((field) => chartColumns.has(field)),
  );
  const canRenderChart = supportedChartType && chartFieldsMatchTable;
  const chartLines = chart?.yFields.map((field, index) => ({
    key: field,
    label: columnLabel(field, run),
    color: seriesColor(index),
    unit: columnUnit(field, run) ?? undefined,
  })) ?? [];
  const filters = filterEntries(run.evidence?.filters ?? {});
  const chartTitle = chart ? `${columnLabel(chart.xField, run)}별 ${chartLines.map((line) => line.label).join("·")}` : "";
  const resultTitle = tidyAnalysisTitle(analysisTitle(run));
  const provenanceLabel = dataProvenanceLabel(run.sources);
  const hasLongCategories = Boolean(chart && table?.rows.some((row) => [...String(row[chart.xField] ?? "")].length > 10));
  const defaultChartDisplayType = chartType === "bar" && hasLongCategories ? "horizontal-bar" : chartType;
  const chartDisplayOptions = chartType === "bar"
    ? [{ type: "bar", label: "세로" }, { type: "horizontal-bar", label: "가로" }]
    : chartType === "line"
      ? [{ type: "line", label: "선" }, { type: "area", label: "영역" }]
      : [];
  const chartDisplayType = chartDisplayOptions.some((option) => option.type === chartDisplayOverride)
    ? chartDisplayOverride
    : defaultChartDisplayType;
  const chartHeight = chartDisplayType === "horizontal-bar"
    ? Math.max(280, Math.min(420, (table?.rows.length ?? 0) * 46 + 54))
    : 280;
  const chartDescription = chart
    ? `${columnLabel(chart.xField, run)} 기준으로 ${chartLines.map((line) => line.label).join(", ")}을 비교합니다. 같은 값은 아래 상세 데이터 표에서도 확인할 수 있습니다.`
    : "";
  const numericColumns = new Set(table?.columns.filter((column) => table.rows.some((row) => (
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

  if (viewState === "LOADING" || viewState === "DELAYED") {
    return <section className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite" aria-busy="true"><header><LoaderCircle className="spin" size={18} aria-hidden="true" /><div><b>{copy.title}</b></div></header><p>{copy.description}</p><button type="button" className="analysis-cancel" disabled={cancelRequested} onClick={onCancel}><StopCircle size={15} aria-hidden="true" />{cancelRequested ? "취소 요청 중" : "분석 취소"}</button><AnalysisProgress elapsed={elapsed} /></section>;
  }

  return <section ref={terminalStateRef} tabIndex={-1} className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite">
    {!showResult && <header><Icon size={18} aria-hidden="true" /><div><b>{suggestions.length ? run.error?.clarification_type === "period" ? "어떤 기간으로 분석할까요?" : "어떤 지표로 분석할까요?" : run.error?.code === "CONTEXT_INCOMPLETE" ? "추가 정보 필요" : failureTitle || copy.title}</b></div></header>}
    {!showResult && <p>{run.error?.message ?? run.summary ?? copy.description}</p>}
    {suggestions.length > 0 && <div className="analysis-suggestions" aria-label={run.error?.clarification_type === "period" ? "분석 기간 선택" : "분석 지표 선택"}>{suggestions.map((suggestion) => <button type="button" key={suggestion} disabled={suggestionsDisabled} onClick={() => onSuggestion?.(suggestion)}>{suggestion}</button>)}</div>}
    {!showResult && requiredAction === "RETRY" && suggestions.length === 0 && <button type="button" className="analysis-retry" onClick={onRetry}><RotateCcw size={14} />같은 질문 다시 분석</button>}
    {!showResult && run.error && suggestions.length === 0 && <>{nextAction && <p className="analysis-next-action"><b>다음 행동</b> {nextAction}</p>}<details className="analysis-error" data-error-code={run.error.code} data-retryable={String(run.error.retryable)}><summary>기술 정보</summary><dl><div><dt>오류 코드</dt><dd>{run.error.code}</dd></div><div><dt>다시 시도</dt><dd>{run.error.retryable ? "가능" : "불가"}</dd></div>{run.error.missing_requirements?.length ? <div><dt>누락 항목</dt><dd>{run.error.missing_requirements.join(", ")}</dd></div> : null}<div><dt>추적 ID</dt><dd>{run.error.trace_id || run.traceId || "발급 전"}</dd></div></dl></details></>}
    {showResult && <div className="analysis-dashboard">
      <header className="analysis-dashboard-header"><div><div className="analysis-result-badges"><span className={`analysis-result-badge ${viewState === "PARTIAL" ? "is-partial" : ""}`}>{viewState === "PARTIAL" ? "일부 데이터" : "분석 결과"}</span>{provenanceLabel && <span className="analysis-result-badge is-synthetic">{provenanceLabel}</span>}</div><small>분석 결과</small><h2>{resultTitle}</h2></div><div className="analysis-dashboard-meta"><span>데이터 출처 {run.sources.length}개</span>{run.meta.asOf && <span>기준일 {run.meta.asOf}</span>}</div></header>
      {provenanceLabel && <p className="data-provenance-note analysis-data-provenance" role="note"><AlertTriangle size={15} aria-hidden="true" /><span><b>{provenanceLabel}</b> 실제 호텔 운영 성과가 아닌 교육·시연용 결과입니다.</span></p>}
      {viewState === "PARTIAL" && run.error && <div className="analysis-partial-notice analysis-partial-notice--summary" role="status"><AlertTriangle size={15} aria-hidden="true" /><span>{run.error.message}</span>{requiredAction === "RETRY" && onRetry && <button type="button" onClick={onRetry}><RotateCcw size={13} aria-hidden="true" />다시 분석</button>}</div>}

      {run.metrics.length > 0 && <section className="analysis-kpi-section" aria-labelledby="analysis-kpi-title"><header><div><small>핵심 결과</small><h3 id="analysis-kpi-title">주요 지표</h3></div><span>{run.metrics.length}개 지표</span></header><div className="analysis-metrics">{run.metrics.map((metric) => <article key={metric.metricId}><small>{metric.label}</small><strong title={formatMetricValue(metric.value, { unit: metric.unit })}>{formatKpiValue(metric.value, metric.unit)}{metric.unit && metric.value !== null && metric.value !== undefined && metric.value !== "" && <em>{metric.unit}</em>}</strong>{metric.definition && <p>{metric.definition}</p>}</article>)}</div></section>}

      <div className="analysis-overview-grid">
        <section className="analysis-summary-card"><header><small>핵심 해석</small><h3>분석 요약</h3></header><p>{run.summary || "표와 차트에서 세부 결과를 확인할 수 있습니다."}</p></section>
        <section className="analysis-context-card" aria-label="분석 조건"><header><small>조회 조건</small><h3>분석 기준</h3></header><dl><div><dt>조회 기간</dt><dd>{formatPeriod(run)}</dd></div><div><dt>적용 필터</dt><dd>{filters.length ? <ul className="analysis-filter-list">{filters.map((entry) => <li key={`${entry.label}-${entry.value}`}><span>{entry.label}</span><b>{entry.value}</b></li>)}</ul> : "추가 필터 없음"}</dd></div><div><dt>데이터 행</dt><dd>{run.evidence?.sampling.returnedRows.toLocaleString("ko-KR") ?? 0}{run.evidence?.sampling.totalRows !== null && run.evidence?.sampling.totalRows !== undefined ? ` / 전체 ${run.evidence.sampling.totalRows.toLocaleString("ko-KR")}` : ""}</dd></div></dl></section>
      </div>

      {viewState === "PARTIAL" && <section className="analysis-partial-notice analysis-partial-notice--sources"><b>일부 데이터 소스의 응답을 확인해 주세요.</b><ul>{run.sources.map((source) => <li key={source.urn}><span>{source.name}</span><em>{SOURCE_STATUS[source.status] || "확인 필요"}</em></li>)}</ul></section>}

      {chart && table?.rows.length && canRenderChart ? <section className="analysis-result-section analysis-visual-section"><header><div><small>차트</small><h3>{chartTitle}</h3></div><div className="analysis-chart-actions"><span>{table.rows.length.toLocaleString("ko-KR")}개 항목</span>{chartDisplayOptions.length > 0 && <div role="group" aria-label="차트 표현 방식">{chartDisplayOptions.map((option) => <button type="button" key={option.type} aria-pressed={chartDisplayType === option.type} onClick={() => setChartDisplayOverride(option.type)}>{option.label}</button>)}</div>}</div></header><figure className="analysis-chart"><EnterpriseChart data={table.rows} xKey={chart.xField} xLabel={columnLabel(chart.xField, run)} series={chartLines} type={chartDisplayType} height={chartHeight} valueFormatter={(value, item) => formatMetricValue(value, { unit: item?.unit })} axisFormatter={formatCompactNumber} ariaLabel={`${chartTitle} ${chartDisplayType === "horizontal-bar" ? "가로 막대" : chartDisplayType === "bar" ? "세로 막대" : chartDisplayType === "area" ? "영역" : "선"} 차트`} description={chartDescription} /><figcaption>{chartDescription}</figcaption></figure></section> : null}
      {chart && (!hasTableColumns || (Boolean(table?.rows.length) && !canRenderChart)) ? <section className="analysis-chart-fallback" role="status"><AlertTriangle size={16} aria-hidden="true" /><div><b>{supportedChartType ? "차트 메타데이터를 확인할 수 없습니다." : "지원하지 않는 차트 형식입니다."}</b><p>{supportedChartType ? hasTableColumns ? "차트 필드와 상세 데이터 열이 일치하지 않아 임의로 해석하지 않았습니다. 제공된 데이터는 아래 표에서 확인할 수 있습니다." : "차트와 연결된 상세 데이터가 없어 임의로 시각화하지 않았습니다." : <>데이터를 임의의 차트로 바꾸지 않고 아래 표로 표시합니다. 차트 형식 <code>{chart.chartType || "없음"}</code></>}</p></div></section> : null}

      {table?.columns.length ? <section className="analysis-result-section analysis-data-section"><header><div><small>데이터</small><h3>상세 데이터</h3></div><span>{table.rows.length.toLocaleString("ko-KR")}행 · {table.columns.length.toLocaleString("ko-KR")}열</span></header><div className="analysis-table" tabIndex={0} aria-label="상세 데이터 표. 표가 넓으면 좌우로 스크롤할 수 있습니다."><table><caption className="sr-only">{resultTitle} 상세 데이터</caption><thead><tr><th scope="col" className="row-number">#</th>{table.columns.map((column) => { const unit = columnUnit(column, run); const label = columnLabel(column, run); return <th scope="col" aria-sort={tableSort.column === column ? (tableSort.direction === "asc" ? "ascending" : "descending") : "none"} className={numericColumns.has(column) ? "is-numeric" : ""} key={column}><button type="button" className="analysis-table-sort" aria-label={`${metricUnitLabel(label, unit)} 열 정렬`} onClick={() => setTableSort((current) => nextTableSort(current, column))}><span>{label}{unit && <small className="analysis-column-unit">{unit}</small>}</span><ArrowUpDown size={12} aria-hidden="true" /></button></th>; })}</tr></thead><tbody>{visibleRows.map((row, index) => <tr key={`${run.requestId}-${index}`}><th scope="row" className="row-number">{index + 1}</th>{table.columns.map((column) => <td className={numericColumns.has(column) ? "is-numeric" : ""} key={column}>{formatMetricValue(row[column], { includeUnit: false })}</td>)}</tr>)}</tbody></table></div></section> : null}
    </div>}
  </section>;
}
