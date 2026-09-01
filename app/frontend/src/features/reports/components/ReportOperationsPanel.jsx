/** 승인 보고서의 실행 내역·예약과 초안 생성 기록을 표시하는 운영 모듈이다. */
import { memo } from "react";
import { Clock3, Inbox, RotateCcw } from "lucide-react";

import { formatSeoulTime, reportRunStatusLabel } from "../reportPageLabels";

function reportRunBlockMessage(status) {
  if (status === "success") return "최신 데이터 반영을 완료했습니다.";
  if (status === "partial") return "일부 결과만 반영되었습니다. 다시 생성해 주세요.";
  if (status === "failed") return "이 블록을 생성하지 못했습니다. 다시 시도해 주세요.";
  if (status === "cancelled") return "실행이 취소되었습니다.";
  return "실행 결과를 확인해 주세요.";
}

/** 승인본 실행·schedule·assistant trace를 관리하며 pending 명령을 중복 제출하지 않는다. */
export const ReportOperationsPanel = memo(function ReportOperationsPanel({
  assistantTrace,
  cadence,
  filteredRunCount,
  onCreateSchedule,
  onLoadRuns,
  onRetryRun,
  onSelectRun,
  onSetScheduleEnabled,
  onShowMoreRuns,
  pending,
  runQuery,
  runs,
  scheduleAt,
  schedules,
  selectedRun,
  setCadence,
  setRunQuery,
  setScheduleAt,
  visibleRunCount,
  visibleRuns,
}) {
  return <>
    <details className="card editor-advanced">
      <summary>실행 및 예약 관리</summary>
      <section className="report-run-actual">
        <header><h3>실행 이력</h3><button onClick={onLoadRuns} disabled={Boolean(pending)}><RotateCcw size={13} />불러오기</button></header>
        <label className="report-search"><span>실행 검색</span><input value={runQuery} onChange={(event) => setRunQuery(event.target.value)} placeholder="상태·버전·오류 검색" /></label>
        {visibleRuns.length ? <ul>{visibleRuns.map((run) => <li key={run.runId}><button type="button" aria-pressed={selectedRun?.runId === run.runId} onClick={() => onSelectRun(run)}><b>{reportRunStatusLabel(run.status)}</b><span>버전 {run.definitionVersion} · 기준 {formatSeoulTime(run.asOf)}</span></button></li>)}</ul> : <p className="report-api-state"><Inbox size={17} />{runs.length ? "검색 조건에 맞는 실행이 없습니다." : "실행 이력이 없습니다."}</p>}
        {filteredRunCount > visibleRunCount && <button type="button" onClick={onShowMoreRuns}>실행 더 보기</button>}
        {selectedRun && <article className="report-run-detail"><header><div><b>{reportRunStatusLabel(selectedRun.status)}</b><span>버전 {selectedRun.definitionVersion} · 데이터 기준 {formatSeoulTime(selectedRun.asOf)}</span></div>{["failed", "partial"].includes(selectedRun.status) && <button type="button" onClick={onRetryRun} disabled={Boolean(pending)}><RotateCcw size={13} />최신 데이터로 다시 생성</button>}</header><ul>{selectedRun.blocks.map((block) => <li key={block.blockId}><div><b>{reportRunStatusLabel(block.status)}</b><span>{reportRunBlockMessage(block.status)}</span><details><summary>기술 정보</summary>{block.failureCode && <code>오류 코드 {block.failureCode}</code>}<code>Artifact {block.artifactId || "없음"}</code><code>Query {block.queryId || "없음"}</code></details></div></li>)}</ul></article>}
      </section>
      <section className="report-schedule-actual">
        <header><div><h3>예약 실행</h3><small>입력값은 브라우저 위치와 관계없이 서울 현지 시각으로 저장합니다.</small></div></header>
        <div className="report-schedule-form"><label>주기<select value={cadence} onChange={(event) => setCadence(event.target.value)} disabled={Boolean(pending)}><option value="daily">매일</option><option value="weekly">매주</option><option value="monthly">매월</option></select></label><label>다음 실행 시각 (서울)<input type="datetime-local" value={scheduleAt} onChange={(event) => setScheduleAt(event.target.value)} disabled={Boolean(pending)} /></label><button className="primary" onClick={onCreateSchedule} disabled={Boolean(pending) || !scheduleAt}><Clock3 size={14} />예약 생성</button></div>
        <div className="report-schedule-list">{schedules.map((schedule) => <article key={schedule.schedule_id}><div><b>{schedule.cadence === "daily" ? "매일" : schedule.cadence === "weekly" ? "매주" : "매월"} · {schedule.enabled ? "실행 중" : "중지됨"}</b><small>다음 실행 {formatSeoulTime(schedule.next_run_at)}</small></div><button disabled={Boolean(pending)} onClick={() => onSetScheduleEnabled(schedule.schedule_id, !schedule.enabled)}>{schedule.enabled ? "중지" : "재개"}</button></article>)}</div>
      </section>
    </details>
    {assistantTrace && <details className="card editor-advanced"><summary>초안 생성 정보</summary><p>생성 완료 · {(assistantTrace.duration_ms / 1000).toFixed(1)}초</p></details>}
  </>;
});
