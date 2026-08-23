/** 애플리케이션 상단의 화면 제목·역할·세션 명령을 표시하는 모듈이다. */
import { LogOut, Menu, UserRound } from "lucide-react";
import { roleLabel } from "../../authorization.ts";
import { ThemeToggle } from "../common/ThemeToggle";

/** 현재 화면·세션 역할과 전역 메뉴/로그아웃 동작을 표시하는 상단 셸이다. */
export function AppHeader({ title, description, role, theme, onMenu, onSignOut, onToggleTheme }) {
  const label = roleLabel(role);
  return <header className="topbar"><button className="mobile-menu" onClick={onMenu} aria-label="메뉴 열기"><Menu size={20} /></button><div><p>ANSWERVICE</p><h1>{title}</h1><span>{description}</span></div><div className="top-actions"><ThemeToggle theme={theme} onToggle={onToggleTheme} /><span className="account-summary" title={label}><UserRound size={15} /><span>{label}</span></span><button className="session-signout" type="button" aria-label="로그아웃" onClick={onSignOut}><LogOut size={15} /><span>로그아웃</span></button></div></header>;
}
