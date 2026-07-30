import { useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Building2,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  CloudCog,
  Database,
  GitBranch,
  KeyRound,
  Layers3,
  MessageSquareText,
  Network,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  TableProperties,
  TrendingUp,
  UserRound,
  Wrench,
} from "lucide-react";
import { MetaStrip, SectionTitle, StatusBadge } from "../components/common/EnterpriseUi";
import { connections, dataProducts, mcpTools } from "../data/enterpriseDemoData";

const ONTOLOGY_NODES = [
  [170, 110, "Customer", UserRound],
  [360, 105, "Reservation", CalendarDays],
  [530, 110, "Stay", KeyRound],
  [710, 90, "Room", Building2],
  [710, 220, "Review", MessageSquareText],
  [170, 310, "Order", CloudCog],
  [360, 310, "Product", Layers3],
  [570, 350, "Revenue", TrendingUp],
];

const RELATIONSHIPS = [
  ["MAKES", "Reservation"],
  ["PLACES", "Order"],
  ["WRITES", "Review"],
];

const SOURCE_GROUPS = [
  ["PMS", "예약·객실", "pms"],
  ["POS", "F&B·구매", "pos"],
  ["CRM", "고객·멤버십", "crm"],
  ["FACILITY", "시설·센서", "facility"],
  ["BANQUET", "연회·행사", "banquet"],
];

const DATA_CONSUMERS = [
  [MessageSquareText, "분석 Agent", "근거 기반 질의"],
  [TableProperties, "정기 보고서", "일·주·월 자동화"],
];

