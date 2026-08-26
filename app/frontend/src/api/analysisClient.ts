/** 분석·인증·저장 실행 HTTP 포트를 구현하고 모든 wire 응답을 계약 모델로 정규화하는 모듈이다. */
import {
  normalizeApiResponse,
  OPENAPI_VERSION,
  type AnalysisApiResponse,
  type AnalysisRun,
  type AnalysisValue,
  type ConversationCommandProgress,
} from "../contracts/analysis.ts";
import { createUuid } from "../utils/createUuid.ts";
import { CAPABILITY, type ServiceCapability, type ServiceRole } from "../authorization.ts";

/** conversation command API가 받는 구조화된 사용자 명령 계약이다. */
export interface ConversationCommandPayload {
  user_message: string;
  expected_head_turn_id?: string | null;
  idempotency_key?: string;
  requested_route?: "ANALYSIS" | "PRESENTATION" | "REPORT_ACTION";
  presentation_type?: "SUMMARY" | "KPI" | "TABLE" | "BAR" | "LINE" | "PIE" | "HORIZONTAL_BAR" | "DONUT" | "FULL";
}

/** command 요청의 추적·취소와 향후 typed progress 전달 지점을 제공하는 선택 옵션이다. */
export interface SubmitTurnCommandOptions {
  traceId?: string;
  signal?: AbortSignal;
  onProgress?: (progress: ConversationCommandProgress) => void;
}

/** 인증·분석·저장 실행 API가 제공해야 하는 비동기 포트다. 모든 실패는 reject되어 호출자가 상태를 결정한다. */
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
  createConversation(): Promise<{ conversation_id: string; created_at: string }>;
  getConversationTurns(conversationId: string): Promise<ConversationTurnWire[]>;
  executeTurnCommand(
    conversationId: string,
    payload: ConversationCommandPayload,
    options?: SubmitTurnCommandOptions,
  ): Promise<any>;
  submitTurnCommand(
    conversationId: string,
    payload: ConversationCommandPayload,
    options?: SubmitTurnCommandOptions,
  ): Promise<any>;
}

/**
 * 서버 데이터베이스에서 수화된 대화 턴의 불변 유선 계약이다.
 */
export interface ConversationTurnWire {
  turn_id: string;
  conversation_id: string;
  turn_index: number;
  user_message: string;
  route: "ANALYSIS" | "PRESENTATION" | "REPORT_ACTION";
  source_turn_ids: string[];
  request_id: string | null;
  artifact_id: string | null;
  view_spec_id: string | null;
  report_definition_id: string | null;
  resolved_slots: {
    metric_id?: string | null;
    dimension_fields?: Array<{ column: string; asset_fqn: string }> | null;
    time_range?: {
      start: string;
      end_exclusive: string;
      source_text: string;
    } | null;
    target_chart_type?: string | null;
    is_inherited_metric?: boolean;
    is_inherited_dimension?: boolean;
    is_inherited_period?: boolean;
  };
  created_at: string;
  artifact_summary?: string | null;
  view_type?: string | null;
  spec_json?: Record<string, unknown> | null;
  command_status?: "COMPLETED" | "FAILED" | null;
  command_error?: {
    code?: string;
    message?: string;
    retryable?: boolean;
    required_action?: string;
  } | null;
}

/**
 * 멀티턴 명령 실행 후 서버가 반환하는 결과 계약이다.
 */
export interface ConversationTurnResult {
  status: string;
  turn: ConversationTurnWire;
  conversation: {
    conversation_id: string;
    head_turn_id: string;
    turn_count: number;
  };
}

/** 서버가 검증한 현재 세션의 최소 공개 정보다. */
export interface SessionInfo {
  status: "authenticated";
  role: ServiceRole;
  capabilities: ServiceCapability[];
}

/** 로그인 성공 응답은 검증된 세션 계약과 동일하다. */
export type LoginSession = SessionInfo;

const SESSION_ROLES = new Set<ServiceRole>([
  "analyst",
  "admin",
]);
const SESSION_CAPABILITIES = new Set<ServiceCapability>(Object.values(CAPABILITY));

