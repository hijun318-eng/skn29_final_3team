import {
  normalizeApiResponse,
  OPENAPI_VERSION,
  type AnalysisApiResponse,
  type AccessProfile,
  type AnalysisRun,
} from "../contracts/analysis.ts";
import { createUuid } from "../utils/createUuid.ts";
import { getAuthorizationHeader } from "./authSession.ts";

export interface AnalysisClient {
  analyze(question: string, conversationId: string, accessProfile?: AccessProfile, onProgress?: (run: AnalysisRun) => void): Promise<AnalysisRun>;
  listRecent(limit?: number): Promise<RecentAnalysisItem[]>;
  getProgress(requestId: string, accessProfile: AccessProfile): Promise<AnalysisProgressResponse>;
  getResult(requestId: string, question: string, conversationId: string, accessProfile: AccessProfile): Promise<AnalysisRun>;
}

export interface RecentAnalysisItem {
  request_id: string;
  trace_id: string;
  question_text_redacted: string;
  status: "RECEIVED" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "DENIED";
  started_at: string;
  as_of: string;
  access_profile: AccessProfile;
}

export interface AnalysisProgressResponse {
  request_id: string;
  status: "RECEIVED" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "DENIED";
  events: Array<{ sequence: number; stage: string; outcome: string; created_at: string }>;
}

type Fetch = typeof fetch;

export class AnalysisRequestError extends Error {
  readonly code: string;
  readonly retryable: boolean;

  constructor(
    code: string,
    message: string,
    retryable: boolean,
  ) {
    super(message);
    this.name = "AnalysisRequestError";
    this.code = code;
    this.retryable = retryable;
  }
}

const env = import.meta.env ?? {};

export function createHttpAnalysisClient(
  baseUrl = env.VITE_BACKEND_BASE_URL || "http://127.0.0.1:18000",
  request: Fetch = fetch,
): AnalysisClient {
  return {
    async listRecent(limit = 20) {
      const root = baseUrl.replace(/\/$/, "");
      const response = await request(`${root}/analysis/recent?limit=${limit}`, {
        headers: {
          Authorization: getAuthorizationHeader(),
          "X-As-Of": env.VITE_ANALYSIS_AS_OF || new Date().toISOString().slice(0, 10),
          "X-Access-Profile": "pms_only",
          "X-Contract-Version": OPENAPI_VERSION,
          "X-Timezone": "Asia/Seoul",
          "X-Trace-Id": createUuid(),
        },
      });
      if (!response.ok) throw new Error(`최근 분석 API가 HTTP ${response.status}로 거부되었습니다.`);
      const payload = await response.json() as { items: RecentAnalysisItem[] };
      return payload.items;
    },
    async getProgress(requestId, accessProfile) {
      const root = baseUrl.replace(/\/$/, "");
      const response = await request(`${root}/analysis/${requestId}/progress`, {
        headers: {
          Authorization: getAuthorizationHeader(),
          "X-As-Of": env.VITE_ANALYSIS_AS_OF || new Date().toISOString().slice(0, 10),
          "X-Access-Profile": accessProfile,
          "X-Contract-Version": OPENAPI_VERSION,
          "X-Timezone": "Asia/Seoul",
          "X-Trace-Id": createUuid(),
        },
      });
      if (!response.ok) throw new Error(`분석 진행 API가 HTTP ${response.status}로 거부되었습니다.`);
      return response.json() as Promise<AnalysisProgressResponse>;
    },
    async getResult(requestId, question, conversationId, accessProfile) {
      const root = baseUrl.replace(/\/$/, "");
      const response = await request(`${root}/analysis/${requestId}/result`, {
        headers: {
          Authorization: getAuthorizationHeader(),
          "X-As-Of": env.VITE_ANALYSIS_AS_OF || new Date().toISOString().slice(0, 10),
          "X-Access-Profile": accessProfile,
          "X-Contract-Version": OPENAPI_VERSION,
          "X-Timezone": "Asia/Seoul",
          "X-Trace-Id": createUuid(),
        },
      });
      const payload = await response.json().catch(() => ({})) as AnalysisApiResponse & { detail?: string };
      if (!response.ok) {
        throw new AnalysisRequestError(
          response.status === 403 ? "ACCESS_DENIED" : "INTERNAL_ERROR",
          payload.detail || "저장된 Analysis 결과를 복원하지 못했습니다.",
          response.status >= 500,
        );
      }
      return normalizeApiResponse(payload, question, conversationId);
    },
    async analyze(question, conversationId, accessProfile = "pms_only", onProgress) {
      const traceId = createUuid();
      const requestId = createUuid();
      const root = baseUrl.replace(/\/$/, "");
      const headers = {
        Authorization: getAuthorizationHeader(),
        "X-As-Of": env.VITE_ANALYSIS_AS_OF || new Date().toISOString().slice(0, 10),
        "X-Access-Profile": accessProfile,
        "X-Contract-Version": OPENAPI_VERSION,
        "X-Timezone": "Asia/Seoul",
        "X-Trace-Id": traceId,
      };
      let settled = false;
      let latestProgress: Array<{ sequence: number; stage: string; outcome: string; createdAt: string }> = [];
      const responsePromise = request(`${root}/analysis`, {
        method: "POST",
        signal: AbortSignal.timeout(300_000),
        headers: {
          ...headers,
          "Content-Type": "application/json",
          "X-Request-Id": requestId,
        },
        body: JSON.stringify({ question }),
      });
      const fetchProgress = async () => {
          try {
            const progressResponse = await request(`${root}/analysis/${requestId}/progress`, { method: "GET", headers });
            if (progressResponse.ok) {
              const progress = await progressResponse.json() as AnalysisProgressResponse;
              latestProgress = progress.events.map(({ sequence, stage, outcome, created_at }) => ({ sequence, stage, outcome, createdAt: created_at }));
              onProgress?.({
                conversationId,
                requestId,
                traceId,
                status: "running",
                question,
                metrics: [],
                sources: [],
                progress: latestProgress,
                meta: { asOf: headers["X-As-Of"], timezone: "Asia/Seoul", synthetic: true, seed: "", schemaVersion: "", contractVersion: OPENAPI_VERSION },
              });
            }
          } catch {
            // 최종 POST 응답이 오류를 정규화하므로 progress 실패를 성공으로 대체하지 않는다.
          }
      };
      const poll = async () => {
        while (!settled) {
          await fetchProgress();
          if (!settled) await new Promise((resolve) => setTimeout(resolve, 500));
        }
      };
      const progressPromise = onProgress ? poll() : Promise.resolve();
      let response: Response;
      try {
        response = await responsePromise;
      } finally {
        settled = true;
        await progressPromise;
        if (onProgress) await fetchProgress();
      }
      const payload = await response.json() as AnalysisApiResponse;
      if (!response.ok) {
        throw new AnalysisRequestError(
          payload.error?.code || "INTERNAL_ERROR",
          payload.error?.message || `분석 API 요청이 HTTP ${response.status}로 거부되었습니다.`,
          payload.error?.retryable ?? response.status >= 500,
        );
      }
      if (!payload?.data || !payload.meta) throw new Error("Analysis API returned an invalid response");
      return { ...normalizeApiResponse(payload, question, conversationId), progress: latestProgress };
    },
  };
}

export function createAnalysisClient(request: Fetch = fetch): AnalysisClient {
  return createHttpAnalysisClient(undefined, request);
}
