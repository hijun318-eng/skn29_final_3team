import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowLeft, Ban, BarChart3, Check, ChevronRight, CircleCheck,
  CircleX, Clock3, Columns2, Download, FileOutput, FilePlus2, GripVertical,
  Inbox, Info, LoaderCircle, Minus, Quote, RotateCcw, Save, Send, Share2,
  ShieldAlert, Sparkles, Table2, Target, Trash2, Type,
} from "lucide-react";
import { SYNTHETIC_META } from "../data/enterpriseDemoData";
import { normalizeDraftLayout, serializeDraftLayout } from "../contracts/report";

const REPORTS = [
  { id: 1, type: "주간", period: "07/21~07/27", status: "초안", author: "박준희", updated: "10분 전 수정" },
  { id: 2, type: "주간", period: "07/14~07/20", status: "확정", author: "박준희", updated: "07.21 확정" },
  { id: 3, type: "주간", period: "07/07~07/13", status: "확정", author: "박준희", updated: "07.14 확정" },
  { id: 4, type: "월간", period: "2026년 06월", status: "확정", author: "박준희", updated: "07.03 확정" },
  { id: 5, type: "분기", period: "2026 Q2", status: "확정", author: "CX 운영팀", updated: "07.05 확정" },
];

const RUN_HISTORY = [
  { id: "run-queued", status: "queued", label: "대기", icon: Clock3, summary: "실행 순서를 기다리는 fixture입니다.", blocks: [["객실 매출", "대기"], ["회원 분석", "대기"]] },
  { id: "run-running", status: "running", label: "실행 중", icon: LoaderCircle, summary: "로컬 상태 전환을 확인하는 fixture입니다.", blocks: [["객실 매출", "완료"], ["회원 분석", "실행 중"]] },
  { id: "run-success", status: "success", label: "성공", icon: CircleCheck, summary: "모든 블록이 성공한 표시 예시이며 실제 실행 결과가 아닙니다.", blocks: [["객실 매출", "성공"], ["회원 분석", "성공"]] },
  { id: "run-partial", status: "partial", label: "부분 성공", icon: AlertTriangle, summary: "성공·부분 성공·실패 블록을 함께 표시합니다.", blocks: [["객실 매출", "성공"], ["회원 분석", "부분 성공"], ["연회 분석", "실패"]] },
  { id: "run-failed", status: "failed", label: "실패", icon: CircleX, summary: "오류 원인을 표시하되 정상 결과로 승격하지 않습니다.", blocks: [["객실 매출", "실패"], ["회원 분석", "취소"]] },
  { id: "run-cancelled", status: "cancelled", label: "취소", icon: Ban, summary: "취소된 fixture이며 보고서 결과를 만들지 않습니다.", blocks: [["객실 매출", "취소"], ["회원 분석", "취소"]] },
];

const VIEW_STATE_EXAMPLES = [
  { id: "role", label: "권한 차단", icon: ShieldAlert, text: "REPORT_ADMIN 권한이 없는 사용자는 실행 정보를 볼 수 없습니다." },
  { id: "loading", label: "로딩", icon: LoaderCircle, text: "로컬 실행 이력을 불러오는 중입니다." },
  { id: "empty", label: "비어 있음", icon: Inbox, text: "표시할 실행 이력이 없습니다." },
  { id: "error", label: "오류", icon: AlertTriangle, text: "실행 이력을 불러오지 못했습니다. 오류 코드를 확인하세요." },
];

const DECISIONS = [
  { id: 1, priority: "우선 검토", title: "객실 매출 Artifact를 주간 보고서 정의에 연결", reason: "검증된 분석 결과를 다시 계산하지 않고 질문·기간·출처와 함께 재사용합니다.", impact: "동일 근거로 보고서 재현", condition: "추가 원천 조회 없음", evidence: "artifact 7d5f23db · query fixture-query-success", owner: "보고서 관리자" },
  { id: 2, priority: "기준 확인", title: "보고서 기준 시각을 2026-07-30으로 고정", reason: "PMS·CRM·Banquet 결과의 기준 시각을 맞춰 이후 실행과 비교 가능한 상태로 보존합니다.", impact: "시점 혼용 방지", condition: "Asia/Seoul · schema 1.0.0", evidence: "synthetic seed 20260729", owner: "데이터 관리자" },
  { id: 3, priority: "정책 검토", title: "부분 실패 시 블록별 상태 표시 유지", reason: "일부 원천이 실패해도 성공 블록과 실패 블록을 구분하고 마지막 성공값 사용 여부를 명시해야 합니다.", impact: "누락을 정상 결과로 오인 방지", condition: "자동 성공 승격 금지", evidence: "SUCCESS · PARTIAL_SUCCESS · FAILED 계약", owner: "보고서 관리자" },
];

