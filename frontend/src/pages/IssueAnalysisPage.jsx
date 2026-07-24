import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Database,
  FileSearch,
  Hexagon,
  MessageCircle,
  MessageSquareText,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Sidebar } from "../components/layout/Sidebar";
import { HeaderUtilities } from "../components/layout/Header";

const dailyTrend = [
  { day: "월", voc: 19, wait: 8 },
  { day: "화", voc: 22, wait: 9 },
  { day: "수", voc: 18, wait: 7 },
  { day: "목", voc: 25, wait: 10 },
  { day: "금", voc: 31, wait: 12 },
  { day: "토", voc: 42, wait: 16 },
  { day: "일", voc: 27, wait: 11 },
];

const evidence = [
  { label: "부정 VOC", value: "184건", note: "전주 대비 +18%", icon: MessageSquareText, tone: "danger" },
  { label: "집중 시간", value: "08:00~09:00", note: "관련 의견의 61%", icon: Clock3, tone: "warning" },
  { label: "평균 대기", value: "16분", note: "목표 대비 +7분", icon: Users, tone: "warning" },
  { label: "대응 후 대기", value: "9분", note: "배치 전 대비 -44%", icon: TrendingDown, tone: "positive" },
];

const analysisSteps = [
  ["VOC 탐색", "최근 7일 부정 VOC 184건을 시설·시간대·키워드별로 집계"],
  ["운영 데이터 교차 확인", "조식 입장·좌석 점유·인력 배치 시각을 동일 시간축으로 비교"],
  ["원인 후보 검증", "혼잡과 함께 변한 지표, 반대 근거, 확인되지 않은 필드를 분리"],
  ["영향 예측", "현재 추세 유지·운영 조정·수요 증가의 3개 시나리오를 비교"],
];

const scenarios = [
  { name: "운영 조정", wait: "8~10분", voc: "-31%", effect: "단체 입장 분산 + 좌석 회전 점검", tone: "positive" },
  { name: "현재 유지", wait: "14~17분", voc: "+6%", effect: "추가 조정 없이 현 배치 유지", tone: "neutral" },
  { name: "수요 증가", wait: "19~23분", voc: "+24%", effect: "주말 투숙률 8%p 상승 가정", tone: "danger" },
];

const conversationHistory = [
  ["피자힐 대기시간 분석", "오늘 14:20"],
  ["구역별 미해결 현황", "오늘 11:05"],
  ["주간 VOC 추이", "어제 17:40"],
];

const suggestedQueries = ["지난주 피자힐 평균 대기시간 보여줘", "이번 주 VOC 추이", "구역별 미해결 현황", "어제 위험 VOC 건수"];

