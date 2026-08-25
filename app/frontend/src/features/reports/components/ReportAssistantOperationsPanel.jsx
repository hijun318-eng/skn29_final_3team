/** 관리자에게만 안전한 Report Assistant 기간 품질·비용 지표를 표시한다. */
import { memo } from "react";

const percent = (value) => value == null ? "데이터 없음" : `${(value * 100).toFixed(1)}%`;

/** 기간 집계와 안전한 실패 code만 표시하고 raw prompt·SQL은 소비하지 않는다. */
export const ReportAssistantOperationsPanel = memo(function ReportAssistantOperationsPanel({
  failures,
  onRefresh,
  pending,
  summary,
}) {
  return <section className="card report-assistant-operations" aria-label="Report Assistant 운영 지표">
    <header><div><small>Agent quality</small><h2>Report Assistant 운영 지표</h2></div><button type="button" onClick={onRefresh} disabled={Boolean(pending)}>새로고침</button></header>
    {!summary ? <p>운영 지표를 불러오는 중입니다.</p> : <>
      <p>{new Date(summary.period_start).toLocaleString("ko-KR")} ~ {new Date(summary.period_end).toLocaleString("ko-KR")} · 분모 {summary.denominator}건</p>
      <dl className="report-operations-summary">
        <div><dt>전체 요청</dt><dd>{summary.total_requests}</dd></div>
        <div><dt>계약 성공률</dt><dd>{percent(summary.contract_success_rate)}</dd></div>
        <div><dt>승인률</dt><dd>{percent(summary.approval_rate)}</dd></div>
        <div><dt>Revision 성공률</dt><dd>{percent(summary.revision_success_rate)}</dd></div>
        <div><dt>평균 응답</dt><dd>{summary.average_model_latency_ms == null ? "데이터 없음" : `${Math.round(summary.average_model_latency_ms)}ms`}</dd></div>
        <div><dt>Token</dt><dd>{summary.total_input_tokens == null ? "데이터 없음" : `${summary.total_input_tokens} / ${summary.total_output_tokens ?? "-"}`}</dd></div>
        <div><dt>예상 비용</dt><dd>{summary.estimated_cost_total == null ? "데이터 없음" : `$${summary.estimated_cost_total}`}</dd></div>
      </dl>
      <details><summary>최근 실패 {failures.length}건</summary>{failures.length ? <ul>{failures.map((failure) => <li key={failure.evaluation_id}><code>{failure.error_code}</code> · {failure.final_phase}</li>)}</ul> : <p>기간 내 실패가 없습니다.</p>}</details>
    </>}
  </section>;
});
