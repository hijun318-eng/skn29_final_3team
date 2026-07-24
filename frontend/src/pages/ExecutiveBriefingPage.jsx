import { useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, BarChart3, Building2, Check, ChevronRight, Columns2, Download, FileOutput, FilePlus2, GripVertical, Info, Minus, Plus, Quote, RotateCcw, Save, Send, Share2, Sparkles, Table2, Target, Trash2, TrendingDown, TrendingUp, Type } from "lucide-react";
import { Sidebar } from "../components/layout/Sidebar";
import { HeaderUtilities } from "../components/layout/Header";
import { HOTEL_COMPARISON_DATA, HOTEL_COMPARISON_INSIGHTS, HOTEL_COMPARISON_META } from "../components/charts/hotelComparisonData";
import { ImpactComparison } from "../components/simulation/ImpactComparison";
import { responseOptions } from "../components/map/operationMapData";
import "../styles/executive-briefing.css";

const DECISIONS = [
  { id: 1, priority: "우선 결정", title: "주말 조식 탄력 인력 2명 상시 배치", reason: "최근 4주 중 3주간 08:00~09:00 평균 대기시간이 목표 10분을 초과했습니다.", impact: "대기시간 16분 → 9분", cost: "월 인건비 +320만원", evidence: "VOC 184건 · 운영 로그 28일", owner: "식음부" },
  { id: 2, priority: "승인 필요", title: "피크 시간 임시 좌석 24석 운영", reason: "좌석 부족이 조식 부정 VOC의 41%를 차지하며 단체 고객 입장 시 반복적으로 증가합니다.", impact: "혼잡도 약 21% 감소", cost: "초기 비용 480만원", evidence: "부정 VOC 76건 · 좌석 회전율", owner: "식음부·시설부" },
  { id: 3, priority: "정책 검토", title: "단체 고객 조식 입장시간 분산", reason: "20인 이상 단체가 15분 이내 동시 입장할 경우 일반 고객 대기시간이 평균 7분 증가합니다.", impact: "일반 고객 만족도 +8%p", cost: "예약 안내 정책 변경", evidence: "단체 예약 12건 · 대기 데이터", owner: "객실부·예약실" },
];

const PERFORMANCE = [
  ["고객 만족도", "4.7 / 5", "4.6", "+0.2", "목표 초과", "positive"],
  ["부정 VOC 비율", "18.2%", "15% 이하", "-2.4%p", "개선 필요", "warning"],
  ["평균 대기시간", "8분", "10분 이하", "-5분", "목표 달성", "positive"],
  ["VOC 조치 완료율", "86%", "90%", "+7%p", "목표 근접", "neutral"],
  ["평균 최초 응답", "22분", "30분 이하", "-11분", "목표 달성", "positive"],
];

const ACTIONS = [
  ["조식 인력 재배치 시범 운영", "식음부 김도윤", "08.12", "진행 중", "65%"],
  ["임시 좌석 동선 안전 검토", "시설부 박선우", "08.14", "검토 중", "30%"],
  ["단체 예약 안내 문구 개정", "예약실 이서연", "08.16", "예정", "0%"],
  ["조식 혼잡 알림 자동화", "CX 운영팀", "08.18", "진행 중", "48%"],
];

const REPORTS = [
  { id: 1, type: "주간", period: "07/21~07/27", status: "초안", author: "박준희", updated: "10분 전 수정" },
  { id: 2, type: "주간", period: "07/14~07/20", status: "확정", author: "박준희", updated: "07.21 확정" },
  { id: 3, type: "주간", period: "07/07~07/13", status: "확정", author: "박준희", updated: "07.14 확정" },
  { id: 4, type: "월간", period: "2026년 06월", status: "확정", author: "박준희", updated: "07.03 확정" },
  { id: 5, type: "분기", period: "2026 Q2", status: "확정", author: "CX 운영팀", updated: "07.05 확정" },
];

const EDITOR_BLOCKS = [
  { id: "summary", type: "summary", span: 2, title: "요약 (자동 작성)", content: "이번 주 조식 운영의 평균 대기시간은 전주 대비 2.1분 증가했습니다. 목요일 저녁과 주말 피크가 관찰되어 탄력 인력 배치 검토가 필요합니다." },
  { id: "wait-chart", type: "chart", span: 1, title: "평균 대기시간", values: [8, 10, 14, 18, 14, 11, 9], caption: "평균 대기 12.4분 · 전주 대비 +2.1분" },
  { id: "voc-chart", type: "chart", span: 1, title: "VOC 추이", values: [12, 18, 15, 24, 20, 16, 22], caption: "일 평균 18.1건 · 조식 혼잡 VOC 중심" },
  { id: "dining", type: "text", span: 2, title: "구역 섹션: 다이닝", content: "다이닝 구역의 주요 운영 이슈와 관리자 검토 의견을 입력하세요." },
];

