/** RAG 서버 응답을 공통 Agent 실행 화면 계약으로 변환한다. */
import { OPENAPI_VERSION } from "../contracts/analysis.ts";


/** 내부 문서 답변과 인용 근거를 Agent의 성공 실행 상태로 변환한다. */
export function ragRun(question, result) {
  const answerText = result?.answer?.text || result?.document?.body || "";
  const summary = result?.status === "NO_EVIDENCE"
    ? "관련 내부지침 근거를 찾지 못했습니다."
    : answerText;
  return {
    requestId: result?.request_id || "",
    traceId: result?.trace_id || "",
    status: "success",
    question,
    summary,
    metrics: [],
    sources: [],
    meta: {
      asOf: "",
      timezone: "Asia/Seoul",
      seed: "",
      schemaVersion: "",
      contractVersion: OPENAPI_VERSION,
    },
    rag: {
      ...(result?.document || {}),
      status: result?.status,
      answer_type: result?.answer_type,
      response_status: result?.response_status || "ANSWERED",
      answer_id: result?.answer_id || result?.request_id || "",
      answer_text: answerText,
      processing_steps: result?.processing_steps || [],
      evidence_bundle: result?.evidence_bundle || [],
      citations: result?.citations || [],
      conflicts: result?.conflicts || [],
      clarification_options: result?.clarification_options || [],
    },
  };
}


/** MCP ML 예측 결과를 대화 화면의 성공 실행 상태로 변환한다. */
export function mlPredictionRun(question, result) {
  const forecasts = Array.isArray(result?.daily_forecasts)
    ? result.daily_forecasts
    : [];
  const propertyId = typeof result?.property_id === "string"
    ? result.property_id.trim()
    : "";
  const dayCount = forecasts.length;
  return {
    requestId: result?.execution_id || "",
    traceId: result?.mcp_tool_run_id || "",
    status: "success",
    question,
    summary: `${propertyId ? `${propertyId} ` : ""}객실 수요 ${dayCount}일 예측을 완료했습니다.`,
    metrics: [],
    sources: [],
    meta: {
      asOf: result?.as_of || "",
      timezone: "Asia/Seoul",
      seed: "",
      schemaVersion: result?.schema_version || "",
      contractVersion: OPENAPI_VERSION,
    },
    mlPrediction: result,
  };
}


/** 대표 run에 복합 실행으로 함께 반환된 RAG·ML 결과를 손실 없이 결합한다. */
export function attachAgentResults(baseRun, question, { ragResult, mlPrediction } = {}) {
  if (!baseRun) return null;
  return {
    ...baseRun,
    ...(ragResult ? { rag: ragRun(question, ragResult).rag } : {}),
    ...(mlPrediction ? { mlPrediction } : {}),
  };
}
