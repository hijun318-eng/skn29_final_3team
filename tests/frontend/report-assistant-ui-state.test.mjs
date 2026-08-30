import assert from "node:assert/strict";
import test from "node:test";

import {
  INITIAL_REPORT_ASSISTANT_SCOPE_STATE,
  hydrateReportAssistantMessages,
  reduceReportAssistantScope,
  reportAssistantMessagesFromTurnHistory,
} from "../../app/frontend/src/features/reports/reportAssistantUiState.js";

test("서버 대화 이력을 Panel 메시지로 순서대로 복구한다", () => {
  const messages = reportAssistantMessagesFromTurnHistory([
    { role: "user", content: "보고서 제목을 제안해 주세요." },
    { role: "assistant", content: "어느 기간을 강조할까요?" },
  ]);
  assert.deepEqual(messages, [
    { role: "user", text: "보고서 제목을 제안해 주세요." },
    { role: "assistant", text: "어느 기간을 강조할까요?" },
  ]);

  const local = [{ role: "user", text: "방금 입력한 로컬 메시지" }];
  assert.equal(
    hydrateReportAssistantMessages(local, [{ role: "assistant", content: "서버 응답" }]),
    local,
    "같은 세션에서 표시한 로컬 transcript를 서버 prop 갱신으로 초기화하면 안 된다",
  );
  assert.deepEqual(
    hydrateReportAssistantMessages([], [{ role: "assistant", content: "복구된 응답" }]),
    [{ role: "assistant", text: "복구된 응답" }],
  );
});

test("제목 명확화 대화는 제목 범위를 유지하고 변경안 생성 뒤 해제한다", () => {
  let state = reduceReportAssistantScope(INITIAL_REPORT_ASSISTANT_SCOPE_STATE, {
    type: "title-request",
  });
  assert.equal(state.operationScope, "report_title");

  state = reduceReportAssistantScope(state, {
    type: "session",
    sessionId: "session-1",
    status: "ready",
    operationScope: "report_title",
  });
  assert.equal(state.operationScope, "report_title", "첫 서버 세션 연결은 제목 요청 범위를 보존해야 한다");

  state = reduceReportAssistantScope(state, {
    type: "message-result",
    operationScope: "report_title",
    status: "clarification_required",
  });
  assert.equal(state.operationScope, "report_title");

  state = reduceReportAssistantScope(state, {
    type: "message-result",
    operationScope: state.operationScope,
    status: "patch_approval_required",
  });
  assert.equal(state.operationScope, "full_report");
});

test("새 세션과 terminal 상태는 보조 제목 범위를 해제한다", () => {
  const titleState = reduceReportAssistantScope({
    operationScope: "report_title",
    sessionId: "session-1",
  }, {
    type: "session",
    sessionId: "session-2",
    status: "ready",
    operationScope: "full_report",
  });
  assert.deepEqual(titleState, {
    operationScope: "full_report",
    sessionId: "session-2",
  });

  const cancelled = reduceReportAssistantScope({
    operationScope: "report_title",
    sessionId: "session-2",
  }, {
    type: "session",
    sessionId: "session-2",
    status: "cancelled",
    operationScope: "report_title",
  });
  assert.equal(cancelled.operationScope, "full_report");
});

test("일반 보고서 명확화는 제목 범위로 승격하지 않는다", () => {
  const state = reduceReportAssistantScope(INITIAL_REPORT_ASSISTANT_SCOPE_STATE, {
    type: "message-result",
    operationScope: "full_report",
    status: "clarification_required",
  });
  assert.equal(state.operationScope, "full_report");
});

test("네트워크 결과가 없으면 현재 제목 범위를 보존한다", () => {
  const titleState = { operationScope: "report_title", sessionId: "session-1" };
  assert.equal(reduceReportAssistantScope(titleState, {
    type: "message-result",
    operationScope: "report_title",
    status: undefined,
  }), titleState);
  assert.equal(reduceReportAssistantScope(titleState, {
    type: "message-result",
    operationScope: "report_title",
    status: null,
  }), titleState);
});

test("복구한 세션의 서버 범위를 로컬 추정보다 우선한다", () => {
  const restored = reduceReportAssistantScope(INITIAL_REPORT_ASSISTANT_SCOPE_STATE, {
    type: "session",
    sessionId: "restored-session",
    status: "ready",
    operationScope: "report_title",
  });
  assert.equal(restored.operationScope, "report_title");

  const invalid = reduceReportAssistantScope(restored, {
    type: "session",
    sessionId: "restored-session",
    status: "ready",
    operationScope: "unknown_scope",
  });
  assert.equal(invalid.operationScope, "full_report");
});
