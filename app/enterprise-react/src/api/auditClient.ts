import { createUuid } from "../utils/createUuid.ts";
import { OPENAPI_VERSION } from "../contracts/analysis.ts";
import { getAuthorizationHeader } from "./authSession.ts";

const env = import.meta.env ?? {};
type Fetch = typeof fetch;

export interface AuditRequestSummary {
  request_id: string;
  user_id: string;
  user_role: string;
  request_type: string;
  status: string;
  error_type: string | null;
  trace_id: string;
  started_at: string;
  completed_at: string | null;
}

export interface EffectiveAccess {
  policy_version: string;
  subject: string;
  role: "hotel_analyst" | "report_admin" | "data_admin";
  mapping_source: "test_seed" | "release_principal";
}

export interface RecoveryStatus {
  generated_at: string;
  retention: { status: "unknown" | "not_run" | "dry_run" | "applied"; last_run_at: string | null };
  backup: { status: "unknown" | "not_run" | "available"; created_at: string | null; age_hours: number | null; sha256: string | null; rpo_target_hours: number; rpo_passed: boolean | null };
  restore: { status: "unknown" | "not_run" | "verified"; verified_at: string | null; mode: "unknown" | "not_run" | "archive-list-only" | "isolated-restore"; backup_age_hours: number | null; restore_duration_hours: number | null; rpo_target_hours: number; rpo_passed: boolean | null; rto_target_hours: number; rto_passed: boolean | null; backup_sha256: string | null };
}

export interface AuditTrace extends AuditRequestSummary {
  transitions: ReadonlyArray<{ sequence: number; from_status: string | null; to_status: string; created_at: string }>;
  analysis_definition: { definition_id: string; version: number; status: string } | null;
  context: { release_id: string | null; release_key: string | null; release_version: number | null; release_hash: string | null; package_id: string | null; package_hash: string | null };
  policy: { sql_policy_version: string; policy_version: string; entitlement_hash: string | null };
  access: { access_profile: string | null; allowed_domains: readonly string[]; datahub_actor: string | null; allowed_urns: readonly string[]; trino_role: string | null; datahub_search_attempted: boolean; trino_execution_attempted: boolean };
  model: { model_version_id: string; model_role: string; model_name: string; model_revision: string; runtime_name: string } | null;
  query: { query_id: string | null; generation_mode: string; validation_status: string; execution_status: string; duration_ms: number | null; source_urns: readonly string[] } | null;
  artifact: { artifact_id: string; artifact_type: string; freshness_status: string; status: string; artifact_checksum: string; masking: { applied: boolean; fields: readonly string[] } } | null;
  reports: ReadonlyArray<{ definition_id: string; definition_version: number; run_id: string; status: string }>;
}

async function parse<T>(response: Response): Promise<T> {
  const payload: any = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.detail || `감사 Trace 요청에 실패했습니다. (${response.status})`);
  return payload as T;
}

export function createAuditClient(
  baseUrl = env.VITE_BACKEND_BASE_URL || "http://127.0.0.1:18000",
  request: Fetch = fetch,
) {
  const send = (path: string) => request(`${baseUrl.replace(/\/$/, "")}${path}`, {
    headers: {
      Authorization: getAuthorizationHeader(),
      "X-As-Of": new Date().toISOString().slice(0, 10),
      "X-Contract-Version": OPENAPI_VERSION,
      "X-Timezone": "Asia/Seoul",
      "X-Trace-Id": createUuid(),
    },
  });

  return {
    async getAccess(): Promise<EffectiveAccess> {
      return parse<EffectiveAccess>(await send("/operations/audit/access"));
    },
    async getRecovery(): Promise<RecoveryStatus> {
      return parse<RecoveryStatus>(await send("/operations/audit/recovery"));
    },
    async search(filters: { requestId?: string; status?: string; startedFrom?: string; startedTo?: string } | string = {}): Promise<readonly AuditRequestSummary[]> {
      const normalized = typeof filters === "string" ? { requestId: filters } : filters;
      const parameters = new URLSearchParams();
      if (normalized.requestId?.trim()) parameters.set("request_id", normalized.requestId.trim());
      if (normalized.status?.trim()) parameters.set("status", normalized.status.trim());
      if (normalized.startedFrom) parameters.set("started_from", normalized.startedFrom);
      if (normalized.startedTo) parameters.set("started_to", normalized.startedTo);
      const query = parameters.size ? `?${parameters}` : "";
      return (await parse<{ items: AuditRequestSummary[] }>(await send(`/operations/audit${query}`))).items;
    },
    async get(requestId: string): Promise<AuditTrace> {
      return parse<AuditTrace>(await send(`/operations/audit/${encodeURIComponent(requestId)}`));
    },
  };
}
