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
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { resolveViewState, type AnalysisRun, type AnalysisViewState } from "../../contracts/analysis";

const COLUMN_LABELS: Record<string, string> = {
  business_date: "일자",
  recognized_room_revenue: "객실 매출",
  occupancy_rate: "객실 점유율",
  direct_booking_share: "직접 예약 비중",
  banquet_changes: "연회 일정 변경",
  cancelled_room_nights: "연계 객실 취소",
};

const COLUMN_UNITS: Record<string, string> = {
  banquet_changes: "건",
  cancelled_room_nights: "박",
};

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

function formatValue(value: unknown) {
  return typeof value === "number" ? value.toLocaleString("ko-KR") : String(value ?? "—");
}

function formatMetric(value: unknown, unit?: string) {
  if (typeof value !== "number") return `${formatValue(value)}${unit ? ` ${unit}` : ""}`;
  if (unit === "KRW") {
    if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}억 원`;
    if (value >= 10_000) return `${(value / 10_000).toLocaleString("ko-KR")}만 원`;
    return `${value.toLocaleString("ko-KR")}원`;
  }
  return `${value.toLocaleString("ko-KR")}${unit ? ` ${unit}` : ""}`;
}

function formatAxisValue(value: number) {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)}억`;
  if (value >= 10_000) return `${Math.round(value / 10_000).toLocaleString("ko-KR")}만`;
  return value.toLocaleString("ko-KR");
}

const PIPELINE_STEPS = [
  ["DATAHUB", "자산 · 권한 확인", "선택한 Profile 권한으로 DataHub Dataset을 조회합니다."],
  ["NODE1", "질문 이해", "질문의 목적, 기간, 업무 영역을 구조화합니다."],
  ["G1", "1차 검증 — SQL 생성 전", "지표 · 기간 · 승인 Context · 권한을 확인합니다."],
  ["NODE2", "통합 SQL 생성", "허용된 자산과 Join Policy만 사용해 SQL을 생성합니다."],
  ["G2", "2차 검증 — SQL 실행 전", "AST · 컬럼 · Join · Filter · 읽기 전용 경계를 확인합니다."],
  ["TRINO", "통합 조회 실행", "Profile 전용 읽기 계정으로 Trino 조회를 실행합니다."],
  ["G3", "3차 검증 — 결과 제공 전", "결과 구조 · 빈 결과 · Sampling · 민감정보 증적을 확인합니다."],
  ["NODE3", "결과 설명", "검증을 통과한 결과만 자연어로 설명합니다."],
  ["ARTIFACT", "결과 저장", "표 · 차트 · 산출 근거를 함께 보존합니다."],
] as const;

function AnalysisProgress({ run }: { run: AnalysisRun }) {
  const events = run.progress ?? [];
  if (!events.length) return null;
  const latest = new Map(events.map((event) => [event.stage, event.outcome]));
  const completed = PIPELINE_STEPS.filter(([stage]) => latest.has(stage)).length;
  const failed = events.findLast((event) => event.outcome === "FAILED" || event.outcome === "BLOCKED");
  return (
    <details className="analysis-process" open={run.status === "queued" || run.status === "running"}>
      <summary><span className="analysis-process-caret">›</span><b>처리 과정</b><span>{failed ? `${completed} 단계에서 중단` : `${completed} / ${PIPELINE_STEPS.length} 단계`}</span></summary>
      <ol aria-label="실제 분석 실행 단계">
        {PIPELINE_STEPS.map(([stage, label, description], index) => {
          const outcome = latest.get(stage);
          const state = outcome === "STARTED" ? "busy" : outcome === "PASSED" ? "done" : outcome === "SKIPPED" ? "skip" : outcome === "FAILED" || outcome === "BLOCKED" ? "fail" : "pending";
          const gate = state === "busy" ? "진행 중" : state === "done" ? "완료" : state === "skip" ? "생략" : state === "fail" ? (outcome === "BLOCKED" ? "차단" : "실패") : "";
          return <li key={stage} className={`analysis-process-step ${state}`}><span className="analysis-process-dot">{state === "fail" ? "!" : index + 1}</span><span><b>{label}</b><small>{description}</small></span><em>{gate}</em></li>;
        })}
      </ol>
    </details>
  );
}

