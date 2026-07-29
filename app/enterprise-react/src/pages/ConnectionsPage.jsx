import { useState } from "react";
import { ChevronDown, Database, Plus, ShieldCheck } from "lucide-react";
import { MetaStrip, StatusBadge } from "../components/common/EnterpriseUi";
import { connections } from "../data/enterpriseDemoData";

const FILTERS = [
  ["all", "전체"],
  ["connected", "연결됨"],
  ["delayed", "지연"],
  ["error", "오류"],
];

export function ConnectionsPage() {
  const [filter, setFilter] = useState("all");
  const filtered = filter === "all"
    ? connections
    : connections.filter((item) => item.status === filter);

  const countByStatus = (status) => status === "all"
    ? connections.length
    : connections.filter((item) => item.status === status).length;

  return (
    <div className="page-content">
      <MetaStrip />
      <div className="management-toolbar">
        <div className="filter-tabs">
          {FILTERS.map(([id, label]) => (
            <button className={filter === id ? "active" : ""} onClick={() => setFilter(id)} key={id}>
              {label}<span>{countByStatus(id)}</span>
            </button>
          ))}
        </div>
        <button className="primary"><Plus size={15} />새 연결 등록</button>
      </div>
      <section className="connection-grid">
        {filtered.map((item) => (
          <article className="card connection-card" key={item.name}>
            <header>
              <span className="vendor-icon"><Database size={21} /></span>
              <div><h3>{item.name}</h3><p>{item.vendor}</p></div>
              <StatusBadge status={item.status} />
              <button aria-label={`${item.name} 메뉴`}><ChevronDown size={16} /></button>
            </header>
            <dl>
              <div><dt>Catalog</dt><dd>{item.catalog}</dd></div>
              <div><dt>Business domain</dt><dd>{item.domain}</dd></div>
              <div><dt>Endpoint</dt><dd>{item.endpoint}</dd></div>
              <div><dt>Last health check</dt><dd>{item.sync}</dd></div>
            </dl>
            <div className="health-meter">
              <span><small>Health score</small><b>{item.health || "N/A"}{item.health ? "%" : ""}</b></span>
              <i><em style={{ width: `${item.health}%` }} /></i>
            </div>
            <footer>
              <span><ShieldCheck size={13} />Read only</span>
              <button>연결 테스트</button>
              <button>상세 관리</button>
            </footer>
          </article>
        ))}
      </section>
    </div>
  );
}