export function IssueAnalysisPage() {
  const [collapsed, setCollapsed] = useState(false);
  const [thinkingOpen, setThinkingOpen] = useState(true);
  const initialQuery = useMemo(() => new URLSearchParams(window.location.search).get("q")?.trim() || "", []);
  const [query, setQuery] = useState(initialQuery);
  const [activeQuery, setActiveQuery] = useState(initialQuery || "이번 주 위험 이슈 요약");
  const [briefing, setBriefing] = useState(true);
  const [hasAnalysis, setHasAnalysis] = useState(Boolean(initialQuery));

  const runAnalysis = (nextQuery) => {
    const normalizedQuery = nextQuery.trim();
    if (!normalizedQuery) return;
    setQuery(normalizedQuery);
    setBriefing(false);
    setHasAnalysis(true);
    window.setTimeout(() => {
      setActiveQuery(normalizedQuery);
      window.history.replaceState({}, "", `/issues?q=${encodeURIComponent(normalizedQuery)}`);
      setBriefing(true);
      setThinkingOpen(true);
    }, 450);
  };

  const submit = (event) => {
    event.preventDefault();
    runAnalysis(query);
  };

  if (!hasAnalysis) return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="workspace issue-agent-workspace">
        <header className="issue-agent-header admin-page-header"><div><p>AI ISSUE ANALYSIS</p><h1>대화형 조회 · 내부 운영/VOC 분석</h1><span>운영 데이터와 고객 VOC를 자연어로 조회하세요.</span></div><HeaderUtilities /></header>
        <div className="issue-agent-layout">
          <aside className="issue-chat-history">
            <button className="issue-new-chat" type="button" onClick={() => setQuery("")}><Plus size={16} />새 대화</button>
            <p>대화 이력 <span>(세션 유지)</span></p>
            <div>{conversationHistory.map(([title, time]) => <button type="button" onClick={() => runAnalysis(title)} key={title}><MessageCircle size={15} /><span><b>{title}</b><small>{time}</small></span></button>)}</div>
            <small>새 창 분리 여부는 논의 예정</small>
          </aside>
          <section className="issue-chat-main">
            <div className="issue-chat-welcome">
              <div>{suggestedQueries.map((suggestion) => <button type="button" onClick={() => runAnalysis(suggestion)} key={suggestion}><MessageCircle size={15} />{suggestion}</button>)}</div>
            </div>
            <form className="issue-chat-composer" onSubmit={submit}><input aria-label="이슈 분석 질문" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="질문 입력 (/ 로 포커스) · 예: 이번 주 VOC 추이" /><button type="submit">전송 <Send size={15} /></button></form>
          </section>
        </div>
      </div>
    </div>
  );

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="workspace issue-workspace">
        <header className="issue-header admin-page-header">
          <div><p>AI ISSUE ANALYSIS</p><h1>이슈 분석</h1><span>흩어진 VOC와 운영 데이터를 질문 한 번으로 조회하고, 근거·영향·대응안까지 이어서 확인합니다.</span></div>
          <HeaderUtilities />
        </header>

        <main className="issue-main">
          <form className="issue-query card" onSubmit={submit}>
            <span><Search size={20} /></span>
            <div><label htmlFor="issue-query">분석 에이전트에게 질문</label><input id="issue-query" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
            <button type="submit"><span>분석 요청</span><Send size={15} /></button>
          </form>

          {!briefing ? <section className="issue-loading card" aria-live="polite" aria-busy="true"><i /><b>VOC와 운영 지표를 연결하고 있습니다.</b><span>조회 범위, 근거 상태와 시나리오 가정을 확인하는 중입니다.</span></section> : <>
            <section className="issue-conversation card">
              <div className="issue-user-question"><span>{activeQuery}</span></div>
              <button className="thinking-toggle" type="button" onClick={() => setThinkingOpen((value) => !value)} aria-expanded={thinkingOpen}>
                <BrainCircuit size={18} /><b>분석 과정</b><small>4단계 완료</small><ChevronDown size={16} className={thinkingOpen ? "is-open" : ""} />
              </button>
              {thinkingOpen && <ol className="thinking-steps">
                {analysisSteps.map(([title, description], index) => <li key={title}><span>{index + 1}</span><div><b>{title}</b><small>{description}</small></div><CheckCircle2 size={16} /></li>)}
              </ol>}
            </section>

            <section className="issue-briefing card" aria-live="polite">
              <div className="issue-briefing__head"><span><Bot size={22} /></span><div><p>AI BRIEFING</p><h2>주말 조식 혼잡이 이번 주 최우선 운영 이슈입니다</h2></div><i><Sparkles size={13} /> 분석 완료</i></div>
              <div className="issue-briefing__copy">
                <p>08:00~09:00 이용객이 평시보다 28% 증가하면서 평균 대기시간이 16분까지 늘었고, 같은 시간대 부정 VOC도 함께 증가했습니다. 특히 <b>토요일의 조식 대기·좌석 부족 언급이 주간 최고치</b>를 기록했습니다.</p>
                <p>추가 인력 배치 후 대기시간은 9분으로 낮아졌지만 좌석 부족 의견은 계속 관측됐습니다. 인력 부족을 단일 원인으로 확정하지 않고 <b>단체 입장 분산과 좌석 회전 상태를 함께 확인</b>해야 합니다.</p>
              </div>
              <div className="briefing-boundary"><ShieldCheck size={15} /><span>아래 결과는 합성 데이터 기반 의사결정 보조 정보입니다. 예측값은 가정에 따라 달라지며 현장 확인 전 자동 실행하지 않습니다.</span></div>
            </section>

            <section className="issue-evidence-grid" aria-label="핵심 분석 지표">
              {evidence.map(({ label, value, note, icon: Icon, tone }) => <article className={`card issue-metric issue-metric--${tone}`} key={label}><span><Icon size={17} /></span><div><small>{label}</small><strong>{value}</strong><em>{note}</em></div></article>)}
            </section>

            <section className="issue-report-grid">
              <article className="issue-analysis-trend card">
                <div className="issue-section-title"><div><p>OBSERVED TREND</p><h2>요일별 조식 부정 VOC</h2><span>막대에 마우스를 올리면 건수와 평균 대기시간을 확인할 수 있습니다.</span></div><TrendingUp size={20} /></div>
                <div className="issue-chart" aria-label="요일별 조식 부정 VOC 막대 차트">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={dailyTrend} margin={{ top: 18, right: 6, left: -22, bottom: 0 }}>
                      <CartesianGrid vertical={false} stroke="#eee9e2" />
                      <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: "#878a90", fontSize: 10 }} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fill: "#a0a2a6", fontSize: 9 }} />
                      <Tooltip cursor={{ fill: "#f5f1eb" }} formatter={(value, name, item) => [`${value}건 · 대기 ${item.payload.wait}분`, "부정 VOC"]} />
                      <Bar dataKey="voc" fill="#9d7a50" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </article>

              <article className="issue-findings card">
                <div className="issue-section-title"><div><p>EVIDENCE CHECK</p><h2>원인 후보와 근거 상태</h2></div><FileSearch size={20} /></div>
                <ul>
                  <li><span className="evidence-strength evidence-strength--high">근거 강함</span><div><b>조식 점유율 92% 초과</b><small>혼잡 발생 시각과 예약·입장 데이터가 일치</small></div></li>
                  <li><span className="evidence-strength evidence-strength--medium">추가 확인</span><div><b>단체 고객 동시 입장</b><small>08:05 전후 2개 단체 입장 기록 확인</small></div></li>
                  <li><span className="evidence-strength evidence-strength--low">가설</span><div><b>좌석 회전 지연</b><small>퇴장 시각 데이터가 없어 현장 관찰 필요</small></div></li>
                </ul>
              </article>
            </section>

            <section className="issue-forecast card">
              <div className="issue-section-title"><div><p>NEXT WEEK SCENARIOS</p><h2>다음 주 영향 예측</h2><span>최근 4주 패턴과 투숙률 가정을 반영한 범위 추정입니다.</span></div><i>예측 구간 · 7/27~8/2</i></div>
              <div className="forecast-table" role="table" aria-label="다음 주 영향 예측 시나리오">
                <div className="forecast-row forecast-head" role="row"><span>시나리오</span><span>예상 대기</span><span>부정 VOC</span><span>주요 가정</span></div>
                {scenarios.map((scenario) => <div className="forecast-row" role="row" key={scenario.name}><b>{scenario.name}</b><strong>{scenario.wait}</strong><em className={`forecast-tone--${scenario.tone}`}>{scenario.voc}</em><span>{scenario.effect}</span></div>)}
              </div>
            </section>

            <section className="issue-actions card">
              <div className="issue-section-title"><div><p>MANAGER ACTION</p><h2>권장 확인 순서</h2><span>승인이나 실행이 아닌 현장 확인용 제안입니다.</span></div><CheckCircle2 size={20} /></div>
              <ol><li><span>1</span><div><b>단체 입장 시간 10분 분산 가능 여부</b><small>예약팀 · 오늘 14:00까지 확인</small></div></li><li><span>2</span><div><b>좌석 회전 지연 구간 현장 점검</b><small>식음팀 · 다음 피크 시간 관찰</small></div></li><li><span>3</span><div><b>임시 좌석 운영 안전 기준 검토</b><small>시설팀 · 동선과 비상구 우선 확인</small></div></li></ol>
              <a href="/monitoring">실시간 운영 맵에서 확인 <ArrowRight size={15} /></a>
            </section>
          </>}
        </main>
      </div>
    </div>
  );
}
