import { FileBarChart, MessageSquareText, X } from "lucide-react";
import { PAGE_PATHS } from "../../routing";

const NAVIGATION = [
  { id: "chat", path: PAGE_PATHS.chat, label: "분석 Agent", icon: MessageSquareText, roles: ["hotel_analyst"] },
  { id: "reports", path: PAGE_PATHS.reports, label: "Report", icon: FileBarChart, roles: ["hotel_analyst", "report_admin"] },
];

export function AppSidebar({ page, role, onNavigate, open, onClose }) {
  const navigation = NAVIGATION.filter((item) => item.roles.includes(role));
  return <>{open && <button className="scrim" aria-label="메뉴 닫기" onClick={onClose} />}<aside className={`sidebar ${open ? "sidebar--open" : ""}`}><div className="brand"><div className="brand-mark">AS</div><div><b>ANSWERVICE</b><small>Enterprise Intelligence</small></div><button onClick={onClose} aria-label="메뉴 닫기"><X size={18} /></button></div><nav><small className="nav-group">WORKSPACE</small>{navigation.map(({ id, path, label, icon: Icon }) => <button className={page === id ? "active" : ""} aria-current={page === id ? "page" : undefined} onClick={() => { onNavigate(path); onClose(); }} key={id}><Icon size={18} /><span>{label}</span></button>)}</nav></aside></>;
}
