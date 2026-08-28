/** 관리자 계정·연결 상태와 서버 grouping 감사 trail을 cookie 인증 HTTP 요청으로 제공한다. */
import type { ServiceRole } from "../authorization.ts";
import { OPENAPI_VERSION } from "../contracts/analysis.ts";
import {
  normalizeAuditTrailDetail,
  normalizeAuditTrailPage,
  type AuditTrailFilters,
} from "../features/admin/audit/auditTrailTypes.ts";
import { createUuid } from "../utils/createUuid.ts";

type Fetch = typeof fetch;
const env = import.meta.env ?? {};

/** 관리자 계정 목록과 변경 응답에 포함되는 비밀정보 없는 공개 필드다. */
export interface AdminAccount {
  subject: string;
  username: string;
  role: ServiceRole;
  active: boolean;
  created_at: string;
  updated_at: string;
  deactivated_at: string | null;
  deleted_at: string | null;
}

/** 허용 목록으로 제한된 외부 의존성 상태 점검 결과다. */
export interface AdminConnection {
  id: string;
  name: string;
  kind: string;
  status: "ready" | "down";
  latency_ms: number;
  checked_at: string;
}

/** 서버가 확정한 페이지 번호와 전체 건수를 포함하는 목록 계약이다. */
export interface AdminPage<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

/** HTTP 상태와 서버 오류 코드를 보존해 화면이 인증·권한·충돌·서버 실패를 구분하게 한다. */
export class AdminApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function headers(json = false): Record<string, string> {
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
    "X-Contract-Version": OPENAPI_VERSION,
    "X-Timezone": "Asia/Seoul",
    "X-Trace-Id": createUuid(),
  };
}

async function parseData<T>(response: Response): Promise<T> {
  const payload: any = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("answervice:session-expired"));
    }
    throw new AdminApiError(
      response.status,
      payload?.error?.code || `HTTP_${response.status}`,
      payload?.error?.message || (typeof payload?.detail === "string" ? payload.detail : "관리자 API 요청에 실패했습니다."),
    );
  }
  if (!("data" in payload)) throw new Error("관리자 API가 올바르지 않은 응답을 반환했습니다.");
  return payload.data as T;
}

async function ensureEmpty(response: Response): Promise<void> {
  if (!response.ok) await parseData<never>(response);
}

function queryString(values: Record<string, string | number>): string {
  return new URLSearchParams(Object.entries(values).map(([key, value]) => [key, String(value)])).toString();
}

function sparseQueryString(values: Record<string, string | number>): string {
  return new URLSearchParams(
    Object.entries(values)
      .filter(([, value]) => value !== "")
      .map(([key, value]) => [key, String(value)]),
  ).toString();
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeAccount(value: unknown): AdminAccount {
  if (!isRecord(value)
    || typeof value.subject !== "string"
    || typeof value.username !== "string"
    || !["analyst", "report_admin", "data_admin", "platform_admin"].includes(value.role)
    || typeof value.active !== "boolean"
    || typeof value.created_at !== "string"
    || typeof value.updated_at !== "string"
    || !(value.deactivated_at === null || typeof value.deactivated_at === "string")
    || !(value.deleted_at === null || typeof value.deleted_at === "string")) {
    throw new Error("관리자 계정 API가 올바르지 않은 응답을 반환했습니다.");
  }
  return value as AdminAccount;
}

function normalizePage<T>(value: unknown, normalizeItem: (item: unknown) => T): AdminPage<T> {
  if (!isRecord(value)
    || !Array.isArray(value.items)
    || !Number.isInteger(value.page)
    || !Number.isInteger(value.page_size)
    || !Number.isInteger(value.total)) {
    throw new Error("관리자 목록 API가 올바르지 않은 응답을 반환했습니다.");
  }
  return { items: value.items.map(normalizeItem), page: value.page, page_size: value.page_size, total: value.total };
}

function normalizeConnection(value: unknown): AdminConnection {
  if (!isRecord(value)
    || typeof value.id !== "string"
    || typeof value.name !== "string"
    || typeof value.kind !== "string"
    || !["ready", "down"].includes(value.status)
    || !Number.isInteger(value.latency_ms)
    || typeof value.checked_at !== "string") {
    throw new Error("관리자 연결 API가 올바르지 않은 응답을 반환했습니다.");
  }
  return value as AdminConnection;
}

/** 단일 Backend origin에만 관리자 요청을 보내고 모든 변경 요청에 현재 cookie 세션을 포함한다. */
export function createAdminClient(baseUrl = env.VITE_BACKEND_BASE_URL, request: Fetch = fetch) {
  if (!baseUrl) throw new Error("VITE_BACKEND_BASE_URL is required");
  const endpoint = (path: string) => `${baseUrl.replace(/\/$/, "")}${path}`;
  const send = (path: string, method = "GET", body?: unknown) => request(endpoint(path), {
    method,
    credentials: "include",
    headers: headers(body !== undefined),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  return {
    async listAccounts(page = 1, search = ""): Promise<AdminPage<AdminAccount>> {
      return normalizePage(await parseData(await send(`/admin/accounts?${queryString({ page, page_size: 50, search })}`)), normalizeAccount);
    },
    async createAccount(input: { username: string; password: string; role: ServiceRole }): Promise<AdminAccount> {
      return normalizeAccount(await parseData(await send("/admin/accounts", "POST", input)));
    },
    async updateAccount(subject: string, input: { username?: string; role?: ServiceRole; active?: boolean }): Promise<AdminAccount> {
      return normalizeAccount(await parseData(await send(`/admin/accounts/${encodeURIComponent(subject)}`, "PATCH", input)));
    },
    async resetPassword(subject: string, password: string): Promise<void> {
      await ensureEmpty(await send(`/admin/accounts/${encodeURIComponent(subject)}/password`, "POST", { password }));
    },
    async deleteAccount(subject: string): Promise<void> {
      await ensureEmpty(await send(`/admin/accounts/${encodeURIComponent(subject)}`, "DELETE"));
    },
    async listConnections(): Promise<AdminConnection[]> {
      const data = await parseData<unknown>(await send("/admin/connections"));
      if (!isRecord(data) || !Array.isArray(data.items)) throw new Error("관리자 연결 API가 올바르지 않은 응답을 반환했습니다.");
      return data.items.map(normalizeConnection);
    },
    async listAuditTrails(filters: AuditTrailFilters, cursor = "") {
      const query = sparseQueryString({
        cursor,
        limit: 30,
        query: filters.query,
        outcome: filters.outcome,
        action: filters.action,
        from: filters.from,
        to: filters.to,
      });
      return normalizeAuditTrailPage(await parseData(await send(`/admin/audit-trails?${query}`)));
    },
    async getAuditTrail(trailId: string) {
      return normalizeAuditTrailDetail(await parseData(await send(`/admin/audit-trails/${encodeURIComponent(trailId)}`)));
    },
  };
}
