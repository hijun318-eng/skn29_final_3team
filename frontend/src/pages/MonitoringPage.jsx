import { useState } from "react";
import { Activity, Clock3, Radio, ShieldCheck } from "lucide-react";
import { Sidebar } from "../components/layout/Sidebar";
import { OperationMapSection } from "../components/map/OperationMapSection";

export function MonitoringPage() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="workspace monitoring-workspace">
        <header className="monitoring-header">
          <div>
            <p>LIVE OPERATION INTELLIGENCE</p>
            <h1>호텔 실시간 운영 모니터링</h1>
            <span>시설 혼잡도와 운영 상태를 실시간으로 확인하고 대응 시나리오를 검토합니다.</span>
          </div>
          <div className="monitoring-live-status">
            <i />
            <div><b>실시간 연결</b><small>마지막 갱신 10:42:18</small></div>
          </div>
        </header>

        <main className="monitoring-main">
          <section className="monitoring-summary">
            <article><span><Radio size={18} /></span><div><small>모니터링 시설</small><strong>7개</strong></div></article>
            <article><span><Activity size={18} /></span><div><small>주의 필요</small><strong>2개</strong></div></article>
            <article><span><Clock3 size={18} /></span><div><small>평균 대기시간</small><strong>8분</strong></div></article>
            <article><span><ShieldCheck size={18} /></span><div><small>운영 상태</small><strong>안정</strong></div></article>
          </section>
          <OperationMapSection />
        </main>
      </div>
    </div>
  );
}
