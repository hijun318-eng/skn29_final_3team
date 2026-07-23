import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, BarChart3, Bot, CheckCircle2, Clock3, Database, MessageSquareText, Search, Send, ShieldCheck, Sparkles } from "lucide-react";
import { Sidebar } from "../components/layout/Sidebar";

const evidence = [
  ["부정 VOC", "184건", "전주 대비 +18%"],
  ["집중 시간", "08:00~09:00", "전체 관련 의견의 61%"],
  ["평균 대기", "16분", "목표 대비 +7분"],
  ["주요 키워드", "좌석 부족", "관련 의견 76건"],
];

const causes = [
  { title: "조식 점유율 92% 초과", note: "예약·입장 데이터와 혼잡 발생 시간이 일치합니다.", confidence: "근거 강함" },
  { title: "단체 고객 동시 입장", note: "08:05 전후 2개 단체의 입장이 확인되었습니다.", confidence: "추가 확인" },
  { title: "좌석 회전 지연", note: "퇴장 시각 데이터가 없어 현장 확인이 필요합니다.", confidence: "가설" },
];

export function IssueAnalysisPage() {
  const [collapsed, setCollapsed] = useState(false);
  const initialQuery = useMemo(() => new URLSearchParams(window.location.search).get("q")?.trim() || "이번 주 위험 이슈 요약", []);
  const [query, setQuery] = useState(initialQuery);
  const [activeQuery, setActiveQuery] = useState(initialQuery);
  const [briefing, setBriefing] = useState(true);

  const submit = (event) => {
    event.preventDefault();
    const normalizedQuery = query.trim();
    if (!normalizedQuery) return;
    setBriefing(false);
    window.setTimeout(() => {
      setActiveQuery(normalizedQuery);
      window.history.replaceState({}, "", `/issues?q=${encodeURIComponent(normalizedQuery)}`);
      setBriefing(true);
    }, 450);
  };

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="workspace issue-workspace">
        <header className="issue-header">
          <div><p>AI ISSUE BRIEFING</p><h1>이슈 분석</h1><span>운영 데이터와 실시간 VOC를 함께 검토해 원인 후보와 우선 확인 항목을 브리핑합니다.</span></div>
          <div className="issue-analysis-meta"><span><Database size={14} /> Synthetic data</span><b>분석 ID · SP-260722-014</b></div>
        </header>

        <main className="issue-main">
          <form className="issue-query card" onSubmit={submit}>
            <span><Search size={20} /></span>
            <div><label htmlFor="issue-query">AI ASSISTANT에게 후속 질문</label><input id="issue-query" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
            <button type="submit"><span>분석 요청</span><Send size={15} /></button>
          </form>

          <section className={`issue-briefing card ${briefing ? "" : "is-loading"}`} aria-live="polite" aria-busy={!briefing}>
            {!briefing ? <div className="issue-loading"><i /><b>관련 VOC와 운영 데이터를 분석하고 있습니다.</b><span>질문 조건과 근거를 확인하는 중입니다.</span></div> : <>
              <div className="issue-briefing__head"><span><Bot size={22} /></span><div><p>AI BRIEFING</p><h2>{activeQuery}</h2></div><i><Sparkles size={13} /> 분석 완료</i></div>
              <div className="issue-briefing__copy">
                <p>이번 주 가장 우선적으로 확인할 이슈는 <b>주말 조식 시간대의 혼잡과 좌석 부족</b>입니다. 08:00~09:00 사이 이용객이 평시보다 28% 증가하면서 평균 대기시간이 16분까지 늘었고, 같은 시간대 부정 VOC도 함께 증가했습니다.</p>
                <p>추가 인력을 배치한 이후 대기시간은 9분으로 낮아졌지만 좌석 부족 관련 의견은 계속 관측되었습니다. 따라서 인력 부족만을 단일 원인으로 확정하기보다 <b>단체 입장 시간과 좌석 회전 상태를 함께 확인</b>하는 것이 필요합니다.</p>
              </div>
              <div className="briefing-boundary"><ShieldCheck size={15} /><span>AI가 제시한 원인 후보이며, 현장 확인 전 확정 원인이나 자동 실행 지시로 사용하지 않습니다.</span></div>
            </>}
          </section>

          <section className="issue-evidence-grid">
            {evidence.map(([label, value, note]) => <article className="card" key={label}><small>{label}</small><strong>{value}</strong><span>{note}</span></article>)}
          </section>

          <section className="issue-analysis-grid">
            <article className="issue-causes card">
              <div className="issue-section-title"><div><p>ROOT CAUSE CANDIDATES</p><h2>원인 후보와 근거 상태</h2></div><BarChart3 size={20} /></div>
              <div className="issue-cause-list">{causes.map((cause, index) => <div key={cause.title}><span>{index + 1}</span><div><b>{cause.title}</b><small>{cause.note}</small></div><i>{cause.confidence}</i></div>)}</div>
            </article>
            <article className="issue-actions card">
              <div className="issue-section-title"><div><p>MANAGER CHECK</p><h2>우선 확인 항목</h2></div><CheckCircle2 size={20} /></div>
              <ol><li><span><Clock3 size={15} /></span><div><b>단체 입장 시간 조정 가능 여부</b><small>예약팀 · 오늘 14:00까지 확인</small></div></li><li><span><MessageSquareText size={15} /></span><div><b>좌석 회전 지연 구간 현장 점검</b><small>식음팀 · 다음 피크 시간 관찰</small></div></li><li><span><AlertTriangle size={15} /></span><div><b>임시 좌석 운영 안전 기준 검토</b><small>시설팀 · 동선과 비상구 우선 확인</small></div></li></ol>
              <a href="/monitoring">실시간 운영 맵에서 확인 <ArrowRight size={15} /></a>
            </article>
          </section>
        </main>
      </div>
    </div>
  );
}
