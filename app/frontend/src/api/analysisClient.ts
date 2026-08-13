import {
  normalizeApiResponse,
  OPENAPI_VERSION,
  type AnalysisApiResponse,
  type AnalysisRun,
  type AnalysisValue,
} from "../contracts/analysis.ts";
import { createUuid } from "../utils/createUuid.ts";

export interface AnalysisClient {
  login(username: string, password: string): Promise<LoginSession>;
  validateSession(): Promise<SessionInfo>;
  analyze(question: string, conversationId: string, parameters: { period_start: string; period_end_exclusive: string }): Promise<AnalysisRun>;
  createDefinition(title: string, question: string, parameters: Record<string, AnalysisValue>): Promise<SavedAnalysisDefinition>;
  listDefinitions(): Promise<SavedAnalysisDefinition[]>;
  replayDefinition(definitionId: string, parameters: Record<string, AnalysisValue>): Promise<SavedAnalysisRun>;
  getRunArtifact(requestId: string, conversationId: string): Promise<AnalysisRun>;
  listRuns(): Promise<SavedAnalysisRun[]>;
}

export interface SessionInfo {
  status: "authenticated";
  role: "hotel_analyst" | "report_admin" | "data_admin";
}

export interface LoginSession extends SessionInfo {
  session_token: string;
}

export interface SavedAnalysisDefinition {
  definition_id: string;
  version: number;
  status: "approved";
  title: string;
  parameter_types: Record<string, string>;
  created_at: string;
}

export interface SavedAnalysisRun {
  request_id: string;
  definition_id: string;
  definition_version: number;
  status: "RECEIVED" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "BLOCKED";
  as_of: string;
  timezone: string;
  trace_id: string;
  query_id: string | null;
  artifact_id: string | null;
  error_type: string | null;
  started_at: string;
  completed_at: string | null;
}

interface SavedAnalysisArtifact {
  request_id: string;
  trace_id: string;
  status: "SUCCEEDED" | "PARTIAL";
  question: string;
  summary: string;
  table: { columns: string[]; rows: Array<Record<string, AnalysisValue>> };
  chart: { chart_type: string; x_field: string; y_fields: string[] } | null;
  evidence: NonNullable<NonNullable<AnalysisApiResponse["data"]["result"]>["evidence"]>;
  artifact_id: string;
  query_id: string;
  artifact_checksum: string;
}

type Fetch = typeof fetch;
const env = import.meta.env ?? {};

function seoulToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function authenticationHeaders(explicitToken = "") {
  if (!explicitToken) throw new Error("분석 인증 세션이 없습니다.");
  return { Authorization: `Bearer ${explicitToken}` };
}

export function createHttpAnalysisClient(
  baseUrl = env.VITE_BACKEND_BASE_URL,
  request: Fetch = fetch,
  authToken = "",
): AnalysisClient {
  if (!baseUrl) throw new Error("VITE_BACKEND_BASE_URL is required");
  const endpoint = (path: string) => `${baseUrl.replace(/\/$/, "")}${path}`;
  const headers = (json = false) => ({
    ...(json ? { "Content-Type": "application/json" } : {}),
    ...authenticationHeaders(authToken),
    "X-As-Of": env.VITE_ANALYSIS_AS_OF || seoulToday(),
    "X-Contract-Version": OPENAPI_VERSION,
    "X-Timezone": "Asia/Seoul",
    "X-Trace-Id": createUuid(),
  });
  const parse = async <T>(response: Response): Promise<T> => {
    const payload: any = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error?.message || payload?.detail || `Analysis API request failed (${response.status})`);
    return payload as T;
  };
  return {
    async login(username, password) {
      const payload = await parse<{ data: LoginSession }>(await request(endpoint("/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      }));
      if (payload?.data?.status !== "authenticated" || !payload.data.session_token) {
        throw new Error("로그인 API가 올바르지 않은 응답을 반환했습니다.");
      }
      return payload.data;
    },
    async validateSession() {
      const payload = await parse<{ data: SessionInfo }>(await request(endpoint("/auth/session"), {
        headers: authenticationHeaders(authToken),
      }));
      if (payload?.data?.status !== "authenticated") throw new Error("인증 API가 올바르지 않은 응답을 반환했습니다.");
      return payload.data;
    },
    async analyze(question, conversationId, parameters) {
      const response = await request(endpoint("/analysis"), {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ question, parameters }),
      });
      const payload = await parse<AnalysisApiResponse>(response);
      if (!payload?.data || !payload.meta) throw new Error("Analysis API returned an invalid response");
      return normalizeApiResponse(payload, question, conversationId);
    },
    async createDefinition(title, question, parameters) {
      return parse<SavedAnalysisDefinition>(await request(endpoint("/analysis/definitions"), {
        method: "POST", headers: headers(true), body: JSON.stringify({ title, question, parameters }),
      }));
    },
    async listDefinitions() {
      return (await parse<{ items: SavedAnalysisDefinition[] }>(
        await request(endpoint("/analysis/definitions"), { headers: headers() }),
      )).items;
    },
    async replayDefinition(definitionId, parameters) {
      return parse<SavedAnalysisRun>(await request(endpoint(`/analysis/definitions/${encodeURIComponent(definitionId)}/runs`), {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ as_of: env.VITE_ANALYSIS_AS_OF || seoulToday(), idempotency_key: createUuid(), parameters }),
      }));
    },
    async getRunArtifact(requestId, conversationId) {
      const detail = await parse<SavedAnalysisArtifact>(await request(
        endpoint(`/analysis/runs/${encodeURIComponent(requestId)}/artifact`),
        { headers: headers() },
      ));
      return normalizeApiResponse({
        data: {
          status: detail.status,
          artifact: {
            artifact_id: detail.artifact_id,
            query_id: detail.query_id,
          },
          result: {
            summary: detail.summary,
            metrics: [],
            table: detail.table,
            chart: detail.chart,
            evidence: detail.evidence,
          },
        },
        meta: {
          request_id: detail.request_id,
          trace_id: detail.trace_id,
          as_of: detail.evidence.as_of,
          contract_version: OPENAPI_VERSION,
          timestamp: new Date().toISOString(),
        },
      }, detail.question, conversationId);
    },
    async listRuns() {
      return (await parse<{ items: SavedAnalysisRun[] }>(
        await request(endpoint("/analysis/runs"), { headers: headers() }),
      )).items;
    },
  };
}

export function createAnalysisClient(request: Fetch = fetch, authToken = ""): AnalysisClient {
  return createHttpAnalysisClient(undefined, request, authToken);
}
