import { useState } from "react";
import { Clock3, MessageSquareText, Search, Send, ShieldAlert } from "lucide-react";
import { Header } from "../components/layout/Header";
import { Sidebar } from "../components/layout/Sidebar";
import { KpiCard } from "../components/cards/KpiCard";
import { VocTrendChart } from "../components/charts/VocTrendChart";
import { HotelComparisonChart } from "../components/charts/HotelComparisonChart";
import { PriorityIssues } from "../components/cards/PriorityIssues";
import { RootCauses } from "../components/cards/RootCauses";
import { InspectionChecklist } from "../components/cards/InspectionChecklist";
import { EvidenceReviewTable } from "../components/tables/EvidenceReviewTable";

const suggestedQuestions = ["체크인 대기 증가 원인", "이번 주 위험 이슈 요약", "레스토랑 VOC 트렌드", "전주 대비 개선 항목"];

export function DashboardPage() {
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const submit = (event) => {
    event.preventDefault();
    const normalizedQuery = query.trim();
    if (!normalizedQuery) return;
    setSubmitted(true);
    window.location.href = `/issues?q=${encodeURIComponent(normalizedQuery)}`;
  };

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      <div className="workspace">
        <Header />
        <main className="dashboard">
          <section className="ai-assistant card">
            <form className="ai-search" onSubmit={submit}>
              <span className="ai-badge"><Search size={20} /></span>
              <div><label htmlFor="ai-query">AI ASSISTANT</label><input id="ai-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="AI에게 운영 데이터를 질문해보세요 — 예: '이번 주 부정 VOC 급증 원인이 뭔가요?'" /></div>
              <button type="submit" aria-label="분석 요청" className={submitted ? "is-loading" : ""}>{submitted ? <span className="loader" /> : <><span>분석 요청</span><Send size={16} /></>}</button>
            </form>
            <div className="suggested-questions">{suggestedQuestions.map((item) => <button key={item} onClick={() => setQuery(item)}>{item}</button>)}</div>
          </section>

          <section className="kpi-grid">
            <KpiCard icon={MessageSquareText} title="전체 VOC" value="2,847" unit="" subtext="이번 주 누적" delta="12.4%" deltaText="전주 대비" trend="down" tone="navy" />
            <KpiCard icon={ShieldAlert} title="부정 VOC 비율" value="31.8" unit="%" subtext="732건 부정 리뷰" delta="4.2%p" deltaText="전주 대비" trend="down" tone="danger" />
            <KpiCard icon={ShieldAlert} title="위험 이슈" value="7" unit="" subtext="즉각 대응 필요" delta="2건" deltaText="전주 대비" trend="down" tone="gold" />
            <KpiCard icon={Clock3} title="평균 대기시간" value="26" unit="분" subtext="체크인 기준" delta="8분" deltaText="전주 대비" trend="down" tone="brown" />
          </section>

          <HotelComparisonChart />
          <section className="main-grid"><VocTrendChart /><PriorityIssues /></section>
          <section className="bottom-grid"><RootCauses /><InspectionChecklist /><EvidenceReviewTable /></section>
        </main>
      </div>
    </div>
  );
}
