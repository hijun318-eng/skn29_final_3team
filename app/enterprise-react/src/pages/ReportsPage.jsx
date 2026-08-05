import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowLeft, Ban, BarChart3, Check, ChevronRight, CircleCheck,
  CircleX, Clock3, Columns2, Copy, Download, Eye, FileOutput, FilePlus2, GripVertical,
  Inbox, Info, LoaderCircle, Minus, Quote, RotateCcw, Save, Send, Share2,
  ShieldAlert, Sparkles, Table2, Target, Trash2, Type,
} from "lucide-react";
import { SYNTHETIC_META } from "../data/enterpriseDemoData";
import { createReportClient, ReportApiError, usesFixtureReportClient } from "../api/reportClient";
import { normalizeDraftLayout, serializeDraftLayout, toReportBlockRequest } from "../contracts/report";
import { createUuid } from "../utils/createUuid";

const REPORTS = [
  { id: 1, type: "주간", period: "07/21~07/27", title: "여름 성수기 객실 운영 주간 보고", summary: "성수기 진입으로 객실 판매와 점유율이 전주보다 상승했습니다. 주말 체크인 집중 시간대의 프런트 대기 증가가 함께 관측돼 운영 인력 배치 검토가 필요합니다.", kpi: "객실 매출 286.4백만원\n점유율 84.7%\n평균 객실 단가 168,000원\n직접 예약 비중 44.1%", note: "금·토요일 15~17시 체크인 인력을 보강하고 직접 예약 전환 추이를 다음 주에도 확인합니다.", status: "초안", author: "박준희", updated: "10분 전 수정" },
  { id: 2, type: "주간", period: "07/14~07/20", title: "회원 예약 전환 및 객실 운영 보고", summary: "회원 대상 패키지 판매 이후 직접 예약 비중과 재방문 예약이 증가했습니다. 객실 점유율은 안정적으로 유지됐으며 취소율은 전주보다 낮아졌습니다.", kpi: "직접 예약 비중 46.8%\n회원 예약 312건\n재방문 예약률 28.4%\n예약 취소율 6.1%", note: "회원 패키지 판매 기간을 1주 연장하고 채널별 예약 전환을 비교합니다.", status: "확정", author: "박준희", updated: "07.21 확정" },
  { id: 3, type: "주간", period: "07/07~07/13", title: "연회 행사 연계 매출 주간 보고", summary: "기업 연회 5건이 정상 진행됐고 연계 객실 판매가 증가했습니다. 행사일 전후 객실 수요가 집중돼 단체 예약과 일반 예약의 재고 배분을 조정했습니다.", kpi: "기업 연회 5건\n연회 매출 92.6백만원\n연계 객실 148박\n행사 취소 0건", note: "대형 행사 전후 2일의 객실 재고를 사전 확보하는 운영 기준을 유지합니다.", status: "확정", author: "박준희", updated: "07.14 확정" },
  { id: 4, type: "월간", period: "2026년 06월", title: "6월 객실·회원·연회 통합 운영 보고", summary: "6월 객실 매출과 회원 직접 예약은 전월 대비 증가했습니다. 연회 매출은 계획 범위였으며 주말 객실 점유율이 평일보다 높게 나타났습니다.", kpi: "객실 매출 1,084백만원\n평균 점유율 78.9%\n회원 예약 1,126건\n연회 매출 318백만원", note: "7월 성수기에는 주말 수요 집중과 직접 예약 전환을 핵심 관리 지표로 운영합니다.", status: "확정", author: "박준희", updated: "07.03 확정" },
  { id: 5, type: "분기", period: "2026 Q2", title: "2026년 2분기 호텔 운영 성과 보고", summary: "2분기 객실과 연회 매출이 계획 수준을 달성했고 회원 예약 비중이 지속해서 증가했습니다. 원천별 합성 데이터를 동일 기준 시각으로 집계한 경영 검토용 보고서입니다.", kpi: "객실 매출 3,126백만원\n평균 점유율 76.3%\n직접 예약 비중 42.7%\n연회 매출 946백만원", note: "3분기에는 직접 예약 비중 확대와 성수기 객실 운영 안정성을 중심으로 관리합니다.", status: "확정", author: "CX 운영팀", updated: "07.05 확정" },
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
  { id: "pms", label: "Hotel PMS", description: "객실 예약·매출 근거 원천", detail: "pms.public.pms_stays" },
  { id: "crm", label: "Membership CRM", description: "회원 등급 이력 근거 원천", detail: "crm.dbo.crm_member_grade_history" },
  { id: "banquet", label: "Banquet Sales", description: "연회 일정·연계 객실 근거 원천", detail: "banquet.public.banquet_bookings" },
  { id: "asof", label: "기준 시각 고정", description: "실행 결과를 같은 시점 기준으로 비교", detail: "2026-07-30 · Asia/Seoul" },
];

const PERFORMANCE = [
  ["인식 객실 매출", "128,400,000 KRW", "2026년 7월", "Hotel PMS", "검증됨", "positive"],
  ["객실 점유율", "72.5%", "2026-07-30", "Hotel PMS", "검증됨", "positive"],
  ["직접 예약 비중", "43.5% → 38.2%", "07/28~07/30", "Membership CRM", "관측됨", "warning"],
  ["연회 일정 변경", "2건 · 객실 62박", "07/29~07/30", "Banquet Sales", "관측됨", "warning"],
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
  ["Hotel PMS", "PostgreSQL", "객실 매출·점유율", "성공", "pms.public.pms_stays"],
  ["Membership CRM", "SQL Server", "회원 등급 이력", "성공", "crm.dbo.crm_member_grade_history"],
  ["Banquet Sales", "PostgreSQL", "연회 일정·연계 객실", "성공", "banquet.public.banquet_bookings"],
];

