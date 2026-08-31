import assert from "node:assert/strict";
import test from "node:test";

import {
  reportAssistantSessionMatchesDefinition,
  reportAssistantSessionStorageKey,
} from "../../app/frontend/src/features/reports/reportAssistantSessionRecovery.ts";

const definition = { definitionId: "report/alpha", version: 7 };
const session = {
  assistant_request_id: "assistant-1",
  definition_id: "report/alpha",
  definition_version: 7,
  phase: "ready",
  result_revision: null,
};

test("복구 key는 보고서 draft identity만 사용한다", () => {
  assert.equal(
    reportAssistantSessionStorageKey(definition),
    "answervice.report-assistant:v2:report%2Falpha:7",
  );
  assert.equal(reportAssistantSessionStorageKey({ ...definition }), reportAssistantSessionStorageKey(definition));
  assert.equal(reportAssistantSessionStorageKey({ definitionId: "", version: 7 }), "");
  assert.equal(reportAssistantSessionStorageKey({ definitionId: "report/alpha", version: 0 }), "");
});

test("같은 보고서와 draft revision의 서버 세션만 복구한다", () => {
  assert.equal(reportAssistantSessionMatchesDefinition(session, definition), true);
  assert.equal(reportAssistantSessionMatchesDefinition(
    { ...session, definition_id: "report/beta" },
    definition,
  ), false);
  assert.equal(reportAssistantSessionMatchesDefinition(
    { ...session, definition_version: 6 },
    definition,
  ), false);
});

test("완료 세션이 만든 현재 revision은 안전하게 이어서 표시한다", () => {
  assert.equal(reportAssistantSessionMatchesDefinition({
    ...session,
    phase: "completed",
    definition_version: 6,
    result_revision: 7,
  }, definition), true);
  assert.equal(reportAssistantSessionMatchesDefinition({
    ...session,
    phase: "failed",
    definition_version: 6,
    result_revision: 7,
  }, definition), false);
});
