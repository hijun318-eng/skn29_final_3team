/** AgentPage의 run/turn 상태 변환을 담당하는 순수 헬퍼 모듈이다. React 상태를 갖지 않는다. */
import { AnalysisApiError } from "../api/analysisClient.ts";
import {
  OPENAPI_VERSION,
  normalizeAnalysisChart,
  normalizeAnalysisEvidence,
  normalizeAnalysisMetrics,
} from "../contracts/analysis.ts";

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
 * PRESENTATION이 재사용할 Artifact·query·근거가 서로 같은 식별자로 완전하게 연결됐는지 확인한다.
 * @param {object|null|undefined} run - 기존 분석 결과 run.
 * @returns {boolean} 세 식별자가 모두 존재하고 일치하면 true.
 */
export function hasReusablePresentationArtifact(run) {
  const artifactId = run?.artifact?.artifactId;
  const queryId = run?.artifact?.queryId;
  return Boolean(
    artifactId
    && queryId
    && run?.evidence
    && run.evidence.artifactId === artifactId
    && run.evidence.queryId === queryId,
  );
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
 * conversation command가 알려 준 보완 대상이 지표인지 기간인지 exact enum으로 고정한다.
 * @param {object} command - command top-level 응답 data.
 * @param {object|null|undefined} serverTurn - 저장된 서버 turn.
 * @returns {"metric"|"period"} 화면이 사용할 보완 대상.
 */
export function commandClarificationType(command, serverTurn) {
  const value = command?.clarification_type
    ?? serverTurn?.resolved_slots?.clarification_type;
  return value === "period" ? "period" : "metric";
}

/** 서버의 공개 안내를 우선하고, 없으면 typed 보완 대상별 원인 문구를 반환한다. */
export function commandClarificationMessage(command, clarificationType) {
  if (typeof command?.message === "string" && command.message.trim()) {
    return command.message.trim();
  }
  return clarificationType === "period"
    ? "분석을 시작하려면 분석할 기간을 함께 입력해 주세요."
    : "새 분석을 시작하려면 분석할 지표를 함께 입력해 주세요.";
}

/**
 * 서버 분석 상태 코드를 화면 표시용 한국어 라벨로 변환한다.
 * @param {string} status - 서버가 반환한 분석 상태 코드.
 * @returns {string} 매핑되는 한국어 라벨, 매핑 없으면 "확인 필요".
 */
export function savedRunStatus(status) {
  return ({ SUCCESS: "완료", SUCCEEDED: "완료", PARTIAL: "일부 완료", BLOCKED: "완료되지 않음", CLARIFYING: "입력 필요", FAILED: "실패", RECEIVED: "처리 중", QUEUED: "대기 중", RUNNING: "처리 중", CANCELLED: "취소됨" })[status] || "확인 필요";
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
 * conversation command의 공개 오류 필드만 AnalysisRun으로 옮긴다.
 * 저장된 내부 detail/type은 화면에 복사하지 않으며 catalog 실패를 질문 보완으로 바꾸지 않는다.
 * @param {string} question - 실패한 사용자 질문.
 * @param {object} command - command top-level 결과 또는 저장된 command_error.
 * @returns {object} 서버 code/message/retryable/action을 보존한 실패 run.
 */
export function commandErrorRun(question, command) {
  const source = command?.command_error || command?.error || command || {};
  const code = typeof source.code === "string" && source.code ? source.code : "INTERNAL_ERROR";
  const requiredAction = code === "CONTEXT_SOURCE_FAILED" && source.required_action === "PROVIDE_CONTEXT"
    ? "CONTACT_SUPPORT"
    : (source.required_action || "CONTACT_SUPPORT");
  return {
    ...transientRun(question, "failed"),
    error: {
      code,
      message: typeof source.message === "string" && source.message
        ? source.message
        : "분석 서비스를 검증하지 못했습니다. 서비스 관리자 확인 후 다시 시도해 주세요.",
      retryable: Boolean(source.retryable),
      required_action: requiredAction,
    },
  };
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
        const sourceArtifactId = lastAnalysisRun?.artifact?.artifactId;
        if (!hasReusablePresentationArtifact(lastAnalysisRun) || !st.artifact_id || st.artifact_id !== sourceArtifactId) {
          run = commandErrorRun(userMessage, {
            code: "INSUFFICIENT_EVIDENCE",
            message: "기존 분석 결과의 연결 정보를 확인할 수 없어 보기를 복원하지 않았습니다.",
            retryable: false,
            required_action: "NONE",
          });
        } else {
          run = {
            ...lastAnalysisRun,
            question: userMessage,
            status: "success",
            summary: lastAnalysisRun.summary || st.artifact_summary || "기존 분석 결과를 다시 표시했습니다.",
            chart: st.chart_spec_json ? normalizeAnalysisChart(st.chart_spec_json) : lastAnalysisRun.chart,
            viewSpecId: st.view_spec_id,
          };
        }
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
            message: commandClarificationMessage(st, clarType),
            clarification_type: clarType,
            disambiguation_options: options,
            suggestions: options.map((o) => o.label || o.value || o.metric_id),
            retryable: false,
            required_action: "PROVIDE_CONTEXT",
          },
        };
      } else if (st.command_status === "FAILED" || st.command_error) {
        run = commandErrorRun(userMessage, st);
      } else if (st.data_snapshot_json) {
        const tableData = st.data_snapshot_json;
        const chartSpec = st.chart_spec_json;
        const evidence = st.evidence_json || {};
        const normalizedEvidence = normalizeAnalysisEvidence(evidence);
        const metricValues = Array.isArray(evidence.metric_values)
          ? evidence.metric_values
          : [];
        const sources = Array.isArray(evidence.sources) ? evidence.sources : [];
        run = {
          ...transientRun(userMessage, "success"),
          requestId: st.request_id || "",
          traceId: evidence?.trace_id || "",
          status: "success",
          question: userMessage,
          summary: st.narrative_markdown || userMessage,
          table: tableData || null,
          chart: normalizeAnalysisChart(chartSpec) || null,
          evidence: normalizedEvidence,
          metrics: normalizeAnalysisMetrics(metricValues),
          sources: sources.map((source) => ({
            name: source.name,
            urn: source.urn,
            fqn: source.fqn,
            schemaVersion: source.schema_version,
            seedVersion: source.seed_version,
            synthetic: typeof source.synthetic === "boolean" ? source.synthetic : undefined,
            status: "success",
          })),
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
        run = commandErrorRun(userMessage, {
          code: "INTERNAL_ERROR",
          message: "저장된 분석 명령의 결과 상태를 확인하지 못했습니다.",
          retryable: true,
          required_action: "CONTACT_SUPPORT",
        });
      }

      hydrated.push({
        turnId: st.turn_id,
        question: userMessage,
        run,
        resolvedSlots: st.resolved_slots || null,
        viewType: isPresentation
          ? (st.view_type || "TABLE")
          : (st.view_type || st.resolved_slots?.target_chart_type || null),
        isArtifactReuse: isPresentation && hasReusablePresentationArtifact(run),
        reusePending: false,
        viewSpecId: isPresentation ? st.view_spec_id : null,
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
  SUMMARY: { label: "요약으로 보기", action: { requested_route: "PRESENTATION", presentation_type: "SUMMARY" } },
  CHART: { label: "그래프로 보기", action: { requested_route: "PRESENTATION", presentation_type: "BAR" } },
  TABLE: { label: "표로 보기", action: { requested_route: "PRESENTATION", presentation_type: "TABLE" } },
  KPI: { label: "KPI만 보기", action: { requested_route: "PRESENTATION", presentation_type: "KPI" } },
  REPORT: { label: "보고서에 담기", action: { requested_route: "REPORT_ACTION" } },
};

/**
 * 빠른 동작을 대화에 남길 서버 typed action으로 변환한다.
 * 모든 표현 변경을 PRESENTATION 턴으로 기록해 기존 응답을 교체하지 않고 같은 Artifact의
 * 후속 결과를 누적한다. 지원하지 않는 모드는 null로 닫는다.
 * @param {"SUMMARY"|"CHART"|"TABLE"|"KPI"|"REPORT"|string} mode - 사용자가 누른 빠른 동작
 * @returns {{label: string, action: object}|null} 서버로 보낼 동작, 지원하지 않으면 null
 */
export function quickViewAction(mode) {
  return QUICK_ACTION[mode] || null;
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
