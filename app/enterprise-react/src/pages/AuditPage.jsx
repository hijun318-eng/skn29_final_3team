import { Download, Search, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createAuditClient } from "../api/auditClient.ts";

const formatTime = (value) => value ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value)) : "-";

function Metadata({ label, value }) {
  return <div><dt>{label}</dt><dd>{value ?? "-"}</dd></div>;
}

export function AuditPage() {
  const client = useMemo(() => createAuditClient(), []);
  const [requestId, setRequestId] = useState("");
  const [status, setStatus] = useState("");
  const [startedFrom, setStartedFrom] = useState("");
  const [startedTo, setStartedTo] = useState("");
  const [items, setItems] = useState([]);
  const [trace, setTrace] = useState(null);
  const [access, setAccess] = useState(null);
  const [recovery, setRecovery] = useState(null);
  const [state, setState] = useState({ loading: true, error: "" });

  const load = useCallback(async (filters = {}) => {
    setState({ loading: true, error: "" });
    try {
      const [nextItems, effectiveAccess, recoveryStatus] = await Promise.all([client.search(filters), client.getAccess(), client.getRecovery().catch(() => null)]);
      setItems(nextItems);
      setAccess(effectiveAccess);
      setRecovery(recoveryStatus);
      setTrace(nextItems.length === 1 ? await client.get(nextItems[0].request_id) : null);
      setState({ loading: false, error: "" });
    } catch (error) {
      setItems([]);
      setTrace(null);
      setAccess(null);
      setRecovery(null);
      setState({ loading: false, error: error instanceof Error ? error.message : "감사 Trace를 불러오지 못했습니다." });
    }
  }, [client]);

  useEffect(() => { void load(); }, [load]);

  const select = async (id) => {
    setState({ loading: true, error: "" });
    try {
      setTrace(await client.get(id));
      setState({ loading: false, error: "" });
    } catch (error) {
      setState({ loading: false, error: error instanceof Error ? error.message : "감사 Trace를 불러오지 못했습니다." });
    }
  };

  const download = () => {
    if (!trace) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(trace, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `audit-${trace.request_id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page-content audit-page">
      <section className="card audit-search">
        <header><div><small>OWNER-SCOPED TRACE</small><h2>요청 감사 조회</h2><p>본인 요청의 상태 전이와 정책·모델·Artifact·보고서 연결 메타데이터를 확인합니다.</p>{access && <p>유효 권한: <b>{access.role}</b> · 정책 <code>{access.policy_version}</code></p>}</div><ShieldCheck /></header>
        <form onSubmit={(event) => { event.preventDefault(); void load({ requestId, status, startedFrom: startedFrom ? new Date(startedFrom).toISOString() : "", startedTo: startedTo ? new Date(startedTo).toISOString() : "" }); }}>
          <input aria-label="Request ID" placeholder="Request ID (비우면 최근 요청)" value={requestId} onChange={(event) => setRequestId(event.target.value)} />
          <select aria-label="상태" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">전체 상태</option>{["RECEIVED", "SUCCEEDED", "PARTIAL", "DENIED", "FAILED"].map((value) => <option key={value}>{value}</option>)}</select>
          <input aria-label="시작일 시작" type="datetime-local" value={startedFrom} onChange={(event) => setStartedFrom(event.target.value)} />
          <input aria-label="시작일 종료" type="datetime-local" value={startedTo} onChange={(event) => setStartedTo(event.target.value)} />
          <button className="primary" type="submit" disabled={state.loading}><Search size={16} />조회</button>
        </form>
      </section>

      {state.error && <p className="report-api-state error" role="alert">{state.error}</p>}
      {state.loading && <p className="report-api-state" role="status">감사 기록을 조회하고 있습니다.</p>}

      {recovery && <section className="audit-recovery" aria-label="보존 및 복구 상태">
        <article className="card"><small>RETENTION</small><h3>보존 정책</h3><b>{recovery.retention.status}</b><p>마지막 실행 {formatTime(recovery.retention.last_run_at)}</p></article>
        <article className="card"><small>BACKUP · RPO {recovery.backup.rpo_target_hours}h</small><h3>암호화 백업</h3><b>{recovery.backup.status}</b><p>나이 {recovery.backup.age_hours == null ? "-" : `${recovery.backup.age_hours}h`} · RPO {recovery.backup.rpo_passed == null ? "미확인" : recovery.backup.rpo_passed ? "충족" : "초과"}</p><code>{recovery.backup.sha256 || "hash 미확인"}</code></article>
        <article className="card"><small>RESTORE · RTO {recovery.restore.rto_target_hours}h</small><h3>복구 검증</h3><b>{recovery.restore.status}</b><p>{recovery.restore.mode} · 마지막 검증 {formatTime(recovery.restore.verified_at)}</p><p>RPO {recovery.restore.rpo_passed == null ? "미확인" : recovery.restore.rpo_passed ? "충족" : "초과"} · RTO {recovery.restore.rto_passed == null ? "미확인" : recovery.restore.rto_passed ? "충족" : "초과"}</p><code>{recovery.restore.backup_sha256 || "hash 미확인"}</code></article>
      </section>}

      <div className="audit-layout">
        <section className="card audit-list">
          <header><h3>요청 목록</h3><span>{items.length}건</span></header>
          {items.map((item) => <button key={item.request_id} aria-pressed={trace?.request_id === item.request_id} onClick={() => void select(item.request_id)}><b>{item.request_type}</b><code>{item.request_id}</code><span>{item.status} · {formatTime(item.started_at)}</span></button>)}
          {!state.loading && items.length === 0 && !state.error && <p>조회 가능한 요청이 없습니다.</p>}
        </section>

        <section className="card audit-detail">
          <header><div><small>TRACE DETAIL</small><h3>{trace ? trace.request_id : "요청을 선택하세요"}</h3></div><button className="secondary" onClick={download} disabled={!trace}><Download size={15} />JSON 저장</button></header>
          {trace && <>
            <dl className="audit-metadata">
              <Metadata label="상태" value={trace.status} /><Metadata label="Trace ID" value={trace.trace_id} />
              <Metadata label="역할" value={trace.user_role} /><Metadata label="SQL 정책" value={trace.policy.sql_policy_version} />
              <Metadata label="접근 Profile" value={trace.access.access_profile} /><Metadata label="정책 Version" value={trace.policy.policy_version} />
              <Metadata label="허용 Domain" value={trace.access.allowed_domains.join(", ")} /><Metadata label="DataHub actor" value={trace.access.datahub_actor} />
              <Metadata label="Entitlement hash" value={trace.policy.entitlement_hash} /><Metadata label="Trino role" value={trace.access.trino_role} />
              <Metadata label="DataHub 검색 시도" value={trace.access.datahub_search_attempted ? "예" : "아니오"} /><Metadata label="Trino 실행 시도" value={trace.access.trino_execution_attempted ? "예" : "아니오"} />
              <Metadata label="시작" value={formatTime(trace.started_at)} /><Metadata label="완료" value={formatTime(trace.completed_at)} />
              <Metadata label="Context release" value={trace.context.release_key ? `${trace.context.release_key} v${trace.context.release_version}` : null} />
              <Metadata label="Model" value={trace.model ? `${trace.model.model_name} / ${trace.model.model_revision}` : null} />
              <Metadata label="Query" value={trace.query?.query_id} /><Metadata label="Artifact" value={trace.artifact?.artifact_id} />
              <Metadata label="Source URNs" value={trace.query?.source_urns?.join(", ")} /><Metadata label="Masking" value={trace.artifact ? `${trace.artifact.masking.applied ? "적용" : "미적용"}${trace.artifact.masking.fields.length ? ` (${trace.artifact.masking.fields.join(", ")})` : ""}` : null} />
              <Metadata label="허용 URNs" value={trace.access.allowed_urns.join(", ")} />
            </dl>
            <div className="audit-transitions"><h4>상태 전이</h4><ol>{trace.transitions.map((item) => <li key={item.sequence}><i>{item.sequence}</i><b>{item.from_status || "START"} → {item.to_status}</b><time>{formatTime(item.created_at)}</time></li>)}</ol></div>
            <div className="audit-reports"><h4>보고서 실행 연결</h4>{trace.reports.length ? trace.reports.map((report) => <p key={report.run_id}><code>{report.run_id}</code><span>v{report.definition_version} · {report.status}</span></p>) : <p>연결된 보고서 실행이 없습니다.</p>}</div>
          </>}
        </section>
      </div>
    </div>
  );
}
