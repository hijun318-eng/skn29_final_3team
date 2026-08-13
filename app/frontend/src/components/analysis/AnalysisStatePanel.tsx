import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowUpDown, Ban, CheckCircle2, CircleX, Clock3, FileWarning, LoaderCircle, RotateCcw, SearchX, StopCircle } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { resolveViewState, type AnalysisRun, type AnalysisViewState } from "../../contracts/analysis";

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
};

const ERROR_ACTIONS: Record<string, string> = {
  AUTHENTICATION_REQUIRED: "로그인 상태를 다시 확인해 주세요.",
  ACCESS_DENIED: "현재 계정의 권한을 관리자에게 확인해 주세요.",
  DATA_ASSET_NOT_FOUND: "분석 대상이나 지표를 바꾸거나 데이터 권한을 관리자에게 요청해 주세요.",
  CONTEXT_SOURCE_FAILED: "잠시 후 다시 시도하고, 반복되면 데이터 관리자에게 문의해 주세요.",
  MODEL_CONTRACT_INVALID: "같은 질문으로 다시 시도하고, 반복되면 추적 ID와 함께 문의해 주세요.",
  MODEL_TIMEOUT: "잠시 후 같은 질문으로 다시 시도해 주세요.",
  SQL_POLICY_BLOCKED: "조회하려는 범위와 지표를 더 구체적으로 바꿔 주세요.",
  SQL_REPAIR_FAILED: "질문 범위를 줄이거나 지표를 하나만 지정해 다시 요청해 주세요.",
  TRINO_CONNECTION_FAILED: "데이터 조회 서비스가 복구된 뒤 다시 시도해 주세요.",
  QUERY_TIMEOUT: "기간이나 분석 범위를 줄여 다시 시도해 주세요.",
  QUERY_SOURCE_FAILED: "잠시 후 다시 시도하고, 반복되면 데이터 관리자에게 문의해 주세요.",
  RESULT_VALIDATION_FAILED: "기간과 지표를 확인한 뒤 질문을 더 구체적으로 작성해 주세요.",
  RESULT_EVIDENCE_MISSING: "근거 데이터가 준비된 기간이나 다른 지표로 요청해 주세요.",
  ARTIFACT_PERSIST_FAILED: "결과 저장소가 복구된 뒤 같은 질문으로 다시 시도해 주세요.",
  NETWORK_UNAVAILABLE: "네트워크 연결을 확인한 뒤 같은 질문으로 다시 시도해 주세요.",
  REQUEST_CANCELLED: "필요하면 같은 질문을 다시 전송해 주세요.",
};

const ANALYSIS_PHASES = [
  ["질문 해석", "질문의 지표와 기간을 확인합니다."],
  ["사용 가능한 데이터 확인", "권한이 있는 데이터와 업무 정의를 확인합니다."],
  ["분석 계획 생성", "승인된 조건으로 조회 계획을 만듭니다."],
  ["안전성 검증", "읽기 전용 정책과 조회 범위를 검증합니다."],
  ["데이터 조회", "승인된 데이터 소스에서 결과를 조회합니다."],
  ["결과 검증", "반환된 값과 근거의 일치 여부를 확인합니다."],
  ["설명과 Artifact 저장", "설명과 검증 근거를 함께 저장합니다."],
] as const;

function reachedPhases(run: AnalysisRun) {
  const trace = run.trace ?? [];
  const stages = new Set(trace.filter((step) => step.outcome === "PASSED").map((step) => step.stage));
  const modelCount = trace.filter((step) => step.stage === "MODEL" && step.outcome === "PASSED").length;
  return [stages.has("ROUTER"), stages.has("CONTEXT") || stages.has("G1"), modelCount >= 2, stages.has("G2"), stages.has("QUERY"), stages.has("G3"), stages.has("ARTIFACT")];
}

function failedPhase(run: AnalysisRun) {
  const trace = run.trace ?? [];
  const failedIndex = trace.findLastIndex((step) => step.outcome === "FAILED");
  if (failedIndex < 0) return -1;
  const step = trace[failedIndex];
  if (step.stage === "ROUTER" || step.stage === "CONTROLLER") return 0;
  if (step.stage === "CONTEXT" || step.stage === "G1") return 1;
  if (step.stage === "G2" || step.stage === "REPAIR") return 3;
  if (step.stage === "QUERY") return 4;
  if (step.stage === "G3") return 5;
  if (step.stage === "ARTIFACT") return 6;
  if (step.stage === "MODEL") {
    const modelIndex = trace.slice(0, failedIndex + 1).filter((item) => item.stage === "MODEL").length - 1;
    return [0, 2, 6][Math.min(modelIndex, 2)];
  }
  return -1;
}

