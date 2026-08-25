/** 관리자 화면의 프런트엔드 정보 구조와 향후 Backend 연결 경계를 소유한다. */
import { Database, FileClock, RefreshCw, ShieldCheck, UserCog, UserPlus } from "lucide-react";
import { useState } from "react";
import { roleLabel } from "../authorization.ts";

const ADMIN_SECTIONS = [
  { id: "connections", label: "연결 상태", icon: Database },
  { id: "accounts", label: "권한 관리", icon: UserCog },
  { id: "audit", label: "감사 로그", icon: FileClock },
];

const CONNECTION_TARGETS = [
  { id: "pms", name: "PMS", technology: "PostgreSQL" },
  { id: "pos", name: "POS", technology: "MySQL" },
  { id: "crm", name: "CRM", technology: "SQL Server" },
  { id: "facility", name: "Facility", technology: "ClickHouse" },
  { id: "banquet", name: "Banquet", technology: "PostgreSQL" },
  { id: "app_postgres", name: "App PostgreSQL", technology: "PostgreSQL" },
  { id: "trino", name: "Trino", technology: "HTTPS" },
  { id: "datahub", name: "DataHub", technology: "HTTPS" },
  { id: "model_api", name: "Model API", technology: "HTTP" },
];

const STATUS_LABELS = {
  ready: "정상",
  down: "연결 실패",
  checking: "확인 중",
  unknown: "확인 전",
};

/**
 * 관리자 운영 화면을 렌더링한다.
 * `data`가 없으면 가짜 운영값을 만들지 않고 Backend 연결 전 상태를 표시하며,
 * 추후 연결 시 연결 상태(`id/status/latencyMs`), 계정(`id/name/email/role/status/createdAt`),
 * 감사 로그(`id/occurredAt/actor/event/target/result/detail`)를 `data`로 전달한다.
 */