const RESPONSE_OPTIONS = [
  { id: "artifact", label: "검증 Artifact", description: "원 질문과 실행 결과를 보고서에 연결", detail: "artifact 7d5f23db" },
  { id: "pms", label: "PMS reservations", description: "객실 예약·매출 근거 원천", detail: "DataHub URN · Trino FQN" },
  { id: "crm", label: "CRM membership", description: "회원 이력 근거 원천", detail: "DataHub URN · Trino FQN" },
  { id: "banquet", label: "Banquet bookings", description: "연회 일정·연계 객실 근거 원천", detail: "DataHub URN · Trino FQN" },
  { id: "asof", label: "기준 시각 고정", description: "실행 결과를 같은 시점 기준으로 비교", detail: "2026-07-30 · Asia/Seoul" },
];

const PERFORMANCE = [
  ["인식 객실 매출", "128,400,000 KRW", "2026년 7월", "PMS reservations", "검증됨", "positive"],
  ["객실 점유율", "72.5%", "2026-07-30", "PMS reservations", "검증됨", "positive"],
  ["직접 예약 비중", "43.5% → 38.2%", "07/28~07/30", "CRM membership", "관측됨", "warning"],
  ["연회 일정 변경", "2건 · 객실 62박", "07/29~07/30", "Banquet bookings", "관측됨", "warning"],
  ["원천 상태", "3 / 3 성공", "동일 as_of", "PMS · CRM · Banquet", "완전", "positive"],
  ["데이터 계약", "schema 1.0.0", "seed 20260729", "synthetic", "고정", "neutral"],
];

const ACTIONS = [
  ["검증 Artifact 연결", "분석 관리자", "artifact 7d5f23db", "완료", "정의 검토"],
  ["보고서 정의 초안", "보고서 관리자", "DRAFT", "검토 중", "승인 여부 결정"],
  ["수동 실행", "보고서 관리자", "승인된 정의", "대기", "결과 확인"],
  ["스케줄 활성화", "보고서 관리자", "수동 실행 안정화 후", "비활성", "별도 승인"],
];

const SOURCE_TRACE = [
  ["PMS reservations", "PostgreSQL", "객실 매출·점유율", "성공", "DataHub URN · Trino FQN"],
  ["CRM membership history", "SQL Server", "회원 이력", "성공", "DataHub URN · Trino FQN"],
  ["Banquet bookings", "PostgreSQL", "연회 일정·연계 객실", "성공", "DataHub URN · Trino FQN"],
];

const BLOCK_CATALOG = [
  { key: "executive-summary", group: "분석 요약", title: "검증 결과 요약", description: "Artifact 기반 핵심 지표와 해석", type: "summary", span: 2, content: "7월 28~30일 객실 매출은 45.2백만원에서 40.1백만원으로 낮아졌습니다. 같은 기간 직접 예약 비중 감소와 기업 연회 2건의 일정 변경, 연계 객실 62박 취소가 함께 관측됐으며 인과관계로 단정하지 않습니다." },
  { key: "decisions", group: "보고서 검토", title: "결정 필요 안건", description: "정의·기준 시각·부분 실패 정책 검토", type: "text", span: 2, content: "1. 검증 Artifact를 주간 보고서 정의에 연결\n2. 기준 시각을 2026-07-30으로 고정\n3. 부분 실패 시 블록별 상태 표시" },
  { key: "response-review", group: "근거 검토", title: "분석 근거와 실행 조건", description: "원천·기간·필터·as_of 확인", type: "text", span: 2, content: "원천: PMS reservations, CRM membership history, Banquet bookings\n기준 시각: 2026-07-30 Asia/Seoul\n결과는 synthetic fixture이며 관리자 검토 후 실행합니다." },
  { key: "performance", group: "분석 결과", title: "검증된 핵심 지표", description: "객실·예약·연회 통합 지표", type: "chart", span: 1, values: [45.2, 40.1, 43.5, 38.2, 62], caption: "객실 매출 시작·종료(백만원) · 직접 예약 시작·종료(%) · 연계 객실 취소(박)" },
  { key: "issues", group: "해석", title: "결과 해석과 한계", description: "관측 사실과 해석 경계", type: "text", span: 1, content: "관측: 객실 매출·점유율·직접 예약 비중 감소와 연회 2건 일정 변경이 같은 기간 나타남\n연계: 연회 일정 변경과 연결된 객실 62박 취소\n한계: 인과·미래 추정 결과가 아님" },
  { key: "source-trace", group: "근거 추적", title: "데이터 출처 추적", description: "PMS·CRM·Banquet 원천과 실행 식별자", type: "text", span: 2, content: "PMS reservations · PostgreSQL · 성공\nCRM membership history · SQL Server · 성공\nBanquet bookings · PostgreSQL · 성공\nquery fixture-query-success" },
  { key: "action-tracker", group: "실행 관리", title: "보고서 실행 단계", description: "정의·승인·수동 실행·스케줄", type: "text", span: 2, content: "Artifact 연결 · 완료\n보고서 정의 초안 · 검토 중\n수동 실행 · 대기\n스케줄 · 비활성" },
  { key: "run-status", group: "실행 상태", title: "실행 상태 처리", description: "SUCCESS·PARTIAL_SUCCESS·FAILED", type: "text", span: 2, content: "SUCCESS: 모든 블록 표시\nPARTIAL_SUCCESS: 실패 블록 분리\nFAILED: 결과 승격 금지" },
];

