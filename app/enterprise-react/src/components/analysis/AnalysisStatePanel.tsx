import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleX,
  Clock3,
  FileWarning,
  LoaderCircle,
  SearchX,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { resolveViewState, type AnalysisRun, type AnalysisViewState } from "../../contracts/analysis";

const VIEW_COPY: Record<AnalysisViewState, { title: string; description: string; icon: typeof CheckCircle2 }> = {
  LOADING: { title: "분석 중", description: "승인된 분석 경로를 확인하고 있습니다.", icon: LoaderCircle },
  EMPTY: { title: "결과 없음", description: "조건을 바꾸거나 기간을 넓혀 다시 질문해 보세요.", icon: SearchX },
  READY: { title: "분석 완료", description: "검증된 결과와 근거를 표시합니다.", icon: CheckCircle2 },
  DELAYED: { title: "응답 지연", description: "일부 원천 응답을 기다리고 있습니다.", icon: Clock3 },
  PARTIAL: { title: "부분 완료", description: "성공한 원천과 실패한 원천을 구분해 표시합니다.", icon: AlertTriangle },
  ERROR: { title: "분석 실패", description: "안전한 범위에서 다시 시도하거나 관리자에게 문의하세요.", icon: CircleX },
  FORBIDDEN: { title: "접근 불가", description: "현재 역할에는 이 분석 범위가 허용되지 않습니다.", icon: Ban },
  INSUFFICIENT_EVIDENCE: { title: "근거 부족", description: "검증 근거가 확보될 때까지 결과를 표시하지 않습니다.", icon: FileWarning },
  CANCELLED: { title: "분석 취소", description: "새 질문으로 다시 시작할 수 있습니다.", icon: CircleX },
};

export function AnalysisStatePanel({
  run,
  onAddArtifact,
}: {
  run: AnalysisRun;
  onAddArtifact?: (artifactId: string) => void;
}) {
  const viewState = resolveViewState(run);
  const copy = VIEW_COPY[viewState];
  const Icon = copy.icon;
  const showResult = viewState === "READY" || viewState === "PARTIAL";
  const chart = showResult ? run.chart : null;
  const table = showResult ? run.table : null;

  return (
    <section className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite">
      <header>
        <Icon size={18} aria-hidden="true" />
        <div><b>{run.status === "blocked" ? "요청 차단" : copy.title}</b><span>{viewState}</span></div>
      </header>
      <p>{run.error?.message ?? run.summary ?? copy.description}</p>
      {showResult && <div className="analysis-summary"><small>API 제공 요약</small><strong>{run.summary}</strong></div>}
      {viewState === "PARTIAL" && (
          <ul>{run.sources.map((source) => <li key={source.urn}>{source.name}: {source.status === "success" ? "성공" : "실패"}</li>)}</ul>
      )}
      {showResult && run.metrics.length > 0 && (
        <div className="analysis-metrics" aria-label="API 제공 지표">
          {run.metrics.map((metric) => (
            <article key={metric.metricId}>
              <small>{metric.label}</small>
              <strong>{String(metric.value ?? "—")} {metric.unit ?? ""}</strong>
              <code>{metric.metricId}</code>
            </article>
          ))}
        </div>
      )}
      {chart && table?.rows.length ? (
        <div className="analysis-chart" aria-label={`API 제공 ${chart.chartType} 차트`}>
          <small>{chart.chartType} · x={chart.xField} · y={chart.yFields.join(", ")}</small>
          <ResponsiveContainer width="100%" height={210}>
            <LineChart data={table.rows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey={chart.xField} />
              <YAxis />
              <Tooltip />
              {chart.yFields.map((field) => (
                <Line key={field} dataKey={field} name={field} type="monotone" stroke="#9d7b45" />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : null}
      {table?.columns.length ? (
        <div className="analysis-table">
          <table>
            <thead><tr>{table.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
            <tbody>
              {table.rows.map((row, index) => (
                <tr key={`${run.requestId}-${index}`}>
                  {table.columns.map((column) => <td key={column}>{String(row[column] ?? "—")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {run.artifact && (
        <div className="artifact-bridge">
          <div>
            <small>Artifact</small>
            <code>{run.artifact.artifactId}</code>
          </div>
          <button type="button" onClick={() => onAddArtifact?.(run.artifact!.artifactId)}>
            보고서에 담기
          </button>
        </div>
      )}
      <footer>
        <code>{run.status}</code>
        <span>request {run.requestId}</span>
        <span>run/trace {run.traceId}</span>
      </footer>
    </section>
  );
}
