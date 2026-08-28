/** 서버 Capability에 맞춘 전역 탐색과 현재 화면·세션 명령을 상단에 제공하는 모듈이다. */
import { LogOut, UserRound } from "lucide-react";
import { CAPABILITY, hasCapability, roleLabel } from "../../authorization.ts";
import { PAGE_PATHS } from "../../routing";
import { ThemeToggle } from "../common/ThemeToggle";

const NAVIGATION = [
  { id: "chat", path: PAGE_PATHS.chat, label: "데이터 분석", capability: CAPABILITY.runAnalysis },
  { id: "reports", path: PAGE_PATHS.reports, label: "보고서", capability: CAPABILITY.draftReport, alternative: CAPABILITY.manageReport },
  { id: "admin", path: PAGE_PATHS.admin, label: "관리자", capability: CAPABILITY.manageSystem },
];

/** 허용된 메뉴만 노출하고 현재 위치·브랜드 홈·세션 명령을 하나의 키보드 순서로 제공한다. */
export function AppHeader({ page, title, description, role, capabilities, theme, onNavigate, onSignOut, onToggleTheme }) {
  const label = roleLabel(role);
  const navigation = NAVIGATION.filter((item) => hasCapability(capabilities, item.capability) || (item.alternative && hasCapability(capabilities, item.alternative)));
  const homePath = navigation[0]?.path ?? PAGE_PATHS.chat;
  return <header className="topbar">
    <div className="topbar-main">
      <button className="app-brand" type="button" aria-label="ANSWERVICE 홈" onClick={() => onNavigate(homePath)}><span className="app-brand-mark" aria-hidden="true">AS</span><span className="app-brand-copy"><b>ANSWERVICE</b><small>데이터 분석 서비스</small></span></button>
      <nav className="top-navigation" aria-label="주요 메뉴">
        {navigation.map(({ id, path, label: itemLabel }) => <button type="button" className={page === id ? "active" : ""} aria-current={page === id ? "page" : undefined} onClick={() => onNavigate(path)} key={id}>{itemLabel}</button>)}
      </nav>
      <div className="top-actions"><ThemeToggle theme={theme} onToggle={onToggleTheme} /><span className="account-summary" title={label}><UserRound size={15} /><span>{label}</span></span><button className="session-signout" type="button" aria-label="로그아웃" onClick={onSignOut}><LogOut size={15} /><span>로그아웃</span></button></div>
    </div>
    <div className="page-context"><h1>{title}</h1><span>{description}</span></div>
  </header>;
}