const BASIC_BLOCKS = {
  heading: { type: "heading", title: "새 제목", content: "보고서 제목을 입력하세요.", span: 2 },
  text: { type: "text", title: "새 텍스트", content: "클릭해 내용을 입력하세요.", span: 2 },
  quote: { type: "quote", title: "인용", content: "강조할 분석 해석과 근거를 입력하세요.", span: 1 },
  kpi: { type: "kpi", title: "KPI 카드", content: "객실 매출 45.2→40.1백만원 · 직접 예약 43.5→38.2% · 연계 객실 취소 62박", span: 1 },
  table: { type: "table", title: "데이터 표", content: "항목 | 변화 | 근거\n객실 매출 | 45.2→40.1백만원 | PMS\n직접 예약 | 43.5→38.2% | CRM\n연회 변경 | 2건·62박 | Banquet", span: 2 },
  divider: { type: "divider", title: "구분선", content: "", span: 2 },
};

const toLayoutBlock = (block) => ({
  ...block,
  columns: block.w ?? (block.span ?? 2) * 6,
  w: block.w ?? (block.span ?? 2) * 6,
  h: block.h ?? 4,
});

const INITIAL_BLOCKS = normalizeDraftLayout(
  BLOCK_CATALOG.slice(0, 5).map((block, index) => toLayoutBlock({ ...block, id: `${block.key}-${index}` })),
);

function initialEditorBlocks() {
  try {
    const candidate = JSON.parse(window.sessionStorage.getItem("answervice.report.artifact"));
    if (!candidate?.artifactId) return INITIAL_BLOCKS;
    return normalizeDraftLayout([{
      id: `artifact-${candidate.artifactId}`,
      key: "chat-artifact",
      type: "text",
      title: candidate.question || "Chat Artifact",
      content: `Artifact ${candidate.artifactId}\nQuery ${candidate.queryId || "—"}\nSources ${(candidate.sourceUrns || []).join(", ") || "—"}`,
      artifactId: candidate.artifactId,
      columns: 12,
      w: 12,
      h: 4,
    }, ...INITIAL_BLOCKS]);
  } catch {
    return INITIAL_BLOCKS;
  }
}

function savedEditorBlocks(reportId) {
  try {
    const saved = JSON.parse(window.localStorage.getItem(`answervice.report.blocks.${reportId}`));
    return saved ? normalizeDraftLayout(saved.map(toLayoutBlock)) : initialEditorBlocks();
  } catch {
    return initialEditorBlocks();
  }
}

function savedReports() {
  try {
    return JSON.parse(window.localStorage.getItem("answervice.reports")) || REPORTS;
  } catch {
    return REPORTS;
  }
}

function Toast({ message }) {
  return message ? <div className="enterprise-toast" role="status" aria-live="polite"><Check size={14} />{message}</div> : null;
}