const BLOCK_CATALOG = [
  { key: "executive-summary", group: "분석 요약", title: "검증 결과 요약", description: "Artifact 기반 핵심 지표와 해석", type: "summary", span: 2, content: "7월 28~30일 객실 매출은 4,520만원에서 4,010만원으로 낮아졌습니다. 같은 기간 직접 예약 비중 감소와 기업 연회 2건의 일정 변경, 연계 객실 62박 취소가 함께 관측됐으며 인과관계로 단정하지 않습니다." },
  { key: "decisions", group: "보고서 검토", title: "결정 필요 안건", description: "정의·기준 시각·부분 실패 정책 검토", type: "text", span: 2, content: "1. 검증 Artifact를 주간 보고서 정의에 연결\n2. 기준 시각을 2026-07-30으로 고정\n3. 부분 실패 시 블록별 상태 표시" },
  { key: "response-review", group: "근거 검토", title: "데이터 출처 및 분석 기준", description: "DataHub·Trino 출처와 as_of 확인", type: "text", span: 2, content: "Hotel PMS · pms.public.pms_stays\nMembership CRM · crm.dbo.crm_member_grade_history\nBanquet Sales · banquet.public.banquet_bookings\n기준 시각: 2026-07-30 Asia/Seoul · synthetic seed 20260729 · schema 1.0.0" },
  { key: "performance", group: "분석 결과", title: "검증된 핵심 지표", description: "객실·예약·연회 통합 지표", type: "chart", span: 1, values: [45.2, 40.1, 43.5, 38.2, 62], labels: ["4,520", "4,010", "43.5", "38.2", "62"], caption: "객실 매출 시작·종료(만원) · 직접 예약 시작·종료(%) · 연계 객실 취소(박)" },
  { key: "issues", group: "해석", title: "결과 해석과 한계", description: "관측 사실과 해석 경계", type: "text", span: 1, content: "관측: 객실 매출·점유율·직접 예약 비중 감소와 연회 2건 일정 변경이 같은 기간 나타남\n연계: 연회 일정 변경과 연결된 객실 62박 취소\n한계: 인과·미래 추정 결과가 아님" },
  { key: "source-trace", group: "근거 추적", title: "데이터 출처 추적", description: "카탈로그 원천과 실행 식별자", type: "text", span: 2, content: "Hotel PMS · PostgreSQL · pms.public.pms_stays\nMembership CRM · SQL Server · crm.dbo.crm_member_grade_history\nBanquet Sales · PostgreSQL · banquet.public.banquet_bookings\nquery fixture-query-success" },
  { key: "action-tracker", group: "실행 관리", title: "보고서 실행 단계", description: "정의·승인·수동 실행·스케줄", type: "text", span: 2, content: "Artifact 연결 · 완료\n보고서 정의 초안 · 검토 중\n수동 실행 · 대기\n스케줄 · 비활성" },
  { key: "run-status", group: "실행 상태", title: "실행 상태 처리", description: "SUCCESS·PARTIAL_SUCCESS·FAILED", type: "text", span: 2, content: "SUCCESS: 모든 블록 표시\nPARTIAL_SUCCESS: 실패 블록 분리\nFAILED: 결과 승격 금지" },
];

const BASIC_BLOCKS = {
  heading: { type: "heading", title: "새 제목", content: "보고서 제목을 입력하세요.", span: 2 },
  text: { type: "text", title: "새 텍스트", content: "클릭해 내용을 입력하세요.", span: 2 },
  quote: { type: "quote", title: "인용", content: "강조할 분석 해석과 근거를 입력하세요.", span: 1 },
  kpi: { type: "kpi", title: "KPI 카드", content: "객실 매출 4,520→4,010만원\n직접 예약 43.5→38.2%\n연계 객실 취소 62박", span: 1 },
  table: { type: "table", title: "데이터 표", content: "항목 | 변화 | 근거\n객실 매출 | 4,520→4,010만원 | PMS\n직접 예약 | 43.5→38.2% | CRM\n연회 변경 | 2건·62박 | Banquet", span: 2 },
  divider: { type: "divider", title: "구분선", content: "", span: 2 },
};

const toLayoutBlock = (block) => ({
  ...block,
  content: typeof block.content === "string" ? block.content.replaceAll("45.2→40.1백만원", "4,520→4,010만원") : block.content,
  caption: typeof block.caption === "string" ? block.caption.replaceAll("객실 매출(백만원) 45.2→40.1", "객실 매출(만원) 4,520→4,010") : block.caption,
  labels: block.labels || (block.title === "매출·점유율 비교" ? ["4,520", "4,010", "76.1", "68.6"] : undefined),
  columns: block.w ?? (block.span ?? 2) * 6,
  w: block.w ?? (block.span ?? 2) * 6,
  h: block.h ?? 4,
});

const withReportTitle = (blocks, id = "report-title") => blocks.some((block) => block.type === "heading") ? blocks : [{
  ...BASIC_BLOCKS.heading,
  id,
  origin: "basic",
  content: "객실 매출 감소 통합 분석 보고서",
  w: 12,
  h: 2,
}, ...blocks];

const INITIAL_BLOCKS = normalizeDraftLayout(
  withReportTitle(BLOCK_CATALOG.slice(0, 5).map((block, index) => toLayoutBlock({ ...block, id: `${block.key}-${index}` }))),
);

const mockReportBlocks = (report) => normalizeDraftLayout([
  toLayoutBlock({ id: `report-${report.id}-title`, type: "heading", title: "보고서 제목", content: report.title, w: 12, h: 2 }),
  toLayoutBlock({ id: `report-${report.id}-summary`, type: "summary", title: "운영 요약", content: report.summary, w: 12, h: 4 }),
  toLayoutBlock({ id: `report-${report.id}-kpi`, type: "kpi", title: "핵심 KPI", content: report.kpi, w: 6, h: 4 }),
  toLayoutBlock({ id: `report-${report.id}-note`, type: "quote", title: "관리자 검토 사항", content: report.note, w: 6, h: 4 }),
  toLayoutBlock({ id: `report-${report.id}-source`, type: "text", title: "데이터 출처 및 분석 기준", content: `Hotel PMS · Membership CRM · Banquet Sales\nsynthetic · schema 1.0.0 · 보고 기간 ${report.period}`, w: 12, h: 3 }),
]);

