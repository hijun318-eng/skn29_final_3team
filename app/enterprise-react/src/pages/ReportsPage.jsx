import { useMemo, useState } from "react";
import {
  AlertTriangle, ArrowLeft, BarChart3, Building2, Check, ChevronRight,
  Columns2, Download, FileOutput, FilePlus2, GripVertical, Info, Minus,
  Quote, RotateCcw, Save, Send, Share2, Sparkles, Table2, Target, Trash2,
  TrendingDown, TrendingUp, Type,
} from "lucide-react";
import { SYNTHETIC_META } from "../data/enterpriseDemoData";

const REPORTS = [
  { id: 1, type: "주간", period: "07/21~07/27", status: "초안", author: "박준희", updated: "10분 전 수정" },
  { id: 2, type: "주간", period: "07/14~07/20", status: "확정", author: "박준희", updated: "07.21 확정" },
  { id: 3, type: "주간", period: "07/07~07/13", status: "확정", author: "박준희", updated: "07.14 확정" },
  { id: 4, type: "월간", period: "2026년 06월", status: "확정", author: "박준희", updated: "07.03 확정" },
  { id: 5, type: "분기", period: "2026 Q2", status: "확정", author: "CX 운영팀", updated: "07.05 확정" },
];

const DECISIONS = [
  { id: 1, priority: "우선 결정", title: "주말 조식 탄력 인력 2명 상시 배치", reason: "최근 4주 중 3주간 08:00~09:00 평균 대기시간이 목표 10분을 초과했습니다.", impact: "대기시간 16분 → 9분", cost: "월 인건비 +320만원", evidence: "VOC 184건 · 운영 로그 28일", owner: "식음부" },
  { id: 2, priority: "승인 필요", title: "피크 시간 임시 좌석 24석 운영", reason: "좌석 부족이 조식 부정 VOC의 41%를 차지하며 단체 고객 입장 시 반복적으로 증가합니다.", impact: "혼잡도 약 21% 감소", cost: "초기 비용 480만원", evidence: "부정 VOC 76건 · 좌석 회전율", owner: "식음부·시설부" },
  { id: 3, priority: "정책 검토", title: "단체 고객 조식 입장시간 분산", reason: "20인 이상 단체가 15분 이내 동시 입장할 경우 일반 고객 대기시간이 평균 7분 증가합니다.", impact: "일반 고객 만족도 +8%p", cost: "예약 안내 정책 변경", evidence: "단체 예약 12건 · 대기 데이터", owner: "객실부·예약실" },
];

const RESPONSE_OPTIONS = [
  { id: "staff", label: "운영 인력 +2명", description: "피크 시간 서비스 인력 보강", cost: 64000, wait: 4, voc: 2 },
  { id: "seats", label: "임시 좌석 +20석", description: "가용 공간에 임시 좌석 배치", cost: 32000, wait: 2, voc: 2 },
  { id: "group", label: "단체 고객 입장 15분 분산", description: "단체별 입장 시간을 순차 안내", cost: 0, wait: 3, voc: 3 },
  { id: "guide", label: "안내 직원 1명 배치", description: "대기열 분기와 좌석 안내 지원", cost: 28000, wait: 1, voc: 1 },
];

const PERFORMANCE = [
  ["고객 만족도", "4.7 / 5", "4.6", "+0.2", "목표 초과", "positive"],
  ["부정 VOC 비율", "18.2%", "15% 이하", "-2.4%p", "개선 필요", "warning"],
  ["평균 대기시간", "8분", "10분 이하", "-5분", "목표 달성", "positive"],
  ["VOC 조치 완료율", "86%", "90%", "+7%p", "목표 근접", "neutral"],
  ["평균 최초 응답", "22분", "30분 이하", "-11분", "목표 달성", "positive"],
];

