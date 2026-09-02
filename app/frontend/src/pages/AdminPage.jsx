/** 관리자 계정·연결 상태와 읽기 전용 감사 추적 화면의 탭·공통 상태를 조정한다. */
import {
  AlertTriangle,
  BrainCircuit,
  Check,
  ChevronLeft,
  ChevronRight,
  Database,
  FileClock,
  KeyRound,
  Pencil,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  UserCog,
  UserPlus,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { DiMsqlServer } from "react-icons/di";
import { SiClickhouse, SiMysql, SiPostgresql, SiTrino } from "react-icons/si";
import { AdminApiError } from "../api/adminClient.ts";
import {
  AUTH_ACCOUNT_ROLE_OPTIONS,
  roleLabel,
} from "../authorization.ts";
import { AuditTrailPanel } from "../features/admin/audit/AuditTrailPanel.tsx";

const ADMIN_SECTIONS = [
  { id: "connections", label: "연결 상태", icon: Database },
  { id: "accounts", label: "계정 관리", icon: UserCog },
  { id: "audit", label: "감사 로그", icon: FileClock },
];

const STATUS_LABELS = { ready: "정상", down: "연결 실패", paused: "점검 중지" };
const EMPTY_PAGE = { items: [], page: 1, page_size: 50, total: 0 };
const PAUSED_CONNECTIONS_STORAGE_KEY = "answervice:admin-paused-connections";

/** DataHub 공식 저장소의 color mark를 카드 크기에 맞춘다. */
function DataHubMark({ size = 26 }) {
  return <svg width={size} height={size} viewBox="0 0 121 120" fill="none">
    <path d="M8.40165 90.0111C13.5905 98.9778 21.0239 106.467 29.9461 111.722C38.8683 116.978 49.2794 120 60.3683 120C76.9239 120 91.9461 113.278 102.791 102.422C113.646 91.5778 120.368 76.5444 120.368 60C120.368 43.4444 113.646 28.4222 102.791 17.5778C91.9461 6.72222 76.9239 0 60.3683 0C57.8239 0 55.7572 2.06667 55.7572 4.61111C55.7572 7.15556 57.8239 9.22222 60.3683 9.22222C74.4017 9.22222 87.0683 14.9 96.2683 24.0889C105.457 33.2889 111.135 45.9556 111.135 59.9889C111.135 74.0222 105.457 86.6889 96.2683 95.8889C87.0683 105.089 74.4017 110.756 60.3683 110.756C50.9572 110.756 42.1794 108.2 34.635 103.756C27.0905 99.3111 20.7794 92.9556 16.3905 85.3667C15.1128 83.1556 12.2905 82.4111 10.0794 83.6889C7.86832 84.9667 7.12388 87.7889 8.40165 90V90.0111Z" fill="#006DCD" />
    <path d="M81.1353 24.0222C74.8131 20.3778 67.6242 18.4556 60.3353 18.4556C53.2909 18.4556 46.1242 20.2556 39.602 24.0222C32.9464 27.8556 27.7464 33.2889 24.2131 39.5333C20.6798 45.7778 18.8242 52.8556 18.8242 60.0333C18.8242 67.0778 20.6242 74.2445 24.3909 80.7667C28.2242 87.4111 33.6576 92.6222 39.902 96.1556C46.1464 99.6889 53.2131 101.544 60.402 101.544C67.4464 101.544 74.6131 99.7444 81.1353 95.9778C83.3464 94.7 84.102 91.8778 82.8242 89.6778C81.5464 87.4667 78.7242 86.7111 76.5242 87.9889C71.4242 90.9333 65.8798 92.3222 60.402 92.3222C54.8242 92.3222 49.302 90.8667 44.4464 88.1222C39.5909 85.3778 35.3909 81.3556 32.3909 76.1556C29.4464 71.0556 28.0576 65.5222 28.0576 60.0333C28.0576 54.4556 29.5131 48.9333 32.2576 44.0778C35.002 39.2222 39.0242 35.0222 44.2242 32.0222C49.3242 29.0778 54.8576 27.6889 60.3464 27.6889C66.0242 27.6889 71.6242 29.1889 76.5464 32.0222C78.7576 33.3 81.5798 32.5333 82.8464 30.3222C84.1131 28.1111 83.3464 25.2889 81.1353 24.0222Z" fill="#EC9E32" />
    <path d="M60.3689 83.078C66.7245 83.078 72.5245 80.4891 76.6911 76.3224C80.8578 72.1557 83.4578 66.3668 83.4467 60.0002C83.4467 53.6446 80.8578 47.8446 76.6911 43.678C72.5245 39.5113 66.7356 36.9113 60.3689 36.9224C57.8245 36.9224 55.7578 38.9891 55.7578 41.5335C55.7578 44.078 57.8245 46.1446 60.3689 46.1446C64.2023 46.1446 67.6356 47.6891 70.1578 50.2002C72.6689 52.7224 74.2134 56.1557 74.2134 59.9891C74.2134 63.8224 72.6689 67.2557 70.1578 69.778C67.6356 72.2891 64.2023 73.8335 60.3689 73.8335C57.8245 73.8335 55.7578 75.9002 55.7578 78.4446C55.7578 80.9891 57.8245 83.078 60.3689 83.078Z" fill="#D23500" />
  </svg>;
}

const CONNECTION_VISUALS = Object.freeze({
  pms: { icon: SiPostgresql, tone: "postgresql", label: "PostgreSQL" },
  pos: { icon: SiMysql, tone: "mysql", label: "MySQL" },
  crm: { icon: DiMsqlServer, tone: "sqlserver", label: "SQL Server" },
  facility: { icon: SiClickhouse, tone: "clickhouse", label: "ClickHouse" },
  banquet: { icon: SiPostgresql, tone: "postgresql", label: "PostgreSQL" },
  "app-postgres": { icon: SiPostgresql, tone: "postgresql", label: "PostgreSQL" },
  trino: { icon: SiTrino, tone: "trino", label: "Trino" },
  datahub: { icon: DataHubMark, tone: "datahub", label: "DataHub" },
  "model-api": { icon: BrainCircuit, tone: "model", label: "Model API" },
});
const CONNECTION_IDS = new Set(Object.keys(CONNECTION_VISUALS));

function readPausedConnectionIds() {
  if (typeof window === "undefined") return [];
  try {
    return (window.sessionStorage.getItem(PAUSED_CONNECTIONS_STORAGE_KEY) || "")
      .split(",")
      .filter((id) => CONNECTION_IDS.has(id));
  } catch {
    return [];
  }
}

function savePausedConnectionIds(ids) {
  try {
    if (ids.length > 0) window.sessionStorage.setItem(PAUSED_CONNECTIONS_STORAGE_KEY, ids.join(","));
    else window.sessionStorage.removeItem(PAUSED_CONNECTIONS_STORAGE_KEY);
  } catch {
    // 브라우저 저장소가 차단돼도 현재 화면의 토글 상태는 유지한다.
  }
}

function adminErrorMessage(error) {
  if (!(error instanceof AdminApiError)) return "관리자 API 응답을 확인할 수 없습니다.";
  if (error.status === 401) return "로그인 세션이 만료되었습니다. 다시 로그인해 주세요.";
  if (error.status === 403) return "관리자 권한이 없어 이 요청을 실행할 수 없습니다.";
  if (error.status === 409) return error.message;
  if (error.status >= 500) return "관리자 서버에서 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
  return error.message;
}

function formatTimestamp(value) {
  if (!value) return "-";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
}

/** 고정 연결 ID에 대응하는 엔진 아이콘과 상태 점검 switch를 한 카드에 표시한다. */
function ConnectionCard({ connection, index, paused, pending, onToggle }) {
  const visual = CONNECTION_VISUALS[connection.id] ?? { icon: Database, tone: "default", label: connection.kind };
  const Icon = visual.icon;
  const status = paused ? "paused" : connection.status;
  const enabled = status !== "paused";

  return <article className={`admin-connection-card card${enabled ? "" : " is-paused"}`} data-connection-tone={visual.tone}>
    <header>
      <span className="admin-connection-card__icon" aria-hidden="true"><Icon size={26} /></span>
      <span className="admin-connection-card__index">{String(index + 1).padStart(2, "0")}</span>
      <button
        className="admin-connection-switch"
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={`${connection.name} 상태 점검 ${enabled ? "끄기" : "켜기"}`}
        disabled={pending}
        onClick={() => onToggle(connection)}
      ><span aria-hidden="true"><i /></span><em>{enabled ? "ON" : "OFF"}</em></button>
    </header>
    <div className="admin-connection-card__body">
      <span>{visual.label}</span>
      <h3>{connection.name}</h3>
      <p>{enabled && Number.isFinite(connection.latency_ms) ? `${connection.latency_ms} ms 응답` : "상태 점검 일시중지"}</p>
    </div>
    <footer>
      <span className={`admin-status admin-status--${status}`}><i />{STATUS_LABELS[status] ?? status}</span>
      <small>{enabled ? connection.kind : "수동으로 다시 켤 수 있습니다"}</small>
    </footer>
  </article>;
}

/** 계정 생성·수정·비밀번호 초기화 입력을 native modal dialog로 수집한다. */
function AccountDialog({ account, form, mode, pending, error, onChange, onClose, onSubmit }) {
  const dialogRef = useRef(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => { if (dialog?.open) dialog.close(); };
  }, []);

  const passwordMode = mode === "password";
  const title = mode === "create" ? "계정 추가" : passwordMode ? "비밀번호 초기화" : "계정 수정";
  return <dialog
    ref={dialogRef}
    className="admin-account-dialog"
    aria-labelledby="admin-account-dialog-title"
    onCancel={(event) => { if (pending) event.preventDefault(); else onClose(); }}
  >
    <form onSubmit={onSubmit}>
      <header><div><small>ADMIN ACCOUNT</small><h2 id="admin-account-dialog-title">{title}</h2>{account && <p>{account.username}</p>}</div><button type="button" aria-label="닫기" onClick={onClose} disabled={pending}><X size={18} /></button></header>
      <div className="admin-account-dialog__fields">
        {!passwordMode && <>
          <label><span>사용자 아이디</span><input required minLength={3} maxLength={64} pattern="[a-z0-9._-]+" autoComplete="off" value={form.username} onChange={(event) => onChange({ ...form, username: event.target.value.toLowerCase() })} /></label>
          <label><span>역할</span><select value={form.role} onChange={(event) => onChange({ ...form, role: event.target.value })}>{AUTH_ACCOUNT_ROLE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label} ({option.value})</option>)}</select></label>
        </>}
        {(mode === "create" || passwordMode) && <label><span>{passwordMode ? "새 비밀번호" : "초기 비밀번호"}</span><input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={form.password} onChange={(event) => onChange({ ...form, password: event.target.value })} /></label>}
        {mode === "edit" && <label className="admin-account-dialog__check"><input type="checkbox" checked={form.active} onChange={(event) => onChange({ ...form, active: event.target.checked })} /><span>활성 계정</span></label>}
        {error && <p className="admin-account-dialog__error" role="alert"><AlertTriangle size={16} />{error}</p>}
      </div>
      <footer><button type="button" onClick={onClose} disabled={pending}>취소</button><button className="primary" type="submit" disabled={pending}>{pending ? "저장 중…" : passwordMode ? "비밀번호 변경" : "저장"}</button></footer>
    </form>
  </dialog>;
}

