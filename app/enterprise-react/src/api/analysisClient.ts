import { analysisFixtures, type FixtureKey } from "../data/analysisFixtures";
import type { AnalysisRun } from "../contracts/analysis";

export interface AnalysisClient {
  analyze(question: string, conversationId: string, fixtureKey: FixtureKey): Promise<AnalysisRun>;
}

export function createMockAnalysisClient(): AnalysisClient {
  return {
    async analyze(question, conversationId, fixtureKey) {
      await new Promise((resolve) => window.setTimeout(resolve, 250));
      const selected = structuredClone(analysisFixtures[fixtureKey]);
      return {
        ...selected,
        question,
        conversationId,
        requestId: crypto.randomUUID(),
        traceId: crypto.randomUUID().replaceAll("-", ""),
      };
    },
  };
}
