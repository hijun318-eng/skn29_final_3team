import { BarChart3, CalendarDays, ChevronLeft, ChevronRight, FileSearch, LayoutDashboard, Map } from "lucide-react";

const navigation = [
  { label: "실시간 모니터링", icon: Map, href: "/monitoring" },
  { label: "이슈 분석 AGENT", icon: BarChart3, href: "/issues" },
  { label: "정기 보고서", icon: CalendarDays, href: "/reports" },
  { label: "내부 리뷰 데이터", icon: FileSearch, href: "/evidence-review" },
  { label: "외부 리뷰 데이터", icon: LayoutDashboard, href: "/" },
];

export function Sidebar({ collapsed, onToggle }) {
  const currentPath = window.location.pathname;
  return <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`}>
    <a className="brand" href="/" aria-label="Sense Place 외부 리뷰 데이터로 이동"><span className="brand__mark"><span className="brand__monogram">SP</span><i aria-hidden="true" /></span>{!collapsed && <span><b>SENSE PLACE</b><small>Operation Intelligence</small></span>}</a>
    <nav className="navigation" aria-label="Primary navigation">
      {navigation.map(({ label, icon: Icon, href }) => {
        const active = href ? (href === "/" ? currentPath === "/" : currentPath.startsWith(href)) : false;
        const content = <><Icon size={19} strokeWidth={1.8} />{!collapsed && <span>{label}</span>}</>;
        return href ? <a className={`nav-item ${active ? "nav-item--active" : ""}`} href={href} key={label} title={collapsed ? label : undefined}>{content}</a> : <button className="nav-item" key={label} title={collapsed ? label : undefined}>{content}</button>;
      })}
    </nav>
    <div className="sidebar__footer">{!collapsed && <div className="manager-profile"><span>P</span><div><b>박준희 · 총괄 매니저</b><small>CX Operations</small></div></div>}<button className="collapse-button" onClick={onToggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>{collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}</button></div>
  </aside>;
}
