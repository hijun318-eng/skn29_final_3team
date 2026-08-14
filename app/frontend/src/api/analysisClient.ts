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
  logout(): Promise<void>;
  analyze(
    question: string,
    parameters?: Record<string, AnalysisValue>,
    options?: AnalysisOptions,
  ): Promise<AnalysisRun>;
  cancelAnalysis(traceId: string): Promise<AnalysisProgress>;
  createDefinition(title: string, sourceRequestId: string): Promise<SavedAnalysisDefinition>;
  listDefinitions(): Promise<SavedAnalysisDefinition[]>;
  replayDefinition(definitionId: string, parameters: Record<string, AnalysisValue>): Promise<SavedAnalysisRun>;
  getRunArtifact(requestId: string): Promise<AnalysisRun>;
  listRuns(): Promise<SavedAnalysisRun[]>;
}

export interface SessionInfo {
  status: "authenticated";
  role: "hotel_analyst" | "report_admin" | "data_admin";
}

export type LoginSession = SessionInfo;

export interface SavedAnalysisDefinition {
  definition_id: string;
  version: number;
  status: "approved";
  title: string;
  question: string;
  parameter_types: Record<string, string>;
  semantic_request: Record<string, unknown>;
  parameter_schema: Record<string, string>;
  created_at: string;
}

export interface SavedAnalysisRun {
  request_id: string;
  definition_id: string;
  definition_version: number;
  status: "RECEIVED" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "BLOCKED" | "CANCELLED";
  as_of: string;
  timezone: string;
  trace_id: string;
  query_id: string | null;
  artifact_id: string | null;
  error_type: string | null;
  started_at: string;
  completed_at: string | null;
  question: string;
  period_start: string | null;
  period_end_exclusive: string | null;
}

export interface AnalysisProgress {
  trace_id: string;
  request_id: string;
  status: "RECEIVED" | "ROUTED" | "SUCCEEDED" | "BLOCKED" | "PARTIAL" | "FAILED" | "CANCELLED";
  started_at: string;
  elapsed_seconds: number;
  cancel_requested: boolean;
  trace: Array<{ stage: string; outcome: string; detail?: string | null }>;
}

export interface AnalysisOptions {
  traceId?: string;
  onProgress?: (progress: AnalysisProgress) => void;
}

interface SavedAnalysisArtifact {
  request_id: string;
  trace_id: string;
  status: "SUCCEEDED" | "PARTIAL";
  question: string;
  summary: string;
  metrics: NonNullable<NonNullable<AnalysisApiResponse["data"]["result"]>["metrics"]>;
  table: { columns: string[]; rows: Array<Record<string, AnalysisValue>> };
  chart: { chart_type: string; x_field: string; y_fields: string[] } | null;
  evidence: NonNullable<NonNullable<AnalysisApiResponse["data"]["result"]>["evidence"]>;
  artifact_id: string;
  query_id: string;
  artifact_checksum: string;
}

type Fetch = typeof fetch;
const env = import.meta.env ?? {};

export class AnalysisApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly requiredAction: string;
  readonly suggestions: string[];
  readonly missingRequirements: string[];
  readonly traceId: string;

  constructor(status: number, code: string, message: string, options: {
    retryable?: boolean;
    requiredAction?: string;
    suggestions?: string[];
    missingRequirements?: string[];
    traceId?: string;
  } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryable = options.retryable ?? false;
    this.requiredAction = options.requiredAction ?? "NONE";
    this.suggestions = options.suggestions ?? [];
    this.missingRequirements = options.missingRequirements ?? [];
    this.traceId = options.traceId ?? "";
  }
}

function seoulToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function authenticationHeaders(explicitToken = "") {
  return explicitToken ? { Authorization: `Bearer ${explicitToken}` } : {};
}

