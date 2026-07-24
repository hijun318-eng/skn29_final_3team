import { useMemo, useState } from "react";
import { AlertTriangle, Building2, Check, ChevronRight, Download, FileOutput, Info, Send, Share2, Sparkles, Target, TrendingDown, TrendingUp } from "lucide-react";
import { Sidebar } from "../components/layout/Sidebar";
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

export function ExecutiveBriefingPage() {
  const [collapsed, setCollapsed] = useState(false);
  const [period, setPeriod] = useState("Weekly Report");
  const [decisions, setDecisions] = useState({});
  const [selectedResponseOptions, setSelectedResponseOptions] = useState(["staff", "seats"]);
  const [responseDecision, setResponseDecision] = useState("");
  const [responseMemo, setResponseMemo] = useState("");
  const [toast, setToast] = useState("");

  const responseCost = useMemo(() => responseOptions.filter((option) => selectedResponseOptions.includes(option.id)).reduce((sum, option) => sum + option.cost, 0), [selectedResponseOptions]);
  const responseImpact = useMemo(() => {
    const effects = { staff: { wait: 4, voc: 2 }, seats: { wait: 2, voc: 2 }, group: { wait: 3, voc: 3 }, guide: { wait: 1, voc: 1 } };
    const total = selectedResponseOptions.reduce((summary, id) => ({ wait: summary.wait + (effects[id]?.wait || 0), voc: summary.voc + (effects[id]?.voc || 0) }), { wait: 0, voc: 0 });
    const wait = Math.max(7, 18 - total.wait);
    return { wait, voc: Math.max(4, 13 - total.voc), status: wait <= 10 ? "정상" : wait <= 14 ? "주의" : "위험" };
  }, [selectedResponseOptions]);

  const decide = (id, status) => setDecisions((current) => ({ ...current, [id]: status }));
  const toggleResponseOption = (id) => { setSelectedResponseOptions((current) => current.includes(id) ? current.filter((optionId) => optionId !== id) : [...current, id]); setResponseDecision(""); };
  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 1800); };

  return <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
    <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
    <div className="workspace report-document-workspace">
      <header className="report-document-header admin-page-header">
        <div><p>MANAGEMENT DECISION REPORT</p><h1>Executive Briefing</h1><span>운영 현황을 요약하고 경영 의사결정과 후속 실행을 지원합니다.</span></div>
        <div className="report-header-actions"><button onClick={() => notify("보고서를 다시 생성했습니다.")}><Sparkles size={14} />보고서 갱신</button><button onClick={() => notify("PDF 내보내기를 준비했습니다.")}><Download size={14} />PDF</button><button onClick={() => notify("PPT 내보내기를 준비했습니다.")}><FileOutput size={14} />PPT</button><button onClick={() => notify("경영진 공유 링크를 생성했습니다.")}><Share2 size={14} />공유</button></div>
      </header>

      <main className="report-document">
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
