/** Report Assistant 메시지 범위를 서버 요청 사이에서만 보조적으로 유지하는 UI 상태다. */
export const INITIAL_REPORT_ASSISTANT_SCOPE_STATE = Object.freeze({
  operationScope: "full_report",
  sessionId: "",
});

/** 검증된 서버 대화를 Panel의 로컬 표시 모델로 변환한다. */
export function reportAssistantMessagesFromTurnHistory(turnHistory) {
  return turnHistory.map((turn) => ({ role: turn.role, text: turn.content }));
}

/** 같은 세션에서 이미 표시한 로컬 메시지는 유지하고 빈 transcript만 서버 이력으로 복구한다. */
export function hydrateReportAssistantMessages(current, turnHistory) {
  return current.length ? current : reportAssistantMessagesFromTurnHistory(turnHistory);
}

/** 서버 phase·세션 변경과 메시지 결과에 따라 다음 메시지 범위를 보수적으로 계산한다. */
export function reduceReportAssistantScope(state, event) {
  if (event.type === "title-request") {
    return { ...state, operationScope: "report_title" };
  }
  if (event.type === "message-result") {
    if (event.status == null) return state;
    return {
      ...state,
      operationScope: event.operationScope === "report_title"
        && event.status === "clarification_required"
        ? "report_title"
        : "full_report",
    };
  }
  if (event.type === "session") {
    const sessionId = event.sessionId || "";
    const terminal = ["completed", "failed", "cancelled"].includes(event.status);
    const serverScope = ["full_report", "report_title"].includes(event.operationScope)
      ? event.operationScope
      : "full_report";
    return {
      sessionId,
      operationScope: terminal ? "full_report" : serverScope,
    };
  }
  return state;
}