const ACTIONS = [
  ["조식 인력 재배치 시범 운영", "식음부 김도윤", "08.12", "진행 중", 65],
  ["임시 좌석 동선 안전 검토", "시설부 박선우", "08.14", "검토 중", 30],
  ["단체 예약 안내 문구 개정", "예약실 이서연", "08.16", "예정", 0],
  ["조식 혼잡 알림 자동화", "CX 운영팀", "08.18", "진행 중", 48],
];

const HOTELS = [
  ["SENSE PLACE 서울", 18.2, 8, 4.7, 86, 1240],
  ["그랜드 플레이스", 24.8, 13, 4.4, 74, 986],
  ["비스타 플레이스", 15.1, 7, 4.8, 91, 812],
  ["리버사이드", 27.4, 16, 4.2, 69, 678],
  ["포레스트 빌라", 19.7, 9, 4.6, 83, 544],
];

const BLOCK_CATALOG = [
  { key: "executive-summary", group: "경영 요약", title: "경영진 종합 결론", description: "운영 상태와 최우선 권고안 요약", type: "summary", span: 2, content: "이번 주 호텔 운영은 전반적으로 안정적이었으며 고객 만족도는 상승했습니다. 주말 조식 피크 시간대 탄력 인력 운영을 정규 정책으로 전환할 것을 권고합니다." },
  { key: "decisions", group: "의사결정", title: "결정 필요 안건", description: "승인·보류가 필요한 운영 안건", type: "text", span: 2, content: "1. 주말 조식 탄력 인력 2명 상시 배치\n2. 피크 시간 임시 좌석 24석 운영\n3. 단체 고객 조식 입장시간 분산" },
  { key: "response-review", group: "의사결정", title: "운영 대응안 검토", description: "대응안 선택과 예상 효과 비교", type: "text", span: 2, content: "선택 대응안: 인력 추가 배치, 임시 좌석 운영\n예상 효과: 평균 대기시간 18분 → 12분\n관리자 검토 의견을 입력하세요." },
  { key: "performance", group: "성과 분석", title: "목표 대비 주요 성과", description: "만족도·VOC·대기시간 핵심 KPI", type: "chart", span: 1, values: [94, 82, 86, 73, 90], caption: "고객 만족도 · 부정 VOC · 평균 대기시간 · 조치 완료율 · 최초 응답" },
  { key: "issues", group: "성과 분석", title: "핵심 이슈와 근거", description: "집중 이슈의 원인과 운영 영향", type: "text", span: 1, content: "집중 이슈: 조식 혼잡 및 좌석 부족\n직접 원인: 점유율 92% 초과\n촉발 요인: 단체 고객 동시 입장\n분석 신뢰도: 96%" },
  { key: "hotel-benchmark", group: "비교 분석", title: "호텔별 비교 인사이트", description: "호텔별 VOC·대기·만족도 비교", type: "chart", span: 2, values: [18, 24, 15, 27, 20], caption: "호텔별 부정 VOC 비율 비교 · synthetic data" },
  { key: "action-tracker", group: "실행 관리", title: "결정 이후 실행 과제", description: "담당자·목표일·진척도 관리", type: "text", span: 2, content: "조식 인력 재배치 시범 운영 · 진행 중 65%\n임시 좌석 동선 안전 검토 · 검토 중 30%\n단체 예약 안내 문구 개정 · 예정 0%" },
  { key: "outlook", group: "전망", title: "다음 주 전망과 시나리오", description: "기본·개선·위험 시나리오", type: "chart", span: 2, values: [68, 81, 43], caption: "기본 전망 · 권고안 적용 · 위험 시나리오 발생 가능성" },
];

