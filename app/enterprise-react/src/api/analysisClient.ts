import {
  normalizeApiResponse,
  OPENAPI_VERSION,
  type AnalysisApiResponse,
  type AnalysisRun,
} from "../contracts/analysis.ts";
import { createUuid } from "../utils/createUuid.ts";

export interface AnalysisClient {
  analyze(question: string, conversationId: string): Promise<AnalysisRun>;
}

type Fetch = typeof fetch;

const env = import.meta.env ?? {};

export function createHttpAnalysisClient(
  baseUrl = env.VITE_BACKEND_BASE_URL || "http://127.0.0.1:18000",
  request: Fetch = fetch,
): AnalysisClient {
  return {
    async analyze(question, conversationId) {
      const traceId = createUuid();
      const response = await request(`${baseUrl.replace(/\/$/, "")}/analysis`, {
        method: "POST",
        headers: {
          Authorization: "Bearer runtime-test-token",
          "Content-Type": "application/json",
          "X-As-Of": env.VITE_ANALYSIS_AS_OF || new Date().toISOString().slice(0, 10),
          "X-Contract-Version": OPENAPI_VERSION,
          "X-Role": "hotel_analyst",
          "X-Timezone": "Asia/Seoul",
          "X-Trace-Id": traceId,
          "X-User-Id": "00000000-0000-0000-0000-000000000001",
        },
        body: JSON.stringify({ question }),
      });
      if (!response.ok) throw new Error(`Analysis API request failed (${response.status})`);
      const payload = await response.json() as AnalysisApiResponse;
      if (!payload?.data || !payload.meta) throw new Error("Analysis API returned an invalid response");
      return normalizeApiResponse(payload, question, conversationId);
    },
  };
}

export function createAnalysisClient(request: Fetch = fetch): AnalysisClient {
  return createHttpAnalysisClient(undefined, request);
}
