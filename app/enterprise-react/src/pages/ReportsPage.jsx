import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CalendarClock, Check, Clock3, FilePlus2, Inbox, Info, LoaderCircle, RotateCcw, Save, ShieldAlert } from "lucide-react";
import { createReportClient, ReportApiError } from "../api/reportClient";
import { toReportBlockRequest } from "../contracts/report";
import { createUuid } from "../utils/createUuid";

function apiError(error) {
  if (error instanceof ReportApiError && error.status === 401) return `401 · 로그인이 필요합니다. ${error.message}`;
  if (error instanceof ReportApiError && error.status === 403) return `403 · Report 사용 권한이 필요합니다. ${error.message}`;
  return error instanceof ReportApiError ? `${error.status} · ${error.code} · ${error.message}`
    : error instanceof Error ? error.message : "Report API 요청에 실패했습니다.";
}

export function ReportsPage() {
  const client = useMemo(() => createReportClient(), []);
  const [definitions, setDefinitions] = useState([]);
  const [definitionState, setDefinitionState] = useState("loading");
  const [runs, setRuns] = useState([]);
  const [runState, setRunState] = useState("loading");
  const [selectedDefinition, setSelectedDefinition] = useState(null);
  const [apiBlocks, setApiBlocks] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [command, setCommand] = useState(null);
  const [schedules, setSchedules] = useState([]);
  const [scheduleState, setScheduleState] = useState("loading");
  const [scheduleMessage, setScheduleMessage] = useState("");
  const [scheduleForm, setScheduleForm] = useState({ frequency: "daily", hour: 9, minute: 0, weekday: 0, dayOfMonth: 1, enabled: false });
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");

  const upsertDefinition = (definition) => {
    setDefinitions((current) => {
      const remaining = current.filter((item) => !(item.definitionId === definition.definitionId && item.version === definition.version));
      return [...remaining, definition].sort((a, b) => a.definitionId.localeCompare(b.definitionId) || a.version - b.version);
    });
    setSelectedDefinition(definition);
    setApiBlocks(definition.blocks);
  };

  const loadDefinitions = async () => {
    setDefinitionState("loading");
    try {
      const items = await client.listDefinitions();
      setDefinitions(items);
      setDefinitionState(items.length ? "ready" : "empty");
    } catch (nextError) {
      setError(apiError(nextError));
      setDefinitionState("error");
    }
  };

  const loadRuns = async () => {
    setRunState("loading");
    try {
      const items = await client.listRuns();
      setRuns(items);
      setRunState(items.length ? "ready" : "empty");
    } catch (nextError) {
      setError(apiError(nextError));
      setRunState("error");
    }
  };

  const loadSchedules = async () => {
    setScheduleState("loading");
    try {
      const items = await client.listSchedules();
      setSchedules(items);
      setScheduleState(items.length ? "ready" : "empty");
    } catch (nextError) {
      setError(apiError(nextError));
      setScheduleState("error");
    }
  };

  useEffect(() => { void loadDefinitions(); void loadRuns(); void loadSchedules(); }, []);
  useEffect(() => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    const schedule = schedules.find((item) => item.definitionId === selectedDefinition.definitionId && item.version === selectedDefinition.version);
    setScheduleForm(schedule ? {
      frequency: schedule.frequency,
      hour: schedule.hour,
      minute: schedule.minute,
      weekday: schedule.weekday ?? 0,
      dayOfMonth: schedule.dayOfMonth ?? 1,
      enabled: schedule.enabled,
    } : { frequency: "daily", hour: 9, minute: 0, weekday: 0, dayOfMonth: 1, enabled: false });
  }, [schedules, selectedDefinition]);

  const mutate = async (name, action) => {
    setPending(name);
    setError("");
    try { return await action(); } catch (nextError) { setError(apiError(nextError)); return null; } finally { setPending(""); }
  };

  const createDefinition = async () => {
    const definition = await mutate("create", () => client.createDefinition({
      definition_id: createUuid(),
      title: "새 Report 정의",
      blocks: [{ block_id: createUuid(), title: "보고서 내용", columns: 12, type: "text", x: 0, y: 0, w: 12, h: 2, content: "" }],
    }));
    if (definition) { upsertDefinition(definition); setDefinitionState("ready"); }
  };

  const openDefinition = async (definition) => {
    setScheduleMessage("");
    const current = await mutate("definition", () => client.getDefinition(definition.definitionId, definition.version));
    if (current) upsertDefinition(current);
  };

  const saveDraft = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "draft") return;
    const saved = await mutate("save", () => client.replaceDraftBlocks(selectedDefinition.definitionId, selectedDefinition.version, apiBlocks.map(toReportBlockRequest)));
    if (saved) upsertDefinition(saved);
  };

  const approve = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "draft") return;
    const approved = await mutate("approve", () => client.approveDefinition(selectedDefinition.definitionId, selectedDefinition.version, new Date().toISOString()));
    if (approved) upsertDefinition(approved);
  };

  const createNextDraft = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    const draft = await mutate("draft", () => client.createNextDraft(selectedDefinition.definitionId, selectedDefinition.version));
    if (draft) upsertDefinition(draft);
  };

  const queueManualRun = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    const receipt = await mutate("manual", () => client.createManualRun({ definition_id: selectedDefinition.definitionId, version: selectedDefinition.version, as_of: new Date().toISOString(), idempotency_key: createUuid() }));
    if (receipt) setCommand(receipt);
  };

  const openRun = async (run) => {
    const detail = await mutate("run", () => client.getRun(run.runId));
    if (detail) setSelectedRun(detail);
  };

  const saveSchedule = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    setScheduleMessage("");
    const saved = await mutate("schedule", () => client.upsertSchedule(selectedDefinition.definitionId, selectedDefinition.version, {
      frequency: scheduleForm.frequency,
      hour: Number(scheduleForm.hour),
      minute: Number(scheduleForm.minute),
      ...(scheduleForm.frequency === "weekly" ? { weekday: Number(scheduleForm.weekday) } : {}),
      ...(scheduleForm.frequency === "monthly" ? { day_of_month: Number(scheduleForm.dayOfMonth) } : {}),
      enabled: scheduleForm.enabled,
    }));
    if (!saved) return;
    setSchedules((current) => [...current.filter((item) => item.scheduleId !== saved.scheduleId), saved]);
    setScheduleState("ready");
    setScheduleMessage(saved.enabled ? "스케줄을 활성화했습니다." : "스케줄을 비활성 상태로 저장했습니다.");
  };

  return <div className="page-content report-api-page">
    <div className="meta-strip"><Info size={13} />REPORT API<span>owner scope</span></div>
    <header className="card report-api-header"><div><p>REPORT API</p><h2>서버 Report 정의와 실행 이력</h2><small>Report API 응답 상태만 표시합니다.</small></div><div><button onClick={() => void loadDefinitions()} disabled={definitionState === "loading"}><RotateCcw size={14} />정의 새로고침</button><button className="primary" onClick={() => void createDefinition()} disabled={Boolean(pending)}><FilePlus2 size={14} />초안 생성</button></div></header>
    {error && <p className="report-api-state error" role="alert" aria-live="assertive">{/^40[13]/.test(error) ? <ShieldAlert size={17} /> : <AlertTriangle size={17} />}{error}</p>}
    <section className="report-api-grid">
      <article className="card report-api-panel"><header><h3>정의·버전</h3><small>서버가 반환한 title·version·status</small></header>
        {definitionState === "loading" && <p className="report-api-state" role="status" aria-live="polite"><LoaderCircle size={17} />Report 정의를 불러오는 중입니다.</p>}
        {definitionState === "error" && <p className="report-api-state error" role="alert"><ShieldAlert size={17} />Report 정의를 불러오지 못했습니다.</p>}
        {definitionState === "empty" && <p className="report-api-state"><Inbox size={17} />서버에 표시할 Report 정의가 없습니다.</p>}
        {definitionState === "ready" && <div className="report-api-list">{definitions.map((definition) => <button aria-pressed={selectedDefinition?.definitionId === definition.definitionId && selectedDefinition?.version === definition.version} onClick={() => void openDefinition(definition)} key={`${definition.definitionId}-${definition.version}`}><span><b>{definition.title}</b><small>{definition.definitionId}</small></span><em>v{definition.version} · {definition.status}</em></button>)}</div>}
      </article>
      <article className="card report-api-panel"><header><h3>실행 이력</h3><button onClick={() => void loadRuns()} disabled={runState === "loading"}><RotateCcw size={13} />새로고침</button></header>
        {runState === "loading" && <p className="report-api-state" role="status" aria-live="polite"><LoaderCircle size={17} />Run History를 불러오는 중입니다.</p>}
        {runState === "error" && <p className="report-api-state error" role="alert"><AlertTriangle size={17} />Run History를 불러오지 못했습니다.</p>}
        {runState === "empty" && <p className="report-api-state"><Inbox size={17} />서버에 생성된 Report run이 없습니다.</p>}
        {runState === "ready" && <div className="report-api-list">{runs.map((run) => <button aria-pressed={selectedRun?.runId === run.runId} onClick={() => void openRun(run)} key={run.runId}><span><b>{run.status}</b><small>{run.runId}</small></span><em>definition v{run.definitionVersion}</em></button>)}</div>}
      </article>
    </section>
    {selectedDefinition && <section className="card report-api-editor" aria-live="polite"><header><div><small>{selectedDefinition.definitionId}</small><h3>{selectedDefinition.title} · v{selectedDefinition.version}</h3><p>{selectedDefinition.status}{selectedDefinition.approvedAt ? ` · ${selectedDefinition.approvedAt}` : ""}</p></div><div>{selectedDefinition.status === "draft" ? <><button onClick={() => void saveDraft()} disabled={Boolean(pending)}><Save size={14} />초안 저장</button><button className="primary" onClick={() => void approve()} disabled={Boolean(pending)}><Check size={14} />명시적 승인</button></> : <><button onClick={() => void createNextDraft()} disabled={Boolean(pending)}><FilePlus2 size={14} />다음 초안</button><button className="primary" onClick={() => void queueManualRun()} disabled={Boolean(pending)}><Clock3 size={14} />수동 실행 요청</button></>}</div></header>
      <div className="report-api-blocks">{apiBlocks.map((block) => <article key={block.id}><header><b>{block.title}</b><small>{block.type} · x{block.x + 1} y{block.y + 1} · {block.w}×{block.h}</small></header>{block.type === "text" ? <textarea aria-label={`${block.title} 내용`} disabled={selectedDefinition.status !== "draft"} value={block.content || ""} onChange={(event) => setApiBlocks((current) => current.map((item) => item.id === block.id ? { ...item, content: event.target.value } : item))} /> : <p>Artifact {block.artifactId}<br />Query {block.queryId || "—"}</p>}</article>)}</div>
      {selectedDefinition.status === "approved" && <section className="report-schedule-editor"><header><CalendarClock size={18} /><div><b>예약 실행</b><small>{scheduleState === "loading" ? "스케줄 조회 중" : "Asia/Seoul 기준"}</small></div></header><div className="report-schedule-fields"><label>주기<select value={scheduleForm.frequency} onChange={(event) => setScheduleForm((current) => ({ ...current, frequency: event.target.value }))}><option value="daily">매일</option><option value="weekly">매주</option><option value="monthly">매월</option></select></label>{scheduleForm.frequency === "weekly" && <label>요일<select value={scheduleForm.weekday} onChange={(event) => setScheduleForm((current) => ({ ...current, weekday: Number(event.target.value) }))}>{["월", "화", "수", "목", "금", "토", "일"].map((label, index) => <option value={index} key={label}>{label}요일</option>)}</select></label>}{scheduleForm.frequency === "monthly" && <label>일<input type="number" min="1" max="31" value={scheduleForm.dayOfMonth} onChange={(event) => setScheduleForm((current) => ({ ...current, dayOfMonth: Number(event.target.value) }))} /></label>}<label>시<input type="number" min="0" max="23" value={scheduleForm.hour} onChange={(event) => setScheduleForm((current) => ({ ...current, hour: Number(event.target.value) }))} /></label><label>분<input type="number" min="0" max="59" value={scheduleForm.minute} onChange={(event) => setScheduleForm((current) => ({ ...current, minute: Number(event.target.value) }))} /></label><label className="report-schedule-toggle"><input type="checkbox" checked={scheduleForm.enabled} onChange={(event) => setScheduleForm((current) => ({ ...current, enabled: event.target.checked }))} />활성화</label><button className="primary" onClick={() => void saveSchedule()} disabled={Boolean(pending) || scheduleState === "loading"}><Save size={14} />스케줄 저장</button></div>{scheduleMessage && <p role="status" aria-live="polite">{scheduleMessage}</p>}{schedules.find((item) => item.definitionId === selectedDefinition.definitionId && item.version === selectedDefinition.version)?.nextRunAt && <p>다음 실행: {schedules.find((item) => item.definitionId === selectedDefinition.definitionId && item.version === selectedDefinition.version).nextRunAt}</p>}</section>}
    </section>}
    {command && <section className="card report-command-receipt" role="status" aria-live="polite"><Clock3 size={18} /><div><b>서버가 수동 실행 명령을 queued로 접수했습니다.</b><p>command {command.command_id}</p></div></section>}
    {selectedRun && <section className="card report-run-actual" aria-live="polite"><header><div><small>{selectedRun.runId}</small><h3>run · {selectedRun.status}</h3></div><span>definition v{selectedRun.definitionVersion}</span></header><p>as_of {selectedRun.asOf} · policy {selectedRun.policyVersion}</p><ul>{selectedRun.blocks.map((block) => <li key={block.blockId}><span>{block.blockId}</span><b>{block.status}</b></li>)}</ul></section>}
  </div>;
}
