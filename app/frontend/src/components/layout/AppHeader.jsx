import { LogOut, Menu } from "lucide-react";

export function AppHeader({ title, description, onMenu, onSignOut }) {
  return <header className="topbar"><button className="mobile-menu" onClick={onMenu} aria-label="메뉴 열기"><Menu size={20} /></button><div><p>ENTERPRISE INTELLIGENCE</p><h1>{title}</h1><span>{description}</span></div><button className="session-signout" type="button" onClick={onSignOut}><LogOut size={15} />세션 종료</button></header>;
}