function initialEditorBlocks() {
  try {
    const candidate = JSON.parse(window.sessionStorage.getItem("answervice.report.artifact"));
    if (!candidate?.artifactId) return INITIAL_BLOCKS;
    if (candidate.blocks?.length) return normalizeDraftLayout(withReportTitle(candidate.blocks.map(toLayoutBlock), `artifact-${candidate.artifactId}-title`));
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

function savedEditorBlocks(report) {
  try {
    const saved = JSON.parse(window.localStorage.getItem(`answervice.report.blocks.${report.id}`));
    return saved ? normalizeDraftLayout(withReportTitle(saved.map((block) => toLayoutBlock({
      ...block,
      origin: block.origin || (block.id?.startsWith(`${block.type}-`) ? "basic" : undefined),
      title: block.title === "데이터 근거 및 기준 시각" ? "데이터 출처 및 분석 기준" : block.title,
      content: typeof block.content === "string" ? (block.type === "kpi" ? block.content.replaceAll(" · ", "\n") : block.content)
        .replaceAll("PMS reservations", "Hotel PMS · pms.public.pms_stays")
        .replaceAll("CRM membership history", "Membership CRM · crm.dbo.crm_member_grade_history")
        .replaceAll("Banquet bookings", "Banquet Sales · banquet.public.banquet_bookings") : block.content,
    })), `report-${report.id}-title`)) : report.title ? mockReportBlocks(report) : initialEditorBlocks();
  } catch {
    return initialEditorBlocks();
  }
}

function savedReports() {
  try {
    const storedReports = JSON.parse(window.localStorage.getItem("answervice.reports")) || REPORTS;
    const reports = storedReports.map((report) => {
      const mock = REPORTS.find((candidate) => candidate.id === report.id);
      return mock ? { ...mock, ...report, title: mock.title, summary: mock.summary, kpi: mock.kpi, note: mock.note } : report;
    });
    const artifact = JSON.parse(window.sessionStorage.getItem("answervice.report.artifact"));
    const importedId = artifact?.artifactId ? `artifact-${artifact.artifactId}` : null;
    if (!importedId) return reports;
    const importedTitle = artifact.title || artifact.blocks?.find((block) => block.type === "heading")?.content || "분석 결과 보고서";
    return reports.some((report) => report.id === importedId)
      ? reports.map((report) => report.id === importedId ? { ...report, period: "07/28~07/30", title: importedTitle } : report)
      : [{ id: importedId, type: "주간", period: "07/28~07/30", title: importedTitle, status: "초안", author: "AI Agent", updated: "방금 추가" }, ...reports];
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

const isBasicDocumentBlock = (block) => block.origin === "basic" && ["heading", "text", "divider"].includes(block.type);
const hasReportNumber = (block) => block.type !== "divider" && !isBasicDocumentBlock(block);

function GeneratedReportBlock({ block, number }) {
  if (block.type === "divider") return <hr className="generated-report-divider" />;
  if (isBasicDocumentBlock(block) && block.type === "heading") return <h2 className="generated-report-basic generated-report-heading" style={{ "--report-block-width": block.reportWidth }}>{block.content}</h2>;
  if (isBasicDocumentBlock(block) && block.type === "text") return <p className="generated-report-basic generated-report-text" style={{ "--report-block-width": block.reportWidth }}>{block.content}</p>;
  return <article className={`card generated-report-block generated-report-block--${block.type}`} style={{ "--report-block-width": block.reportWidth }}>
    <header>{number && <span>{String(number).padStart(2, "0")}</span>}<div><small>{block.group || "REPORT SECTION"}</small><h2>{block.title}</h2></div></header>
    {block.type === "chart" ? <><div className="generated-report-chart">{block.values.map((value, index) => <div key={`${block.id}-${index}`}><b>{block.labels?.[index] ?? value}</b><i style={{ height: `${Math.max(28, (value / Math.max(...block.values)) * 132)}px` }} /><small>{block.axisLabels?.[index] ?? index + 1}</small></div>)}</div><p className="generated-report-caption">{block.caption}</p></> : block.type === "quote" ? <blockquote>{block.content}</blockquote> : block.type === "kpi" ? <strong className="generated-report-kpi">{block.content}</strong> : <p className="generated-report-copy">{block.content}</p>}
  </article>;
}

function buildGeneratedReportLayout(blocks) {
  const layout = [];
  let sectionNumber = 1;
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index];
    if (block.type === "divider" || block.w >= 12) {
      layout.push({ ...block, reportWidth: 12, reportNumber: hasReportNumber(block) ? sectionNumber++ : null });
      continue;
    }
    const next = blocks[index + 1];
    if (next && next.type !== "divider" && next.w < 12) {
      const total = block.w + next.w;
      const firstWidth = Math.max(1, Math.min(11, Math.round((block.w / total) * 12)));
      layout.push({ ...block, reportWidth: firstWidth, reportNumber: hasReportNumber(block) ? sectionNumber++ : null });
      layout.push({ ...next, reportWidth: 12 - firstWidth, reportNumber: hasReportNumber(next) ? sectionNumber++ : null });
      index += 1;
      continue;
    }
    layout.push({ ...block, reportWidth: 12, reportNumber: hasReportNumber(block) ? sectionNumber++ : null });
  }
  return layout;
}

function apiError(error) {
  if (error instanceof ReportApiError && error.status === 401) return `401 · 로그인이 필요합니다. ${error.message}`;
  if (error instanceof ReportApiError && error.status === 403) return `403 · REPORT_ADMIN 권한이 필요합니다. ${error.message}`;
  return error instanceof ReportApiError ? `${error.status} · ${error.code} · ${error.message}`
    : error instanceof Error ? error.message : "Report API 요청에 실패했습니다.";
}

function ReportApiPage() {
  const client = useMemo(() => createReportClient(), []);
  const [definitions, setDefinitions] = useState([]);
  const [definitionState, setDefinitionState] = useState("loading");
  const [runs, setRuns] = useState([]);
  const [runState, setRunState] = useState("loading");
  const [selectedDefinition, setSelectedDefinition] = useState(null);
  const [apiBlocks, setApiBlocks] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [command, setCommand] = useState(null);
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
  useEffect(() => { void loadDefinitions(); void loadRuns(); }, []);

  const mutate = async (name, action) => {
    setPending(name);
    setError("");
    try { return await action(); } catch (nextError) { setError(apiError(nextError)); return null; } finally { setPending(""); }
  };
  const createDefinition = async () => {
    const definition = await mutate("create", () => client.createDefinition({
      definition_id: createUuid(),
      title: "새 Report 정의",
      blocks: [{
        block_id: createUuid(), title: "보고서 내용", columns: 12, type: "text",
        x: 0, y: 0, w: 12, h: 2, content: "검토할 보고서 내용을 입력하세요.",
      }],
    }));
    if (definition) { upsertDefinition(definition); setDefinitionState("ready"); }
  };
  const openDefinition = async (definition) => {
    const current = await mutate("definition", () => client.getDefinition(definition.definitionId, definition.version));
    if (current) upsertDefinition(current);
  };
  const saveDraft = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "draft") return;
    const saved = await mutate("save", () => client.replaceDraftBlocks(
      selectedDefinition.definitionId,
      selectedDefinition.version,
      apiBlocks.map(toReportBlockRequest),
    ));
    if (saved) upsertDefinition(saved);
  };
  const approve = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "draft") return;
    const approved = await mutate("approve", () => client.approveDefinition(
      selectedDefinition.definitionId, selectedDefinition.version, new Date().toISOString(),
    ));
    if (approved) upsertDefinition(approved);
  };
  const createNextDraft = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    const draft = await mutate("draft", () => client.createNextDraft(selectedDefinition.definitionId, selectedDefinition.version));
    if (draft) upsertDefinition(draft);
  };
  const queueManualRun = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    const receipt = await mutate("manual", () => client.createManualRun({
      definition_id: selectedDefinition.definitionId,
      version: selectedDefinition.version,
      as_of: new Date().toISOString(),
      idempotency_key: createUuid(),
    }));
    if (receipt) setCommand(receipt);
  };
  const openRun = async (run) => {
    const detail = await mutate("run", () => client.getRun(run.runId));
    if (detail) setSelectedRun(detail);
  };

  return <div className="page-content report-api-page">
    <div className="meta-strip"><Info size={13} />ACTUAL LOCAL REPORT API<span>REPORT_ADMIN owner scope</span><span>worker 미연결</span></div>
    <header className="card report-api-header"><div><p>REPORT API</p><h2>서버 Report 정의와 실행 이력</h2><small>화면은 API 응답 상태만 표시하며 오류 시 fixture로 전환하지 않습니다.</small></div><div><button onClick={() => void loadDefinitions()} disabled={definitionState === "loading"}><RotateCcw size={14} />정의 새로고침</button><button className="primary" onClick={() => void createDefinition()} disabled={Boolean(pending)}><FilePlus2 size={14} />초안 생성</button></div></header>
    {error && <p className="report-api-state error" role="alert" aria-live="assertive">{/^40[13]/.test(error) ? <ShieldAlert size={17} /> : <AlertTriangle size={17} />}{error}</p>}
    <section className="report-api-grid">
      <article className="card report-api-panel"><header><h3>정의·버전</h3><small>서버가 반환한 title·version·status</small></header>
        {definitionState === "loading" && <p className="report-api-state" role="status" aria-live="polite"><LoaderCircle size={17} />Report 정의를 불러오는 중입니다.</p>}
        {definitionState === "error" && <p className="report-api-state error" role="alert"><ShieldAlert size={17} />Report 정의를 불러오지 못했습니다.</p>}
        {definitionState === "empty" && <p className="report-api-state"><Inbox size={17} />서버에 표시할 Report 정의가 없습니다.</p>}
        {definitionState === "ready" && <div className="report-api-list">{definitions.map((definition) => <button aria-pressed={selectedDefinition?.definitionId === definition.definitionId && selectedDefinition?.version === definition.version} onClick={() => void openDefinition(definition)} key={`${definition.definitionId}-${definition.version}`}><span><b>{definition.title}</b><small>{definition.definitionId}</small></span><em>v{definition.version} · {definition.status}</em></button>)}</div>}
      </article>
      <article className="card report-api-panel"><header><h3>실행 이력</h3><button onClick={() => void loadRuns()} disabled={runState === "loading"}><RotateCcw size={13} />새로고침</button></header>
        {runState === "loading" && <p className="report-api-state" role="status" aria-live="polite"><LoaderCircle size={17} />실제 Run History를 불러오는 중입니다.</p>}
        {runState === "error" && <p className="report-api-state error" role="alert"><AlertTriangle size={17} />Run History를 불러오지 못했습니다.</p>}
        {runState === "empty" && <p className="report-api-state"><Inbox size={17} />서버에 생성된 Report run이 없습니다.</p>}
        {runState === "ready" && <div className="report-api-list">{runs.map((run) => <button aria-pressed={selectedRun?.runId === run.runId} onClick={() => void openRun(run)} key={run.runId}><span><b>{run.status}</b><small>{run.runId}</small></span><em>definition v{run.definitionVersion}</em></button>)}</div>}
      </article>
    </section>
    {selectedDefinition && <section className="card report-api-editor" aria-live="polite"><header><div><small>{selectedDefinition.definitionId}</small><h3>{selectedDefinition.title} · v{selectedDefinition.version}</h3><p>{selectedDefinition.status}{selectedDefinition.approvedAt ? ` · ${selectedDefinition.approvedAt}` : ""}</p></div><div>{selectedDefinition.status === "draft" ? <><button onClick={() => void saveDraft()} disabled={Boolean(pending)}><Save size={14} />초안 저장</button><button className="primary" onClick={() => void approve()} disabled={Boolean(pending)}><Check size={14} />명시적 승인</button></> : <><button onClick={() => void createNextDraft()} disabled={Boolean(pending)}><FilePlus2 size={14} />다음 초안</button><button className="primary" onClick={() => void queueManualRun()} disabled={Boolean(pending)}><Clock3 size={14} />수동 실행 요청</button></>}</div></header>
      <div className="report-api-blocks">{apiBlocks.map((block) => <article key={block.id}><header><b>{block.title}</b><small>{block.type} · x{block.x + 1} y{block.y + 1} · {block.w}×{block.h}</small></header>{block.type === "text" ? <textarea aria-label={`${block.title} 내용`} disabled={selectedDefinition.status !== "draft"} value={block.content || ""} onChange={(event) => setApiBlocks((current) => current.map((item) => item.id === block.id ? { ...item, content: event.target.value } : item))} /> : <p>Artifact {block.artifactId}<br />Query {block.queryId || "—"}</p>}</article>)}</div>
    </section>}
    {command && <section className="card report-command-receipt" role="status" aria-live="polite"><Clock3 size={18} /><div><b>서버가 수동 실행 명령을 queued로 접수했습니다.</b><p>command {command.command_id} · 이 응답에는 run_id가 없으며 worker 진행 상태를 나타내지 않습니다.</p></div></section>}
    {selectedRun && <section className="card report-run-actual" aria-live="polite"><header><div><small>{selectedRun.runId}</small><h3>실제 run · {selectedRun.status}</h3></div><span>definition v{selectedRun.definitionVersion}</span></header><p>as_of {selectedRun.asOf} · policy {selectedRun.policyVersion}</p><ul>{selectedRun.blocks.map((block) => <li key={block.blockId}><span>{block.blockId}</span><b>{block.status}</b></li>)}</ul></section>}
  </div>;
}