const REPORT_BLOCK_CATALOG = [
  { key: "executive-summary", group: "경영 요약", title: "경영진 종합 결론", description: "운영 상태와 최우선 권고안 요약", type: "summary", content: "이번 주 호텔 운영은 전반적으로 안정적이었으며 고객 만족도는 상승했습니다. 주말 조식 피크 시간대 탄력 인력 운영을 정규 정책으로 전환할 것을 권고합니다." },
  { key: "decisions", group: "의사결정", title: "결정 필요 안건", description: "승인·보류가 필요한 운영 안건", type: "text", content: "1. 주말 조식 탄력 인력 2명 상시 배치\n2. 피크 시간 임시 좌석 24석 운영\n3. 단체 고객 조식 입장시간 분산" },
  { key: "response-review", group: "의사결정", title: "운영 대응안 검토", description: "대응안 선택과 예상 효과 비교", type: "text", content: "선택 대응안: 인력 추가 배치, 임시 좌석 운영\n예상 효과: 평균 대기시간 18분 → 12분\n관리자 검토 의견을 입력하세요." },
  { key: "performance", group: "성과 분석", title: "목표 대비 주요 성과", description: "만족도·VOC·대기시간 핵심 KPI", type: "chart", values: [94, 82, 86, 73, 90], caption: "고객 만족도 · 부정 VOC · 평균 대기시간 · 조치 완료율 · 최초 응답" },
  { key: "issues", group: "성과 분석", title: "핵심 이슈와 근거", description: "집중 이슈의 원인과 운영 영향", type: "text", content: "집중 이슈: 조식 혼잡 및 좌석 부족\n직접 원인: 점유율 92% 초과\n촉발 요인: 단체 고객 동시 입장\n분석 신뢰도: 96%" },
  { key: "hotel-benchmark", group: "비교 분석", title: "호텔별 비교 인사이트", description: "호텔별 VOC·대기·만족도 비교", type: "chart", values: [18, 24, 15, 27, 20], caption: "호텔별 부정 VOC 비율 비교 · synthetic data" },
  { key: "voc-operation-trend", group: "외부 리뷰 분석", title: "VOC 및 운영 지표 변화", description: "전체·부정 VOC와 평균 대기시간 일별 추이", type: "chart", values: [340, 365, 405, 382, 432, 394, 367], caption: "전체 VOC 일별 추이 · 부정 VOC와 평균 대기시간 동반 상승 구간 확인" },
  { key: "improvement-priority", group: "외부 리뷰 분석", title: "개선 우선순위", description: "즉시 조치가 필요한 이슈 순위와 증감", type: "text", content: "1. 체크인 대기 시간 과다 · 프론트 데스크 134건 · 긴급 +18\n2. 객실 청결 상태 불량 · 하우스키핑 89건 · 높음 +11\n3. 레스토랑 예약 불편 · F&B 67건 · 높음 +2\n4. 엘리베이터 대기 지연 · 시설관리 45건 · 보통 -5\n5. Wi-Fi 연결 불안정 · IT 38건 · 보통 +8" },
  { key: "root-cause-likelihood", group: "외부 리뷰 분석", title: "원인 후보 및 가능성", description: "체크인 대기 이슈의 원인 후보와 가능성", type: "chart", values: [87, 64, 91, 43, 78], caption: "체크인 인력 부족 · 시스템 처리 지연 · 성수기 예약 집중 · 교육 미흡 · 통신 단체 투숙" },
  { key: "inspection-checklist", group: "외부 리뷰 분석", title: "권장 점검 항목", description: "운영 개선을 위한 점검 목록과 완료 상태", type: "text", content: "□ 프론트 데스크 추가 인력 배치 검토 · 긴급\n□ 체크인 키오스크 운영 시간 연장 · 긴급\n■ 하우스키핑 청결 체크리스트 재점검 · 높음\n□ PMS 시스템 응답속도 진단 의뢰 · 높음\n□ 레스토랑 온라인 예약 채널 확대 · 보통\n■ Wi-Fi AP 증설 및 펌웨어 업데이트 · 보통" },
  { key: "external-evidence-review", group: "외부 리뷰 분석", title: "근거 리뷰", description: "최근 분석된 고객 VOC와 AI 신뢰도", type: "text", content: "7/13 · OTA · 체크인에 40분이나 기다렸습니다. 직원이 너무 부족한 것 같아요. · 부정 · 신뢰도 94%\n7/12 · 네이버 · 객실은 넓고 좋았지만 청결 상태가 기대 이하였어요. · 부정 · 신뢰도 87%\n7/12 · 구글 · 전반적으로 만족스러웠으나 레스토랑 예약이 너무 어려웠습니다. · 혼합 · 신뢰도 79%" },
  { key: "action-tracker", group: "실행 관리", title: "결정 이후 실행 과제", description: "담당자·목표일·진척도 관리", type: "text", content: "조식 인력 재배치 시범 운영 · 진행 중 65%\n임시 좌석 동선 안전 검토 · 검토 중 30%\n단체 예약 안내 문구 개정 · 예정 0%" },
  { key: "outlook", group: "전망", title: "다음 주 전망과 시나리오", description: "기본·개선·위험 시나리오", type: "chart", values: [68, 81, 43], caption: "기본 전망 · 권고안 적용 · 위험 시나리오 발생 가능성" },
  { key: "methodology", group: "근거", title: "분석 기준 및 데이터 범위", description: "기간·표본·합성 데이터 한계", type: "text", content: "분석 기간과 데이터 표본, synthetic schema version, seed 및 해석 시 주의사항을 기록하세요." },
];

