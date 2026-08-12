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

export interface AuditTrace extends AuditRequestSummary {
  transitions: ReadonlyArray<{ sequence: number; from_status: string | null; to_status: string; created_at: string }>;
  analysis_definition: { definition_id: string; version: number; status: string } | null;
  context: { release_id: string | null; release_key: string | null; release_version: number | null; release_hash: string | null; package_id: string | null; package_hash: string | null };
  policy: { sql_policy_version: string };
  model: { model_version_id: string; model_role: string; model_name: string; model_revision: string; runtime_name: string } | null;
  query: { query_id: string | null; generation_mode: string; validation_status: string; execution_status: string; duration_ms: number | null } | null;
  artifact: { artifact_id: string; artifact_type: string; freshness_status: string; status: string; artifact_checksum: string } | null;
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
    async search(requestId = ""): Promise<readonly AuditRequestSummary[]> {
      const query = requestId.trim() ? `?request_id=${encodeURIComponent(requestId.trim())}` : "";
      return (await parse<{ items: AuditRequestSummary[] }>(await send(`/operations/audit${query}`))).items;
    },
    async get(requestId: string): Promise<AuditTrace> {
      return parse<AuditTrace>(await send(`/operations/audit/${encodeURIComponent(requestId)}`));
    },
  };
}