function progressMessage(elapsed: number) {
  if (elapsed >= 60) return "평소보다 오래 걸리고 있지만 요청은 중단되지 않았습니다. 필요하면 분석을 취소할 수 있습니다.";
  if (elapsed >= 30) return "데이터 조회와 결과 검증을 계속 진행하고 있습니다. 완료되는 즉시 결과를 표시합니다.";
  if (elapsed >= 10) return "분석이 계속 진행 중입니다. 현재 단계와 경과 시간을 자동으로 갱신합니다.";
  return "질문은 그대로 보존됩니다. 현재 진행 단계를 자동으로 갱신합니다.";
}

function AnalysisProgress({ run, loading, elapsed }: { run: AnalysisRun; loading: boolean; elapsed: number }) {
  const reached = reachedPhases(run);
  const done = reached.filter(Boolean).length;
  const active = reached.findIndex((value) => !value);
  const failed = loading ? -1 : failedPhase(run);
  return <section className={`analysis-trace ${loading ? "" : "analysis-trace--complete"}`} aria-label="분석 진행 단계">
    <header><div><small>검증 흐름</small><h3>{loading ? "안전하게 분석하고 있습니다" : "분석 처리 단계"}</h3></div><span>{loading ? `${elapsed}초 경과` : `${done}/${ANALYSIS_PHASES.length} 완료 · ${elapsed}초`}</span></header>
    {loading && <p>{progressMessage(elapsed)}</p>}
    <ol>{ANALYSIS_PHASES.map(([title, description], index) => {
      const state = reached[index] ? "done" : failed === index ? "failed" : loading && active === index ? "active" : "";
      return <li className={state} key={title}><i>{state === "done" ? "✓" : state === "failed" ? "!" : index + 1}</i><div><b>{title}</b><small>{description}</small></div><em>{state === "done" ? "완료" : state === "failed" ? "실패" : state === "active" ? "진행 중" : "대기"}</em></li>;
    })}</ol>
  </section>;
}

function columnLabel(column: string, run: AnalysisRun) {
  return run.metrics.find((item) => item.resultField === column)?.label
    ?? run.evidence?.metrics.find((item) => item.resultField === column)?.label
    ?? COLUMN_LABELS[column]
    ?? column;
}

function formatValue(value: unknown, unit?: string | null) {
  const numeric = typeof value === "number"
    ? value
    : typeof value === "string" && /^-?\d+(?:\.\d+)?$/.test(value.trim())
      ? Number(value)
      : null;
  const rendered = numeric !== null && Number.isFinite(numeric)
    ? numeric.toLocaleString("ko-KR", { maximumFractionDigits: 2 })
    : String(value ?? "없음");
  return unit ? `${rendered} ${unit}` : rendered;
}

function columnUnit(column: string, run: AnalysisRun) {
  return run.metrics.find((item) => item.resultField === column)?.unit
    ?? run.evidence?.metrics.find((item) => item.resultField === column)?.unit
    ?? null;
}

