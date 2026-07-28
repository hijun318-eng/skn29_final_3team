import {
  BookOpen,
  Building2,
  ChevronDown,
  Database,
  FileBarChart,
  MessageSquareText,
  UsersRound,
  X,
} from "lucide-react";
import { PAGE_PATHS } from "../../routing";

const NAVIGATION = [
  { id: "chat", path: PAGE_PATHS.chat, label: "분석 Agent", icon: MessageSquareText, group: "workspace" },
  { id: "customer", path: PAGE_PATHS.customer, label: "Customer 360", icon: UsersRound, group: "workspace" },
  { id: "reports", path: PAGE_PATHS.reports, label: "보고서", icon: FileBarChart, group: "workspace" },
  { id: "catalog", path: PAGE_PATHS.catalog, label: "데이터 카탈로그", icon: BookOpen, group: "admin" },
  { id: "connections", path: PAGE_PATHS.connections, label: "DB 연결 관리", icon: Database, group: "admin" },
];

export function AppSidebar({ page, onNavigate, open, onClose }) {
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
          <div className="brand-mark">SP</div>
          <div>
            <b>SENSE PLACE</b>
            <small>Enterprise Intelligence</small>
          </div>
          <button onClick={onClose} aria-label="메뉴 닫기">
            <X size={18} />
          </button>
        </div>
        <nav>
          {renderGroup("workspace", "WORKSPACE")}
          {renderGroup("admin", "ADMINISTRATION")}
        </nav>
        <div className="organization">
          <Building2 size={20} />
          <div>
            <b>Walkerhill Hotels</b>
            <small>Demo Organization</small>
          </div>
          <ChevronDown size={15} />
        </div>
      </aside>
    </>
  );
}
