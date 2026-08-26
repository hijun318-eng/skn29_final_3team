/** 선택한 감사 trail을 순서형 증거선과 redacted 기술 근거로 표시하는 모듈이다. */

import { AlertTriangle, Check, Clipboard, FileClock, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import type { AuditOutcome, AuditTrailDetailData } from "./auditTrailTypes.ts";

const OUTCOME_LABELS: Record<AuditOutcome, string> = {
  SUCCEEDED: "성공",
  FAILED: "실패",
  DENIED: "정책 거부",
  CANCELLED: "취소",
  IN_PROGRESS: "진행 중",
  CLARIFICATION_REQUIRED: "확인 필요",
  UNKNOWN: "확인 불가",
};

const EVIDENCE_LABELS = {
  request_id: "Request",
  trace_id: "Trace",
  query_execution_id: "Query execution",
  query_id: "Trino query",
  artifact_id: "Artifact",
  report_run_id: "Report run",
  context_release_id: "Context release",
  model_version_id: "Model version",
  sql_policy_version: "SQL policy",
};

/** 서버 outcome을 색상 외 텍스트까지 포함한 공통 상태 표지로 렌더링한다. */
export function AuditOutcomeBadge({ outcome }: { outcome: AuditOutcome }) {
  return <span className={`audit-outcome audit-outcome--${outcome.toLowerCase().replaceAll("_", "-")}`}><i />{OUTCOME_LABELS[outcome]}</span>;
}

/** UTC 감사 시각을 서울 시간대의 일관된 날짜·시각 표기로 변환한다. */
export function formatAuditTimestamp(value: string | null) {
  if (!value) return "-";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime())
    ? value
    : timestamp.toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
}

/** 상세 로딩·실패·미선택 상태와 서버 순서 이벤트를 한 영역에서 배타적으로 표시한다. */
export function AuditTrailDetail({
  detail,
  loading,
  error,
  onRetry,
}: {
  detail: AuditTrailDetailData | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
}) {
  const [copyNotice, setCopyNotice] = useState("");

  useEffect(() => setCopyNotice(""), [detail?.trail_id]);

  const copyEvidence = async (label: string, value: string) => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setCopyNotice(`${label} 식별자를 복사했습니다.`);
    } catch {
      setCopyNotice(`${label} 식별자를 복사하지 못했습니다.`);
    }
  };

  if (loading) {
    return <div className="audit-detail-state" role="status"><i className="audit-spinner" /><b>감사 추적을 불러오고 있습니다.</b></div>;
  }
  if (error) {
    return <div className="audit-detail-state audit-detail-state--error" role="alert"><AlertTriangle size={22} /><b>{error}</b><button type="button" onClick={onRetry}><RefreshCw size={14} />다시 시도</button></div>;
  }
  if (!detail) {
    return <div className="audit-detail-state"><FileClock size={25} /><b>확인할 작업을 선택하세요.</b><span>왼쪽 목록에서 하나를 선택하면 요청부터 결과까지의 근거가 이어집니다.</span></div>;
  }

  return <div className="audit-detail-content">
    <header className="audit-detail-heading" id="audit-trail-detail-heading" tabIndex={-1}>
      <div><small>SELECTED AUDIT TRAIL</small><h3>{detail.headline}</h3><p>{formatAuditTimestamp(detail.started_at)} → {formatAuditTimestamp(detail.ended_at)}</p></div>
      <AuditOutcomeBadge outcome={detail.outcome} />
    </header>

    {detail.events.length === 0
      ? <div className="audit-detail-state"><FileClock size={24} /><b>연결된 이벤트가 없습니다.</b><span>서버의 trail grouping 결과를 확인해 주세요.</span></div>
      : <ol className="audit-timeline" aria-label="감사 이벤트 순서">
        {detail.events.map((event) => {
          const evidence = Object.entries(event.evidence).filter((entry): entry is [keyof typeof EVIDENCE_LABELS, string] => Boolean(entry[1]));
          const hasDetails = Object.keys(event.details_redacted).length > 0;
          return <li key={event.event_id} className={`audit-timeline__event audit-timeline__event--${event.outcome.toLowerCase().replaceAll("_", "-")}`}>
            <span className="audit-timeline__node" aria-hidden="true"><Check size={12} /></span>
            <article>
              <header><div><time dateTime={event.occurred_at}>{formatAuditTimestamp(event.occurred_at)}</time><h4>{event.action_label || event.action_code}</h4>{event.action_label && <code>{event.action_code}</code>}</div><AuditOutcomeBadge outcome={event.outcome} /></header>
              <p>{event.summary}</p>
              <dl className="audit-event-context">
                <div><dt>수행자</dt><dd>{event.actor.display_name || "시스템"}<small>{event.actor.role}</small></dd></div>
                <div><dt>대상</dt><dd>{event.object.type}<code>{event.object.id}</code></dd></div>
              </dl>
              {(evidence.length > 0 || hasDetails) && <details className="audit-technical-evidence">
                <summary>기술 근거</summary>
                {evidence.length > 0 && <dl>
                  {evidence.map(([key, value]) => <div key={key}><dt>{EVIDENCE_LABELS[key]}</dt><dd><code title={value}>{value}</code><button type="button" aria-label={`${EVIDENCE_LABELS[key]} 식별자 복사`} onClick={() => void copyEvidence(EVIDENCE_LABELS[key], value)}><Clipboard size={13} /></button></dd></div>)}
                </dl>}
                {hasDetails && <details className="audit-redacted-details"><summary>Redacted 상세</summary><pre>{JSON.stringify(event.details_redacted, null, 2)}</pre></details>}
              </details>}
            </article>
          </li>;
        })}
      </ol>}
    <p className="audit-copy-notice" role="status" aria-live="polite">{copyNotice}</p>
  </div>;
}
