/** 대화 턴의 Trino 쿼리, DataHub 계보, Gate 1~3 검증 내역을 표시하는 서랍 컴포넌트다. */
import React, { useState } from "react";
import { TableProperties, X } from "lucide-react";
import { SectionTitle } from "./common/EnterpriseUi";

const ARTIFACT_TABS = [["report", "보고서"], ["sources", "데이터 출처"], ["run", "실행 정보"]];

function savedRunStatus(status) {
  return ({ SUCCESS: "완료", SUCCEEDED: "완료", PARTIAL: "일부 완료", BLOCKED: "완료되지 않음", FAILED: "실패" })[status] || "확인 필요";
}

function filterSummary(filters = {}) {
  // evidence.filters는 backend가 metric_rules.required_filters로 이미 제한한 거버넌스 필드만 담는다.
  // label·visibility를 판단할 typed 소스가 없으므로 필드명을 임의로 숨기거나 재해석하지 않고
  // 서버가 내려준 실제 컬럼명을 그대로 사람이 읽기 쉬운 형태로만 표시한다.
  const entries = Object.entries(filters).map(([field, value]) => {
    const column = field.split(".").at(-1).replace(/_/g, " ");
    return `${column}: ${String(value ?? "없음")}`;
  });
  return entries.length ? [...new Set(entries)].join(" · ") : "추가 필터 없음";
}

function gateEvidence(run) {
  const history = run.evidence?.gateHistory;
  const final = run.evidence?.gates;
  if (!history && !final) return "없음";
  return ["g1", "g2", "g3"].map((gate) => {
    const outcomes = history?.[gate]?.length ? history[gate] : [final?.[gate]];
    return `${gate.toUpperCase()} ${outcomes.filter(Boolean).join(" → ")}`;
  }).join(" · ");
}

/**
 * 턴별 감사 및 데이터 계보 세부 정보를 사이드 서랍으로 렌더링한다.
 * @param {object} props
 * @param {boolean} props.open
 * @param {object} props.run
 * @param {Function} props.onClose
 * @param {Function} props.onCopy
 */
export function TurnEvidenceDrawer({ open, run, onClose, onCopy }) {
  const [artifactTab, setArtifactTab] = useState("report");
  if (!open || !run) return null;

  return (
    <aside id="analysis-evidence-panel" className="evidence-panel" aria-label="분석 근거">
      <div className="evidence-panel-header">
        <SectionTitle eyebrow="검증 근거" title="분석 근거" />
        <button type="button" aria-label="분석 근거 닫기" onClick={onClose}><X size={18} /></button>
      </div>
      <div className="artifact-tabs" role="tablist" aria-label="분석 근거 종류">
        {ARTIFACT_TABS.map(([id, label]) => (
          <button id={`evidence-tab-${id}`} className={artifactTab === id ? "active" : ""} role="tab" aria-selected={artifactTab === id} onClick={() => setArtifactTab(id)} key={id}>
            {label}
          </button>
        ))}
      </div>

      {artifactTab === "report" && (
        <div id="evidence-panel-report" role="tabpanel" tabIndex={0} className="artifact-report-summary">
          <small>보고서에 사용할 분석 결과</small>
          <h3>{run.question}</h3>
          <p>{run.summary}</p>
          {run.evidence?.metrics?.map((m) => (
            <article className="evidence-metric" key={m.metricId || m.metric_id}>
              <b>{m.label}</b>
              <p>{m.definition}</p>
            </article>
          ))}
        </div>
      )}

      {artifactTab === "sources" && (
        <div id="evidence-panel-sources" role="tabpanel" tabIndex={0} className="evidence-block">
          <h3>사용한 데이터</h3>
          {run.sources?.map((source) => (
            <article className="evidence-source" key={source.urn}>
              <span><TableProperties size={13} />{source.name}</span>
              <dl>
                <div><dt>Schema</dt><dd>{source.schemaVersion || "없음"}</dd></div>
                <div><dt>Snapshot</dt><dd>{source.seedVersion || "없음"}</dd></div>
              </dl>
              <details>
                <summary>데이터 식별 정보</summary>
                <label>DataHub URN<button type="button" onClick={() => onCopy(source.urn)}>복사</button></label>
                <code>{source.urn}</code>
                <label>Trino FQN<button type="button" onClick={() => onCopy(source.fqn)}>복사</button></label>
                <code>{source.fqn || "없음"}</code>
              </details>
            </article>
          ))}
        </div>
      )}

      {artifactTab === "run" && (
        <div id="evidence-panel-run" role="tabpanel" tabIndex={0} className="evidence-block">
          <h3>실행 정보</h3>
          <dl>
            <div><dt>상태</dt><dd>{savedRunStatus(run.status?.toUpperCase())}</dd></div>
            <div><dt>기간</dt><dd>{run.evidence?.period ? `${run.evidence.period.start} ~ ${run.evidence.period.endExclusive} 미포함` : "없음"}</dd></div>
            <div><dt>기준일·시간대</dt><dd>{run.evidence?.asOf || run.meta?.asOf || "없음"} · {run.evidence?.timezone || run.meta?.timezone}</dd></div>
            <div><dt>필터</dt><dd>{filterSummary(run.evidence?.filters)}</dd></div>
            <div><dt>Gate</dt><dd>{gateEvidence(run)}</dd></div>
            <div><dt>캐시</dt><dd>{run.evidence?.cached ? "적용" : "미적용"}</dd></div>
            <div><dt>Sampling</dt><dd>{run.evidence?.sampling?.applied ? "적용" : "미적용"} · {run.evidence?.sampling?.returnedRows ?? 0}/{run.evidence?.sampling?.totalRows ?? "전체 미제공"}행</dd></div>
          </dl>
          <details className="technical-details">
            <summary>모델 및 기술 정보</summary>
            <dl>
              <div><dt>Artifact</dt><dd>{run.artifact?.artifactId || run.artifact?.artifact_id || "없음"}</dd></div>
              <div><dt>Query</dt><dd>{run.artifact?.queryId || run.artifact?.query_id || "없음"}</dd></div>
              <div><dt>Request</dt><dd>{run.requestId}</dd></div>
              <div><dt>Trace</dt><dd>{run.traceId}</dd></div>
            </dl>
          </details>
        </div>
      )}
    </aside>
  );
}