function CatalogOverview({ onManageConnections }) {
  const connectedCount = connections.filter((item) => item.status === "connected").length;
  const issueCount = connections.length - connectedCount;

  return (
    <div className="catalog-overview">
      <section className="card federation-card">
        <SectionTitle
          eyebrow="FEDERATED DATA FOUNDATION"
          title="사일로 데이터를 하나의 비즈니스 맥락으로"
          description="분산된 원천을 물리적으로 복제하지 않고 연결해 Agent가 필요한 데이터를 한 번에 조회합니다."
          action={(
            <button className="primary" onClick={onManageConnections}>
              <Plus size={14} />데이터 소스 연결
            </button>
          )}
        />

        <div className="catalog-metrics" aria-label="카탈로그 요약">
          <span><small>등록 소스</small><b>{connections.length}</b><em>{connectedCount}개 정상</em></span>
          <span><small>데이터 제품</small><b>{dataProducts.length}</b><em>표준화·정제 완료</em></span>
          <span><small>Agent Tool</small><b>{mcpTools.length}</b><em>MCP contract 기반</em></span>
          <span className={issueCount ? "has-issue" : ""}><small>확인 필요</small><b>{issueCount}</b><em>지연·오류 연결</em></span>
        </div>

        <div className="federation-flow">
          <div className="flow-column source-column">
            <p>분산 데이터 소스</p>
            <div className="source-stack">
              {SOURCE_GROUPS.map(([name, domain, catalog]) => (
                <article key={name}>
                  <span><Database size={15} /></span>
                  <div><b>{name}</b><small>{domain}</small></div>
                  <em>{catalog}</em>
                </article>
              ))}
            </div>
          </div>

          <span className="flow-arrow" aria-hidden="true"><ArrowRight size={24} /></span>

          <article className="query-engine">
            <span><Network size={25} /></span>
            <small>FEDERATED QUERY</small>
            <strong>통합 쿼리 레이어</strong>
            <p>Trino 연합 조회<br />DuckDB 로컬 분석</p>
            <em>단일 SQL · 이기종 DB JOIN</em>
          </article>

          <span className="flow-arrow" aria-hidden="true"><ArrowRight size={24} /></span>

          <div className="flow-column consumer-column">
            <p>비즈니스 활용</p>
            <div className="consumer-grid">
              {DATA_CONSUMERS.map(([Icon, name, description]) => (
                <article key={name}>
                  <span><Icon size={16} /></span>
                  <div><b>{name}</b><small>{description}</small></div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="card source-status-card">
        <SectionTitle
          eyebrow="CONNECTED SOURCES"
          title="연결된 데이터 소스"
          description="Catalog 등록 상태와 최근 동기화 현황을 조회합니다. 연결 설정과 인증 정보는 관리자 화면에서 관리합니다."
          action={(
            <button className="secondary" onClick={onManageConnections}>
              <CloudCog size={14} />DB 연결 관리
            </button>
          )}
        />
        <div className="data-table source-status-table">
          <div className="table-row table-head">
            <span>소스명</span><span>업무 영역</span><span>Catalog</span><span>연결 상태</span>
            <span>레코드</span><span>최근 동기화</span><span>담당 조직</span>
          </div>
          {connections.map((item) => (
            <div className="table-row" key={item.name}>
              <span><b>{item.name}</b><small>{item.vendor}</small></span>
              <span>{item.domain}</span>
              <span><em className="catalog-code">{item.catalog}</em></span>
              <span><StatusBadge status={item.status} /></span>
              <span>{item.records}</span>
              <span>{item.sync}</span>
              <span>{item.owner}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function CatalogExplorer({ products, search, onSearch }) {
  return (
    <div className="catalog-layout">
      <aside className="card catalog-tree">
        <h3>Catalog Explorer</h3>
        <div className="search-box">
          <Search size={14} />
          <input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="데이터 제품 검색" />
        </div>
        {connections.slice(0, 5).map((item, index) => (
          <div className="tree-node" key={item.catalog}>
            <p>
              <ChevronDown size={14} />
              <Database size={14} />
              <b>{item.catalog}</b>
              <small>{item.vendor}</small>
            </p>
            {index < 2 && (
              <div>
                <span><ChevronRight size={13} /><Layers3 size={13} />{index === 0 ? "reservation" : "orders"}</span>
                <span><ChevronRight size={13} /><TableProperties size={13} />{index === 0 ? "fact_reservation" : "fact_pos_order"}</span>
              </div>
            )}
          </div>
        ))}
      </aside>
      <main className="card catalog-main">
        <SectionTitle
          eyebrow="DATA PRODUCTS"
          title="정제된 데이터 제품"
          description={`${products.length}개 제품 · 원천 데이터를 표준화한 분석용 dataset`}
          action={<button className="secondary"><RefreshCw size={14} />Metadata 수집</button>}
        />
        <div className="data-table">
          <div className="table-row table-head">
            <span>데이터 제품</span><span>Source · Catalog</span><span>Domain · Owner</span>
            <span>Freshness</span><span>Quality</span><span>Tool</span>
          </div>
          {products.map((item) => (
            <div className="table-row" key={item.product}>
              <span><b>{item.product}</b><small>{item.sensitivity}</small></span>
              <span><b>{item.source}</b><small>{item.catalog}</small></span>
              <span><b>{item.domain}</b><small>{item.owner}</small></span>
              <span>{item.freshness}</span>
              <span><em className="quality">{item.quality}%</em></span>
              <span><em className="tool-label">{item.tool}</em></span>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function OntologyView() {
  return (
    <section className="ontology-layout">
      <div className="card ontology-canvas">
        <SectionTitle
          eyebrow="SEMANTIC LAYER"
          title="Enterprise Ontology Map"
          description="업무 개체와 사일로 데이터 간 관계를 정의합니다."
        />
        <div className="ontology-graph">
          <svg viewBox="0 0 900 480" aria-hidden="true">
            <g className="edges">
              <line x1="170" y1="110" x2="360" y2="105" />
              <line x1="360" y1="105" x2="530" y2="110" />
              <line x1="530" y1="110" x2="710" y2="90" />
              <line x1="530" y1="110" x2="710" y2="220" />
              <line x1="360" y1="105" x2="360" y2="310" />
              <line x1="360" y1="310" x2="570" y2="350" />
              <line x1="170" y1="110" x2="170" y2="310" />
              <line x1="170" y1="310" x2="360" y2="310" />
            </g>
          </svg>
          {ONTOLOGY_NODES.map(([x, y, label, Icon]) => (
            <article
              className="ontology-node"
              style={{ left: `${x / 9}%`, top: `${y / 4.8}%` }}
              key={label}
            >
              <span><Icon size={18} /></span>
              <b>{label}</b>
              <small>{label === "Customer" ? "CRM" : label === "Revenue" ? "Finance" : "PMS · POS"}</small>
            </article>
          ))}
        </div>
      </div>
      <aside className="card ontology-detail">
        <SectionTitle eyebrow="ENTITY DETAIL" title="Customer" />
        <dl>
          <div><dt>Business definition</dt><dd>서비스를 예약·구매·이용하는 마스킹된 고객 개체</dd></div>
          <div><dt>Source systems</dt><dd>CRM · PMS · POS · VOC</dd></div>
          <div><dt>Resolution keys</dt><dd>customer_id · membership_id · email_hash</dd></div>
          <div><dt>Related products</dt><dd>Customer Golden Profile · VOC Sentiment</dd></div>
        </dl>
        <h3>Relationships</h3>
        {RELATIONSHIPS.map(([relation, target]) => (
          <p className="relation" key={relation}><GitBranch size={14} /><b>{relation}</b><span>{target}</span></p>
        ))}
        <h3>Available Tools</h3>
        <span className="tool-label">Customer 360 Tool</span>
        <span className="tool-label">Ontology Traversal</span>
      </aside>
    </section>
  );
}

function ToolRegistry() {
  return (
    <section className="card tool-registry">
      <SectionTitle
        eyebrow="AGENT CAPABILITIES"
        title="MCP Tool Registry"
        description="Agent가 호출할 수 있는 Tool contract와 권한을 관리합니다."
        action={<button className="primary"><Plus size={14} />Tool 등록</button>}
      />
      <div className="data-table tools-table">
        <div className="table-row table-head">
          <span>Tool</span><span>Category · Version</span><span>Health</span>
          <span>Allowed Agent</span><span>Permission</span><span>Last invoked</span>
        </div>
        {mcpTools.map((item) => (
          <div className="table-row" key={item.name}>
            <span><b>{item.name}</b><small>Success {item.success}</small></span>
            <span><b>{item.category}</b><small>{item.version}</small></span>
            <span><StatusBadge status={item.health} /></span>
            <span>{item.agents}</span>
            <span><ShieldCheck size={13} /> {item.permission}</span>
            <span>{item.last}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function CatalogPage({ onManageConnections }) {
  const [search, setSearch] = useState("");
  const products = useMemo(
    () => dataProducts.filter((item) => (
      item.product.toLowerCase().includes(search.toLowerCase())
      || item.domain.includes(search)
      || item.source.toLowerCase().includes(search.toLowerCase())
      || item.catalog.toLowerCase().includes(search.toLowerCase())
    )),
    [search],
  );

  return (
    <div className="page-content">
      <MetaStrip />
      <CatalogOverview onManageConnections={onManageConnections} />
      <CatalogExplorer products={products} search={search} onSearch={setSearch} />
    </div>
  );
}
