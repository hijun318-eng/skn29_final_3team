import { CircleAlert, Menu, RefreshCw } from "lucide-react";

export function AppHeader({ title, description, onMenu }) {
  return (
    <header className="topbar">
      <button className="mobile-menu" onClick={onMenu} aria-label="메뉴 열기">
        <Menu size={20} />
      </button>
      <div>
        <p>ENTERPRISE INTELLIGENCE</p>
        <h1>{title}</h1>
        <span>{description}</span>
      </div>
      <div className="top-actions">
        <span className="live"><i />5개 논리 소스</span>
        <button aria-label="새로고침"><RefreshCw size={16} /></button>
        <button aria-label="알림"><CircleAlert size={16} /></button>
        <div className="avatar">A</div>
      </div>
    </header>
  );
}
