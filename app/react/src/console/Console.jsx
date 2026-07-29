import { useEffect, useState } from "react";
import { Database, FileText, MessageSquare, UserRound } from "lucide-react";
import { PROPERTIES, SYNTHETIC_META } from "./consoleData";
import { AgentChatPage } from "./AgentChatPage";
import { ReportsPage } from "./ReportsPage";
import { Customer360Page } from "./Customer360Page";
import { CatalogPage } from "./CatalogPage";
import "./console.css";

const NAV = [
  { key: "chat", path: "/console/chat", icon: MessageSquare, label: "운영 챗", hint: "질문 · 근거 확인", eyebrow: "VOC AGENT", title: "운영 어시스턴트", desc: "VOC·운영 로그를 함께 조회해 이슈와 원인을 근거와 함께 답변합니다.", Page: AgentChatPage },
  { key: "reports", path: "/console/reports", icon: FileText, label: "보고서", hint: "일일 · 주간 · 월간", eyebrow: "REPORTING", title: "운영 보고서", desc: "정기 보고서를 자동 생성하고 검토자가 확정합니다.", Page: ReportsPage },
  { key: "customers", path: "/console/customers", icon: UserRound, label: "고객 360", hint: "프로필 · 여정 · 대화", eyebrow: "GUEST 360", title: "고객 360 분석", desc: "숙박·결제·VOC·응대 이력을 한 화면에서 확인하고 고객 단위로 질문합니다.", Page: Customer360Page },
  { key: "catalog", path: "/console/catalog", icon: Database, label: "데이터 카탈로그", hint: "소스 · MCP Tool", eyebrow: "DATA PLATFORM", title: "데이터 카탈로그 · MCP", desc: "사일로 소스 연결 상태와 Agent에 노출된 MCP tool을 관리합니다.", Page: CatalogPage },
];

function navFromPath() {
  return NAV.find((n) => window.location.pathname.startsWith(n.path)) ?? NAV[0];
}

export function Console() {
  const [active, setActive] = useState(() => navFromPath().key);
  const nav = NAV.find((n) => n.key === active);
  const { Page } = nav;

  useEffect(() => {
    const onPop = () => setActive(navFromPath().key);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function go(item) {
    window.history.pushState({}, "", item.path);
    setActive(item.key);
  }

  return (
    <div className="wh-root">
      <div className="wh-shell">
        <nav className="wh-rail">
          <div className="wh-brand">
            <b>WALKERHILL</b>
            <i />
            <small>VOC Operations Console</small>
          </div>
          <div className="wh-nav">
            <span>Workspace</span>
            {NAV.map((item) => (
              <button key={item.key} className={item.key === active ? "is-active" : ""} onClick={() => go(item)}>
                <item.icon size={16} />
                <div>
                  <b>{item.label}</b>
                  <small>{item.hint}</small>
                </div>
              </button>
            ))}
          </div>
          <div className="wh-rail-foot">
            <b>Data</b>
            {SYNTHETIC_META.dataset}
            <br />schema {SYNTHETIC_META.schemaVersion} · seed {SYNTHETIC_META.seed}
            <div className="wh-rail-user">
              <span>PJ</span>
              <div>
                <b>박준희</b>
                <small>CX 운영팀</small>
              </div>
            </div>
          </div>
        </nav>

        <main className="wh-main">
          <header className="wh-topbar">
            <div>
              <p className="wh-eyebrow">{nav.eyebrow}</p>
              <h1>{nav.title}</h1>
              <p className="wh-desc">{nav.desc}</p>
            </div>
            <div className="wh-topbar-actions">
              <select className="wh-btn" defaultValue={PROPERTIES[0]} style={{ paddingRight: 10 }}>
                {PROPERTIES.map((p) => <option key={p}>{p}</option>)}
              </select>
              <span className="wh-btn" style={{ cursor: "default", color: "#666" }}>{SYNTHETIC_META.generatedAt} 기준</span>
            </div>
          </header>
          <Page />
        </main>
      </div>
    </div>
  );
}