/** `system.manage`로 보호된 관리자 기능을 조립 지점에서 주입한 단일 API 포트에만 배선한다. */
export function AdminPage({ role, client }) {
  const requestIds = useRef({ connections: 0, accounts: 0 });
  const [section, setSection] = useState("connections");
  const activeSectionRef = useRef(section);
  activeSectionRef.current = section;
  const [loading, setLoading] = useState({ connections: false, accounts: false });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connections, setConnections] = useState([]);
  const [pausedConnectionIds, setPausedConnectionIds] = useState(readPausedConnectionIds);
  const [accounts, setAccounts] = useState(EMPTY_PAGE);
  const [accountPage, setAccountPage] = useState(1);
  const [accountSearch, setAccountSearch] = useState("");
  const [accountSearchInput, setAccountSearchInput] = useState("");
  const [modal, setModal] = useState(null);
  const [accountForm, setAccountForm] = useState({ username: "", password: "", role: "analyst", active: true });
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState("");

  const loadConnections = useCallback(async () => {
    const requestId = ++requestIds.current.connections;
    setLoading((current) => ({ ...current, connections: true }));
    setError("");
    try {
      const items = await client.listConnections(pausedConnectionIds);
      if (requestIds.current.connections !== requestId || activeSectionRef.current !== "connections") return;
      setConnections(items);
    } catch (nextError) {
      if (requestIds.current.connections !== requestId || activeSectionRef.current !== "connections") return;
      setConnections([]);
      setError(adminErrorMessage(nextError));
    } finally {
      if (requestIds.current.connections === requestId) setLoading((current) => ({ ...current, connections: false }));
    }
  }, [client, pausedConnectionIds]);

  const loadAccounts = useCallback(async () => {
    const requestId = ++requestIds.current.accounts;
    setLoading((current) => ({ ...current, accounts: true }));
    setError("");
    try {
      const page = await client.listAccounts(accountPage, accountSearch);
      if (requestIds.current.accounts !== requestId || activeSectionRef.current !== "accounts") return;
      setAccounts(page);
    } catch (nextError) {
      if (requestIds.current.accounts !== requestId || activeSectionRef.current !== "accounts") return;
      setAccounts({ ...EMPTY_PAGE, page: accountPage });
      setError(adminErrorMessage(nextError));
    } finally {
      if (requestIds.current.accounts === requestId) setLoading((current) => ({ ...current, accounts: false }));
    }
  }, [accountPage, accountSearch, client]);

  useEffect(() => {
    for (const id of ["connections", "accounts"]) {
      if (id !== section) requestIds.current[id] += 1;
    }
    setLoading((current) => ({
      connections: section === "connections" ? current.connections : false,
      accounts: section === "accounts" ? current.accounts : false,
    }));
  }, [section]);

  useEffect(() => {
    if (section === "connections") void loadConnections();
    if (section === "accounts") void loadAccounts();
  }, [loadAccounts, loadConnections, section]);

  const openCreate = () => {
    setAccountForm({ username: "", password: "", role: "analyst", active: true });
    setDialogError("");
    setModal({ mode: "create", account: null });
  };

  const toggleConnectionMonitoring = (connection) => {
    const currentlyPaused = pausedConnectionIds.includes(connection.id);
    setPausedConnectionIds((current) => {
      const next = currentlyPaused
        ? current.filter((id) => id !== connection.id)
        : [...current, connection.id].sort();
      savePausedConnectionIds(next);
      return next;
    });
    setNotice(`${connection.name} 상태 점검을 ${currentlyPaused ? "다시 시작했습니다." : "일시 중지했습니다."}`);
  };
  const openEdit = (account) => {
    setAccountForm({ username: account.username, password: "", role: account.role, active: account.active });
    setDialogError("");
    setModal({ mode: "edit", account });
  };
  const openPassword = (account) => {
    setAccountForm({ username: account.username, password: "", role: account.role, active: account.active });
    setDialogError("");
    setModal({ mode: "password", account });
  };

  const refreshAccountsAfterMutation = async () => {
    const requestId = ++requestIds.current.accounts;
    setLoading((current) => ({ ...current, accounts: true }));
    try {
      const page = await client.listAccounts(accountPage, accountSearch);
      if (requestIds.current.accounts !== requestId) return;
      setAccounts(page);
    } catch (nextError) {
      if (requestIds.current.accounts === requestId) setAccounts({ ...EMPTY_PAGE, page: accountPage });
      throw nextError;
    } finally {
      if (requestIds.current.accounts === requestId) setLoading((current) => ({ ...current, accounts: false }));
    }
  };

  const submitAccount = async (event) => {
    event.preventDefault();
    setSaving(true);
    setDialogError("");
    try {
      if (modal.mode === "create") {
        await client.createAccount({ username: accountForm.username.trim(), password: accountForm.password, role: accountForm.role });
        setNotice("계정을 추가했습니다.");
      } else if (modal.mode === "edit") {
        await client.updateAccount(modal.account.subject, {
          username: accountForm.username.trim(),
          active: accountForm.active,
          ...(accountForm.role === modal.account.role ? {} : { role: accountForm.role }),
        });
        setNotice("계정 정보를 변경했습니다. 변경된 계정의 기존 세션은 종료됩니다.");
      } else {
        await client.resetPassword(modal.account.subject, accountForm.password);
        setNotice("비밀번호를 변경했습니다. 해당 계정의 기존 세션은 종료됩니다.");
      }
      await refreshAccountsAfterMutation();
      setModal(null);
    } catch (nextError) {
      setDialogError(adminErrorMessage(nextError));
    } finally {
      setSaving(false);
    }
  };

  const deleteAccount = async (account) => {
    if (!window.confirm(`${account.username} 계정을 삭제할까요? 계정은 복구 가능한 비활성 상태로 보관됩니다.`)) return;
    setSaving(true);
    setError("");
    try {
      await client.deleteAccount(account.subject);
      await refreshAccountsAfterMutation();
      setNotice("계정을 삭제했습니다.");
    } catch (nextError) {
      setError(adminErrorMessage(nextError));
    } finally {
      setSaving(false);
    }
  };

  const checkedAt = connections[0]?.checked_at;
  const accountPageCount = Math.max(1, Math.ceil(accounts.total / accounts.page_size));

  return <div className="page-content admin-console">
    <section className="admin-console__status" aria-label="관리자 시스템 상태">
      <div><ShieldCheck size={18} /><span><b>{roleLabel(role)}</b><small>현재 세션 권한으로 접근 중</small></span></div>
    </section>

    {error && <p className="admin-feedback admin-feedback--error" role="alert"><AlertTriangle size={17} />{error}</p>}
    {notice && <p className="admin-feedback admin-feedback--notice" role="status"><Check size={17} />{notice}<button type="button" aria-label="알림 닫기" onClick={() => setNotice("")}><X size={14} /></button></p>}

    <nav className="admin-console__tabs" role="tablist" aria-label="관리자 기능">
      {ADMIN_SECTIONS.map(({ id, label, icon: Icon }) => <button key={id} id={`admin-tab-${id}`} type="button" role="tab" aria-selected={section === id} aria-controls={`admin-panel-${id}`} className={section === id ? "is-active" : ""} disabled={saving} onClick={() => setSection(id)}><Icon size={17} /><span>{label}</span></button>)}
    </nav>

    {section === "connections" && <section className="admin-panel" id="admin-panel-connections" role="tabpanel" aria-labelledby="admin-tab-connections">
      <header className="admin-panel__header"><div><small>READ ONLY INFRASTRUCTURE</small><h2>데이터 연결 상태</h2><p>연결별 상태 점검을 켜거나 일시 중지하고, 승인된 서비스의 응답 상태를 확인합니다.</p></div><button className="secondary" type="button" disabled={loading.connections} onClick={() => void loadConnections()}><RefreshCw size={15} />{loading.connections ? "확인 중…" : "상태 새로고침"}</button></header>
      <div className="admin-connection-grid">
        {connections.map((connection, index) => <ConnectionCard key={connection.id} connection={connection} index={index} paused={pausedConnectionIds.includes(connection.id)} pending={loading.connections} onToggle={toggleConnectionMonitoring} />)}
      </div>
      {!loading.connections && connections.length === 0 && !error && <div className="admin-empty card"><div><Database size={24} /><b>등록된 연결 점검 대상이 없습니다.</b><span>Backend에 승인된 연결 대상이 등록되면 이곳에 표시됩니다.</span></div></div>}
      <p className="admin-panel__receipt">{checkedAt ? `마지막 확인 ${formatTimestamp(checkedAt)}` : loading.connections ? "연결 상태를 확인하고 있습니다." : "확인된 연결 상태가 없습니다."}</p>
    </section>}

    {section === "accounts" && <section className="admin-panel" id="admin-panel-accounts" role="tabpanel" aria-labelledby="admin-tab-accounts">
      <header className="admin-panel__header"><div><small>USER ACCOUNTS</small><h2>계정 관리</h2><p>서비스 계정의 역할, 활성 상태와 비밀번호를 관리합니다.</p></div><button className="primary" type="button" disabled={saving} onClick={openCreate}><UserPlus size={15} />계정 추가</button></header>
      <form className="admin-list-toolbar" onSubmit={(event) => { event.preventDefault(); setAccountPage(1); setAccountSearch(accountSearchInput.trim()); if (accountPage === 1 && accountSearch === accountSearchInput.trim()) void loadAccounts(); }}><label><Search size={15} /><input value={accountSearchInput} onChange={(event) => setAccountSearchInput(event.target.value)} placeholder="사용자 아이디 검색" aria-label="계정 검색" /></label><button type="submit">검색</button></form>
      <div className="admin-table-card card"><div className="admin-data-table admin-data-table--accounts" role="table" aria-label="사용자 계정">
        <div className="admin-data-table__head" role="row"><span role="columnheader">사용자 아이디</span><span role="columnheader">역할</span><span role="columnheader">상태</span><span role="columnheader">등록일</span><span role="columnheader">관리</span></div>
        {accounts.items.map((account) => <div className="admin-data-table__row" role="row" key={account.subject}><b role="cell" data-label="사용자 아이디">{account.username}</b><span role="cell" data-label="역할"><em>{roleLabel(account.role)}</em></span><span role="cell" data-label="상태"><strong className={`admin-status admin-status--${account.active ? "ready" : "down"}`}><i />{account.active ? "활성" : "비활성"}</strong></span><span role="cell" data-label="등록일">{formatTimestamp(account.created_at)}</span><span className="admin-row-actions" role="cell" data-label="관리"><button type="button" disabled={saving} onClick={() => openEdit(account)}><Pencil size={13} />수정</button><button type="button" disabled={saving} onClick={() => openPassword(account)}><KeyRound size={13} />비밀번호</button><button className="danger" type="button" disabled={saving} onClick={() => void deleteAccount(account)}><Trash2 size={13} />삭제</button></span></div>)}
        {!loading.accounts && accounts.items.length === 0 && <div className="admin-empty" role="row"><div role="cell"><UserCog size={24} /><b>조건에 맞는 계정이 없습니다.</b><span>검색 조건을 변경하거나 계정을 추가해 주세요.</span></div></div>}
      </div></div>
      <div className="admin-pagination"><span>총 {accounts.total.toLocaleString()}개 · {accounts.page}/{accountPageCount} 페이지</span><div><button type="button" disabled={accountPage <= 1 || loading.accounts} onClick={() => setAccountPage((current) => current - 1)}><ChevronLeft size={15} />이전</button><button type="button" disabled={accountPage >= accountPageCount || loading.accounts} onClick={() => setAccountPage((current) => current + 1)}>다음<ChevronRight size={15} /></button></div></div>
    </section>}

    {section === "audit" && <AuditTrailPanel client={client} />}

    {modal && <AccountDialog account={modal.account} form={accountForm} mode={modal.mode} pending={saving} error={dialogError} onChange={setAccountForm} onClose={() => setModal(null)} onSubmit={submitAccount} />}
  </div>;
}