function RunHistoryFixture() {
  const [selectedRunId, setSelectedRunId] = useState(null);
  const detailRef = useRef(null);
  const selectedRun = RUN_HISTORY.find((run) => run.id === selectedRunId);
  const SelectedIcon = selectedRun?.icon;
  const selectRun = (runId) => {
    setSelectedRunId(runId);
    window.requestAnimationFrame(() => detailRef.current?.focus());
  };

  useEffect(() => {
    if (selectedRun) detailRef.current?.focus();
  }, [selectedRun]);

  return <section className="card report-run-fixture" aria-labelledby="run-history-title">
    <header><div><span className="fixture-badge">LOCAL SYNTHETIC FIXTURE</span><h2 id="run-history-title">Run History 상태·접근성 점검</h2><p>아래 항목은 실제 API·스케줄·승인·공유·내보내기 결과가 아닌 화면 검증용 데이터입니다.</p></div><button disabled><Ban size={14} />실제 실행 연결 대기</button></header>
    <div className="report-run-layout">
      <nav className="report-run-list" aria-label="fixture 실행 이력">{RUN_HISTORY.map((run) => {
        const Icon = run.icon;
        return <button type="button" aria-pressed={selectedRunId === run.id} aria-label={`${run.label} fixture 상세 보기`} onClick={() => selectRun(run.id)} key={run.id}><Icon size={17} aria-hidden="true" /><span><b>{run.label}</b><small>{run.status}</small></span><ChevronRight size={14} aria-hidden="true" /></button>;
      })}</nav>
      <section className="report-run-detail" ref={detailRef} tabIndex={-1} role="status" aria-live="polite" aria-atomic="true">
        {selectedRun ? <><header><SelectedIcon size={19} aria-hidden="true" /><div><small>{selectedRun.id}</small><h3>{selectedRun.label}</h3></div></header><p>{selectedRun.summary}</p><ul>{selectedRun.blocks.map(([name, status]) => <li key={name}><span>{name}</span><b>{status}</b></li>)}</ul><button disabled>{["queued", "running"].includes(selectedRun.status) ? "fixture 처리 중 · 조작 불가" : "실제 작업 연결 대기"}</button></> : <div className="report-run-placeholder"><Info size={20} aria-hidden="true" /><p>실행 상태를 선택하면 상세와 블록별 상태가 여기에 표시됩니다.</p></div>}
      </section>
    </div>
    <div className="report-view-states" aria-label="보안과 비동기 상태 예시">{VIEW_STATE_EXAMPLES.map((state) => { const Icon = state.icon; return <article key={state.id}><Icon size={18} aria-hidden="true" /><div><b>{state.label}</b><p>{state.text}</p></div></article>; })}</div>
  </section>;
}

function SectionHeading({ number, eyebrow, title, description, meta }) {
  return <header className="legacy-section-heading"><span>{number}</span><div><p>{eyebrow}</p><h2>{title}</h2>{description && <small>{description}</small>}</div>{meta && <b>{meta}</b>}</header>;
}

