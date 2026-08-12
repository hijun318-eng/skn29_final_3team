import {
  Building2,
  ChevronDown,
  FileBarChart,
  MessageSquareText,
  X,
} from "lucide-react";
import { useState } from "react";
import { clearAuthSession, hasAuthSession, saveAuthSession } from "../../api/authSession";
import { PAGE_PATHS } from "../../routing";

const NAVIGATION = [
  { id: "chat", path: PAGE_PATHS.chat, label: "분석 Agent", icon: MessageSquareText, group: "workspace" },
  { id: "reports", path: PAGE_PATHS.reports, label: "보고서", icon: FileBarChart, group: "workspace" },
];

export function AppSidebar({ page, onNavigate, open, onClose }) {
  const [authenticated, setAuthenticated] = useState(hasAuthSession);
  const [token, setToken] = useState("");
  const renderGroup = (group, title) => (
    <>
      <small className="nav-group">{title}</small>
      {NAVIGATION.filter((item) => item.group === group).map(({ id, path, label, icon: Icon }) => (
        <button
          className={page === id ? "active" : ""}
          aria-current={page === id ? "page" : undefined}
          onClick={() => {
            onNavigate(path);
            onClose();
          }}
          key={id}
        >
          <Icon size={18} />
          <span>{label}</span>
        </button>
      ))}
    </>
  );

  return (
    <>
      {open && <button className="scrim" aria-label="메뉴 닫기" onClick={onClose} />}
      <aside className={`sidebar ${open ? "sidebar--open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">AS</div>
          <div>
            <b>ANSWERVICE</b>
            <small>Enterprise Intelligence</small>
          </div>
          <button onClick={onClose} aria-label="메뉴 닫기">
            <X size={18} />
          </button>
        </div>
        <nav>
          {renderGroup("workspace", "WORKSPACE")}
        </nav>
        <form className="auth-session" onSubmit={(event) => {
          event.preventDefault();
          saveAuthSession(token);
          setToken("");
          setAuthenticated(true);
        }}>
          <small>AUTH SESSION</small>
          {authenticated ? <button type="button" onClick={() => { clearAuthSession(); setAuthenticated(false); }}>로그아웃</button> : <><input type="password" autoComplete="current-password" aria-label="Bearer 로그인 토큰" placeholder="Bearer token" value={token} onChange={(event) => setToken(event.target.value)} /><button type="submit" disabled={!token.trim()}>로그인</button></>}
        </form>
        <div className="organization">
          <Building2 size={20} />
          <div>
            <b>Sense Place Hotel</b>
            <small>Organization</small>
          </div>
          <ChevronDown size={15} />
        </div>
      </aside>
    </>
  );
}