const BASIC_BLOCK_PRESETS = {
  heading: { type: "heading", title: "새 제목", content: "보고서 제목을 입력하세요.", span: 2 },
  text: { type: "text", title: "새 텍스트", content: "클릭해 내용을 입력하세요.", span: 2 },
  quote: { type: "quote", title: "인용", content: "강조할 인사이트나 고객의 목소리를 입력하세요.", span: 1 },
  kpi: { type: "kpi", title: "KPI 카드", content: "핵심 지표 12.4분 · 전주 대비 +2.1분", span: 1 },
  table: { type: "table", title: "데이터 표", content: "항목 | 현재 | 목표\n대기시간 | 12.4분 | 10분\nVOC | 18건 | 12건", span: 2 },
  divider: { type: "divider", title: "구분선", content: "", span: 2 },
  section: { type: "section", title: "새 구역 섹션", content: "구역별 운영 내용을 입력하세요.", span: 2 },
  chart: { type: "chart", title: "새 운영 차트", values: [8, 12, 10, 16, 13, 18, 14], caption: "데이터 설명을 입력하세요.", span: 1 },
};

export function ExecutiveBriefingPage() {
  const [collapsed, setCollapsed] = useState(false);
  const [view, setView] = useState("list");
  const [typeFilter, setTypeFilter] = useState("전체");
  const [periodFilter, setPeriodFilter] = useState("전체");
  const [statusFilter, setStatusFilter] = useState("전체");
  const [period, setPeriod] = useState("Weekly Report");
  const [decisions, setDecisions] = useState({});
  const [selectedResponseOptions, setSelectedResponseOptions] = useState(["staff", "seats"]);
  const [responseDecision, setResponseDecision] = useState("");
  const [responseMemo, setResponseMemo] = useState("");
  const [toast, setToast] = useState("");
  const [selectedReport, setSelectedReport] = useState(REPORTS[0]);
  const [editorBlocks, setEditorBlocks] = useState(EDITOR_BLOCKS);
  const [draggedBlockId, setDraggedBlockId] = useState(null);
  const [draggedLibraryItem, setDraggedLibraryItem] = useState(null);

  const responseCost = useMemo(() => responseOptions.filter((option) => selectedResponseOptions.includes(option.id)).reduce((sum, option) => sum + option.cost, 0), [selectedResponseOptions]);
  const responseImpact = useMemo(() => {
    const effects = { staff: { wait: 4, voc: 2 }, seats: { wait: 2, voc: 2 }, group: { wait: 3, voc: 3 }, guide: { wait: 1, voc: 1 } };
    const total = selectedResponseOptions.reduce((summary, id) => ({ wait: summary.wait + (effects[id]?.wait || 0), voc: summary.voc + (effects[id]?.voc || 0) }), { wait: 0, voc: 0 });
    const wait = Math.max(7, 18 - total.wait);
    return { wait, voc: Math.max(4, 13 - total.voc), status: wait <= 10 ? "정상" : wait <= 14 ? "주의" : "위험" };
  }, [selectedResponseOptions]);
  const filteredReports = useMemo(() => REPORTS.filter((report) =>
    (typeFilter === "전체" || report.type === typeFilter)
    && (periodFilter === "전체" || report.period.includes(periodFilter))
    && (statusFilter === "전체" || report.status === statusFilter)
  ), [periodFilter, statusFilter, typeFilter]);

  const decide = (id, status) => setDecisions((current) => ({ ...current, [id]: status }));
  const toggleResponseOption = (id) => { setSelectedResponseOptions((current) => current.includes(id) ? current.filter((optionId) => optionId !== id) : [...current, id]); setResponseDecision(""); };
  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 1800); };
  const openReport = (report) => { setSelectedReport(report); setView("editor"); };
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
  const addBlock = (type) => {
    setEditorBlocks((current) => [...current, { id: `${type}-${Date.now()}`, ...BASIC_BLOCK_PRESETS[type] }]);
  };
  const addCatalogBlock = (catalogBlock) => {
    setEditorBlocks((current) => [...current, { ...catalogBlock, span: catalogBlock.type === "chart" ? 1 : 2, id: `${catalogBlock.key}-${Date.now()}` }]);
    notify(`${catalogBlock.title} 블록을 추가했습니다.`);
  };
  const dropLibraryItem = (targetId) => {
    if (!draggedLibraryItem) return false;
    const block = draggedLibraryItem.kind === "catalog"
      ? { ...draggedLibraryItem.value, span: draggedLibraryItem.value.type === "chart" ? 1 : 2, id: `${draggedLibraryItem.value.key}-${Date.now()}` }
      : { id: `${draggedLibraryItem.value}-${Date.now()}`, ...BASIC_BLOCK_PRESETS[draggedLibraryItem.value] };
    setEditorBlocks((current) => {
      if (!targetId) return [...current, block];
      const targetIndex = current.findIndex((item) => item.id === targetId);
      const next = [...current];
      next.splice(targetIndex < 0 ? next.length : targetIndex, 0, block);
      return next;
    });
    notify(`${block.title} 블록을 배치했습니다.`);
    setDraggedLibraryItem(null);
    return true;
  };
  const toggleBlockSpan = (id) => setEditorBlocks((current) => current.map((block) => block.id === id ? { ...block, span: (block.span || 2) === 2 ? 1 : 2 } : block));

  if (view === "list") return <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
    <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
    <div className="workspace report-list-workspace">
      <header className="report-list-header admin-page-header">
          <div><p>MANAGEMENT REPORTS</p><h1>정기 보고서</h1><span>운영 성과와 주요 의사결정 보고서를 기간별로 관리합니다.</span></div>
          <HeaderUtilities />
      </header>
      <main className="report-list-page">
        <section className="report-list-toolbar" aria-label="보고서 필터">
          <button className="report-new-button" type="button" onClick={() => openReport(REPORTS[0])}><FilePlus2 size={16} />새 보고서</button>
          <label><span>유형</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option>전체</option><option>주간</option><option>월간</option><option>분기</option></select></label>
          <label><span>기간</span><select value={periodFilter} onChange={(event) => setPeriodFilter(event.target.value)}><option>전체</option><option value="07/">7월</option><option value="06월">6월</option><option value="Q2">2분기</option></select></label>
          <label><span>상태</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>전체</option><option>초안</option><option>확정</option></select></label>
        </section>
        <section className="report-list-card">
          <div className="report-list-head"><span>유형</span><span>기간</span><span>상태</span><span>작성자</span><span>동작</span></div>
          {filteredReports.map((report) => <article className="report-list-row" role="button" tabIndex={0} onClick={() => openReport(report)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") openReport(report); }} key={report.id}>
            <strong>{report.type}</strong><b>{report.period}</b><span><i className={`report-status report-status--${report.status === "초안" ? "draft" : "final"}`}><em />{report.status}</i></span><span>{report.author}</span>
            <div><button type="button" onClick={() => openReport(report)}>열람</button></div>
          </article>)}
          {filteredReports.length === 0 && <div className="report-list-empty">선택한 조건에 해당하는 보고서가 없습니다.</div>}
        </section>
        <p className="report-list-guide">행을 선택해 보고서를 열람할 수 있습니다. 초안은 이어서 편집할 수 있으며 확정 보고서는 읽기 전용입니다.</p>
      </main>
      {toast && <div className="report-toast"><Check size={15} />{toast}</div>}
    </div>
  </div>;

  if (view === "editor") {
    const editable = selectedReport.status === "초안";
    return <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="workspace report-editor-workspace">
        <header className="report-editor-header admin-page-header"><div><button type="button" onClick={() => setView("list")}><ArrowLeft size={15} />보고서 목록</button><p>REPORT BLOCK EDITOR</p><h1>{selectedReport.type} 보고서 · {selectedReport.period}</h1></div><HeaderUtilities /></header>
        <main className="report-editor-layout">
          <aside className="report-block-library">
            <div><p>BLOCK LIBRARY</p><h2>보고서 에디터</h2><span>필요한 항목을 추가한 뒤 문서에서 순서를 변경하세요.</span></div>
            <section><h3><Sparkles size={15} />자연어로 차트 만들기</h3><textarea aria-label="차트 생성 요청" placeholder="예: 지난달 객실동 소음 VOC 추이 차트 만들어줘" /><button type="button" onClick={() => addBlock("chart")}><BarChart3 size={15} />차트 생성</button></section>
            <div className="report-block-search"><p>기존 보고서 구성 · 끌어서 배치</p>{REPORT_BLOCK_CATALOG.map((catalogBlock) => { const used = editorBlocks.some((block) => block.key === catalogBlock.key || block.title === catalogBlock.title); return <button type="button" draggable={editable} onDragStart={() => setDraggedLibraryItem({ kind: "catalog", value: catalogBlock })} onDragEnd={() => setDraggedLibraryItem(null)} key={catalogBlock.key}><span>{catalogBlock.type === "chart" ? <BarChart3 size={15} /> : <FileOutput size={15} />}</span><div><small>{catalogBlock.group}</small><b>{catalogBlock.title}</b><em>{catalogBlock.description}</em></div><i>{used ? "사용 중 · 드래그" : <><GripVertical size={12} />드래그</>}</i></button>; })}</div>
            <div className="report-basic-blocks">
              <p>기본 블록</p>
              <button type="button" draggable={editable} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: "heading" })} onDragEnd={() => setDraggedLibraryItem(null)}><Type size={15} />제목</button>
              <button type="button" draggable={editable} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: "text" })} onDragEnd={() => setDraggedLibraryItem(null)}><FileOutput size={15} />텍스트</button>
              <button type="button" draggable={editable} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: "quote" })} onDragEnd={() => setDraggedLibraryItem(null)}><Quote size={15} />인용</button>
              <button type="button" draggable={editable} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: "kpi" })} onDragEnd={() => setDraggedLibraryItem(null)}><Target size={15} />KPI 카드</button>
              <button type="button" draggable={editable} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: "table" })} onDragEnd={() => setDraggedLibraryItem(null)}><Table2 size={15} />표</button>
              <button type="button" draggable={editable} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: "divider" })} onDragEnd={() => setDraggedLibraryItem(null)}><Minus size={15} />구분선</button>
              <button className="is-wide" type="button" draggable={editable} onDragStart={() => setDraggedLibraryItem({ kind: "basic", value: "section" })} onDragEnd={() => setDraggedLibraryItem(null)}><Columns2 size={15} />구역 섹션</button>
            </div>
            <small className="editor-help">모든 블록을 드래그해 배치하고, 1칸·2칸 폭을 전환할 수 있습니다.</small>
          </aside>
          <section className="report-editor-canvas">
            <div className="report-editor-title"><div><h2>{selectedReport.type} 보고서 · {selectedReport.period}</h2><i className={`report-status report-status--${editable ? "draft" : "final"}`}><em />{selectedReport.status}</i></div><div className="editor-header-actions"><span><Check size={14} />자동 저장됨</span><button type="button" onClick={() => notify("PDF 내보내기를 준비했습니다.")}><Download size={14} />PDF</button>{editable && <button className="editor-confirm" type="button" onClick={() => notify("보고서를 확정했습니다.")}><Save size={14} />확정</button>}</div></div>
            <div className={`report-editor-blocks ${draggedLibraryItem ? "is-library-drop-ready" : ""}`} onDragOver={(event) => editable && event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (editable) dropLibraryItem(); }}>{editorBlocks.map((block, index) => <article className={`report-editor-block is-span-${block.span || 2} ${draggedBlockId === block.id ? "is-dragging" : ""}`} draggable={editable} onDragStart={() => { setDraggedLibraryItem(null); setDraggedBlockId(block.id); }} onDragOver={(event) => editable && event.preventDefault()} onDrop={(event) => { event.stopPropagation(); if (editable && !dropLibraryItem(block.id)) moveBlock(block.id); }} onDragEnd={() => setDraggedBlockId(null)} key={block.id}>
              <header><div><GripVertical size={17} /><b>{index + 1}. {block.title}</b></div>{editable && <div className="report-block-header-tools"><button type="button" onClick={() => toggleBlockSpan(block.id)}><Columns2 size={13} />{block.span || 2}칸</button><button type="button" onClick={() => setEditorBlocks((current) => current.filter((item) => item.id !== block.id))} aria-label={`${block.title} 삭제`}><Trash2 size={13} /></button></div>}</header>
              {block.type === "chart" ? <><div className="editor-mini-chart">{block.values.map((value, valueIndex) => <div key={`${block.id}-${valueIndex}`}><b>{value}</b><i style={{ height: `${Math.max(28, (value / Math.max(...block.values)) * 128)}px` }} /><small>{valueIndex + 1}</small></div>)}</div><p>{block.caption}</p></> : block.type === "divider" ? <div className="editor-divider-preview" /> : <textarea className={`editor-${block.type}`} readOnly={!editable} value={block.content} onChange={(event) => setEditorBlocks((current) => current.map((item) => item.id === block.id ? { ...item, content: event.target.value } : item))} />}
              {editable && block.type === "chart" && <div className="report-block-actions"><button type="button" onClick={() => notify(`${block.title} 블록을 다시 생성했습니다.`)} aria-label={`${block.title} 다시 생성`}><RotateCcw size={14} /></button></div>}
            </article>)}</div>
          </section>
        </main>
        {toast && <div className="report-toast"><Check size={15} />{toast}</div>}
      </div>
    </div>;
  }

  return <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
    <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
    <div className="workspace report-document-workspace">
      <header className="report-document-header admin-page-header">
        <div><button className="report-back-button" type="button" onClick={() => setView("list")}><ArrowLeft size={14} />보고서 목록</button><p>MANAGEMENT DECISION REPORT</p><h1>Executive Briefing</h1><span>운영 현황을 요약하고 경영 의사결정과 후속 실행을 지원합니다.</span></div>
        <HeaderUtilities />
      </header>

      <main className="report-document">
        <div className="report-document-tools"><div className="report-header-actions"><button onClick={() => notify("보고서를 다시 생성했습니다.")}><Sparkles size={14} />보고서 갱신</button><button onClick={() => notify("PDF 내보내기를 준비했습니다.")}><Download size={14} />PDF</button><button onClick={() => notify("PPT 내보내기를 준비했습니다.")}><FileOutput size={14} />PPT</button><button onClick={() => notify("경영진 공유 링크를 생성했습니다.")}><Share2 size={14} />공유</button></div></div>
        <section className="report-cover-strip">
          <div><span>보고서 유형</span><div className="period-selector">{["Daily Report", "Weekly Report", "Monthly Report"].map((item) => <button key={item} className={period === item ? "is-active" : ""} onClick={() => setPeriod(item)}>{item}</button>)}</div></div>
          <div><span>보고 기간</span><strong>2026.08.03 — 2026.08.09</strong></div>
          <div><span>작성 기준</span><strong>2026.08.10 08:45</strong></div>
          <div><span>검토 대상</span><strong>SENSE PLACE 서울 · 전체 시설</strong></div>
        </section>

        <section className="executive-conclusion">
          <div className="report-section-number">01</div>
          <div className="conclusion-body"><p>EXECUTIVE CONCLUSION</p><h2>경영진 종합 결론</h2><div className="conclusion-copy"><Sparkles size={20} /><p>이번 주 호텔 운영은 전반적으로 안정적이었으며 고객 만족도는 전주보다 0.2점 상승했습니다. 다만 주말 조식 피크 시간대의 좌석 부족과 단체 고객 동시 입장이 반복적인 부정 VOC를 유발하고 있습니다. 현장 인력 추가 배치는 대기시간을 평균 7분 단축해 효과가 확인되었으므로, <b>주말 탄력 인력 운영을 정규 정책으로 전환하는 결정을 권고합니다.</b></p></div></div>
          <aside><span>종합 운영 판단</span><strong>안정 · 일부 개선 필요</strong><small>AI 신뢰도 96% · 관리자 검토 필요</small></aside>
        </section>

        <section className="report-section decision-section">
          <div className="report-section-heading"><span>02</span><div><p>DECISION REQUIRED</p><h2>이번 회의에서 결정할 안건</h2><small>근거와 예상 효과를 확인한 뒤 승인 또는 보류해 주세요.</small></div><b>{Object.keys(decisions).length} / {DECISIONS.length} 결정</b></div>
          <div className="decision-list">{DECISIONS.map((item) => <article key={item.id} className={decisions[item.id] ? `is-${decisions[item.id]}` : ""}>
            <div className="decision-rank"><span>{String(item.id).padStart(2, "0")}</span><i>{item.priority}</i></div>
            <div className="decision-content"><h3>{item.title}</h3><p>{item.reason}</p><div className="decision-evidence"><span><b>예상 효과</b>{item.impact}</span><span><b>비용·변경</b>{item.cost}</span><span><b>판단 근거</b>{item.evidence}</span><span><b>담당</b>{item.owner}</span></div></div>
            <div className="decision-controls">{decisions[item.id] ? <div className="decision-complete"><Check size={16} /><b>{decisions[item.id] === "approved" ? "승인됨" : "보류됨"}</b><button onClick={() => decide(item.id, null)}>변경</button></div> : <><button className="approve" onClick={() => decide(item.id, "approved")}><Check size={14} />승인</button><button onClick={() => decide(item.id, "held")}>보류</button></>}</div>
          </article>)}</div>
        </section>

        <section className="report-section response-review-section" id="response-review">
          <div className="report-section-heading"><span>03</span><div><p>OPERATION RESPONSE REVIEW</p><h2>운영 대응안 검토</h2><small>실시간 모니터링에서 확인한 조식 혼잡 이슈의 대응안을 선택하고 예상 효과를 비교합니다.</small></div><b>Synthetic scenario</b></div>
          <div className="response-review-layout">
            <div className="report-response-options"><h3>대응안 선택 <small>복수 선택 가능</small></h3><div className="report-option-grid">{responseOptions.map((option) => { const selected = selectedResponseOptions.includes(option.id); return <button type="button" className={selected ? "is-selected" : ""} aria-pressed={selected} onClick={() => toggleResponseOption(option.id)} key={option.id}><span>{selected && <Check size={13} />}</span><div><b>{option.label}</b><small>{option.description}</small><em>{option.cost ? `${option.cost.toLocaleString("ko-KR")}원` : "추가 비용 없음"}</em></div></button>; })}</div></div>
            <ImpactComparison result={responseImpact} cost={responseCost} />
          </div>
          <div className="response-manager-review"><div><label htmlFor="response-review-memo">관리자 검토 메모</label><textarea id="response-review-memo" value={responseMemo} onChange={(event) => setResponseMemo(event.target.value)} placeholder="대응안 선택 사유와 추가 확인 사항을 기록하세요." /></div><p><Info size={13} /> 승인은 실행 후보 등록이며 실제 운영 조치를 자동 실행하지 않습니다.</p><div>{["승인", "보류", "반려"].map((status) => <button type="button" className={responseDecision === status ? "is-active" : ""} onClick={() => setResponseDecision(status)} key={status}>{status}</button>)}</div>{responseDecision && <strong role="status"><Check size={14} />{responseDecision} 상태로 검토 결과가 저장되었습니다.</strong>}</div>
        </section>

        <section className="report-two-column">
          <article className="report-section performance-section"><div className="report-section-heading compact"><span>04</span><div><p>PERFORMANCE REVIEW</p><h2>목표 대비 주요 성과</h2></div></div><div className="performance-table"><div className="performance-head"><span>지표</span><span>현재</span><span>목표</span><span>전주 대비</span><span>판단</span></div>{PERFORMANCE.map(([metric,current,target,change,status,tone]) => <div key={metric}><b>{metric}</b><strong>{current}</strong><span>{target}</span><em>{change}</em><i className={tone}>{status}</i></div>)}</div></article>
          <article className="report-section issue-section"><div className="report-section-heading compact"><span>05</span><div><p>KEY ISSUE ANALYSIS</p><h2>핵심 이슈와 근거</h2></div></div><div className="issue-report"><div><AlertTriangle size={18} /><span><small>이번 주 집중 이슈</small><h3>조식 혼잡 및 좌석 부족</h3></span><b>높음</b></div><p>부정 VOC 184건 중 76건이 조식과 관련되었으며, 그중 41%가 좌석 부족을 언급했습니다. 문제는 토·일요일 08:00~09:00에 집중되었습니다.</p><dl><div><dt>직접 원인</dt><dd>점유율 92% 초과</dd></div><div><dt>촉발 요인</dt><dd>단체 고객 동시 입장</dd></div><div><dt>운영 영향</dt><dd>대기시간 최대 16분</dd></div><div><dt>분석 신뢰도</dt><dd>96%</dd></div></dl><button>상세 근거 검토 <ChevronRight size={14} /></button></div></article>
        </section>

        <section className="report-section hotel-insight-section">
          <div className="report-section-heading"><span>06</span><div><p>HOTEL BENCHMARK INSIGHT</p><h2>호텔별 비교 인사이트</h2><small>호텔 간 차이를 같은 기준으로 비교해 우선순위와 확산 가능한 운영 방식을 제안합니다.</small></div><b>{HOTEL_COMPARISON_META.label} · {HOTEL_COMPARISON_META.schemaVersion}</b></div>
          <div className="hotel-insight-layout">
            <div className="hotel-benchmark-table">
              <div className="hotel-benchmark-head"><span>호텔</span><span>부정 VOC</span><span>평균 대기</span><span>만족도</span><span>조치 완료율</span></div>
              {HOTEL_COMPARISON_DATA.map((hotel) => <div className={hotel.negativeRate >= 25 ? "is-risk" : ""} key={hotel.hotel}>
                <span><Building2 size={14} /><b>{hotel.hotel}</b><small>{hotel.vocCount.toLocaleString()}건 분석</small></span>
                <span><b>{hotel.negativeRate}%</b><i><em style={{ width: `${hotel.negativeRate}%` }} /></i></span>
                <strong>{hotel.waitMinutes}분</strong><strong>{hotel.satisfaction} / 5</strong><strong>{hotel.resolutionRate}%</strong>
              </div>)}
            </div>
            <div className="hotel-insight-list">{HOTEL_COMPARISON_INSIGHTS.map((insight) => <article className={`hotel-insight-card hotel-insight-card--${insight.tone}`} key={insight.title}>
              <small>{insight.title}</small><h3>{insight.hotel}</h3><p>{insight.summary}</p><div><Target size={13} /><span>{insight.action}</span></div>
            </article>)}</div>
          </div>
          <p className="hotel-insight-boundary"><Info size={13} /> 비교 결과는 {HOTEL_COMPARISON_META.period}의 합성 데이터(seed {HOTEL_COMPARISON_META.seed}) 기반이며, 호텔별 VOC 표본 수와 채널 구성이 달라 단순 순위만으로 성과를 확정하지 않습니다.</p>
        </section>

        <section className="report-section action-tracker"><div className="report-section-heading"><span>07</span><div><p>EXECUTION TRACKER</p><h2>결정 이후 실행 과제</h2><small>담당자와 완료 목표일을 기준으로 후속 실행을 관리합니다.</small></div></div><div className="action-table"><div><span>실행 과제</span><span>담당</span><span>완료 목표</span><span>상태</span><span>진척도</span></div>{ACTIONS.map(([task,owner,due,status,progress]) => <div key={task}><b>{task}</b><span>{owner}</span><span>{due}</span><i>{status}</i><strong><span style={{ width: progress }} />{progress}</strong></div>)}</div></section>

        <section className="report-section outlook-section"><div className="report-section-heading"><span>08</span><div><p>OUTLOOK & SCENARIO</p><h2>다음 주 전망과 시나리오</h2><small>현재 예약과 운영 계획을 기준으로 산출한 전망입니다.</small></div></div><div className="scenario-grid"><article><span><TrendingUp size={18} />기본 전망</span><strong>점유율 89%</strong><p>주말 조식 수요는 이번 주와 유사합니다. 현재 인력 계획 유지 시 평균 대기시간은 12분으로 예상됩니다.</p><i>발생 가능성 68%</i></article><article className="recommended"><span><Target size={18} />권장안 적용</span><strong>대기시간 8분</strong><p>탄력 인력과 임시 좌석을 함께 운영하면 만족도 4.8점, 부정 VOC 14%가 예상됩니다.</p><i>권장 시나리오</i></article><article><span><TrendingDown size={18} />위험 시나리오</span><strong>대기시간 18분</strong><p>단체 2팀이 동일 시간에 입장하고 추가 인력이 없을 경우 부정 VOC가 최대 26%까지 증가할 수 있습니다.</p><i>발생 가능성 21%</i></article></div></section>

        <footer className="report-methodology"><Info size={15} /><div><b>분석 기준 및 한계</b><p>예약 데이터, POS, 운영 로그, QR 피드백, 푸시 설문, 직원 보고, 온라인 리뷰를 채널별로 분리 분석했습니다. 외부 리뷰는 작성 시차가 있어 실시간 VOC와 단순 합산하지 않았으며, 예상 효과는 과거 유사 운영 조치에 기반한 추정치입니다.</p></div><button onClick={() => notify("경영진 공유 링크를 생성했습니다.")}><Send size={14} />경영진에게 보고서 공유</button></footer>
      </main>
      {toast && <div className="report-toast"><Check size={15} />{toast}</div>}
    </div>
  </div>;
}