const BASIC_BLOCKS = {
  heading: { type: "heading", title: "새 제목", content: "보고서 제목을 입력하세요.", span: 2 },
  text: { type: "text", title: "새 텍스트", content: "클릭해 내용을 입력하세요.", span: 2 },
  quote: { type: "quote", title: "인용", content: "강조할 인사이트나 고객의 목소리를 입력하세요.", span: 1 },
  kpi: { type: "kpi", title: "KPI 카드", content: "핵심 지표 12.4분 · 전주 대비 +2.1분", span: 1 },
  table: { type: "table", title: "데이터 표", content: "항목 | 현재 | 목표\n대기시간 | 12.4분 | 10분\nVOC | 18건 | 12건", span: 2 },
  divider: { type: "divider", title: "구분선", content: "", span: 2 },
};

const INITIAL_BLOCKS = BLOCK_CATALOG.slice(0, 5).map((block, index) => ({ ...block, id: `${block.key}-${index}` }));

function Toast({ message }) {
  return message ? <div className="enterprise-toast"><Check size={14} />{message}</div> : null;
}

function SectionHeading({ number, eyebrow, title, description, meta }) {
  return <header className="legacy-section-heading"><span>{number}</span><div><p>{eyebrow}</p><h2>{title}</h2>{description && <small>{description}</small>}</div>{meta && <b>{meta}</b>}</header>;
}