function FixtureReportsPage() {
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
  const [toast, setToast] = useState(() => window.sessionStorage.getItem("answervice.report.importNotice") || "");
  const [importedArtifact] = useState(() => {
    try { return JSON.parse(window.sessionStorage.getItem("answervice.report.artifact")); } catch { return null; }
  });
  const [editorBlocks, setEditorBlocks] = useState(initialEditorBlocks);
  const [selectedBlockId, setSelectedBlockId] = useState(null);
  const [saveState, setSaveState] = useState("saved");
  const [lastSavedAt, setLastSavedAt] = useState("");
  const [draggedBlockId, setDraggedBlockId] = useState(null);
  const [draggedLibraryItem, setDraggedLibraryItem] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);
  const [chartPrompt, setChartPrompt] = useState("객실 매출과 점유율 변화를 비교해줘");
  const [revealBlockId, setRevealBlockId] = useState(null);
  const editorCanvasRef = useRef(null);
  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 1800); };
  const filteredReports = reports.filter((report) => {
    const query = reportSearch.trim().toLowerCase();
    return (typeFilter === "전체" || report.type === typeFilter)
      && (statusFilter === "전체" || report.status === statusFilter)
      && (!query || [report.type, report.period, report.title, report.status, report.author].filter(Boolean).some((value) => value.toLowerCase().includes(query)));
  });
  const openReport = (report, targetView = "document") => {
    setSelectedReport(report);
    if (targetView === "editor" || targetView === "document") {
      setEditorBlocks(savedEditorBlocks(report));
      setSelectedBlockId(null);
    }
    setView(targetView);
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
    window.localStorage.setItem(`answervice.report.blocks.${selectedReport.id}`, serializeDraftLayout(editorBlocks));
    setSaveState("saved");
    setLastSavedAt(new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }));
    setReports((current) => current.map((report) => report.id === selectedReport.id ? { ...report, updated: "방금 저장" } : report));
    notify(selectedReport.status === "확정" ? "확정 보고서의 변경사항을 저장했습니다." : "보고서 초안을 저장했습니다.");
  };
  const finalizeReport = () => {
    window.localStorage.setItem(`answervice.report.blocks.${selectedReport.id}`, serializeDraftLayout(editorBlocks));
    const finalized = { ...selectedReport, status: "확정", updated: "방금 확정" };
    setSelectedReport(finalized);
    setReports((current) => current.map((report) => report.id === finalized.id ? finalized : report));
    window.sessionStorage.removeItem("answervice.report.openEditor");
    notify(selectedReport.status === "확정" ? "확정 보고서의 변경사항을 저장했습니다." : "보고서를 확정했습니다.");
    setView("document");
  };
  useEffect(() => {
    window.localStorage.setItem("answervice.reports", JSON.stringify(reports));
  }, [reports]);
  useEffect(() => {
    window.sessionStorage.removeItem("answervice.report.openEditor");
    if (!toast) return;
    window.sessionStorage.removeItem("answervice.report.importNotice");
    const timer = window.setTimeout(() => setToast(""), 2600);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    const showReportList = (event) => {
      if (event.detail === "/reports") {
        setView("list");
        setSelectedBlockId(null);
      }
    };
    window.addEventListener("answervice:navigate", showReportList);
    return () => window.removeEventListener("answervice:navigate", showReportList);
  }, []);
  useEffect(() => {
    if (view === "editor") {
      setSaveState("saving");
      const timer = window.setTimeout(() => {
        window.localStorage.setItem(`answervice.report.blocks.${selectedReport.id}`, serializeDraftLayout(editorBlocks));
        setSaveState("saved");
        setLastSavedAt(new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }));
      }, 300);
      return () => window.clearTimeout(timer);
    }
  }, [editorBlocks, selectedReport.id, selectedReport.status, view]);
  useEffect(() => {
    if (!revealBlockId || view !== "editor") return;
    const frame = window.requestAnimationFrame(() => {
      document.querySelector(".editor-canvas .editor-block.selected")?.scrollIntoView({ behavior: "smooth", block: "center" });
      setRevealBlockId(null);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [editorBlocks, revealBlockId, view]);
  useEffect(() => {
    if (view !== "editor") return undefined;
    const handleSaveShortcut = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveReport();
      }
      if (event.key === "Escape") {
        setSelectedBlockId(null);
        setDropTarget(null);
        setDraggedBlockId(null);
        setDraggedLibraryItem(null);
      }
      if (event.altKey && selectedBlockId && ["ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"].includes(event.key)) {
        event.preventDefault();
        moveBlockBy(selectedBlockId, ["ArrowUp", "ArrowLeft"].includes(event.key) ? -1 : 1);
      }
    };
    window.addEventListener("keydown", handleSaveShortcut);
    return () => window.removeEventListener("keydown", handleSaveShortcut);
  }, [editorBlocks, selectedReport, view]);
  useEffect(() => {
    window.localStorage.setItem("answervice.reports", JSON.stringify(reports));
  }, [reports]);
  const createBlock = (item) => toLayoutBlock({ ...item, id: `${item.key || item.type}-${Date.now()}-${Math.random().toString(16).slice(2)}` });
  const insertBlock = (current, block, targetId, position = "after") => {
    if (!targetId) return normalizeDraftLayout([...current, block]);
    const targetIndex = current.findIndex((item) => item.id === targetId);
    const insertIndex = targetIndex < 0 ? current.length : targetIndex + (position === "after" ? 1 : 0);
    const next = [...current];
    next.splice(insertIndex, 0, block);
    return normalizeDraftLayout(next);
  };
  const addBlock = (item, reveal = false) => {
    const block = createBlock(item);
    setEditorBlocks((current) => insertBlock(current, block, selectedBlockId, "after"));
    setSelectedBlockId(block.id);
    if (reveal) setRevealBlockId(block.id);
    notify(`${block.title} 블록을 추가했습니다.`);
  };
  const generateChart = () => {
    const prompt = chartPrompt.trim();
    if (!prompt) return notify("차트로 만들 내용을 입력해주세요.");
    const chart = prompt.includes("연회")
      ? { title: "연회 변경 영향", values: [2, 62], labels: ["2건", "62박"], axisLabels: ["일정 변경", "객실 취소"], caption: "연회 일정 변경 2건 · 연계 객실 취소 62박" }
      : prompt.includes("예약")
        ? { title: "직접 예약 비중 비교", values: [43.5, 38.2], labels: ["43.5%", "38.2%"], axisLabels: ["7/28", "7/30"], caption: "직접 예약 비중 43.5% → 38.2%" }
        : { title: "객실 매출·점유율 비교", values: [45.2, 40.1, 76.1, 68.6], labels: ["4,520만원", "4,010만원", "76.1%", "68.6%"], axisLabels: ["매출 시작", "매출 종료", "점유율 시작", "점유율 종료"], caption: "객실 매출 4,520→4,010만원 · 점유율 76.1→68.6%" };
    addBlock({ ...chart, type: "chart", group: "AI 생성 차트", description: prompt, span: 1 }, true);
  };
  const dropLibraryItem = (targetId, position = "after") => {
    if (!draggedLibraryItem) return false;
    const block = createBlock(draggedLibraryItem.kind === "catalog" ? draggedLibraryItem.value : { ...BASIC_BLOCKS[draggedLibraryItem.value], origin: "basic" });
    setEditorBlocks((current) => insertBlock(current, block, targetId, position));
    setSelectedBlockId(block.id);
    setDraggedLibraryItem(null);
    setDropTarget(null);
    notify(`${block.title} 블록을 배치했습니다.`);
    return true;
  };
  const moveBlock = (targetId, position = "after") => {
    if (!draggedBlockId || draggedBlockId === targetId) return;
    setEditorBlocks((current) => {
      const from = current.findIndex((block) => block.id === draggedBlockId);
      const next = [...current];
      const [moved] = next.splice(from, 1);
      return insertBlock(next, moved, targetId, position);
    });
    setDraggedBlockId(null);
    setDropTarget(null);
  };
  const updateDropTarget = (event, targetId) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const position = event.clientY < rect.top + rect.height / 2 ? "before" : "after";
    setDropTarget((current) => current?.id === targetId && current.position === position ? current : { id: targetId, position });
    const canvas = editorCanvasRef.current;
    if (canvas) {
      const bounds = canvas.getBoundingClientRect();
      const edge = 80;
      if (event.clientY < bounds.top + edge) canvas.scrollBy({ top: -18, behavior: "auto" });
      if (event.clientY > bounds.bottom - edge) canvas.scrollBy({ top: 18, behavior: "auto" });
    }
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
  const setBlockWidth = (blockId, width) => {
    setEditorBlocks((current) => normalizeDraftLayout(current.map((block) => block.id === blockId
      ? { ...block, w: width, columns: width }
      : block)));
  };
  const duplicateBlock = (blockId) => {
    setEditorBlocks((current) => {
      const index = current.findIndex((block) => block.id === blockId);
      if (index < 0) return current;
      const duplicate = { ...current[index], id: `${current[index].type}-${Date.now()}-${Math.random().toString(16).slice(2)}`, title: `${current[index].title} 복사본` };
      const next = [...current];
      next.splice(index + 1, 0, duplicate);
      setSelectedBlockId(duplicate.id);
      return normalizeDraftLayout(next);
    });
  };
  const removeBlock = (blockId) => {
    setEditorBlocks((current) => normalizeDraftLayout(current.filter((block) => block.id !== blockId)));
    setSelectedBlockId(null);
  };
  const selectedBlock = editorBlocks.find((block) => block.id === selectedBlockId);
  const reportTitleBlock = editorBlocks.find((block) => block.type === "heading");
  const generatedReportBlocks = buildGeneratedReportLayout(editorBlocks.filter((block) => block.id !== reportTitleBlock?.id));

  if (view === "list") return <div className="page-content enterprise-reports-list">
    <div className="meta-strip"><Info size={13} />{SYNTHETIC_META.label}<span>seed {SYNTHETIC_META.seed}</span><span>schema {SYNTHETIC_META.schemaVersion}</span></div>
    <div className="legacy-report-toolbar"><button className="primary" onClick={createAutomatedReport}><FilePlus2 size={15} />자동 보고서 생성</button><label className="report-search">검색<input aria-label="보고서 검색" value={reportSearch} onChange={(event) => setReportSearch(event.target.value)} placeholder="기간, 작성자, 상태 검색" /></label><label>유형<select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option>전체</option><option>주간</option><option>월간</option><option>분기</option></select></label><label>상태<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>전체</option><option>초안</option><option>확정</option></select></label></div>
    <RunHistoryFixture />
    <section className="card legacy-report-list"><div className="legacy-report-row legacy-report-head"><span>유형</span><span>기간·제목</span><span>상태</span><span>작성자</span><span>최근 변경</span><span>동작</span></div>{filteredReports.map((report) => <article className="legacy-report-row" key={report.id} onClick={() => openReport(report, "document")}><strong>{report.type}</strong><b>{report.period}{report.title && <small>{report.title}</small>}</b><span><i className={`legacy-report-status ${report.status === "초안" ? "draft" : "final"}`}><em />{report.status}</i></span><span>{report.author}</span><span>{report.updated}</span><nav className="legacy-report-actions" aria-label={`${report.type} ${report.period} 보고서 동작`}><button className="edit" onClick={(event) => { event.stopPropagation(); openReport(report, "editor"); }}>편집</button><button className="view" onClick={(event) => { event.stopPropagation(); openReport(report, "document"); }}>열람 <ChevronRight size={13} /></button></nav></article>)}</section>
    <p className="legacy-report-guide">초안과 확정 보고서 모두 편집할 수 있으며 변경사항은 자동 저장됩니다.</p>
  </div>;

  if (view === "editor") return <div className="enterprise-report-editor">
    <aside className="card editor-library"><header><p>BLOCK LIBRARY</p><h2>보고서 에디터</h2><span>드래그하거나 버튼을 눌러 블록을 추가하세요.</span></header><section><h3><Sparkles size={14} />자연어로 차트 만들기</h3><textarea aria-label="차트 생성 요청" value={chartPrompt} onChange={(event) => setChartPrompt(event.target.value)} placeholder="예: 객실 매출과 점유율 변화를 비교해줘" /><button onClick={generateChart}><BarChart3 size={14} />차트 생성</button><small className="editor-chart-hint">선택한 블록 다음에 차트가 추가됩니다.</small></section><div className="editor-catalog"><p>기존 보고서 구성</p>{BLOCK_CATALOG.map((block) => <button draggable onClick={() => addBlock(block)} onDragStart={() => setDraggedLibraryItem({ kind: "catalog", value: block })} onDragEnd={() => setDraggedLibraryItem(null)} key={block.key}><span>{block.type === "chart" ? <BarChart3 size={14} /> : <FileOutput size={14} />}</span><div><small>{block.group}</small><b>{block.title}</b><em>{block.description}</em></div><GripVertical size={14} /></button>)}</div><div className="editor-basic"><p>기본 블록</p>{[["heading",Type,"제목"],["text",FileOutput,"텍스트"],["quote",Quote,"인용"],["kpi",Target,"KPI"],["table",Table2,"표"],["divider",Minus,"구분선"]].map(([type,Icon,label]) => <button draggable onClick={() => addBlock({ ...BASIC_BLOCKS[type], origin: "basic" })} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: type })} onDragEnd={() => setDraggedLibraryItem(null)} key={type}><Icon size={14} />{label} 추가</button>)}</div></aside>
    <main className="editor-workspace"><header className="card editor-topbar"><div><button onClick={() => setView("list")}><ArrowLeft size={14} />보고서 목록</button><p>REPORT BLOCK EDITOR</p><h2>{selectedReport.title || `${selectedReport.type} 보고서 · ${selectedReport.period}`}</h2><small>{selectedReport.type} · {selectedReport.period}{importedArtifact?.artifactId ? ` · Artifact ${importedArtifact.artifactId}` : " · LOCAL SYNTHETIC FIXTURE"}</small><div className="demo-steps compact"><b className="done"><Check size={12} />분석 완료</b><span>→</span><b className="done"><Check size={12} />초안 반영</b><span>→</span><b className="active">편집</b><span>→</span><b className={selectedReport.status === "확정" ? "done" : ""}>{selectedReport.status === "확정" && <Check size={12} />}확정</b></div></div><div><span className={`editor-save-state ${saveState}`} role="status"><Check size={13} />{saveState === "saving" ? "변경사항 저장 중" : `${lastSavedAt || "방금"} 자동 저장`}</span><button onClick={() => setView("document")}><Eye size={14} />미리보기</button><button onClick={saveReport}><Save size={14} />저장</button><button className="primary" onClick={finalizeReport}><Check size={14} />{selectedReport.status === "확정" ? "확정 내용 저장" : "보고서 확정"}</button></div></header>{selectedBlock && <section className="card editor-selection-toolbar" aria-label="선택 블록 도구"><div><small>선택된 블록</small><b>{selectedBlock.title}</b><span>{selectedBlock.w}/12 너비 · {selectedBlock.type}</span></div><nav><button disabled={editorBlocks[0]?.id === selectedBlock.id} onClick={() => moveBlockBy(selectedBlock.id, -1)}>위로</button><button disabled={editorBlocks[editorBlocks.length - 1]?.id === selectedBlock.id} onClick={() => moveBlockBy(selectedBlock.id, 1)}>아래로</button><button className={selectedBlock.w === 6 ? "active" : ""} onClick={() => setBlockWidth(selectedBlock.id, 6)}><Columns2 size={13} />6/12</button><button className={selectedBlock.w === 12 ? "active" : ""} onClick={() => setBlockWidth(selectedBlock.id, 12)}><Columns2 size={13} />12/12</button><button onClick={() => duplicateBlock(selectedBlock.id)}><Copy size={13} />복제</button><button className="danger" onClick={() => removeBlock(selectedBlock.id)}><Trash2 size={13} />삭제</button></nav></section>}<section ref={editorCanvasRef} className={`editor-canvas ${draggedLibraryItem || draggedBlockId ? "drop-ready" : ""}`} aria-label="12-column 보고서 초안 배치" onClick={(event) => { if (event.target === event.currentTarget) setSelectedBlockId(null); }} onDragOver={(event) => { event.preventDefault(); if (event.target === event.currentTarget) setDropTarget({ id: null, position: "after" }); }} onDrop={(event) => { event.preventDefault(); if (!dropLibraryItem(dropTarget?.id, dropTarget?.position)) moveBlock(dropTarget?.id, dropTarget?.position); }}>{editorBlocks.length === 0 && <div className="editor-empty-drop">여기에 블록을 놓으세요</div>}{editorBlocks.map((block, index) => <article aria-label={`${block.title} 블록`} aria-selected={selectedBlockId === block.id} className={`card editor-block ${selectedBlockId === block.id ? "selected" : ""} ${block.origin === "basic" ? `editor-block--basic editor-block--${block.type}` : ""} ${draggedBlockId === block.id ? "dragging" : ""} ${dropTarget?.id === block.id ? `drop-${dropTarget.position}` : ""}`} style={{ "--block-x": block.x + 1, "--block-y": block.y + 1, "--block-w": block.w, "--block-h": block.h }} tabIndex={0} onClick={() => setSelectedBlockId(block.id)} onFocus={() => setSelectedBlockId(block.id)} onDragOver={(event) => updateDropTarget(event, block.id)} onDrop={(event) => { event.preventDefault(); event.stopPropagation(); if (!dropLibraryItem(block.id, dropTarget?.position)) moveBlock(block.id, dropTarget?.position); }} key={block.id}><header>{block.origin !== "basic" && <div><GripVertical className="editor-drag-handle" size={16} draggable onDragStart={() => { setDraggedLibraryItem(null); setDraggedBlockId(block.id); }} onDragEnd={() => { setDraggedBlockId(null); setDropTarget(null); }} /><b>{index + 1}. {block.title}</b><small>x{block.x + 1} y{block.y + 1} · {block.w}×{block.h}</small></div>}<nav aria-label={`${block.title} 배치 조정`}><button aria-label={`${block.title} 앞으로 이동`} disabled={index === 0} onClick={() => moveBlockBy(block.id, -1)}>↑</button><button aria-label={`${block.title} 뒤로 이동`} disabled={index === editorBlocks.length - 1} onClick={() => moveBlockBy(block.id, 1)}>↓</button><button aria-label={`${block.title} 너비 줄이기`} onClick={() => resizeBlock(block.id, "w", -1)}>−</button><button aria-label={`${block.title} 너비 늘리기`} onClick={() => resizeBlock(block.id, "w", 1)}><Columns2 size={13} />{block.w}/12</button><button aria-label={`${block.title} 높이 줄이기`} onClick={() => resizeBlock(block.id, "h", -1)}>높이−</button><button aria-label={`${block.title} 높이 늘리기`} onClick={() => resizeBlock(block.id, "h", 1)}>높이+</button><button aria-label={`${block.title} 삭제`} onClick={() => removeBlock(block.id)}><Trash2 size={13} /></button></nav></header>{block.type === "chart" ? <><div className="editor-chart">{block.values.map((value, valueIndex) => <div key={`${block.id}-${valueIndex}`}><b>{value}</b><i style={{ height: `${Math.max(24, (value / Math.max(...block.values)) * 118)}px` }} /><small>{valueIndex + 1}</small></div>)}</div><p>{block.caption}</p><button className="regenerate" onClick={() => notify(`${block.title} 블록을 다시 생성했습니다.`)}><RotateCcw size={13} /></button></> : block.type === "divider" ? <hr /> : <textarea aria-label={`${block.title} 내용`} className={`block-${block.type}`} value={block.content} onChange={(event) => setEditorBlocks((current) => current.map((item) => item.id === block.id ? { ...item, content: event.target.value } : item))} />}</article>)}</section></main><Toast message={toast} />
  </div>;

  return <div className="page-content legacy-report-document generated-preview">
    <div className="legacy-document-actions"><button className="secondary" onClick={() => setView("list")}><ArrowLeft size={14} />보고서 목록</button><div><button onClick={() => setView("editor")}><ArrowLeft size={14} />편집으로 돌아가기</button><button onClick={() => notify("보고서를 다시 생성했습니다.")}><Sparkles size={14} />보고서 갱신</button><button onClick={() => notify("PDF 내보내기를 준비했습니다.")}><Download size={14} />PDF</button><button onClick={() => notify("PPT 내보내기를 준비했습니다.")}><FileOutput size={14} />PPT</button><button onClick={() => notify("경영진 공유 링크를 생성했습니다.")}><Share2 size={14} />공유</button></div></div>
    <section className="card generated-report-cover"><div><small>{selectedReport.type} REPORT · {selectedReport.period}</small><h1>{reportTitleBlock?.content || `${selectedReport.type} 보고서`}</h1><p>검증된 분석 결과와 데이터 출처를 기준 시각과 함께 구성한 보고서입니다.</p></div><dl><div><dt>상태</dt><dd>{selectedReport.status}</dd></div><div><dt>기준 시각</dt><dd>2026-07-30 · Asia/Seoul</dd></div><div><dt>데이터</dt><dd>synthetic · schema 1.0.0</dd></div></dl></section>
    <section className="generated-report-grid" aria-label="생성된 보고서 블록">{generatedReportBlocks.map((block) => <GeneratedReportBlock block={block} number={block.reportNumber} key={block.id} />)}</section>
    {importedArtifact?.artifactId && <div className="demo-steps document"><b className="done"><Check size={12} />분석 완료</b><span>→</span><b className="done"><Check size={12} />초안 반영</b><span>→</span><b className="done"><Check size={12} />편집</b><span>→</span><b className={selectedReport.status === "확정" ? "done" : "active"}>확정</b></div>}
    {/* The actual Report API is rendered by ReportApiPage; this older fixture branch is intentionally inactive.
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
    */}
    <section className="card legacy-cover-strip"><div><span>보고서 유형</span><nav>{["Daily Report", "Weekly Report", "Monthly Report"].map((item) => <button className={period === item ? "active" : ""} onClick={() => setPeriod(item)} key={item}>{item}</button>)}</nav></div><div><span>보고 기간</span><strong>{selectedReport.period}</strong></div><div><span>작성 기준</span><strong>2026.08.10 08:45</strong></div><div><span>검토 대상</span><strong>Sense Place Hotel · 전체 시설</strong></div></section>

    <section className="card legacy-conclusion"><div className="legacy-number">01</div><div><p>VERIFIED ANALYSIS SUMMARY</p><h2>검증 결과 요약</h2><article><Sparkles size={19} /><p>7월 28~30일 객실 매출은 <b>4,520만원에서 4,010만원</b>으로 낮아졌습니다. 같은 기간 직접 예약 비중이 43.5%에서 38.2%로 감소했고, 기업 연회 2건의 일정 변경과 연결된 객실 62박 취소가 함께 관측됐습니다. 이 결과는 인과관계를 확정하지 않으며 관리자 검토가 필요합니다.</p></article></div><aside><small>실행 상태</small><strong>SUCCESS · 3개 원천</strong><span>as_of 2026-07-30 · 관리자 검토 필요</span></aside></section>

    <section className="card legacy-report-section"><SectionHeading number="02" eyebrow="REPORT DEFINITION REVIEW" title="보고서 정의 검토 안건" description="근거·기준 시각·실패 처리 정책을 확인한 뒤 승인 또는 보류해 주세요." meta={`${Object.keys(decisions).length} / ${DECISIONS.length} 결정`} /><div className="legacy-decision-list">{DECISIONS.map((item) => <article className={decisions[item.id] ? `is-${decisions[item.id]}` : ""} key={item.id}><div className="legacy-rank"><span>{String(item.id).padStart(2, "0")}</span><i>{item.priority}</i></div><div><h3>{item.title}</h3><p>{item.reason}</p><dl><div><dt>효과</dt><dd>{item.impact}</dd></div><div><dt>실행 조건</dt><dd>{item.condition}</dd></div><div><dt>판단 근거</dt><dd>{item.evidence}</dd></div><div><dt>담당</dt><dd>{item.owner}</dd></div></dl></div><footer>{decisions[item.id] ? <><Check size={15} /><b>{decisions[item.id] === "approved" ? "승인됨" : "보류됨"}</b><button onClick={() => setDecisions((current) => ({ ...current, [item.id]: null }))}>변경</button></> : <><button className="approve" onClick={() => setDecisions((current) => ({ ...current, [item.id]: "approved" }))}>승인</button><button onClick={() => setDecisions((current) => ({ ...current, [item.id]: "held" }))}>보류</button></>}</footer></article>)}</div></section>

    <section className="card legacy-report-section"><SectionHeading number="03" eyebrow="EVIDENCE & RUN CONDITIONS" title="분석 근거·실행 조건 검토" description="보고서 정의에 포함할 Artifact, 원천, 기준 시각을 확인합니다." meta="Synthetic fixture" /><div className="legacy-response-layout"><div className="legacy-options"><h3>근거 선택 <small>복수 선택 가능</small></h3>{RESPONSE_OPTIONS.map((option) => { const selected = selectedOptions.includes(option.id); return <button className={selected ? "selected" : ""} onClick={() => setSelectedOptions((current) => selected ? current.filter((id) => id !== option.id) : [...current, option.id])} key={option.id}><span>{selected && <Check size={12} />}</span><div><b>{option.label}</b><small>{option.description}</small><em>{option.detail}</em></div></button>; })}</div><div className="legacy-impact"><p>선택 조건 요약</p><div><span>선택 근거<strong>{selectedOptions.length}개</strong></span><span>성공 원천<strong>PMS · CRM · Banquet</strong></span><span>기준 시각<strong>2026-07-30</strong></span></div><article><small>보고서 실행 상태</small><strong>검토 필요</strong><p>선택 내용은 보고서 정의 초안에만 반영되며 승인 전에는 예약 실행되지 않습니다.</p></article></div></div><div className="legacy-manager-review"><label>관리자 검토 메모<textarea value={memo} onChange={(event) => setMemo(event.target.value)} placeholder="선택 사유와 추가 확인 사항을 기록하세요." /></label><p><Info size={13} />승인은 정의 승인 후보 등록이며 실제 보고서 실행을 자동 시작하지 않습니다.</p><div>{["승인", "보류", "반려"].map((status) => <button className={responseDecision === status ? "active" : ""} onClick={() => setResponseDecision(status)} key={status}>{status}</button>)}</div></div></section>

    <div className="legacy-two-column"><section className="card legacy-report-section"><SectionHeading number="04" eyebrow="VERIFIED METRICS" title="검증된 핵심 지표" /><div className="legacy-performance"><div><span>지표</span><span>값</span><span>조건</span><span>근거</span><span>상태</span></div>{PERFORMANCE.map(([metric,current,target,change,status,tone]) => <div key={metric}><b>{metric}</b><strong>{current}</strong><span>{target}</span><em>{change}</em><i className={tone}>{status}</i></div>)}</div></section><section className="card legacy-report-section"><SectionHeading number="05" eyebrow="INTERPRETATION BOUNDARY" title="결과 해석과 한계" /><div className="legacy-issue"><header><AlertTriangle size={18} /><div><small>관측된 변화</small><h3>객실·예약 채널·연회 일정 동시 변화</h3></div><b>확인</b></header><p>7월 28~30일 객실 매출과 점유율, 직접 예약 비중이 함께 낮아졌고 기업 연회 2건의 일정 변경과 연계 객실 62박 취소가 확인됐습니다. 이 화면은 관측된 연관성을 설명하며 특정 요인을 원인으로 확정하지 않습니다.</p><dl><div><dt>분석 기간</dt><dd>2026-07-28~07-30</dd></div><div><dt>기준 시각</dt><dd>2026-07-30</dd></div><div><dt>결과 식별자</dt><dd>fixture-query-success</dd></div><div><dt>데이터 성격</dt><dd>synthetic fixture</dd></div></dl></div></section></div>

    <section className="card legacy-report-section"><SectionHeading number="06" eyebrow="SOURCE TRACE" title="데이터 출처 추적" description="표시된 수치가 어떤 원천과 실행 식별자에서 왔는지 확인합니다." meta="DataHub metadata · Trino read-only" /><div className="legacy-hotel-table"><div><span>원천</span><span>시스템</span><span>사용 범위</span><span>상태</span><span>근거 식별자</span></div>{SOURCE_TRACE.map(([source,system,scope,status,evidence]) => <div key={source}><span><b>{source}</b><small>synthetic</small></span><strong>{system}</strong><strong>{scope}</strong><strong>{status}</strong><strong>{evidence}</strong></div>)}</div><p className="legacy-boundary"><Info size={13} />DataHub는 메타데이터 기준 시스템, Trino는 읽기 전용 연합 조회 엔진입니다. 화면은 API가 반환한 근거를 재계산하지 않고 표시합니다.</p></section>

    <section className="card legacy-report-section"><SectionHeading number="07" eyebrow="REPORT RUN TRACKER" title="보고서 실행 단계" description="Artifact 연결부터 정의 승인, 수동 실행, 스케줄 활성화까지 상태를 구분합니다." /><div className="legacy-actions"><div><span>실행 단계</span><span>담당</span><span>근거·조건</span><span>상태</span><span>다음 단계</span></div>{ACTIONS.map(([task,owner,evidence,status,next]) => <div key={task}><b>{task}</b><span>{owner}</span><span>{evidence}</span><i>{status}</i><span>{next}</span></div>)}</div></section>

    <section className="card legacy-report-section"><SectionHeading number="08" eyebrow="RUN STATUS CONTRACT" title="보고서 실행 상태 처리" description="미래 추정값 대신 실제 실행 결과의 성공·부분 성공·실패 상태를 명확히 구분합니다." /><div className="legacy-scenarios"><article className="recommended"><span><Check size={17} />SUCCESS</span><strong>전체 블록 표시</strong><p>모든 원천과 블록이 같은 기준 시각으로 완료되며 Artifact 참조를 보존합니다.</p><i>현재 fixture 상태</i></article><article><span><AlertTriangle size={17} />PARTIAL_SUCCESS</span><strong>실패 블록 분리</strong><p>성공 결과와 실패 원천을 함께 표시하고 마지막 성공값 사용 여부를 명시합니다.</p><i>관리자 확인 필요</i></article><article><span><Target size={17} />FAILED</span><strong>결과 승격 금지</strong><p>실패 실행은 정상 보고서로 확정하지 않고 기존 근거를 보존한 채 재시도합니다.</p><i>오류 원인 기록</i></article></div></section>

    <footer className="card legacy-methodology"><Info size={15} /><div><b>분석 기준 및 한계</b><p>Hotel PMS, Membership CRM, Banquet Sales의 합성 데이터를 사용했으며 seed 20260729, schema 1.0.0, as_of 2026-07-30을 기록했습니다. DataHub URN과 Trino FQN으로 출처를 추적하며, 관측된 변화는 인과관계나 미래 값으로 해석하지 않습니다.</p></div><button className="primary" onClick={() => notify("검토용 공유 링크를 생성했습니다.")}><Send size={14} />검토자에게 공유</button></footer><Toast message={toast} />
  </div>;
}

export function ReportsPage() {
  return usesFixtureReportClient ? <FixtureReportsPage /> : <ReportApiPage />;
}
