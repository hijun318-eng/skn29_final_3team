/** 대화 턴의 Trino 쿼리, DataHub 계보, Gate 1~3 검증 내역을 표시하는 서랍 컴포넌트다. */
import React, { useState } from "react";
import { Database, FileText, ShieldCheck, TableProperties, X } from "lucide-react";
import { SectionTitle } from "./common/EnterpriseUi";
import { analysisTitle, localizeMetricDefinition, metricDisplayLabel } from "../utils/presentation";
import { createAnalysisValueScale, userFacingAnalysisSummary } from "./analysis/analysisValueScale";

const ARTIFACT_TABS = [
  ["report", "결과 요약", FileText],
  ["sources", "데이터 출처", Database],
  ["run", "실행 검증", ShieldCheck],
];

function sourceDisplayName(source) {
  const suppliedName = String(source.name || "").trim();
  return /[가-힣]/.test(suppliedName) ? suppliedName : "분석 데이터";
}

function timezoneDisplayName(timezone) {
  if (!timezone) return "시간대 정보 없음";
  return timezone === "Asia/Seoul" ? "서울 시간" : timezone;
}

function savedRunStatus(status) {
  return ({ SUCCESS: "완료", SUCCEEDED: "완료", PARTIAL: "일부 완료", BLOCKED: "완료되지 않음", CLARIFYING: "입력 필요", FAILED: "실패" })[status] || "확인 필요";
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

function validationSummary(run) {
  const gates = run.evidence?.gates;
  return gates && [gates.g1, gates.g2, gates.g3].every((outcome) => outcome === "PASSED")
    ? "문맥·SQL·결과 검증 통과"
    : "일부 검증 결과 확인 필요";
}

function periodSummary(run) {
  if (run.evidence?.period) {
    return `${run.evidence.period.start.replaceAll("-", ".")}부터 ${run.evidence.period.endExclusive.replaceAll("-", ".")} 전까지`;
  }
  if (run.evidence?.snapshot?.selection === "max_source_value_lt_as_of") {
    return `${run.evidence.snapshot.cutoff.replaceAll("-", ".")} 이전 최신 데이터`;
  }
  return "지정된 시간 기준 없음";
}

function samplingSummary(run) {
  const sampling = run.evidence?.sampling;
  if (!sampling?.applied) return "전체 결과 사용";
  return sampling.totalRows === null || sampling.totalRows === undefined
    ? `${sampling.returnedRows ?? 0}행 표시`
    : `전체 ${sampling.totalRows}행 중 ${sampling.returnedRows ?? 0}행 표시`;
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
  const valueScale = createAnalysisValueScale(run.metrics ?? [], run.table?.rows ?? []);

  return (
    <aside id="analysis-evidence-panel" className="evidence-panel" aria-label="분석 근거">
      <div className="evidence-panel-header">
        <div>
          <SectionTitle eyebrow="검증 근거" title="분석 근거" />
          <p>결과에 사용된 데이터와 검증 과정을 확인합니다.</p>
        </div>
        <button type="button" aria-label="분석 근거 닫기" onClick={onClose}><X size={18} /></button>
      </div>
      <div className="artifact-tabs" role="tablist" aria-label="분석 근거 종류">
        {ARTIFACT_TABS.map(([id, label, Icon]) => (
          <button id={`evidence-tab-${id}`} aria-controls={`evidence-panel-${id}`} className={artifactTab === id ? "active" : ""} role="tab" aria-selected={artifactTab === id} onClick={() => setArtifactTab(id)} key={id}>
            <Icon size={13} aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </div>

      {artifactTab === "report" && (
        <div id="evidence-panel-report" aria-labelledby="evidence-tab-report" role="tabpanel" tabIndex={0} className="artifact-report-summary">
          <small>검증된 결과 요약</small>
          <h3>{analysisTitle(run)}</h3>
          <p>{userFacingAnalysisSummary(run, valueScale)}</p>
          <div className="evidence-validation-status"><ShieldCheck size={14} aria-hidden="true" /><span>{validationSummary(run)}</span></div>
          {run.evidence?.metrics?.map((m) => (
            <article className="evidence-metric" key={m.metricId || m.metric_id}>
              <b>{metricDisplayLabel(m)}</b>
              <p>{localizeMetricDefinition(m.definition)}</p>
            </article>
          ))}
        </div>
      )}

      {artifactTab === "sources" && (
        <div id="evidence-panel-sources" aria-labelledby="evidence-tab-sources" role="tabpanel" tabIndex={0} className="evidence-block">
          <h3>사용한 데이터</h3>
          {!run.sources?.length && <p className="evidence-empty">연결된 데이터 출처가 없습니다.</p>}
          {run.sources?.map((source) => (
            <article className="evidence-source" key={source.urn}>
              <span><TableProperties size={13} />{sourceDisplayName(source)}{source.synthetic && <em>합성 데이터</em>}</span>
              <dl>
                <div><dt>스키마 버전</dt><dd>{source.schemaVersion || "정보 없음"}</dd></div>
                <div><dt>데이터 버전</dt><dd>{source.seedVersion || "정보 없음"}</dd></div>
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
        <div id="evidence-panel-run" aria-labelledby="evidence-tab-run" role="tabpanel" tabIndex={0} className="evidence-block">
          <h3>실행 검증</h3>
          <dl>
            <div><dt>상태</dt><dd>{savedRunStatus(run.status?.toUpperCase())}</dd></div>
            <div><dt>분석 기간</dt><dd>{periodSummary(run)}</dd></div>
            <div><dt>기준일·시간대</dt><dd>{run.evidence?.asOf || run.meta?.asOf || "없음"} · {timezoneDisplayName(run.evidence?.timezone || run.meta?.timezone)}</dd></div>
            <div><dt>필터</dt><dd>{filterSummary(run.evidence?.filters)}</dd></div>
            <div><dt>검증 결과</dt><dd>{validationSummary(run)}</dd></div>
            <div><dt>데이터 조회</dt><dd>{run.evidence?.cached ? "검증된 이전 결과 재사용" : "새로 조회"}</dd></div>
            <div><dt>표시 범위</dt><dd>{samplingSummary(run)}</dd></div>
          </dl>
          <details className="technical-details">
            <summary>모델 및 기술 정보</summary>
            <dl>
              <div><dt>Gate 이력</dt><dd>{gateEvidence(run)}</dd></div>
              <div><dt>Artifact</dt><dd>{run.artifact?.artifactId || run.artifact?.artifact_id || "없음"}</dd></div>
              <div><dt>Query</dt><dd>{run.artifact?.queryId || run.artifact?.query_id || "없음"}</dd></div>
              <div><dt>Product Release</dt><dd>{run.evidence?.productReleaseId || "없음"}</dd></div>
              <div><dt>Evidence Cutoff</dt><dd>{run.evidence?.evidenceCutoff || "없음"}</dd></div>
              <div><dt>원본 시간대</dt><dd>{run.evidence?.timezone || run.meta?.timezone || "없음"}</dd></div>
              <div><dt>Trino 처리 행</dt><dd>{run.evidence?.execution?.processedRows ?? 0}</dd></div>
              <div><dt>Trino 스캔</dt><dd>{run.evidence?.execution?.scanBytes ?? 0} bytes</dd></div>
              <div><dt>실행 주의</dt><dd>{run.evidence?.execution?.warningCount ?? 0}건</dd></div>
            </dl>
          </details>
        </div>
      )}
    </aside>
  );
}
