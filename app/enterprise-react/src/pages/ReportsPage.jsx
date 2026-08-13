import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Clock3, FilePlus2, GripVertical, Inbox, Info, LoaderCircle, Plus, RotateCcw, Save, Send, ShieldAlert, Sparkles, Trash2 } from "lucide-react";
import { createReportClient, ReportApiError } from "../api/reportClient";
import { normalizeDraftLayout, reorderDraftBlocks, toReportBlockRequest } from "../contracts/report";
import { createUuid } from "../utils/createUuid";

function apiError(error) {
  if (error instanceof ReportApiError && error.status === 401) return `401 · 로그인이 필요합니다. ${error.message}`;
  if (error instanceof ReportApiError && error.status === 403) return `403 · 현재 역할에 허용되지 않은 작업입니다. ${error.message}`;
  return error instanceof Error ? error.message : "Report API 요청에 실패했습니다.";
}

function formatSeoulTime(value) {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short",
  }).format(new Date(value));
}

export function ReportsPage({ authToken, role }) {
  const client = useMemo(() => createReportClient(undefined, fetch, authToken), [authToken]);
  const isAdmin = role === "report_admin";
  const [definitions, setDefinitions] = useState([]);
  const [definitionState, setDefinitionState] = useState("loading");
  const [selectedDefinition, setSelectedDefinition] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [schedules, setSchedules] = useState([]);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [definitionQuery, setDefinitionQuery] = useState("");
  const [definitionFilter, setDefinitionFilter] = useState("all");
  const [cadence, setCadence] = useState("daily");
  const [scheduleAt, setScheduleAt] = useState("");
  const [assistantInstruction, setAssistantInstruction] = useState("");
  const [assistantTrace, setAssistantTrace] = useState(null);
  const [draggedBlockId, setDraggedBlockId] = useState("");
  const [dropTargetId, setDropTargetId] = useState("");

  const upsertDefinition = (definition) => {
    setDefinitions((current) => [definition, ...current.filter((item) => !(item.definitionId === definition.definitionId && item.version === definition.version))]);
    setSelectedDefinition(definition);
    setBlocks(definition.blocks);
  };
  const visibleDefinitions = useMemo(() => {
    const query = definitionQuery.trim().toLocaleLowerCase("ko-KR");
    return definitions.filter((definition) => (
      (definitionFilter === "all" || definition.status === definitionFilter)
      && (!query || definition.title.toLocaleLowerCase("ko-KR").includes(query) || definition.definitionId.toLowerCase().includes(query))
    ));
  }, [definitions, definitionFilter, definitionQuery]);
  const mutate = async (name, action) => {
    setPending(name); setError("");
    try { return await action(); } catch (nextError) { setError(apiError(nextError)); return null; } finally { setPending(""); }
  };
  const loadDefinitions = async () => {
    setDefinitionState("loading");
    const items = await mutate("definitions", () => client.listDefinitions());
    if (!items) return setDefinitionState("error");
    setDefinitions(items); setDefinitionState(items.length ? "ready" : "empty");
  };
  const loadSchedules = async () => { const items = await mutate("schedules", () => client.listSchedules()); if (items) setSchedules(items); };
  const refreshPage = async () => { await loadDefinitions(); if (isAdmin) await loadSchedules(); };
  useEffect(() => { void refreshPage(); }, [isAdmin]);

  const createDefinition = async (event) => {
    event.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) return;
    const definition = await mutate("create", () => client.createDefinition({ definition_id: createUuid(), title: newTitle.trim(), blocks: [{ block_id: createUuid(), title: newTitle.trim(), columns: 12, type: "text", x: 0, y: 0, w: 12, h: 2, content: newContent.trim() }] }));
    if (definition) { upsertDefinition(definition); setDefinitionState("ready"); setNewTitle(""); setNewContent(""); }
  };
  const openDefinition = async (definition) => { const current = await mutate("definition", () => client.getDefinition(definition.definitionId, definition.version)); if (current) upsertDefinition(current); };
  const saveDraft = async () => { if (!selectedDefinition || selectedDefinition.status !== "draft") return; const saved = await mutate("save", () => client.replaceDraftBlocks(selectedDefinition.definitionId, selectedDefinition.version, blocks.map(toReportBlockRequest))); if (saved) upsertDefinition(saved); };
  const approveDefinition = async () => { if (!selectedDefinition || selectedDefinition.status !== "draft") return; const approved = await mutate("approve", () => client.approveDefinition(selectedDefinition.definitionId, selectedDefinition.version, new Date().toISOString())); if (approved) upsertDefinition(approved); };
  const runDefinition = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    const receipt = await mutate("run", () => client.createManualRun({ definition_id: selectedDefinition.definitionId, version: selectedDefinition.version, as_of: new Date().toISOString(), idempotency_key: createUuid() }));
    if (!receipt?.run_id) return;
    const run = await mutate("run-detail", () => client.getRun(receipt.run_id));
    if (run) { setSelectedRun(run); setRuns((current) => [run, ...current.filter((item) => item.runId !== run.runId)]); }
  };
  const loadRuns = async () => { if (!selectedDefinition) return; const items = await mutate("runs", () => client.listRuns(selectedDefinition.definitionId)); if (items) { setRuns(items); setSelectedRun(items.at(-1) || null); } };
  const createSchedule = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved" || !scheduleAt) return;
    const schedule = await mutate("schedule-create", () => client.createSchedule({ schedule_id: createUuid(), definition_id: selectedDefinition.definitionId, version: selectedDefinition.version, cadence, next_run_at: new Date(scheduleAt).toISOString(), timezone: "Asia/Seoul" }));
    if (schedule) setSchedules((current) => [...current, schedule]);
  };
  const setScheduleEnabled = async (scheduleId, enabled) => {
    const schedule = await mutate("schedule-update", () => client.setScheduleEnabled(scheduleId, enabled));
    if (schedule) setSchedules((current) => current.map((item) => item.schedule_id === scheduleId ? schedule : item));
  };
  const createAssistantDraft = async () => {
    const artifact = selectedDefinition?.blocks.find((block) => block.artifactId);
    if (!artifact || !assistantInstruction.trim()) return;
    const result = await mutate("assistant", () => client.createAssistantDraft(artifact.artifactId, assistantInstruction.trim()));
    if (!result) return;
    upsertDefinition(result.definition); setDefinitionState("ready"); setAssistantTrace({ requestId: result.requestId, ...result.trace }); setAssistantInstruction("");
  };
  const isDraft = selectedDefinition?.status === "draft";
  const updateBlock = (blockId, change) => setBlocks((current) => current.map((block) => block.id === blockId ? { ...block, ...change } : block));
  const resizeBlock = (blockId, width) => setBlocks((current) => normalizeDraftLayout(current.map((block) => block.id === blockId ? { ...block, columns: width, w: width } : block)));
  const moveBlock = (blockId, offset) => setBlocks((current) => {
    const index = current.findIndex((block) => block.id === blockId);
    const target = current[index + offset];
    return target ? reorderDraftBlocks(current, blockId, target.id) : current;
  });
  const addTextBlock = () => setBlocks((current) => normalizeDraftLayout([...current, {
    id: createUuid(), title: "새 텍스트", columns: 12, type: "text", content: "", w: 12, h: 2,
  }]));
  const dropBlock = (targetId, sourceId = draggedBlockId) => {
    if (sourceId) setBlocks((current) => reorderDraftBlocks(current, sourceId, targetId));
    setDraggedBlockId(""); setDropTargetId("");
  };
  const selectedSchedules = selectedDefinition ? schedules.filter((item) => item.definition_id === selectedDefinition.definitionId && item.version === selectedDefinition.version) : [];

  return <div className="page-content report-api-page">
    <div className="meta-strip"><Info size={13} />ACTUAL REPORT API<span>{isAdmin ? "REPORT_ADMIN scope" : "REPORT_DRAFT scope"}</span></div>
    <header className="card report-api-header"><div><p>REPORT API</p><h2>{isAdmin ? "Report 정의와 실행" : "Report 초안"}</h2><small>{isAdmin ? "정의, 승인, 실행과 예약을 관리합니다." : "분석 결과를 바탕으로 초안을 작성하고 저장합니다."}</small></div><button onClick={() => void refreshPage()} disabled={Boolean(pending)}><RotateCcw size={14} />새로고침</button></header>
    {error && <p className="report-api-state error" role="alert">{/^40[13]/.test(error) ? <ShieldAlert size={17} /> : <AlertTriangle size={17} />}{error}</p>}
    <form className="card report-create-form" onSubmit={createDefinition}><h3>새 초안</h3><label>제목<input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} required /></label><label>초기 내용<textarea value={newContent} onChange={(event) => setNewContent(event.target.value)} required /></label><button className="primary" disabled={Boolean(pending)}><FilePlus2 size={14} />초안 생성</button></form>
    <section className="report-api-grid"><article className="card report-api-panel"><header><div><h3>정의 · 버전</h3><small>{visibleDefinitions.length} / {definitions.length}건</small></div><small>서버 저장값</small></header><div className="report-definition-toolbar"><label>Report 검색<input aria-label="Report 검색" value={definitionQuery} onChange={(event) => setDefinitionQuery(event.target.value)} placeholder="제목 또는 ID" /></label><label>상태<select aria-label="상태 필터" value={definitionFilter} onChange={(event) => setDefinitionFilter(event.target.value)}><option value="all">전체</option><option value="draft">초안</option><option value="approved">승인됨</option></select></label></div>{definitionState === "loading" && <p className="report-api-state"><LoaderCircle size={17} />불러오는 중</p>}{definitionState === "empty" && <p className="report-api-state"><Inbox size={17} />저장된 Report가 없습니다.</p>}{definitionState === "error" && <p className="report-api-state error"><ShieldAlert size={17} />목록을 불러오지 못했습니다.</p>}{definitionState === "ready" && (visibleDefinitions.length ? <div className="report-api-list">{visibleDefinitions.map((definition) => <button aria-pressed={selectedDefinition?.definitionId === definition.definitionId && selectedDefinition?.version === definition.version} onClick={() => void openDefinition(definition)} key={`${definition.definitionId}-${definition.version}`}><span><b>{definition.title}</b><small>{definition.definitionId}</small></span><em>v{definition.version} · {definition.status}</em></button>)}</div> : <p className="report-api-state"><Inbox size={17} />조건에 맞는 Report가 없습니다.</p>)}</article></section>
    {selectedDefinition && <section className="card report-api-editor">
      <header>
        <div><small>{selectedDefinition.definitionId}</small><h3>{selectedDefinition.title} · v{selectedDefinition.version}</h3><p>{selectedDefinition.status}{selectedDefinition.approvedAt ? ` · ${selectedDefinition.approvedAt}` : ""}</p></div>
        <div>{isDraft ? <><button onClick={addTextBlock} disabled={Boolean(pending)}><Plus size={14} />텍스트 블록</button><button onClick={() => void saveDraft()} disabled={Boolean(pending)}><Save size={14} />배치 저장</button>{isAdmin && <button className="primary" onClick={() => void approveDefinition()} disabled={Boolean(pending)}><Check size={14} />승인</button>}</> : isAdmin ? <><button className="primary" onClick={() => void runDefinition()} disabled={Boolean(pending)}><Send size={14} />수동 실행</button><button onClick={() => void loadRuns()} disabled={Boolean(pending)}><RotateCcw size={14} />실행 이력</button></> : null}</div>
      </header>
      {isDraft && <p className="report-layout-help"><GripVertical size={15} />핸들을 끌어 순서를 바꾸거나 화살표로 이동하세요. 변경사항은 ‘배치 저장’ 후 서버에 반영됩니다.</p>}
      <div className="report-api-blocks">{blocks.map((block, index) => <article
        className={`${draggedBlockId === block.id ? "is-dragging" : ""} ${dropTargetId === block.id ? "is-drop-target" : ""}`.trim()}
        key={block.id}
        style={{ gridColumn: `${(block.x ?? 0) + 1} / span ${block.w ?? block.columns}`, minHeight: `${Math.max(1, block.h ?? 1) * 48}px` }}
        onDragOver={(event) => { if (isDraft && draggedBlockId) { event.preventDefault(); event.dataTransfer.dropEffect = "move"; } }}
        onDragEnter={() => { if (isDraft && draggedBlockId !== block.id) setDropTargetId(block.id); }}
        onDrop={(event) => { event.preventDefault(); dropBlock(block.id, event.dataTransfer.getData("text/plain")); }}
      >
        <header>
          <div className="report-block-title">{isDraft && <button
            type="button"
            className="report-drag-handle"
            draggable
            aria-label={`${block.title} 블록 드래그`}
            title="드래그하여 이동"
            onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", block.id); setDraggedBlockId(block.id); }}
            onDragEnd={() => { setDraggedBlockId(""); setDropTargetId(""); }}
          ><GripVertical size={16} /></button>}{isDraft ? <input aria-label={`${block.title} 제목`} value={block.title} onChange={(event) => updateBlock(block.id, { title: event.target.value })} /> : <b>{block.title}</b>}</div>
          <div className="report-block-controls"><small>{block.type} · x{(block.x ?? 0) + 1} y{(block.y ?? 0) + 1} · {block.w ?? block.columns}×{block.h ?? 1}</small>{isDraft && <>
            <label>너비<input aria-label={`${block.title} 너비`} type="number" min="1" max="12" value={block.w ?? block.columns} onChange={(event) => resizeBlock(block.id, Number(event.target.value))} /></label>
            <button type="button" aria-label={`${block.title} 앞으로 이동`} onClick={() => moveBlock(block.id, -1)} disabled={index === 0}><ChevronLeft size={14} /></button>
            <button type="button" aria-label={`${block.title} 뒤로 이동`} onClick={() => moveBlock(block.id, 1)} disabled={index === blocks.length - 1}><ChevronRight size={14} /></button>
            <button type="button" className="danger" aria-label={`${block.title} 삭제`} onClick={() => setBlocks((current) => normalizeDraftLayout(current.filter((item) => item.id !== block.id)))} disabled={blocks.length === 1}><Trash2 size={14} /></button>
          </>}</div>
        </header>
        {block.type === "text" ? <textarea aria-label={`${block.title} 내용`} disabled={!isDraft} placeholder="보고서 내용을 입력하세요." value={block.content || ""} onChange={(event) => updateBlock(block.id, { content: event.target.value })} /> : <p>Artifact {block.artifactId}<br />Query {block.queryId || "없음"}</p>}
      </article>)}</div>
    </section>}
    {isAdmin && selectedDefinition?.status === "approved" && <section className="card report-run-actual"><h3>실행 이력</h3>{selectedRun ? <><p><b>{selectedRun.status}</b> · {selectedRun.runId}<br />as_of {selectedRun.asOf} · policy {selectedRun.policyVersion}</p><ul>{selectedRun.blocks.map((block) => <li key={block.blockId}><span>{block.blockId}<small>{block.queryId || "없음"}</small></span><b>{block.status}</b></li>)}</ul></> : <p className="report-api-state"><Inbox size={17} />실행 이력을 선택해 주세요.</p>}</section>}
    {isAdmin && selectedDefinition?.status === "approved" && <section className="card report-schedule-actual"><header><div><h3>예약 실행</h3><small>서버가 Asia/Seoul 기준으로 자동 실행합니다.</small></div></header><div className="report-schedule-form"><label>주기<select value={cadence} onChange={(event) => setCadence(event.target.value)}><option value="daily">매일</option><option value="weekly">매주</option><option value="monthly">매월</option></select></label><label>다음 실행 시각<input type="datetime-local" value={scheduleAt} onChange={(event) => setScheduleAt(event.target.value)} required /></label><button className="primary" onClick={() => void createSchedule()} disabled={Boolean(pending) || !scheduleAt}><Clock3 size={14} />예약 생성</button></div><div className="report-schedule-list">{selectedSchedules.length ? selectedSchedules.map((schedule) => <article key={schedule.schedule_id}><div><b>{schedule.cadence} · {schedule.enabled ? "실행 중" : "중지됨"}</b><small>다음 실행 {formatSeoulTime(schedule.next_run_at)}</small>{schedule.last_run_id && <em>최근 Run {schedule.last_run_id}</em>}</div><button onClick={() => void setScheduleEnabled(schedule.schedule_id, !schedule.enabled)} disabled={Boolean(pending)}>{schedule.enabled ? "중지" : "재개"}</button></article>) : <p className="report-api-state"><Inbox size={17} />등록된 예약이 없습니다.</p>}</div></section>}
    {isAdmin && selectedDefinition?.status === "approved" && selectedDefinition.blocks.some((block) => block.artifactId) && <section className="card report-assistant-actual"><header><div><h3>Report Assistant</h3><small>승인된 Artifact 근거 사용</small></div></header><label>초안 지시<textarea value={assistantInstruction} onChange={(event) => setAssistantInstruction(event.target.value)} maxLength={500} required /></label><button className="primary" onClick={() => void createAssistantDraft()} disabled={Boolean(pending) || !assistantInstruction.trim()}><Sparkles size={14} />Assistant 초안 생성</button></section>}
    {assistantTrace && <section className="card report-assistant-trace"><h3>Assistant 생성 완료</h3><p><b>{assistantTrace.prompt_id}@{assistantTrace.prompt_version}</b><br />request {assistantTrace.requestId} · {assistantTrace.model_version} · {assistantTrace.duration_ms}ms</p></section>}
  </div>;
}