export function ReportsPage() {
  const [view, setView] = useState("list");
  const [reports, setReports] = useState(savedReports);
  const [reportSearch, setReportSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("전체");
  const [statusFilter, setStatusFilter] = useState("전체");
  const [selectedReport, setSelectedReport] = useState(REPORTS[0]);
  const [period, setPeriod] = useState("Weekly Report");
  const [decisions, setDecisions] = useState({});
  const [selectedOptions, setSelectedOptions] = useState(["artifact", "pms", "crm", "banquet", "asof"]);
  const [responseDecision, setResponseDecision] = useState("");
  const [memo, setMemo] = useState("");
  const [toast, setToast] = useState("");
  const [editorBlocks, setEditorBlocks] = useState(initialEditorBlocks);
  const [draggedBlockId, setDraggedBlockId] = useState(null);
  const [draggedLibraryItem, setDraggedLibraryItem] = useState(null);
  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 1800); };
  const filteredReports = reports.filter((report) => {
    const query = reportSearch.trim().toLowerCase();
    return (typeFilter === "전체" || report.type === typeFilter)
      && (statusFilter === "전체" || report.status === statusFilter)
      && (!query || [report.type, report.period, report.status, report.author].some((value) => value.toLowerCase().includes(query)));
  });
  const openReport = (report) => {
    setSelectedReport(report);
    if (report.status === "초안") setEditorBlocks(savedEditorBlocks(report.id));
    setView(report.status === "초안" ? "editor" : "document");
  };
  const createAutomatedReport = () => {
    const report = { id: Date.now(), type: "주간", period: "08/03~08/09", status: "초안", author: "송민지", updated: "방금 자동 생성" };
    const blocks = initialEditorBlocks();
    setReports((current) => [report, ...current]);
    setSelectedReport(report);
    setEditorBlocks(blocks);
    window.localStorage.setItem(`answervice.report.blocks.${report.id}`, serializeDraftLayout(blocks));
    setView("editor");
  };
  const saveReport = () => {
    if (selectedReport.status !== "초안") return;
    window.localStorage.setItem(`answervice.report.blocks.${selectedReport.id}`, serializeDraftLayout(editorBlocks));
    setReports((current) => current.map((report) => report.id === selectedReport.id ? { ...report, updated: "방금 저장" } : report));
    notify("보고서 초안을 저장했습니다.");
  };
  useEffect(() => {
    if (view === "editor" && selectedReport.status === "초안") {
      window.localStorage.setItem(`answervice.report.blocks.${selectedReport.id}`, serializeDraftLayout(editorBlocks));
    }
  }, [editorBlocks, selectedReport.id, selectedReport.status, view]);
  useEffect(() => {
    window.localStorage.setItem("answervice.reports", JSON.stringify(reports));
  }, [reports]);
  const createBlock = (item) => toLayoutBlock({ ...item, id: `${item.key || item.type}-${Date.now()}-${Math.random().toString(16).slice(2)}` });
  const addBlock = (item) => {
    const block = createBlock(item);
    setEditorBlocks((current) => normalizeDraftLayout([...current, block]));
    notify(`${block.title} 블록을 추가했습니다.`);
  };
  const dropLibraryItem = (targetId) => {
    if (!draggedLibraryItem) return false;
    const block = createBlock(draggedLibraryItem.kind === "catalog" ? draggedLibraryItem.value : BASIC_BLOCKS[draggedLibraryItem.value]);
    setEditorBlocks((current) => {
      if (!targetId) return normalizeDraftLayout([...current, block]);
      const targetIndex = current.findIndex((item) => item.id === targetId);
      const next = [...current];
      next.splice(targetIndex < 0 ? next.length : targetIndex, 0, block);
      return normalizeDraftLayout(next);
    });
    setDraggedLibraryItem(null);
    notify(`${block.title} 블록을 배치했습니다.`);
    return true;
  };
  const moveBlock = (targetId) => {
    if (!draggedBlockId || draggedBlockId === targetId) return;
    setEditorBlocks((current) => {
      const from = current.findIndex((block) => block.id === draggedBlockId);
      const to = current.findIndex((block) => block.id === targetId);
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return normalizeDraftLayout(next);
    });
    setDraggedBlockId(null);
  };
  const moveBlockBy = (blockId, offset) => {
    setEditorBlocks((current) => {
      const from = current.findIndex((block) => block.id === blockId);
      const to = Math.max(0, Math.min(current.length - 1, from + offset));
      if (from < 0 || from === to) return current;
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return normalizeDraftLayout(next);
    });
  };
  const resizeBlock = (blockId, dimension, amount) => {
    setEditorBlocks((current) => normalizeDraftLayout(current.map((block) => {
      if (block.id !== blockId) return block;
      const limit = dimension === "w" ? 12 : 8;
      const value = Math.max(1, Math.min(limit, block[dimension] + amount));
      return dimension === "w" ? { ...block, w: value, columns: value } : { ...block, h: value };
    })));
  };

  if (view === "list") return <div className="page-content enterprise-reports-list">
    <div className="meta-strip"><Info size={13} />{SYNTHETIC_META.label}<span>seed {SYNTHETIC_META.seed}</span><span>schema {SYNTHETIC_META.schemaVersion}</span></div>
    <div className="legacy-report-toolbar"><button className="primary" onClick={createAutomatedReport}><FilePlus2 size={15} />로컬 보고서 예시 생성</button><label className="report-search">검색<input aria-label="보고서 검색" value={reportSearch} onChange={(event) => setReportSearch(event.target.value)} placeholder="기간, 작성자, 상태 검색" /></label><label>유형<select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option>전체</option><option>주간</option><option>월간</option><option>분기</option></select></label><label>상태<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>전체</option><option>초안</option><option>확정</option></select></label></div>
    <RunHistoryFixture />
    <section className="card legacy-report-list"><div className="legacy-report-row legacy-report-head"><span>유형</span><span>기간</span><span>상태</span><span>작성자</span><span>최근 변경</span><span>동작</span></div>{filteredReports.map((report) => <article className="legacy-report-row" key={report.id}><strong>{report.type}</strong><b>{report.period}</b><span><i className={`legacy-report-status ${report.status === "초안" ? "draft" : "final"}`}><em />{report.status}</i></span><span>{report.author}</span><span>{report.updated}</span><button onClick={() => openReport(report)}>{report.status === "초안" ? "편집" : "열람"} <ChevronRight size={13} /></button></article>)}</section>
    <p className="legacy-report-guide">목록의 상태도 local fixture이며 실제 승인 이력이 아닙니다. 각 보고서는 동작 버튼으로 열 수 있습니다.</p>
  </div>;

  if (view === "editor") return <div className="enterprise-report-editor">
    <aside className="card editor-library"><header><p>BLOCK LIBRARY</p><h2>보고서 에디터</h2><span>드래그하거나 버튼을 눌러 블록을 추가하세요.</span></header><section><h3><Sparkles size={14} />자연어로 차트 만들기</h3><textarea placeholder="예: 지난달 객실 매출과 점유율 추이 차트" /><button onClick={() => addBlock({ ...BASIC_BLOCKS.kpi, type: "chart", title: "AI 생성 차트", values: [8, 12, 10, 16, 13, 18, 14], caption: "자연어 요청 기반 synthetic chart" })}><BarChart3 size={14} />차트 생성</button></section><div className="editor-catalog"><p>기존 보고서 구성</p>{BLOCK_CATALOG.map((block) => <button draggable onClick={() => addBlock(block)} onDragStart={() => setDraggedLibraryItem({ kind: "catalog", value: block })} onDragEnd={() => setDraggedLibraryItem(null)} key={block.key}><span>{block.type === "chart" ? <BarChart3 size={14} /> : <FileOutput size={14} />}</span><div><small>{block.group}</small><b>{block.title}</b><em>{block.description}</em></div><GripVertical size={14} /></button>)}</div><div className="editor-basic"><p>기본 블록</p>{[["heading",Type,"제목"],["text",FileOutput,"텍스트"],["quote",Quote,"인용"],["kpi",Target,"KPI"],["table",Table2,"표"],["divider",Minus,"구분선"]].map(([type,Icon,label]) => <button draggable onClick={() => addBlock(BASIC_BLOCKS[type])} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: type })} onDragEnd={() => setDraggedLibraryItem(null)} key={type}><Icon size={14} />{label} 추가</button>)}</div></aside>
    <main className="editor-workspace"><header className="card editor-topbar"><div><button onClick={() => setView("list")}><ArrowLeft size={14} />보고서 목록</button><p>REPORT BLOCK EDITOR</p><h2>{selectedReport.type} 보고서 · {selectedReport.period}</h2><small>LOCAL SYNTHETIC FIXTURE · 12-column draft</small></div><div><span role="status"><Check size={13} />로컬 초안 자동 저장</span><button disabled title="실제 export API는 연결되지 않았습니다."><Download size={14} />PDF 연결 대기</button><button onClick={saveReport}><Save size={14} />로컬 저장</button><button className="primary" disabled title="서버 승인 계약 전에는 확정하지 않습니다."><Check size={14} />승인 연결 대기</button></div></header><section className={`editor-canvas ${draggedLibraryItem ? "drop-ready" : ""}`} aria-label="12-column 보고서 초안 배치" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); dropLibraryItem(); }}>{editorBlocks.map((block, index) => <article className={`card editor-block ${draggedBlockId === block.id ? "dragging" : ""}`} style={{ "--block-x": block.x + 1, "--block-y": block.y + 1, "--block-w": block.w, "--block-h": block.h }} draggable onDragStart={() => { setDraggedLibraryItem(null); setDraggedBlockId(block.id); }} onDragEnd={() => setDraggedBlockId(null)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.stopPropagation(); if (!dropLibraryItem(block.id)) moveBlock(block.id); }} key={block.id}><header><div><GripVertical size={16} /><b>{index + 1}. {block.title}</b><small>x{block.x + 1} y{block.y + 1} · {block.w}×{block.h}</small></div><nav aria-label={`${block.title} 배치 조정`}><button aria-label={`${block.title} 앞으로 이동`} disabled={index === 0} onClick={() => moveBlockBy(block.id, -1)}>↑</button><button aria-label={`${block.title} 뒤로 이동`} disabled={index === editorBlocks.length - 1} onClick={() => moveBlockBy(block.id, 1)}>↓</button><button aria-label={`${block.title} 너비 줄이기`} onClick={() => resizeBlock(block.id, "w", -1)}>−</button><button aria-label={`${block.title} 너비 늘리기`} onClick={() => resizeBlock(block.id, "w", 1)}><Columns2 size={13} />{block.w}/12</button><button aria-label={`${block.title} 높이 줄이기`} onClick={() => resizeBlock(block.id, "h", -1)}>높이−</button><button aria-label={`${block.title} 높이 늘리기`} onClick={() => resizeBlock(block.id, "h", 1)}>높이+</button><button aria-label={`${block.title} 삭제`} onClick={() => setEditorBlocks((current) => normalizeDraftLayout(current.filter((item) => item.id !== block.id)))}><Trash2 size={13} /></button></nav></header>{block.type === "chart" ? <><div className="editor-chart">{block.values.map((value, valueIndex) => <div key={`${block.id}-${valueIndex}`}><b>{value}</b><i style={{ height: `${Math.max(24, (value / Math.max(...block.values)) * 118)}px` }} /><small>{valueIndex + 1}</small></div>)}</div><p>{block.caption}</p><button className="regenerate" onClick={() => notify(`${block.title} 블록을 다시 생성했습니다.`)}><RotateCcw size={13} /></button></> : block.type === "divider" ? <hr /> : <textarea aria-label={`${block.title} 내용`} className={`block-${block.type}`} value={block.content} onChange={(event) => setEditorBlocks((current) => current.map((item) => item.id === block.id ? { ...item, content: event.target.value } : item))} />}</article>)}</section></main><Toast message={toast} />
  </div>;

  return <div className="page-content legacy-report-document">
    <div className="legacy-document-actions"><button className="secondary" onClick={() => setView("list")}><ArrowLeft size={14} />보고서 목록</button><div><button disabled><Sparkles size={14} />갱신 연결 대기</button><button disabled><Download size={14} />PDF 연결 대기</button><button disabled><FileOutput size={14} />PPT 연결 대기</button><button disabled><Share2 size={14} />공유 연결 대기</button></div></div>
    <section className="card legacy-cover-strip"><div><span>보고서 유형</span><nav>{["Daily Report", "Weekly Report", "Monthly Report"].map((item) => <button className={period === item ? "active" : ""} onClick={() => setPeriod(item)} key={item}>{item}</button>)}</nav></div><div><span>보고 기간</span><strong>{selectedReport.period}</strong></div><div><span>작성 기준</span><strong>2026.08.10 08:45</strong></div><div><span>검토 대상</span><strong>Sense Place Hotel · 전체 시설</strong></div></section>

    <section className="card legacy-conclusion"><div className="legacy-number">01</div><div><p>VERIFIED ANALYSIS SUMMARY</p><h2>검증 결과 요약</h2><article><Sparkles size={19} /><p>7월 28~30일 객실 매출은 <b>45.2백만원에서 40.1백만원</b>으로 낮아졌습니다. 같은 기간 직접 예약 비중이 43.5%에서 38.2%로 감소했고, 기업 연회 2건의 일정 변경과 연결된 객실 62박 취소가 함께 관측됐습니다. 이 결과는 인과관계를 확정하지 않으며 관리자 검토가 필요합니다.</p></article></div><aside><small>실행 상태</small><strong>SUCCESS · 3개 원천</strong><span>as_of 2026-07-30 · 관리자 검토 필요</span></aside></section>

    <section className="card legacy-report-section"><SectionHeading number="02" eyebrow="REPORT DEFINITION REVIEW" title="보고서 정의 검토 안건" description="근거·기준 시각·실패 처리 정책을 확인한 뒤 승인 또는 보류해 주세요." meta={`${Object.keys(decisions).length} / ${DECISIONS.length} 결정`} /><div className="legacy-decision-list">{DECISIONS.map((item) => <article className={decisions[item.id] ? `is-${decisions[item.id]}` : ""} key={item.id}><div className="legacy-rank"><span>{String(item.id).padStart(2, "0")}</span><i>{item.priority}</i></div><div><h3>{item.title}</h3><p>{item.reason}</p><dl><div><dt>효과</dt><dd>{item.impact}</dd></div><div><dt>실행 조건</dt><dd>{item.condition}</dd></div><div><dt>판단 근거</dt><dd>{item.evidence}</dd></div><div><dt>담당</dt><dd>{item.owner}</dd></div></dl></div><footer>{decisions[item.id] ? <><Check size={15} /><b>{decisions[item.id] === "approved" ? "승인됨" : "보류됨"}</b><button onClick={() => setDecisions((current) => ({ ...current, [item.id]: null }))}>변경</button></> : <><button className="approve" onClick={() => setDecisions((current) => ({ ...current, [item.id]: "approved" }))}>승인</button><button onClick={() => setDecisions((current) => ({ ...current, [item.id]: "held" }))}>보류</button></>}</footer></article>)}</div></section>

    <section className="card legacy-report-section"><SectionHeading number="03" eyebrow="EVIDENCE & RUN CONDITIONS" title="분석 근거·실행 조건 검토" description="보고서 정의에 포함할 Artifact, 원천, 기준 시각을 확인합니다." meta="Synthetic fixture" /><div className="legacy-response-layout"><div className="legacy-options"><h3>근거 선택 <small>복수 선택 가능</small></h3>{RESPONSE_OPTIONS.map((option) => { const selected = selectedOptions.includes(option.id); return <button className={selected ? "selected" : ""} onClick={() => setSelectedOptions((current) => selected ? current.filter((id) => id !== option.id) : [...current, option.id])} key={option.id}><span>{selected && <Check size={12} />}</span><div><b>{option.label}</b><small>{option.description}</small><em>{option.detail}</em></div></button>; })}</div><div className="legacy-impact"><p>선택 조건 요약</p><div><span>선택 근거<strong>{selectedOptions.length}개</strong></span><span>성공 원천<strong>PMS · CRM · Banquet</strong></span><span>기준 시각<strong>2026-07-30</strong></span></div><article><small>보고서 실행 상태</small><strong>검토 필요</strong><p>선택 내용은 보고서 정의 초안에만 반영되며 승인 전에는 예약 실행되지 않습니다.</p></article></div></div><div className="legacy-manager-review"><label>관리자 검토 메모<textarea value={memo} onChange={(event) => setMemo(event.target.value)} placeholder="선택 사유와 추가 확인 사항을 기록하세요." /></label><p><Info size={13} />승인은 정의 승인 후보 등록이며 실제 보고서 실행을 자동 시작하지 않습니다.</p><div>{["승인", "보류", "반려"].map((status) => <button className={responseDecision === status ? "active" : ""} onClick={() => setResponseDecision(status)} key={status}>{status}</button>)}</div></div></section>

    <div className="legacy-two-column"><section className="card legacy-report-section"><SectionHeading number="04" eyebrow="VERIFIED METRICS" title="검증된 핵심 지표" /><div className="legacy-performance"><div><span>지표</span><span>값</span><span>조건</span><span>근거</span><span>상태</span></div>{PERFORMANCE.map(([metric,current,target,change,status,tone]) => <div key={metric}><b>{metric}</b><strong>{current}</strong><span>{target}</span><em>{change}</em><i className={tone}>{status}</i></div>)}</div></section><section className="card legacy-report-section"><SectionHeading number="05" eyebrow="INTERPRETATION BOUNDARY" title="결과 해석과 한계" /><div className="legacy-issue"><header><AlertTriangle size={18} /><div><small>관측된 변화</small><h3>객실·예약 채널·연회 일정 동시 변화</h3></div><b>확인</b></header><p>7월 28~30일 객실 매출과 점유율, 직접 예약 비중이 함께 낮아졌고 기업 연회 2건의 일정 변경과 연계 객실 62박 취소가 확인됐습니다. 이 화면은 관측된 연관성을 설명하며 특정 요인을 원인으로 확정하지 않습니다.</p><dl><div><dt>분석 기간</dt><dd>2026-07-28~07-30</dd></div><div><dt>기준 시각</dt><dd>2026-07-30</dd></div><div><dt>결과 식별자</dt><dd>fixture-query-success</dd></div><div><dt>데이터 성격</dt><dd>synthetic fixture</dd></div></dl></div></section></div>

    <section className="card legacy-report-section"><SectionHeading number="06" eyebrow="SOURCE TRACE" title="데이터 출처 추적" description="표시된 수치가 어떤 원천과 실행 식별자에서 왔는지 확인합니다." meta="DataHub metadata · Trino read-only" /><div className="legacy-hotel-table"><div><span>원천</span><span>시스템</span><span>사용 범위</span><span>상태</span><span>근거 식별자</span></div>{SOURCE_TRACE.map(([source,system,scope,status,evidence]) => <div key={source}><span><b>{source}</b><small>synthetic</small></span><strong>{system}</strong><strong>{scope}</strong><strong>{status}</strong><strong>{evidence}</strong></div>)}</div><p className="legacy-boundary"><Info size={13} />DataHub는 메타데이터 기준 시스템, Trino는 읽기 전용 연합 조회 엔진입니다. 화면은 API가 반환한 근거를 재계산하지 않고 표시합니다.</p></section>

    <section className="card legacy-report-section"><SectionHeading number="07" eyebrow="REPORT RUN TRACKER" title="보고서 실행 단계" description="Artifact 연결부터 정의 승인, 수동 실행, 스케줄 활성화까지 상태를 구분합니다." /><div className="legacy-actions"><div><span>실행 단계</span><span>담당</span><span>근거·조건</span><span>상태</span><span>다음 단계</span></div>{ACTIONS.map(([task,owner,evidence,status,next]) => <div key={task}><b>{task}</b><span>{owner}</span><span>{evidence}</span><i>{status}</i><span>{next}</span></div>)}</div></section>

    <section className="card legacy-report-section"><SectionHeading number="08" eyebrow="RUN STATUS CONTRACT" title="보고서 실행 상태 처리" description="미래 추정값 대신 실제 실행 결과의 성공·부분 성공·실패 상태를 명확히 구분합니다." /><div className="legacy-scenarios"><article className="recommended"><span><Check size={17} />SUCCESS</span><strong>전체 블록 표시</strong><p>모든 원천과 블록이 같은 기준 시각으로 완료되며 Artifact 참조를 보존합니다.</p><i>현재 fixture 상태</i></article><article><span><AlertTriangle size={17} />PARTIAL_SUCCESS</span><strong>실패 블록 분리</strong><p>성공 결과와 실패 원천을 함께 표시하고 마지막 성공값 사용 여부를 명시합니다.</p><i>관리자 확인 필요</i></article><article><span><Target size={17} />FAILED</span><strong>결과 승격 금지</strong><p>실패 실행은 정상 보고서로 확정하지 않고 기존 근거를 보존한 채 재시도합니다.</p><i>오류 원인 기록</i></article></div></section>

    <footer className="card legacy-methodology"><Info size={15} /><div><b>분석 기준 및 한계</b><p>PMS reservations, CRM membership history, Banquet bookings의 합성 데이터를 사용했으며 seed 20260729, schema 1.0.0, as_of 2026-07-30을 기록했습니다. DataHub URN과 Trino FQN으로 출처를 추적하며, 관측된 변화는 인과관계나 미래 값으로 해석하지 않습니다.</p></div><button className="primary" disabled><Send size={14} />공유 연결 대기</button></footer><Toast message={toast} />
  </div>;
}
