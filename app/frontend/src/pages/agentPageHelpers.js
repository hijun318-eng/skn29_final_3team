/** AgentPage의 run/turn 상태 변환을 담당하는 순수 헬퍼 모듈이다. React 상태를 갖지 않는다. */
import { AnalysisApiError } from "../api/analysisClient";
import { OPENAPI_VERSION } from "../contracts/analysis";

/**
 * 서버 응답 도착 전 화면에 표시할 임시 run 상태를 만든다.
 * @param {string} question - 사용자 질문 원문.
 * @param {string} [status="idle"] - 초기 표시 상태.
 * @returns {object} table/chart 등 결과 필드가 비어 있는 run 객체.
 */
export function transientRun(question, status = "idle") {
  return {
    requestId: "", traceId: "", status, question,
    metrics: [], sources: [],
    meta: { asOf: "", timezone: "Asia/Seoul", seed: "", schemaVersion: "", contractVersion: OPENAPI_VERSION },
  };
}

/**
 * 사용자가 선택한 disambiguation 옵션을 원 질문 뒤에 붙여 재질의용 질문 문장을 만든다.
 * @param {string} question - 원 질문.
 * @param {string} suggestion - 사용자가 선택한 값.
 * @param {"period"|string} clarificationType - "period"면 "기간", 그 외는 "지표"로 표기.
 * @returns {string} 선택 값이 덧붙은 질문 문장.
 */
export function clarifiedQuestion(question, suggestion, clarificationType) {
  const label = clarificationType === "period" ? "기간" : "지표";
  return `${question.trim()} (선택한 ${label}: ${suggestion})`;
}

/**
 * 서버 분석 상태 코드를 화면 표시용 한국어 라벨로 변환한다.
 * @param {string} status - 서버가 반환한 분석 상태 코드.
 * @returns {string} 매핑되는 한국어 라벨, 매핑 없으면 "확인 필요".
 */
export function savedRunStatus(status) {
  return ({ SUCCESS: "완료", SUCCEEDED: "완료", PARTIAL: "일부 완료", BLOCKED: "완료되지 않음", FAILED: "실패", RECEIVED: "처리 중", QUEUED: "대기 중", RUNNING: "처리 중", CANCELLED: "취소됨" })[status] || "확인 필요";
}

/**
 * 분석 요청 실패 원인을 사용자에게 보여줄 한국어 메시지로 변환한다.
 * @param {unknown} error - catch로 받은 에러 값.
 * @returns {string} 표시용 에러 메시지.
 */
export function analysisError(error) {
  if (error instanceof AnalysisApiError) return error.message;
  if (error instanceof TypeError) return "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.";
  return error instanceof Error ? error.message : "분석 요청이 실패했습니다.";
}

/**
 * ISO 시각 값을 Asia/Seoul 기준 "월 일 시:분" 형식으로 표시한다.
 * @param {string|null|undefined} value - ISO 8601 시각 문자열.
 * @returns {string} 서울 시간 표기 문자열, 값 없으면 "시각 정보 없음".
 */
