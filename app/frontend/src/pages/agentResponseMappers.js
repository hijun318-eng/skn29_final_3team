/** RAG 서버 응답을 공통 Agent 실행 화면 계약으로 변환한다. */
import { OPENAPI_VERSION } from "../contracts/analysis.ts";


/** ML 예측 응답을 기존 대화 실행 계약으로 변환한다. */
export function mlRun(question, result) {
  const forecasts = Array.isArray(result?.daily_forecasts) ? result.daily_forecasts : [];
  const summary = result?.status === "NEEDS_CLARIFICATION"
    ? result.answer_text
    : `${result?.property_id || "선택한"} 호텔의 ${forecasts.length}일 객실 수요 예측입니다.`;
  return {
    requestId: result?.execution_id || "",
    traceId: "",
    status: result?.status === "NEEDS_CLARIFICATION" ? "blocked" : "success",
    question,
    summary,
    metrics: [],
    sources: [],
    meta: {
      asOf: result?.as_of || "",
      timezone: "Asia/Seoul",
      seed: "",
      schemaVersion: result?.model_version || "",
      contractVersion: OPENAPI_VERSION,
    },
    ml: result,
  };
}


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
