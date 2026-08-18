/** 세션 역할별 허용 메뉴와 반응형 navigation 셸을 제공하는 모듈이다. */
import { Building2, FileBarChart, MessageSquareText, PanelLeftClose } from "lucide-react";
import { PAGE_PATHS } from "../../routing";

const NAVIGATION = [
  { id: "chat", path: PAGE_PATHS.chat, label: "데이터 분석", icon: MessageSquareText, roles: ["hotel_analyst"] },
  { id: "reports", path: PAGE_PATHS.reports, label: "보고서", icon: FileBarChart, roles: ["hotel_analyst", "report_admin"] },
];

/** 서버 세션 역할에 허용된 경로만 노출하고 선택된 페이지를 접근성 상태로 표시한다. */
export function AppSidebar({ page, role, onNavigate, open, onClose }) {
  const navigation = NAVIGATION.filter((item) => item.roles.includes(role));
  const roleLabel = role === "report_admin" ? "보고서 관리자" : "호텔 분석가";
  return <>{open && <button className="scrim" aria-label="메뉴 닫기" onClick={onClose} />}<aside className={`sidebar ${open ? "sidebar--open" : ""}`}><div className="brand"><div className="brand-mark">AS</div><div><b>ANSWERVICE</b><small>데이터 분석 서비스</small></div><button onClick={onClose} aria-label="사이드바 접기" title="사이드바 접기"><PanelLeftClose size={17} /></button></div><nav><small className="nav-group">메뉴</small>{navigation.map(({ id, path, label, icon: Icon }) => <button className={page === id ? "active" : ""} aria-current={page === id ? "page" : undefined} onClick={() => { onNavigate(path); onClose(); }} key={id}><Icon size={18} /><span>{label}</span></button>)}</nav><div className="organization"><Building2 size={20} /><div><b>{roleLabel}</b><small>로그인됨</small></div></div></aside></>;
}