export function formatSeoulDateTime(value) {
  if (!value) return "시각 정보 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

/**
 * 서버에서 조회한 turn 목록을 화면 상태(run/resolvedSlots/viewType)로 복원한다.
 * PRESENTATION은 직전 분석 run을 재사용해 재실행 없이 뷰만 전환하고,
 * REPORT_ACTION과 NEEDS_CLARIFICATION, 정상 결과, 무결과는 각각 별도 run 형태로 구성한다.
 * @param {Array<object>} serverTurns - 서버가 반환한 turn 레코드 배열.
 * @returns {Array<object>} 화면에서 바로 렌더링 가능한 turn 객체 배열, 변환 실패 시 빈 배열.
 */
export function hydrateTurnsFromServer(serverTurns) {
  try {
    let lastAnalysisRun = null;
    const hydrated = [];

    for (const st of serverTurns) {
      const isPresentation = st.route === "PRESENTATION";
      const isReportAction = st.route === "REPORT_ACTION";
      const userMessage = st.user_message || "";
      let run;

      if (isPresentation) {
        const tableData = st.data_snapshot_json || lastAnalysisRun?.table || null;
        const chartSpec = st.chart_spec_json || lastAnalysisRun?.chart || null;
        const evidence = st.evidence_json || lastAnalysisRun?.evidence || {};
        run = {
          ...(lastAnalysisRun || transientRun(userMessage, "success")),
          question: userMessage,
          status: "success",
          summary: `Trino 원천 쿼리 재실행 없이 ${st.view_type || "TABLE"} 뷰로 전환했습니다.`,
          table: tableData,
          chart: chartSpec,
          evidence: evidence,
          viewSpecId: st.view_spec_id,
        };
      } else if (isReportAction) {
        run = {
          ...(lastAnalysisRun || transientRun(userMessage, "success")),
          question: userMessage,
          status: "success",
          summary: `분석 대화 결과가 공식 보고서 초안(Draft)으로 결합되었습니다. (/reports에서 확인 가능)`,
          reportDefinitionId: st.report_definition_id,
        };
      } else if (st.resolved_slots?.ambiguity_status === "NEEDS_CLARIFICATION") {
        const options = st.resolved_slots?.disambiguation_options || [];
        const clarType = st.resolved_slots?.clarification_type || "metric";
        run = {
          ...transientRun(userMessage, "blocked"),
          disambiguationOptions: options,
          error: {
            code: "CONTEXT_INCOMPLETE",
            message: "질문이 여러 지표 또는 기간으로 해석될 수 있습니다. 분석할 기준을 선택해 주세요.",
            clarification_type: clarType,
            disambiguation_options: options,
            suggestions: options.map((o) => o.label || o.value || o.metric_id),
            retryable: false,
            required_action: "PROVIDE_CONTEXT",
          },
        };
      } else if (st.data_snapshot_json) {
        const tableData = st.data_snapshot_json;
        const chartSpec = st.chart_spec_json;
        const evidence = st.evidence_json || {};
        run = {
          ...transientRun(userMessage, "success"),
          requestId: st.request_id || "",
          traceId: evidence?.trace_id || "",
          status: "success",
          question: userMessage,
          summary: st.narrative_markdown || userMessage,
          table: tableData || null,
          chart: chartSpec || null,
          evidence: evidence || {},
          metrics: Array.isArray(evidence?.metrics) ? evidence.metrics : [],
          sources: Array.isArray(evidence?.sources) ? evidence.sources : [],
          artifact: st.artifact_id ? {
            artifactId: st.artifact_id,
            queryId: evidence?.query_id || "",
          } : undefined,
          rowCount: Array.isArray(tableData?.rows) ? tableData.rows.length : 0,
          meta: {
            asOf: evidence?.as_of || "",
            timezone: evidence?.timezone || "Asia/Seoul",
            seed: evidence?.seed || "",
            schemaVersion: evidence?.schema_version || "",
            contractVersion: OPENAPI_VERSION,
          },
        };
        lastAnalysisRun = run;
      } else {
        run = {
          ...transientRun(userMessage, "failed"),
          error: {
            code: "NO_MATCH",
            message: "질문과 일치하는 분석 결과를 생성하지 못했습니다.",
            retryable: true,
            required_action: "PROVIDE_CONTEXT",
          },
        };
      }

      hydrated.push({
        turnId: st.turn_id,
        question: userMessage,
        run,
        resolvedSlots: st.resolved_slots || null,
        viewType: isPresentation ? (st.view_type || "TABLE") : null,
      });
    }

    return hydrated;
  } catch (err) {
    console.error("Error hydrating turns:", err);
    return [];
  }
}

/**
 * 빠른 동작 버튼이 서버에 보낼 typed action과 대화 기록에 남길 라벨.
 * 라우팅은 action이 결정하므로 label은 서버 분기에 관여하지 않는 표시용 문구다.
 */
export const QUICK_ACTION = {
  CHART: { label: "차트로 보기", action: { requested_route: "PRESENTATION", presentation_type: "BAR" } },
  TABLE: { label: "표로 보기", action: { requested_route: "PRESENTATION", presentation_type: "TABLE" } },
  REPORT: { label: "보고서에 담기", action: { requested_route: "REPORT_ACTION" } },
};

/**
 * 빠른 동작이 서버 턴을 필요로 하는지 판정한다.
 * 이미 응답에 포함된 차트·표는 재조회 없이 로컬 뷰 전환으로 끝내야 하므로 null을 돌려준다.
 * @param {"CHART"|"TABLE"|"REPORT"|string} mode - 사용자가 누른 빠른 동작
 * @param {{hasChart: boolean, hasTable: boolean}} available - 현재 turn이 이미 가진 표현
 * @returns {{label: string, action: object}|null} 서버로 보낼 동작, 필요 없으면 null
 */
export function quickViewAction(mode, available) {
  if (mode === "REPORT") return QUICK_ACTION.REPORT;
  if (mode === "CHART" && !available.hasChart) return QUICK_ACTION.CHART;
  if (mode === "TABLE" && !available.hasTable) return QUICK_ACTION.TABLE;
  return null;
}

/**
 * 빈 대화 화면에 제시할 예시 질문을 승인된 저장 분석 정의에서 만든다.
 * 화면에 업무 문구를 박아두지 않으며, 저장된 분석이 없으면 예시를 지어내지 않는다.
 * @param {Array<object>} definitions - 서버가 반환한 저장 분석 정의 목록
 * @param {number} [limit=3] - 제시할 최대 개수
 * @returns {Array<{id: string, question: string}>} 예시 질문 목록(없으면 빈 배열)
 */
export function exampleQuestionsFromDefinitions(definitions, limit = 3) {
  if (!Array.isArray(definitions)) return [];
  return definitions
    .filter((item) => item && typeof item.question === "string" && item.question.trim())
    .slice(0, limit)
    .map((item) => ({ id: item.definition_id || item.id || item.question, question: item.question }));
}
