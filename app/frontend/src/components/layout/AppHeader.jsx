import { LogOut, Menu, UserRound } from "lucide-react";

export function AppHeader({ title, description, role, onMenu, onSignOut }) {
  const roleLabel = role === "report_admin" ? "보고서 관리자" : "호텔 분석가";
  return <header className="topbar"><button className="mobile-menu" onClick={onMenu} aria-label="메뉴 열기"><Menu size={20} /></button><div><p>ANSWERVICE</p><h1>{title}</h1><span>{description}</span></div><div className="top-actions"><span className="account-summary" title={roleLabel}><UserRound size={15} /><span>{roleLabel}</span></span><button className="session-signout" type="button" aria-label="로그아웃" onClick={onSignOut}><LogOut size={15} /><span>로그아웃</span></button></div></header>;
}