/** 인증 응답이 지원 Role과 중복 없는 Capability만 포함하는지 런타임에서 검증한다. */
function isSessionInfo(value: unknown): value is SessionInfo {
  if (!value || typeof value !== "object") return false;
  const session = value as Partial<SessionInfo>;
  return session.status === "authenticated"
    && typeof session.role === "string"
    && SESSION_ROLES.has(session.role as ServiceRole)
    && Array.isArray(session.capabilities)
    && session.capabilities.length === new Set(session.capabilities).size
    && session.capabilities.every((item) => SESSION_CAPABILITIES.has(item));
}

/** 재실행 가능한 서버 저장 분석 정의의 wire 계약이다. */
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

/** 저장 분석 실행의 식별자·기간·완료 상태 계약이다. */
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

/** trace 기반 진행 조회가 반환하는 서버 관측 상태다. */
export interface AnalysisProgress {
  trace_id: string;
  request_id: string;
  status: "RECEIVED" | "ROUTED" | "SUCCEEDED" | "BLOCKED" | "PARTIAL" | "FAILED" | "CANCELLED";
  started_at: string;
  elapsed_seconds: number;
  cancel_requested: boolean;
  trace: Array<{ stage: string; outcome: string; detail?: string | null }>;
}

/** 분석 호출의 trace 및 진행 콜백 입력이며 콜백 부재 시 polling을 만들지 않는다. */
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

/** HTTP 오류의 재시도·필요 조치·trace 정보를 보존하는 공개 오류 타입이다. */
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

function authenticationHeaders(explicitToken = "") {
  return explicitToken ? { Authorization: `Bearer ${explicitToken}` } : {};
}

/** 명시된 backend origin에만 cookie 인증 요청을 보내며 origin 누락 시 즉시 실패하는 분석 클라이언트다. */
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
    "X-Contract-Version": OPENAPI_VERSION,
    "X-Timezone": "Asia/Seoul",
    "X-Trace-Id": traceId,
  });
  const parse = async <T>(response: Response): Promise<T> => {
    // 오류 body 파싱 실패 시 빈 오류 메타데이터로만 닫고, 성공 payload는 후속 계약 정규화가 검증한다.
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
      if (!isSessionInfo(payload?.data)) {
        throw new Error("로그인 API가 올바르지 않은 응답을 반환했습니다.");
      }
      return payload.data;
    },
    async validateSession() {
      const payload = await parse<{ data: SessionInfo }>(await request(endpoint("/auth/session"), {
        credentials: "include",
        headers: authenticationHeaders(authToken),
      }));
      if (!isSessionInfo(payload?.data)) throw new Error("인증 API가 올바르지 않은 응답을 반환했습니다.");
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
          // 진행 polling 실패는 최종 분석 응답의 성공·오류 계약을 덮지 않도록 사용자 상태에 반영하지 않는다.
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
        body: JSON.stringify({ idempotency_key: createUuid(), parameters }),
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
    async createConversation() {
      const payload = await parse<{ status: string; data: { conversation_id: string; created_at: string } }>(
        await request(endpoint("/conversations"), {
          method: "POST",
          credentials: "include",
          headers: headers(true),
          body: JSON.stringify({}),
        }),
      );
      return payload.data;
    },
    async getConversationTurns(conversationId) {
      const payload = await parse<{ status: string; data: { conversation_id: string; turns: ConversationTurnWire[] } }>(
        await request(endpoint(`/conversations/${encodeURIComponent(conversationId)}/turns`), {
          credentials: "include",
          headers: headers(),
        }),
      );
      return payload.data?.turns || [];
    },
    async executeTurnCommand(conversationId, cmdPayload, options = {}) {
      return parse<any>(
        await request(endpoint(`/conversations/${encodeURIComponent(conversationId)}/commands`), {
          method: "POST",
          credentials: "include",
          headers: headers(true, options.traceId || createUuid()),
          body: JSON.stringify(cmdPayload),
          signal: options.signal,
        }),
      );
    },
    async submitTurnCommand(conversationId, cmdPayload, options = {}) {
      // 백엔드 command progress transport가 확정되기 전에는 onProgress를 호출하거나 polling하지 않는다.
      return this.executeTurnCommand(conversationId, cmdPayload, options);
    },
  };
}

/** 환경의 backend origin으로 분석 포트를 구성한다. request/token 인자는 테스트·호스트 어댑터 경계에만 사용한다. */
export function createAnalysisClient(request: Fetch = fetch, authToken = ""): AnalysisClient {
  return createHttpAnalysisClient(undefined, request, authToken);
}