function formatAxisValue(value: number) {
  return value.toLocaleString("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
}

function formatPeriod(run: AnalysisRun) {
  const period = run.evidence?.period;
  if (!period) return "기간 정보 없음";
  return `${period.start.replaceAll("-", ".")}부터 ${period.endExclusive.replaceAll("-", ".")} 전까지`;
}

function formatFilterValue(value: unknown) {
  if (value === true) return "예";
  if (value === false) return "아니요";
  return String(value ?? "없음");
}

function filterLabel(field: string) {
  return field.split(".").at(-1)?.replaceAll("_", " ") ?? field;
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
  const [elapsed, setElapsed] = useState(0);
  const [tableSort, setTableSort] = useState<TableSort>({ column: "", direction: "" });
  const chartLines = chart?.yFields.map((field, index) => ({
    field,
    label: columnLabel(field, run),
    color: ["#4f99f5", "#d6a85f", "#68c6a3", "#9b8afb"][index % 4],
  })) ?? [];
  const numericColumns = new Set(table?.columns.filter((column) => table.rows.some((row) => (
    typeof row[column] === "number" || (typeof row[column] === "string" && /^-?\d+(?:\.\d+)?$/.test(row[column].trim()))
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

  if (viewState === "LOADING") {
    return <section className="analysis-state analysis-state--loading" aria-live="polite"><header><LoaderCircle className="spin" size={18} aria-hidden="true" /><div><b>{copy.title}</b></div></header><p>{copy.description}</p><button type="button" className="analysis-cancel" disabled={cancelRequested} onClick={onCancel}><StopCircle size={15} />{cancelRequested ? "취소 요청 중" : "분석 취소"}</button><AnalysisProgress run={run} loading elapsed={elapsed} /></section>;
  }

  return <section className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite">
    {!showResult && <header><Icon size={18} aria-hidden="true" /><div><b>{suggestions.length ? run.error?.clarification_type === "period" ? "어떤 기간으로 분석할까요?" : "어떤 지표로 분석할까요?" : run.error?.code === "CONTEXT_INCOMPLETE" ? "추가 정보 필요" : copy.title}</b></div></header>}
    {!showResult && <p>{run.error?.message ?? run.summary ?? copy.description}</p>}
    {suggestions.length > 0 && <div className="analysis-suggestions" aria-label="분석 지표 선택">{suggestions.map((suggestion) => <button type="button" key={suggestion} disabled={suggestionsDisabled} onClick={() => onSuggestion?.(suggestion)}>{suggestion}</button>)}</div>}
    {run.error?.retryable && suggestions.length === 0 && <button type="button" className="analysis-retry" onClick={onRetry}><RotateCcw size={14} />같은 질문 다시 분석</button>}
    {run.error && suggestions.length === 0 && <><p className="analysis-next-action"><b>다음 행동</b> {ERROR_ACTIONS[run.error.code] ?? (run.error.retryable ? "같은 질문을 다시 분석하거나 잠시 후 시도해 주세요." : "입력된 질문을 확인한 뒤 필요한 내용을 보완해 다시 전송해 주세요.")}</p><details className="analysis-error" data-error-code={run.error.code} data-retryable={String(run.error.retryable)}><summary>기술 정보</summary><dl><div><dt>오류 코드</dt><dd>{run.error.code}</dd></div><div><dt>다시 시도</dt><dd>{run.error.retryable ? "가능" : "불가"}</dd></div><div><dt>추적 ID</dt><dd>{run.traceId || "발급 전"}</dd></div></dl></details></>}
    {showResult && <div className="analysis-dashboard">
      <header className="analysis-dashboard-header"><div><span className={`analysis-result-badge ${viewState === "PARTIAL" ? "is-partial" : ""}`}>{viewState === "PARTIAL" ? "일부 데이터" : "검증된 결과"}</span><small>질문에 대한 답변</small><h2>{run.question}</h2></div><div className="analysis-dashboard-meta"><span>데이터 출처 {run.sources.length}개</span>{run.meta.asOf && <span>기준일 {run.meta.asOf}</span>}</div></header>

      {run.metrics.length > 0 && <section className="analysis-kpi-section" aria-labelledby="analysis-kpi-title"><header><div><small>AT A GLANCE</small><h3 id="analysis-kpi-title">주요 지표</h3></div><span>{run.metrics.length}개 지표</span></header><div className="analysis-metrics">{run.metrics.map((metric, index) => <article className={index === 0 ? "is-primary" : ""} key={metric.metricId}><small>{metric.label}</small><strong>{formatValue(metric.value)}{metric.unit && <em>{metric.unit}</em>}</strong>{metric.definition && <p>{metric.definition}</p>}</article>)}</div></section>}

      <div className="analysis-overview-grid">
        <section className="analysis-summary-card"><header><small>KEY TAKEAWAY</small><h3>분석 요약</h3></header><p>{run.summary || "표와 차트에서 세부 결과를 확인할 수 있습니다."}</p></section>
        <section className="analysis-context-card" aria-label="분석 조건"><header><small>SCOPE</small><h3>분석 기준</h3></header><dl><div><dt>조회 기간</dt><dd>{formatPeriod(run)}</dd></div><div><dt>적용 필터</dt><dd>{Object.entries(run.evidence?.filters ?? {}).length ? Object.entries(run.evidence?.filters ?? {}).map(([key, value]) => `${filterLabel(key)}: ${formatFilterValue(value)}`).join(" · ") : "추가 필터 없음"}</dd></div><div><dt>데이터 행</dt><dd>{run.evidence?.sampling.returnedRows.toLocaleString("ko-KR") ?? 0}{run.evidence?.sampling.totalRows !== null && run.evidence?.sampling.totalRows !== undefined ? ` / 전체 ${run.evidence.sampling.totalRows.toLocaleString("ko-KR")}` : ""}</dd></div></dl></section>
      </div>

      {viewState === "PARTIAL" && <section className="analysis-partial-notice"><b>일부 데이터 소스의 응답을 확인해 주세요.</b><ul>{run.sources.map((source) => <li key={source.urn}><span>{source.name}</span><em>{SOURCE_STATUS[source.status] || "확인 필요"}</em></li>)}</ul></section>}

      {chart && table?.rows.length ? <section className="analysis-result-section analysis-visual-section"><header><div><small>VISUAL</small><h3>추이와 비교</h3></div><span>{table.rows.length.toLocaleString("ko-KR")}개 항목</span></header><figure className="analysis-chart"><ResponsiveContainer width="100%" height={280}>{chart.chartType === "bar" ? <BarChart data={table.rows} margin={{ top: 12, right: 18, bottom: 8, left: 8 }} accessibilityLayer><CartesianGrid strokeDasharray="3 5" vertical={false} /><XAxis dataKey={chart.xField} name={columnLabel(chart.xField, run)} tickLine={false} tickMargin={10} /><YAxis width={76} tickLine={false} tickFormatter={formatAxisValue} /><Tooltip formatter={(value, _name, item) => [formatValue(value, columnUnit(String(item.dataKey), run)), columnLabel(String(item.dataKey), run)]} labelFormatter={(value) => `${columnLabel(chart.xField, run)} ${value}`} /><Legend />{chartLines.map(({ field, label, color }) => <Bar key={field} dataKey={field} name={label} fill={color} radius={[5, 5, 0, 0]} isAnimationActive={false} />)}</BarChart> : <LineChart data={table.rows} margin={{ top: 12, right: 18, bottom: 8, left: 8 }} accessibilityLayer><CartesianGrid strokeDasharray="3 5" vertical={false} /><XAxis dataKey={chart.xField} name={columnLabel(chart.xField, run)} tickLine={false} tickMargin={10} /><YAxis width={76} tickLine={false} tickFormatter={formatAxisValue} /><Tooltip formatter={(value, _name, item) => [formatValue(value, columnUnit(String(item.dataKey), run)), columnLabel(String(item.dataKey), run)]} labelFormatter={(value) => `${columnLabel(chart.xField, run)} ${value}`} /><Legend />{chartLines.map(({ field, label, color }) => <Line key={field} dataKey={field} name={label} type="monotone" stroke={color} strokeWidth={3} dot={table.rows.length <= 12} activeDot={{ r: 5 }} isAnimationActive={false} />)}</LineChart>}</ResponsiveContainer><figcaption>{columnLabel(chart.xField, run)} 기준으로 {chartLines.map((line) => line.label).join(", ")}을 비교합니다.</figcaption></figure></section> : null}

      {table?.columns.length ? <section className="analysis-result-section analysis-data-section"><header><div><small>DETAIL</small><h3>상세 데이터</h3></div><span>{table.rows.length.toLocaleString("ko-KR")}행 · {table.columns.length.toLocaleString("ko-KR")}열</span></header><div className="analysis-table"><table><caption className="sr-only">{run.question} 상세 데이터</caption><thead><tr><th scope="col" className="row-number">#</th>{table.columns.map((column) => <th scope="col" aria-sort={tableSort.column === column ? (tableSort.direction === "asc" ? "ascending" : "descending") : "none"} className={numericColumns.has(column) ? "is-numeric" : ""} key={column}><button type="button" className="analysis-table-sort" aria-label={`${columnLabel(column, run)} 열 정렬`} onClick={() => setTableSort((current) => nextTableSort(current, column))}><span>{columnLabel(column, run)}</span><ArrowUpDown size={12} aria-hidden="true" /></button></th>)}</tr></thead><tbody>{visibleRows.map((row, index) => <tr key={`${run.requestId}-${index}`}><th scope="row" className="row-number">{index + 1}</th>{table.columns.map((column) => <td className={numericColumns.has(column) ? "is-numeric" : ""} key={column}>{formatValue(row[column], columnUnit(column, run))}</td>)}</tr>)}</tbody></table></div></section> : null}
    </div>}
  </section>;
}