export function createHttpAnalysisClient(
  baseUrl = env.VITE_BACKEND_BASE_URL,
  request: Fetch = fetch,
  authToken = "",
): AnalysisClient {
  if (!baseUrl) throw new Error("VITE_BACKEND_BASE_URL is required");
  const endpoint = (path: string) => `${baseUrl.replace(/\/$/, "")}${path}`;
  const headers = (json = false, traceId = createUuid()) => ({
    ...(json ? { "Content-Type": "application/json" } : {}),
    ...authenticationHeaders(authToken),
    "X-As-Of": env.VITE_ANALYSIS_AS_OF || seoulToday(),
    "X-Contract-Version": OPENAPI_VERSION,
    "X-Timezone": "Asia/Seoul",
    "X-Trace-Id": traceId,
  });
  const parse = async <T>(response: Response): Promise<T> => {
    const payload: any = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new AnalysisApiError(
        response.status,
        payload?.error?.code || `HTTP_${response.status}`,
        payload?.error?.message || "분석 API 요청에 실패했습니다.",
        {
          retryable: Boolean(payload?.error?.retryable),
          requiredAction: payload?.error?.required_action,
          suggestions: payload?.error?.suggestions,
          missingRequirements: payload?.error?.missing_requirements,
          traceId: payload?.error?.trace_id,
        },
      );
      if (response.status === 401 && typeof window !== "undefined") window.dispatchEvent(new CustomEvent("answervice:session-expired"));
      throw error;
    }
    return payload as T;
  };
  return {
    async login(username, password) {
      const payload = await parse<{ data: LoginSession }>(await request(endpoint("/auth/login"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      }));
      if (payload?.data?.status !== "authenticated") {
        throw new Error("로그인 API가 올바르지 않은 응답을 반환했습니다.");
      }
      return payload.data;
    },
    async validateSession() {
      const payload = await parse<{ data: SessionInfo }>(await request(endpoint("/auth/session"), {
        credentials: "include",
        headers: authenticationHeaders(authToken),
      }));
      if (payload?.data?.status !== "authenticated") throw new Error("인증 API가 올바르지 않은 응답을 반환했습니다.");
      return payload.data;
    },
    async logout() {
      const response = await request(endpoint("/auth/logout"), {
        method: "POST",
        credentials: "include",
        headers: authenticationHeaders(authToken),
      });
      if (!response.ok) await parse(response);
    },
    async analyze(question, parameters = {}, options = {}) {
      const traceId = options.traceId || createUuid();
      const responsePromise = request(endpoint("/analysis"), {
        method: "POST",
        credentials: "include",
        headers: headers(true, traceId),
        body: JSON.stringify({ question, parameters }),
      });
      const poll = options.onProgress ? window.setInterval(async () => {
        try {
          const response = await request(endpoint(`/analysis/progress/${encodeURIComponent(traceId)}`), {
            credentials: "include",
            headers: headers(false, traceId),
          });
          if (response.status === 404) return;
          const payload = await parse<{ data: AnalysisProgress }>(response);
          options.onProgress?.(payload.data);
        } catch {
          // The final analysis response owns user-facing errors; polling is best-effort only.
        }
      }, 500) : undefined;
      try {
        const payload = await parse<AnalysisApiResponse>(await responsePromise);
        if (!payload?.data || !payload.meta) throw new Error("Analysis API returned an invalid response");
        return normalizeApiResponse(payload, question);
      } finally {
        if (poll !== undefined) window.clearInterval(poll);
      }
    },
    async cancelAnalysis(traceId) {
      const payload = await parse<{ data: AnalysisProgress }>(await request(
        endpoint(`/analysis/progress/${encodeURIComponent(traceId)}/cancel`),
        { method: "POST", credentials: "include", headers: headers(false, traceId) },
      ));
      return payload.data;
    },
    async createDefinition(title, sourceRequestId) {
      return parse<SavedAnalysisDefinition>(await request(endpoint("/analysis/definitions"), {
        method: "POST", credentials: "include", headers: headers(true), body: JSON.stringify({ title, source_request_id: sourceRequestId }),
      }));
    },
    async listDefinitions() {
      return (await parse<{ items: SavedAnalysisDefinition[] }>(
        await request(endpoint("/analysis/definitions"), { credentials: "include", headers: headers() }),
      )).items;
    },
    async replayDefinition(definitionId, parameters) {
      return parse<SavedAnalysisRun>(await request(endpoint(`/analysis/definitions/${encodeURIComponent(definitionId)}/runs`), {
        method: "POST",
        credentials: "include",
        headers: headers(true),
        body: JSON.stringify({ as_of: env.VITE_ANALYSIS_AS_OF || seoulToday(), idempotency_key: createUuid(), parameters }),
      }));
    },
    async getRunArtifact(requestId) {
      const detail = await parse<SavedAnalysisArtifact>(await request(
        endpoint(`/analysis/runs/${encodeURIComponent(requestId)}/artifact`),
        { credentials: "include", headers: headers() },
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
            metrics: detail.metrics ?? [],
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
      }, detail.question);
    },
    async listRuns() {
      return (await parse<{ items: SavedAnalysisRun[] }>(
        await request(endpoint("/analysis/runs"), { credentials: "include", headers: headers() }),
      )).items;
    },
  };
}

export function createAnalysisClient(request: Fetch = fetch, authToken = ""): AnalysisClient {
  return createHttpAnalysisClient(undefined, request, authToken);
}