export function ReportsPage() {
  const [view, setView] = useState("list");
  const [typeFilter, setTypeFilter] = useState("전체");
  const [statusFilter, setStatusFilter] = useState("전체");
  const [selectedReport, setSelectedReport] = useState(REPORTS[0]);
  const [period, setPeriod] = useState("Weekly Report");
  const [decisions, setDecisions] = useState({});
  const [selectedOptions, setSelectedOptions] = useState(["staff", "seats"]);
  const [responseDecision, setResponseDecision] = useState("");
  const [memo, setMemo] = useState("");
  const [toast, setToast] = useState("");
  const [editorBlocks, setEditorBlocks] = useState(INITIAL_BLOCKS);
  const [draggedBlockId, setDraggedBlockId] = useState(null);
  const [draggedLibraryItem, setDraggedLibraryItem] = useState(null);
  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 1800); };
  const filteredReports = REPORTS.filter((report) => (typeFilter === "전체" || report.type === typeFilter) && (statusFilter === "전체" || report.status === statusFilter));
  const result = useMemo(() => {
    const options = RESPONSE_OPTIONS.filter((option) => selectedOptions.includes(option.id));
    return { wait: Math.max(7, 18 - options.reduce((sum, item) => sum + item.wait, 0)), voc: Math.max(4, 13 - options.reduce((sum, item) => sum + item.voc, 0)), cost: options.reduce((sum, item) => sum + item.cost, 0) };
  }, [selectedOptions]);
  const openReport = (report) => { setSelectedReport(report); setView(report.status === "초안" ? "editor" : "document"); };
  const createBlock = (item) => ({ ...item, id: `${item.key || item.type}-${Date.now()}-${Math.random().toString(16).slice(2)}` });
  const dropLibraryItem = (targetId) => {
    if (!draggedLibraryItem) return false;
    const block = createBlock(draggedLibraryItem.kind === "catalog" ? draggedLibraryItem.value : BASIC_BLOCKS[draggedLibraryItem.value]);
    setEditorBlocks((current) => {
      if (!targetId) return [...current, block];
      const targetIndex = current.findIndex((item) => item.id === targetId);
      const next = [...current];
      next.splice(targetIndex < 0 ? next.length : targetIndex, 0, block);
      return next;
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
      return next;
    });
    setDraggedBlockId(null);
  };

  if (view === "list") return <div className="page-content enterprise-reports-list">
    <div className="meta-strip"><Info size={13} />{SYNTHETIC_META.label}<span>seed {SYNTHETIC_META.seed}</span><span>schema {SYNTHETIC_META.schemaVersion}</span></div>
    <div className="legacy-report-toolbar"><button className="primary" onClick={() => { setSelectedReport(REPORTS[0]); setView("editor"); }}><FilePlus2 size={15} />새 보고서</button><label>유형<select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option>전체</option><option>주간</option><option>월간</option><option>분기</option></select></label><label>상태<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>전체</option><option>초안</option><option>확정</option></select></label></div>
    <section className="card legacy-report-list"><div className="legacy-report-row legacy-report-head"><span>유형</span><span>기간</span><span>상태</span><span>작성자</span><span>최근 변경</span><span>동작</span></div>{filteredReports.map((report) => <article className="legacy-report-row" key={report.id} onClick={() => openReport(report)}><strong>{report.type}</strong><b>{report.period}</b><span><i className={`legacy-report-status ${report.status === "초안" ? "draft" : "final"}`}><em />{report.status}</i></span><span>{report.author}</span><span>{report.updated}</span><button onClick={(event) => { event.stopPropagation(); openReport(report); }}>{report.status === "초안" ? "편집" : "열람"} <ChevronRight size={13} /></button></article>)}</section>
    <p className="legacy-report-guide">행을 선택해 보고서를 열람할 수 있습니다. 초안은 검토 후 확정하며, 확정 보고서는 읽기 전용입니다.</p>
  </div>;

  if (view === "editor") return <div className="enterprise-report-editor">
    <aside className="card editor-library"><header><p>BLOCK LIBRARY</p><h2>보고서 에디터</h2><span>블록을 문서로 끌어 배치하세요.</span></header><section><h3><Sparkles size={14} />자연어로 차트 만들기</h3><textarea placeholder="예: 지난달 객실동 소음 VOC 추이 차트" /><button onClick={() => setEditorBlocks((current) => [...current, createBlock({ ...BASIC_BLOCKS.kpi, type: "chart", title: "AI 생성 차트", values: [8, 12, 10, 16, 13, 18, 14], caption: "자연어 요청 기반 synthetic chart" })])}><BarChart3 size={14} />차트 생성</button></section><div className="editor-catalog"><p>기존 보고서 구성</p>{BLOCK_CATALOG.map((block) => <button draggable onDragStart={() => setDraggedLibraryItem({ kind: "catalog", value: block })} onDragEnd={() => setDraggedLibraryItem(null)} key={block.key}><span>{block.type === "chart" ? <BarChart3 size={14} /> : <FileOutput size={14} />}</span><div><small>{block.group}</small><b>{block.title}</b><em>{block.description}</em></div><GripVertical size={14} /></button>)}</div><div className="editor-basic"><p>기본 블록</p>{[["heading",Type,"제목"],["text",FileOutput,"텍스트"],["quote",Quote,"인용"],["kpi",Target,"KPI"],["table",Table2,"표"],["divider",Minus,"구분선"]].map(([type,Icon,label]) => <button draggable onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: type })} onDragEnd={() => setDraggedLibraryItem(null)} key={type}><Icon size={14} />{label}</button>)}</div></aside>
    <main className="editor-workspace"><header className="card editor-topbar"><div><button onClick={() => setView("list")}><ArrowLeft size={14} />보고서 목록</button><p>REPORT BLOCK EDITOR</p><h2>{selectedReport.type} 보고서 · {selectedReport.period}</h2></div><div><span><Check size={13} />자동 저장됨</span><button onClick={() => notify("PDF 내보내기를 준비했습니다.")}><Download size={14} />PDF</button><button className="primary" onClick={() => { notify("보고서를 확정했습니다."); }}><Save size={14} />확정</button></div></header><section className={`editor-canvas ${draggedLibraryItem ? "drop-ready" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); dropLibraryItem(); }}>{editorBlocks.map((block, index) => <article className={`card editor-block span-${block.span || 2} ${draggedBlockId === block.id ? "dragging" : ""}`} draggable onDragStart={() => { setDraggedLibraryItem(null); setDraggedBlockId(block.id); }} onDragEnd={() => setDraggedBlockId(null)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.stopPropagation(); if (!dropLibraryItem(block.id)) moveBlock(block.id); }} key={block.id}><header><div><GripVertical size={16} /><b>{index + 1}. {block.title}</b></div><nav><button onClick={() => setEditorBlocks((current) => current.map((item) => item.id === block.id ? { ...item, span: (item.span || 2) === 2 ? 1 : 2 } : item))}><Columns2 size={13} />{block.span || 2}칸</button><button onClick={() => setEditorBlocks((current) => current.filter((item) => item.id !== block.id))}><Trash2 size={13} /></button></nav></header>{block.type === "chart" ? <><div className="editor-chart">{block.values.map((value, valueIndex) => <div key={`${block.id}-${valueIndex}`}><b>{value}</b><i style={{ height: `${Math.max(24, (value / Math.max(...block.values)) * 118)}px` }} /><small>{valueIndex + 1}</small></div>)}</div><p>{block.caption}</p><button className="regenerate" onClick={() => notify(`${block.title} 블록을 다시 생성했습니다.`)}><RotateCcw size={13} /></button></> : block.type === "divider" ? <hr /> : <textarea className={`block-${block.type}`} value={block.content} onChange={(event) => setEditorBlocks((current) => current.map((item) => item.id === block.id ? { ...item, content: event.target.value } : item))} />}</article>)}</section></main><Toast message={toast} />
  </div>;

  return <div className="page-content legacy-report-document">
    <div className="legacy-document-actions"><button className="secondary" onClick={() => setView("list")}><ArrowLeft size={14} />보고서 목록</button><div><button onClick={() => notify("보고서를 다시 생성했습니다.")}><Sparkles size={14} />보고서 갱신</button><button onClick={() => notify("PDF 내보내기를 준비했습니다.")}><Download size={14} />PDF</button><button onClick={() => notify("PPT 내보내기를 준비했습니다.")}><FileOutput size={14} />PPT</button><button onClick={() => notify("경영진 공유 링크를 생성했습니다.")}><Share2 size={14} />공유</button></div></div>
    <section className="card legacy-cover-strip"><div><span>보고서 유형</span><nav>{["Daily Report", "Weekly Report", "Monthly Report"].map((item) => <button className={period === item ? "active" : ""} onClick={() => setPeriod(item)} key={item}>{item}</button>)}</nav></div><div><span>보고 기간</span><strong>{selectedReport.period}</strong></div><div><span>작성 기준</span><strong>2026.08.10 08:45</strong></div><div><span>검토 대상</span><strong>SENSE PLACE 서울 · 전체 시설</strong></div></section>

    <section className="card legacy-conclusion"><div className="legacy-number">01</div><div><p>EXECUTIVE CONCLUSION</p><h2>경영진 종합 결론</h2><article><Sparkles size={19} /><p>이번 주 호텔 운영은 전반적으로 안정적이었으며 고객 만족도는 전주보다 0.2점 상승했습니다. 다만 주말 조식 피크 시간대의 좌석 부족과 단체 고객 동시 입장이 반복적인 부정 VOC를 유발하고 있습니다. 현장 인력 추가 배치는 대기시간을 평균 7분 단축해 효과가 확인되었으므로, <b>주말 탄력 인력 운영을 정규 정책으로 전환하는 결정을 권고합니다.</b></p></article></div><aside><small>종합 운영 판단</small><strong>안정 · 일부 개선 필요</strong><span>AI 신뢰도 96% · 관리자 검토 필요</span></aside></section>

    <section className="card legacy-report-section"><SectionHeading number="02" eyebrow="DECISION REQUIRED" title="이번 회의에서 결정할 안건" description="근거와 예상 효과를 확인한 뒤 승인 또는 보류해 주세요." meta={`${Object.keys(decisions).length} / ${DECISIONS.length} 결정`} /><div className="legacy-decision-list">{DECISIONS.map((item) => <article className={decisions[item.id] ? `is-${decisions[item.id]}` : ""} key={item.id}><div className="legacy-rank"><span>{String(item.id).padStart(2, "0")}</span><i>{item.priority}</i></div><div><h3>{item.title}</h3><p>{item.reason}</p><dl><div><dt>예상 효과</dt><dd>{item.impact}</dd></div><div><dt>비용·변경</dt><dd>{item.cost}</dd></div><div><dt>판단 근거</dt><dd>{item.evidence}</dd></div><div><dt>담당</dt><dd>{item.owner}</dd></div></dl></div><footer>{decisions[item.id] ? <><Check size={15} /><b>{decisions[item.id] === "approved" ? "승인됨" : "보류됨"}</b><button onClick={() => setDecisions((current) => ({ ...current, [item.id]: null }))}>변경</button></> : <><button className="approve" onClick={() => setDecisions((current) => ({ ...current, [item.id]: "approved" }))}>승인</button><button onClick={() => setDecisions((current) => ({ ...current, [item.id]: "held" }))}>보류</button></>}</footer></article>)}</div></section>

    <section className="card legacy-report-section"><SectionHeading number="03" eyebrow="OPERATION RESPONSE REVIEW" title="운영 대응안 검토" description="조식 혼잡 이슈의 대응안을 선택하고 예상 효과를 비교합니다." meta="Synthetic scenario" /><div className="legacy-response-layout"><div className="legacy-options"><h3>대응안 선택 <small>복수 선택 가능</small></h3>{RESPONSE_OPTIONS.map((option) => { const selected = selectedOptions.includes(option.id); return <button className={selected ? "selected" : ""} onClick={() => setSelectedOptions((current) => selected ? current.filter((id) => id !== option.id) : [...current, option.id])} key={option.id}><span>{selected && <Check size={12} />}</span><div><b>{option.label}</b><small>{option.description}</small><em>{option.cost ? `${option.cost.toLocaleString("ko-KR")}원` : "추가 비용 없음"}</em></div></button>; })}</div><div className="legacy-impact"><p>예상 효과 비교</p><div><span>평균 대기시간<strong>18분 → {result.wait}분</strong></span><span>부정 VOC<strong>13건 → {result.voc}건</strong></span><span>추가 비용<strong>{result.cost.toLocaleString("ko-KR")}원</strong></span></div><article><small>예상 운영 상태</small><strong>{result.wait <= 10 ? "정상" : result.wait <= 14 ? "주의" : "위험"}</strong><p>선택된 대응안의 과거 유사 운영 결과를 기반으로 한 추정치입니다.</p></article></div></div><div className="legacy-manager-review"><label>관리자 검토 메모<textarea value={memo} onChange={(event) => setMemo(event.target.value)} placeholder="선택 사유와 추가 확인 사항을 기록하세요." /></label><p><Info size={13} />승인은 실행 후보 등록이며 실제 운영 조치를 자동 실행하지 않습니다.</p><div>{["승인", "보류", "반려"].map((status) => <button className={responseDecision === status ? "active" : ""} onClick={() => setResponseDecision(status)} key={status}>{status}</button>)}</div></div></section>

    <div className="legacy-two-column"><section className="card legacy-report-section"><SectionHeading number="04" eyebrow="PERFORMANCE REVIEW" title="목표 대비 주요 성과" /><div className="legacy-performance"><div><span>지표</span><span>현재</span><span>목표</span><span>전주 대비</span><span>판단</span></div>{PERFORMANCE.map(([metric,current,target,change,status,tone]) => <div key={metric}><b>{metric}</b><strong>{current}</strong><span>{target}</span><em>{change}</em><i className={tone}>{status}</i></div>)}</div></section><section className="card legacy-report-section"><SectionHeading number="05" eyebrow="KEY ISSUE ANALYSIS" title="핵심 이슈와 근거" /><div className="legacy-issue"><header><AlertTriangle size={18} /><div><small>이번 주 집중 이슈</small><h3>조식 혼잡 및 좌석 부족</h3></div><b>높음</b></header><p>부정 VOC 184건 중 76건이 조식과 관련되었으며, 그중 41%가 좌석 부족을 언급했습니다. 문제는 토·일요일 08:00~09:00에 집중되었습니다.</p><dl><div><dt>직접 원인</dt><dd>점유율 92% 초과</dd></div><div><dt>촉발 요인</dt><dd>단체 고객 동시 입장</dd></div><div><dt>운영 영향</dt><dd>대기시간 최대 16분</dd></div><div><dt>분석 신뢰도</dt><dd>96%</dd></div></dl></div></section></div>

    <section className="card legacy-report-section"><SectionHeading number="06" eyebrow="HOTEL BENCHMARK INSIGHT" title="호텔별 비교 인사이트" description="호텔 간 차이를 같은 기준으로 비교해 우선순위와 확산 가능한 운영 방식을 제안합니다." meta="Synthetic · hotel-comparison-v1" /><div className="legacy-hotel-table"><div><span>호텔</span><span>부정 VOC</span><span>평균 대기</span><span>만족도</span><span>조치 완료율</span></div>{HOTELS.map(([hotel,negative,wait,satisfaction,resolution,count]) => <div className={negative >= 25 ? "risk" : ""} key={hotel}><span><Building2 size={14} /><b>{hotel}</b><small>{count.toLocaleString()}건 분석</small></span><span><b>{negative}%</b><i><em style={{ width: `${negative}%` }} /></i></span><strong>{wait}분</strong><strong>{satisfaction} / 5</strong><strong>{resolution}%</strong></div>)}</div><p className="legacy-boundary"><Info size={13} />비교 결과는 합성 데이터 기반이며 호텔별 표본 수와 채널 구성이 달라 단순 순위만으로 성과를 확정하지 않습니다.</p></section>

    <section className="card legacy-report-section"><SectionHeading number="07" eyebrow="EXECUTION TRACKER" title="결정 이후 실행 과제" description="담당자와 완료 목표일을 기준으로 후속 실행을 관리합니다." /><div className="legacy-actions"><div><span>실행 과제</span><span>담당</span><span>완료 목표</span><span>상태</span><span>진척도</span></div>{ACTIONS.map(([task,owner,due,status,progress]) => <div key={task}><b>{task}</b><span>{owner}</span><span>{due}</span><i>{status}</i><strong><em style={{ width: `${progress}%` }} />{progress}%</strong></div>)}</div></section>

    <section className="card legacy-report-section"><SectionHeading number="08" eyebrow="OUTLOOK & SCENARIO" title="다음 주 전망과 시나리오" description="현재 예약과 운영 계획을 기준으로 산출한 전망입니다." /><div className="legacy-scenarios"><article><span><TrendingUp size={17} />기본 전망</span><strong>점유율 89%</strong><p>현재 인력 계획 유지 시 평균 대기시간은 12분으로 예상됩니다.</p><i>발생 가능성 68%</i></article><article className="recommended"><span><Target size={17} />권장안 적용</span><strong>대기시간 8분</strong><p>탄력 인력과 임시 좌석을 함께 운영하면 만족도 4.8점이 예상됩니다.</p><i>권장 시나리오</i></article><article><span><TrendingDown size={17} />위험 시나리오</span><strong>대기시간 18분</strong><p>단체 2팀 동시 입장과 추가 인력 부재 시 부정 VOC가 증가할 수 있습니다.</p><i>발생 가능성 21%</i></article></div></section>

    <footer className="card legacy-methodology"><Info size={15} /><div><b>분석 기준 및 한계</b><p>예약 데이터, POS, 운영 로그, QR 피드백, 푸시 설문, 직원 보고, 온라인 리뷰를 채널별로 분리 분석했습니다. 예상 효과는 과거 유사 운영 조치에 기반한 추정치입니다.</p></div><button className="primary" onClick={() => notify("경영진 공유 링크를 생성했습니다.")}><Send size={14} />경영진에게 공유</button></footer><Toast message={toast} />
  </div>;
}