export function AnalysisStatePanel({ run }: { run: AnalysisRun }) {
  const viewState = resolveViewState(run);
  const copy = VIEW_COPY[viewState];
  const Icon = copy.icon;
  const needsClarification = run.error?.code === "CONTEXT_INCOMPLETE";
  const showResult = viewState === "READY" || viewState === "PARTIAL";
  const chart = showResult ? run.chart : null;
  const table = showResult ? run.table : null;

  if (viewState === "LOADING") {
    return (
      <section className="analysis-state analysis-state--loading" aria-live="polite"><header><LoaderCircle size={18} /><div><b>분석 요청 중</b><span>실제 단계 조회</span></div></header><p>서버가 기록한 처리 단계와 최종 결과를 기다리고 있습니다.</p><AnalysisProgress run={run} /></section>
    );
  }

  return (
    <section className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite">
      <header>
        <Icon size={18} aria-hidden="true" />
        <div>
          <b>{needsClarification ? "추가 정보 필요" : run.status === "blocked" ? "요청 차단" : copy.title}</b>
          <span>{needsClarification ? "재질문" : viewState}</span>
        </div>
      </header>
      {!showResult && <p>{run.error?.message ?? run.summary ?? copy.description}</p>}
      {run.error && (
        <dl className="analysis-error" data-error-code={run.error.code} data-retryable={String(run.error.retryable)}>
          <div><dt>error.code</dt><dd>{run.error.code}</dd></div>
          <div><dt>error.retryable</dt><dd>{String(run.error.retryable)}</dd></div>
        </dl>
      )}
      <AnalysisProgress run={run} />
      {showResult && (
        <div className="analysis-dashboard">
          <div className="analysis-dashboard-header">
            <div><small>ANALYSIS DASHBOARD</small><h2>객실 운영 분석 결과</h2></div>
            <div className="analysis-dashboard-meta">
              <span>{run.sources.length}개 데이터 소스</span>
              <span>기준 {run.meta.asOf}</span>
            </div>
          </div>
          <div className="analysis-summary"><small>분석 요약</small><strong>{run.summary}</strong></div>
          {viewState === "PARTIAL" && (
            <ul>{run.sources.map((source) => <li key={source.urn}>{source.name}: {source.status}</li>)}</ul>
          )}
          {run.metrics.length > 0 && (
            <section className="analysis-result-section"><h3>주요 지표</h3><div className="analysis-metrics" aria-label="검증된 핵심 지표">
              {run.metrics.map((metric) => (
                <article key={metric.metricId}>
                  <small>{metric.label}</small>
                  <strong>{formatMetric(metric.value, metric.unit)}</strong>
                </article>
              ))}
            </div></section>
          )}
          {chart && table?.rows.length ? (
            <section className="analysis-result-section"><h3>기간별 변화</h3><div className="analysis-chart" aria-label="기간별 변화 차트">
              <ResponsiveContainer width="100%" height={210}>
                {chart.chartType === "bar" ? <BarChart data={table.rows} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey={chart.xField} tick={{ fontSize: 11 }} tickMargin={10} />
                  <YAxis width={72} tick={{ fontSize: 11 }} tickFormatter={formatAxisValue} />
                  <Tooltip formatter={(value) => formatMetric(value, run.metrics.find((metric) => metric.metricId === chart.yFields[0])?.unit)} />
                  {chart.yFields.map((field) => (
                    <Bar key={field} dataKey={field} name={COLUMN_LABELS[field] ?? field} fill="#1c69d4" />
                  ))}
                </BarChart> : <LineChart data={table.rows} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey={chart.xField} tick={{ fontSize: 11 }} tickMargin={10} />
                  <YAxis width={72} tick={{ fontSize: 11 }} tickFormatter={formatAxisValue} />
                  <Tooltip formatter={(value) => formatMetric(value, run.metrics.find((metric) => metric.metricId === chart.yFields[0])?.unit)} />
                  {chart.yFields.map((field) => <Line key={field} dataKey={field} name={COLUMN_LABELS[field] ?? field} type="monotone" stroke="#1c69d4" />)}
                </LineChart>}
              </ResponsiveContainer>
            </div></section>
          ) : null}
          {table?.columns.length ? (
            <section className="analysis-result-section"><h3>상세 데이터</h3><div className="analysis-table">
              <table>
                <thead><tr>{table.columns.map((column) => {
                  const metric = run.metrics.find((item) => item.metricId === column);
                  return <th key={column}>{metric?.label ?? COLUMN_LABELS[column] ?? column}</th>;
                })}</tr></thead>
                <tbody>
                  {table.rows.map((row, index) => (
                    <tr key={`${run.requestId}-${index}`}>
                      {table.columns.map((column) => {
                        const metric = run.metrics.find((item) => item.metricId === column);
                        return <td key={column}>{formatMetric(row[column], metric?.unit ?? COLUMN_UNITS[column])}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div></section>
          ) : null}
        </div>
      )}
    </section>
  );
}
