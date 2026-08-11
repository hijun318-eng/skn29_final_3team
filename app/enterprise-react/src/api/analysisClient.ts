import { analysisFixtures, type FixtureKey } from "../data/analysisFixtures.ts";
import {
  normalizeApiResponse,
  OPENAPI_VERSION,
  type AnalysisApiResponse,
  type AnalysisRun,
} from "../contracts/analysis.ts";
import { createUuid } from "../utils/createUuid.ts";

export interface AnalysisClient {
  analyze(question: string, conversationId: string, fixtureKey: FixtureKey): Promise<AnalysisRun>;
}

type Fetch = typeof fetch;

const env = import.meta.env ?? {};
export const usesMockAnalysisClient = env.VITE_ANALYSIS_MODE === "mock";
export const showsAnalysisScenarios = usesMockAnalysisClient || env.VITE_ANALYSIS_DEMO === "true";

function requestOptions(fixtureKey: FixtureKey) {
  const templateRequest = {
    template_id: "weekly-room-operations",
    parameters: {
      period_start: env.VITE_ANALYSIS_PERIOD_START || "2026-05-01",
      period_end_exclusive: env.VITE_ANALYSIS_PERIOD_END_EXCLUSIVE || "2026-07-01",
    },
  };
  if (!showsAnalysisScenarios || fixtureKey === "ready") return { body: templateRequest, role: "hotel_analyst" };
  if (fixtureKey === "clarification") return { body: { parameters: { scenario: "clarification" } }, role: "hotel_analyst" };
  if (fixtureKey === "forbidden") return { body: templateRequest, role: "report_admin" };
  if (fixtureKey === "error") return { body: { parameters: { scenario: "query_failed" } }, role: "hotel_analyst" };
  if (fixtureKey === "partial") return { body: { parameters: { scenario: "query_partial" } }, role: "hotel_analyst" };
  return { body: templateRequest, role: "hotel_analyst" };
}

export function createHttpAnalysisClient(
  baseUrl = env.VITE_BACKEND_BASE_URL || "http://127.0.0.1:18000",
  request: Fetch = fetch,
): AnalysisClient {
  return {
    async analyze(question, conversationId, fixtureKey) {
      const { body, role } = requestOptions(fixtureKey);
      const traceId = createUuid();
      const response = await request(`${baseUrl.replace(/\/$/, "")}/analysis`, {
        method: "POST",
        headers: {
          Authorization: "Bearer synthetic-local",
          "Content-Type": "application/json",
          "X-As-Of": env.VITE_ANALYSIS_AS_OF || "2026-07-30",
          "X-Contract-Version": OPENAPI_VERSION,
          "X-Role": role,
          "X-Timezone": "Asia/Seoul",
          "X-Trace-Id": traceId,
          "X-User-Id": "00000000-0000-0000-0000-000000000001",
        },
        body: JSON.stringify({ question, ...body }),
      });
      const payload = await response.json() as AnalysisApiResponse;
      return normalizeApiResponse(payload, question, conversationId);
    },
  };
}

export function createMockAnalysisClient(): AnalysisClient {
  return {
    async analyze(question, conversationId, fixtureKey) {
      await new Promise((resolve) => window.setTimeout(resolve, 2200));
      const selected = structuredClone(analysisFixtures[fixtureKey]);
      return {
        ...selected,
        question,
        conversationId,
      };
    },
  };
}

export function createAnalysisClient(): AnalysisClient {
  return usesMockAnalysisClient ? createMockAnalysisClient() : createHttpAnalysisClient();
}
