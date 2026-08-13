import { AlertTriangle, Ban, CheckCircle2, CircleX, Clock3, FileWarning, LoaderCircle, SearchX } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { resolveViewState, type AnalysisRun, type AnalysisViewState } from "../../contracts/analysis";

const VIEW_COPY: Record<AnalysisViewState, { title: string; description: string; icon: typeof CheckCircle2 }> = {
  LOADING: { title: "분석 중", description: "분석 요청을 처리하고 있습니다.", icon: LoaderCircle },
  EMPTY: { title: "결과 없음", description: "조건이나 기간을 바꾸어 다시 요청해 주세요.", icon: SearchX },
  READY: { title: "분석 완료", description: "검증된 결과와 근거를 표시합니다.", icon: CheckCircle2 },
  DELAYED: { title: "응답 지연", description: "데이터 소스의 응답을 기다리고 있습니다.", icon: Clock3 },
  PARTIAL: { title: "부분 완료", description: "성공한 소스와 실패한 소스를 구분해 표시합니다.", icon: AlertTriangle },
  ERROR: { title: "분석 실패", description: "요청을 다시 확인하거나 잠시 후 재시도해 주세요.", icon: CircleX },
  FORBIDDEN: { title: "접근 불가", description: "현재 역할에는 이 분석 범위가 허용되지 않습니다.", icon: Ban },
  INSUFFICIENT_EVIDENCE: { title: "근거 부족", description: "검증 근거를 확보하지 못해 결과를 표시하지 않습니다.", icon: FileWarning },
  CANCELLED: { title: "분석 취소", description: "새 요청으로 다시 시작할 수 있습니다.", icon: CircleX },
};

function formatValue(value: unknown, unit?: string | null) {
  const rendered = typeof value === "number" ? value.toLocaleString("ko-KR") : String(value ?? "없음");
  return unit ? `${rendered} ${unit}` : rendered;
}

function formatAxisValue(value: number) {
  return value.toLocaleString("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
}

export function AnalysisStatePanel({ run }: { run: AnalysisRun }) {
  const viewState = resolveViewState(run);
  const copy = VIEW_COPY[viewState];
  const Icon = copy.icon;
  const showResult = viewState === "READY" || viewState === "PARTIAL";
  const chart = showResult ? run.chart : null;
  const table = showResult ? run.table : null;

  if (viewState === "LOADING") {
    return <section className="analysis-state analysis-state--loading" aria-live="polite"><header><LoaderCircle className="spin" size={18} aria-hidden="true" /><div><b>{copy.title}</b><span>{viewState}</span></div></header><p>{copy.description}</p></section>;
  }

  return <section className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite">
    <header><Icon size={18} aria-hidden="true" /><div><b>{run.error?.code === "CONTEXT_INCOMPLETE" ? "추가 정보 필요" : copy.title}</b><span>{viewState}</span></div></header>
    {!showResult && <p>{run.error?.message ?? run.summary ?? copy.description}</p>}
    {run.error && <dl className="analysis-error" data-error-code={run.error.code} data-retryable={String(run.error.retryable)}><div><dt>error.code</dt><dd>{run.error.code}</dd></div><div><dt>error.retryable</dt><dd>{String(run.error.retryable)}</dd></div></dl>}
    {showResult && <div className="analysis-dashboard">
      <div className="analysis-dashboard-header"><div><small>ANALYSIS DASHBOARD</small><h2>{run.question}</h2></div><div className="analysis-dashboard-meta"><span>source {run.sources.length}</span><span>as_of {run.meta.asOf}</span></div></div>
      {run.summary && <div className="analysis-summary"><small>분석 요약</small><strong>{run.summary}</strong></div>}
      {viewState === "PARTIAL" && <ul>{run.sources.map((source) => <li key={source.urn}>{source.name}: {source.status}</li>)}</ul>}
      {run.metrics.length > 0 && <section className="analysis-result-section"><h3>주요 지표</h3><div className="analysis-metrics">{run.metrics.map((metric) => <article key={metric.metricId}><small>{metric.label}</small><strong>{formatValue(metric.value, metric.unit)}</strong></article>)}</div></section>}
      {chart && table?.rows.length ? <section className="analysis-result-section"><h3>차트</h3><div className="analysis-chart"><ResponsiveContainer width="100%" height={210}><LineChart data={table.rows} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={chart.xField} tick={{ fontSize: 11 }} tickMargin={10} /><YAxis width={72} tick={{ fontSize: 11 }} tickFormatter={formatAxisValue} /><Tooltip formatter={(value, name) => formatValue(value, run.metrics.find((metric) => metric.metricId === name)?.unit)} />{chart.yFields.map((field) => <Line key={field} dataKey={field} name={run.metrics.find((metric) => metric.metricId === field)?.label ?? field} type="monotone" stroke="#1c69d4" />)}</LineChart></ResponsiveContainer></div></section> : null}
      {table?.columns.length ? <section className="analysis-result-section"><h3>상세 데이터</h3><div className="analysis-table"><table><thead><tr>{table.columns.map((column) => <th key={column}>{run.metrics.find((item) => item.metricId === column)?.label ?? column}</th>)}</tr></thead><tbody>{table.rows.map((row, index) => <tr key={`${run.requestId}-${index}`}>{table.columns.map((column) => <td key={column}>{formatValue(row[column], run.metrics.find((item) => item.metricId === column)?.unit)}</td>)}</tr>)}</tbody></table></div></section> : null}
    </div>}
  </section>;
}