export function AdminPage({ role, data, onRefreshConnections, onCreateAccount }) {
  const [section, setSection] = useState("connections");
  const connections = data?.connections ?? [];
  const accounts = data?.accounts ?? [];
  const auditLogs = data?.auditLogs ?? [];
  const backendConnected = data?.backendConnected === true;
  const connectionRows = CONNECTION_TARGETS.map((target) => ({
    ...target,
    status: "unknown",
    ...connections.find((item) => item.id === target.id),
  }));

  return <div className="page-content admin-console">
    <section className="admin-console__status" aria-label="관리자 시스템 상태">
      <div><ShieldCheck size={18} /><span><b>{roleLabel(role)}</b><small>현재 세션 권한으로 접근 중</small></span></div>
      <strong className={backendConnected ? "is-online" : "is-pending"}><i />{backendConnected ? "ADMIN API 연결됨" : "ADMIN API 연결 전"}</strong>
    </section>

    <nav className="admin-console__tabs" role="tablist" aria-label="관리자 기능">
      {ADMIN_SECTIONS.map(({ id, label, icon: Icon }) => <button
        key={id}
        id={`admin-tab-${id}`}
        type="button"
        role="tab"
        aria-selected={section === id}
        aria-controls={`admin-panel-${id}`}
        className={section === id ? "is-active" : ""}
        onClick={() => setSection(id)}
      ><Icon size={17} /><span>{label}</span></button>)}
    </nav>

    {section === "connections" && <section className="admin-panel" id="admin-panel-connections" role="tabpanel" aria-labelledby="admin-tab-connections">
      <header className="admin-panel__header">
        <div><small>READ ONLY INFRASTRUCTURE</small><h2>데이터 연결 상태</h2><p>관리자 시스템이 사용하는 데이터 및 분석 서비스의 읽기 전용 상태를 확인합니다.</p></div>
        <button className="secondary" type="button" disabled={!onRefreshConnections} onClick={onRefreshConnections}><RefreshCw size={15} />상태 새로고침</button>
      </header>
      <div className="admin-connection-grid">
        {connectionRows.map((connection, index) => <article className="admin-connection-card card" key={connection.id}>
          <small>{String(index + 1).padStart(2, "0")}</small>
          <h3>{connection.name}</h3>
          <p>{connection.technology}{Number.isFinite(connection.latencyMs) ? ` · ${connection.latencyMs} ms` : " · 상태 확인 API 연결 전"}</p>
          <span className={`admin-status admin-status--${connection.status}`}><i />{STATUS_LABELS[connection.status] ?? STATUS_LABELS.unknown}</span>
        </article>)}
      </div>
      <p className="admin-panel__receipt">{data?.checkedAt ? `마지막 확인 ${data.checkedAt}` : "Backend 상태 확인 API가 연결되면 마지막 확인 시각이 표시됩니다."}</p>
    </section>}

    {section === "accounts" && <section className="admin-panel" id="admin-panel-accounts" role="tabpanel" aria-labelledby="admin-tab-accounts">
      <header className="admin-panel__header">
        <div><small>ADMIN SYSTEM ACCOUNTS</small><h2>권한 관리</h2><p>관리자 시스템 계정과 역할을 관리합니다. 분석 사용자 권한은 기존 인증 정책을 그대로 따릅니다.</p></div>
        <button className="primary" type="button" disabled={!onCreateAccount} onClick={onCreateAccount}><UserPlus size={15} />관리자 추가</button>
      </header>
      <div className="admin-table-card card">
        <div className="admin-data-table admin-data-table--accounts" role="table" aria-label="관리자 계정">
          <div className="admin-data-table__head" role="row"><span role="columnheader">이름</span><span role="columnheader">이메일</span><span role="columnheader">역할</span><span role="columnheader">상태</span><span role="columnheader">등록일</span><span role="columnheader">관리</span></div>
          {accounts.map((account) => <div className="admin-data-table__row" role="row" key={account.id}>
            <b role="cell">{account.name}</b><span role="cell">{account.email}</span><span role="cell"><em>{account.role}</em></span><span role="cell"><strong className={`admin-status admin-status--${account.status === "active" ? "ready" : account.status === "inactive" ? "down" : "unknown"}`}><i />{account.status === "active" ? "활성" : account.status === "inactive" ? "비활성" : "확인 전"}</strong></span><span role="cell">{account.createdAt}</span><span role="cell">Backend 연결 후 제공</span>
          </div>)}
          {accounts.length === 0 && <div className="admin-empty" role="row"><div role="cell"><UserCog size={24} /><b>표시할 관리자 계정이 없습니다.</b><span>계정 관리 API가 연결되면 이름, 이메일, 역할, 상태와 등록일이 표시됩니다.</span></div></div>}
        </div>
      </div>
    </section>}

    {section === "audit" && <section className="admin-panel" id="admin-panel-audit" role="tabpanel" aria-labelledby="admin-tab-audit">
      <header className="admin-panel__header">
        <div><small>ADMIN ACTIVITY HISTORY</small><h2>감사 로그</h2><p>관리자 로그인, 연결 확인, 계정 변경 등 운영 작업의 결과와 대상을 확인합니다.</p></div>
      </header>
      <div className="admin-table-card card">
        <div className="admin-data-table admin-data-table--audit" role="table" aria-label="관리자 감사 로그">
          <div className="admin-data-table__head" role="row"><span role="columnheader">일시</span><span role="columnheader">수행자</span><span role="columnheader">이벤트</span><span role="columnheader">대상</span><span role="columnheader">결과</span><span role="columnheader">상세</span></div>
          {auditLogs.map((log) => <div className="admin-data-table__row" role="row" key={log.id}>
            <span role="cell">{log.occurredAt}</span><span role="cell">{log.actor}</span><b role="cell">{log.event}</b><span role="cell">{log.target}</span><span role="cell"><strong className={`admin-status admin-status--${log.result === "SUCCESS" ? "ready" : "down"}`}><i />{log.result}</strong></span><code role="cell">{log.detail}</code>
          </div>)}
          {auditLogs.length === 0 && <div className="admin-empty" role="row"><div role="cell"><FileClock size={24} /><b>표시할 감사 로그가 없습니다.</b><span>감사 API가 연결되면 관리자 작업 이력이 시간순으로 표시됩니다.</span></div></div>}
        </div>
      </div>
    </section>}
  </div>;
}
