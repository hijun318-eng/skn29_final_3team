/** 대화형 분석 워크스페이스의 세션·멀티턴 상태·증적 서랍·보고서 연계를 통합 관리하는 모듈이다. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Eye, FilePlus2, History, MessageSquareText, Plus, Save, Send, Sparkles, TableProperties } from "lucide-react";
import { AnalysisApiError, createAnalysisClient } from "../api/analysisClient";
import { createReportClient } from "../api/reportClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MLPredictionCard } from "../components/ml/MLPredictionCard";
import { RagAnswerCard } from "../components/rag/RagAnswerCard";
import RagEmptyState from "../components/rag/RagEmptyState";
import { MetaStrip } from "../components/common/EnterpriseUi";
import { TurnEvidenceDrawer } from "../components/TurnEvidenceDrawer";
import { TurnReportModal } from "../components/TurnReportModal";
import { normalizeApiResponse } from "../contracts/analysis";
import { createUuid } from "../utils/createUuid";
import { reportTitleForAnalysis } from "../utils/presentation";
import { analysisError, clarifiedQuestion, commandClarificationMessage, commandClarificationType, commandErrorRun, exampleQuestionsFromDefinitions, formatSeoulDateTime, hasReusablePresentationArtifact, hydrateTurnsFromServer, quickViewAction, savedRunStatus, transientRun } from "./agentPageHelpers";
import "./AgentPageAgents.css";

const RUN_HISTORY_PAGE_SIZE = 20;
const MAX_QUESTION_LENGTH = 1000;
const QUESTION_DRAFT_KEY = "answervice.questionDraft";
const CONVERSATION_KEY = "answervice.activeConversationId";
const AGENT_MODES = [
  ["AUTO", "자동 선택"],
  ["DATA_ANALYSIS", "데이터 분석"],
  ["INTERNAL_GUIDELINE", "내부지침"],
];

function mlPendingRun(question) {
  return {
    ...transientRun(question, "running"),
    mlPrediction: {
      status: "RUNNING",
      request: { query: question },
      completedStages: 1,
    },
  };
}

function predictionRun(question, result) {
  const request = result.request;
  const summary = result.summary;
  const rows = result.daily || [];
  const weightedPercent = Number(summary.weighted_occupancy_rate || 0) * 100;
  return {
    ...transientRun(question, "success"),
    requestId: result.request_id,
    traceId: result.trace_id,
    summary: `${request.hotel_scope}는 향후 ${request.horizon}일 동안 전체 ${Number(summary.total_available_room_nights).toFixed(0)}객실박 중 ${Number(summary.predicted_sold_room_nights).toFixed(0)}객실박이 판매될 것으로 예측됩니다.`,
    rowCount: rows.length,
    evidenceReady: true,
    metrics: [
      { metricId: "PREDICTED_ROOMS_SOLD", resultField: "predicted_rooms_sold", label: "예측 판매 객실박", definition: "Backend 검증 완료 예측 판매 객실박", value: summary.predicted_sold_room_nights, unit: "객실박" },
      { metricId: "AVAILABLE_ROOM_NIGHTS", resultField: "available_rooms", label: "전체 공급 객실박", definition: "Backend 검증 완료 전체 공급 객실박", value: summary.total_available_room_nights, unit: "객실박" },
      { metricId: "REMAINING_ROOM_NIGHTS", resultField: "remaining_rooms", label: "잔여 예상 객실박", definition: "Backend 검증 완료 잔여 객실박", value: summary.remaining_room_nights, unit: "객실박" },
      { metricId: request.metric, resultField: "predicted_occupancy_rate", label: "가중 예측 점유율", definition: "Backend 가중 집계 점유율", value: weightedPercent, unit: "%" },
    ],
    table: { columns: ["target_date", "available_rooms", "booking_on_hand", "predicted_rooms_sold", "remaining_rooms", "predicted_occupancy_rate"], rows },
    chart: rows.length ? { chartType: "LINE", xField: "target_date", yFields: ["available_rooms", "booking_on_hand", "predicted_rooms_sold"] } : null,
    sources: [{ name: String(result.evidence.feature_source || ""), urn: "urn:answervice:source:live_trino_pms", status: "success" }],
    trace: [
      { stage: "ML_AUTHORIZATION", outcome: result.evidence.authorization, detail: request.hotel_scope },
      { stage: "ML_CAPABILITY", outcome: result.evidence.capability, detail: String(result.evidence.model_version || "") },
      { stage: "ML_VALIDATION", outcome: "PASSED", detail: String(result.evidence.prediction_rows || 0) },
    ],
    meta: { asOf: request.as_of, timezone: "Asia/Seoul", seed: String(result.evidence.model_version || ""), schemaVersion: "ml-analysis-v1", contractVersion: "OPENAPI-v1.0.0" },
    mlPrediction: {
      status: "SUCCESS",
      completedStages: 5,
      request: { hotelScope: request.hotel_scope, metric: request.metric, horizon: request.horizon, asOf: request.as_of },
      summary: {
        totalAvailable: summary.total_available_room_nights,
        totalPredicted: summary.predicted_sold_room_nights,
        totalRemaining: summary.remaining_room_nights,
        dailyAverage: summary.daily_average_predicted_rooms,
        weightedOccupancy: weightedPercent,
      },
      daily: rows,
      roomTypes: result.room_type_details || [],
      trendDescription: result.trend.description,
      limitations: result.limitations || [],
      evidence: {
        requestId: result.request_id,
        traceId: result.trace_id,
        modelName: result.evidence.model_name,
        modelVersion: result.evidence.model_version,
        artifactHash: result.evidence.artifact_hash,
        featureSource: result.evidence.feature_source,
        trainingSource: result.evidence.training_source,
        featureAsOf: result.evidence.feature_as_of,
        predictionRows: result.evidence.prediction_rows,
        executionId: result.evidence.execution_id,
        trinoQueryIds: result.evidence.trino_query_ids || [],
        ragCalled: result.evidence.rag_called,
      },
    },
  };
}

/** 대화형 분석 워크스페이스 최상위 화면을 렌더링한다. */
export function AgentPage({ onNavigate, onAgentModeChange }) {
  const analysisClient = useMemo(() => createAnalysisClient(fetch), []);
  const reportClient = useMemo(() => createReportClient(undefined, fetch), []);
  const [question, setQuestion] = useState(() => window.sessionStorage.getItem(QUESTION_DRAFT_KEY) || "");
  const [inputError, setInputError] = useState("");
  const [conversationId, setConversationId] = useState(() => window.sessionStorage.getItem(CONVERSATION_KEY) || "");
  const [turns, setTurns] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [selectedEvidenceRun, setSelectedEvidenceRun] = useState(null);
  const [agentMode, setAgentMode] = useState("AUTO");
  const [reportModal, setReportModal] = useState("");
  const [reportModalRun, setReportModalRun] = useState(null);
  const [reportTitle, setReportTitle] = useState("");
  const [message, setMessage] = useState("");
  const [savedBusy, setSavedBusy] = useState(false);
  const [definitions, setDefinitions] = useState([]);
  const [definitionQuery, setDefinitionQuery] = useState("");
  const [visibleDefinitionCount, setVisibleDefinitionCount] = useState(10);
  const [savedRuns, setSavedRuns] = useState([]);
  const [visibleRunCount, setVisibleRunCount] = useState(RUN_HISTORY_PAGE_SIZE);
  const requestInFlight = useRef(false);
  const requestGeneration = useRef(0);
  const activeTraceId = useRef("");
  const activeCommandAbortController = useRef(null);
  const threadEndRef = useRef(null);

  const scrollToLatestTurn = () => window.requestAnimationFrame(() => {
    threadEndRef.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "end",
    });
  });

  const activeEvidenceRun = selectedEvidenceRun || turns.at(-1)?.run || transientRun("");

  const filteredDefinitions = useMemo(() => {
    const normalized = definitionQuery.trim().toLocaleLowerCase("ko-KR");
    return definitions.filter((d) => !normalized || `${d.title} ${d.question}`.toLocaleLowerCase("ko-KR").includes(normalized));
  }, [definitionQuery, definitions]);

  const exampleQuestions = useMemo(() => exampleQuestionsFromDefinitions(definitions), [definitions]);
  const visibleDefinitions = filteredDefinitions.slice(0, visibleDefinitionCount);
  const visibleRuns = savedRuns.slice(0, visibleRunCount);
  const latestArtifactTurn = useMemo(
    () => [...turns].reverse().find((turn) => turn.run?.artifact) || null,
    [turns],
  );

  const refreshSaved = async () => {
    const [nextDefs, nextRuns] = await Promise.all([analysisClient.listDefinitions(), analysisClient.listRuns()]);
    setDefinitions(nextDefs);
    setSavedRuns(nextRuns);
  };

  useEffect(() => {
    refreshSaved().catch((err) => setMessage(err instanceof Error ? err.message : "저장된 분석을 불러오지 못했습니다."));

    const storedConvId = window.sessionStorage.getItem(CONVERSATION_KEY);
    if (storedConvId) {
      analysisClient.getConversationTurns(storedConvId)
        .then((serverTurns) => {
          if (Array.isArray(serverTurns) && serverTurns.length > 0) {
            setTurns(hydrateTurnsFromServer(serverTurns));
            scrollToLatestTurn();
          }
        })
        .catch((err) => {
          console.warn("Failed to restore conversation turns on mount:", err);
          if (err?.status === 404) {
            window.sessionStorage.removeItem(CONVERSATION_KEY);
            setConversationId("");
          }
        });
    }
  }, []);

  const handleCancelAnalysis = async (turnId) => {
    const cancelledTraceId = activeTraceId.current;
    activeCommandAbortController.current?.abort();
    activeCommandAbortController.current = null;
    requestGeneration.current += 1;
    activeTraceId.current = "";
    requestInFlight.current = false;
    setSubmitting(false);
    setTurns((prev) =>
      prev.map((t) =>
        t.turnId === turnId || (typeof t.turnId === "string" && t.turnId.startsWith("temp-"))
          ? {
              ...t,
              run: {
                ...t.run,
                status: "cancelled",
                error: {
                  code: "REQUEST_CANCELLED",
                  message: "사용자에 의해 분석이 취소되었습니다.",
                  retryable: true,
                  required_action: "RETRY",
                },
              },
            }
          : t
      )
    );
    if (cancelledTraceId) {
      try {
        await analysisClient.cancelAnalysis(cancelledTraceId);
      } catch (err) {
        console.warn("Cancel analysis error:", err);
      }
    }
  };

  useEffect(() => {
    if (question) window.sessionStorage.setItem(QUESTION_DRAFT_KEY, question);
    else window.sessionStorage.removeItem(QUESTION_DRAFT_KEY);
  }, [question]);

  useEffect(() => () => activeCommandAbortController.current?.abort(), []);

  const initConversation = async (generation) => {
    const conv = await analysisClient.createConversation();
    if (generation !== undefined && requestGeneration.current !== generation) return "";
    const nextId = conv.conversation_id;
    setConversationId(nextId);
    window.sessionStorage.setItem(CONVERSATION_KEY, nextId);
    return nextId;
  };

  const handleNewChat = () => {
    activeCommandAbortController.current?.abort();
    activeCommandAbortController.current = null;
    requestGeneration.current += 1;
    requestInFlight.current = false;
    activeTraceId.current = "";
    setSubmitting(false);
    setQuestion("");
    setInputError("");
    setConversationId("");
    window.sessionStorage.removeItem(CONVERSATION_KEY);
    setTurns([]);
    setEvidenceOpen(false);
    setSelectedEvidenceRun(null);
    setReportModal("");
    setReportModalRun(null);
    setReportTitle("");
    setMessage("");
  };

  // action은 UI가 이미 아는 동작을 자연어로 바꾸지 않고 전달하는 typed 신호다(서버가 재검증).
  const analyzeQuestion = async (nextQuestion, action = null, sourceTurn = null) => {
    const normalized = nextQuestion.trim();
    if (!normalized) { setInputError("분석할 질문을 입력해 주세요."); return; }
    if (requestInFlight.current) return;
    const isPresentationAction = action?.requested_route === "PRESENTATION";
    const sourceRun = sourceTurn?.run || latestArtifactTurn?.run || null;
    if (isPresentationAction && !hasReusablePresentationArtifact(sourceRun)) {
      const unavailableTurn = {
        turnId: `local-${Date.now()}`,
        question: normalized,
        run: {
          ...transientRun(normalized, "blocked"),
          error: {
            code: "INSUFFICIENT_EVIDENCE",
            message: "기존 분석 결과가 없어 해당 보기를 만들 수 없습니다.",
            retryable: false,
            required_action: "NONE",
          },
        },
        resolvedSlots: null,
        viewType: action.presentation_type,
        isArtifactReuse: false,
        reusePending: false,
        viewSpecId: null,
      };
      setTurns((prev) => [...prev, unavailableTurn]);
      scrollToLatestTurn();
      return;
    }
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    requestInFlight.current = true;
    setInputError("");
    setQuestion("");
    setSubmitting(true);
    setEvidenceOpen(false);
    setSelectedEvidenceRun(null);
    setMessage("");
    const traceId = createUuid();
    const commandIdempotencyKey = createUuid();
    activeTraceId.current = traceId;
    const commandAbortController = new AbortController();
    activeCommandAbortController.current = commandAbortController;
    const canReuseArtifact = Boolean(isPresentationAction);

    const optimisticTurn = {
      turnId: `temp-${Date.now()}`,
      question: normalized,
      run: canReuseArtifact
        ? { ...sourceRun, question: normalized, status: "success", traceId, elapsedSeconds: 0 }
        : { ...transientRun(normalized, "running"), traceId },
      resolvedSlots: null,
      viewType: canReuseArtifact ? action.presentation_type : null,
      isArtifactReuse: canReuseArtifact,
      reusePending: canReuseArtifact,
      viewSpecId: null,
    };
    setTurns((prev) => [...prev, optimisticTurn]);
    scrollToLatestTurn();

    const commandOptions = {
      traceId,
      signal: commandAbortController.signal,
      onProgress: (progress) => {
        if (requestGeneration.current !== generation || progress?.traceId !== traceId) return;
        setTurns((prev) => prev.map((turn) => turn.turnId === optimisticTurn.turnId
          ? { ...turn, processViewModel: progress }
          : turn));
      },
    };

    try {
      let activeConvId = conversationId;
      if (!activeConvId) activeConvId = await initConversation(generation);
      if (!activeConvId || requestGeneration.current !== generation) return;
      if (agentMode !== "DATA_ANALYSIS") {
        try {
          const ragResult = await analysisClient.queryManual(
            normalized,
            agentMode === "INTERNAL_GUIDELINE" ? "DOCUMENT_ONLY" : "AUTO",
            activeConvId,
          );
          if (ragResult.status === "ANSWER") {
            const document = ragResult.document || { body: ragResult.answer?.text || "" };
            setTurns((prev) => prev.map((turn) => turn.turnId === optimisticTurn.turnId ? {
              ...turn,
              turnId: ragResult.turn_id || turn.turnId,
              run: {
                ...transientRun(normalized, "success"),
                requestId: ragResult.request_id || "",
                traceId: ragResult.trace_id || traceId,
                summary: document.body || ragResult.answer?.text || "",
                rag: {
                  ...document,
                  answer_type: ragResult.answer_type,
                  response_status: ragResult.response_status || "ANSWERED",
                  answer_id: ragResult.answer_id || ragResult.request_id || "",
                  answer_text: ragResult.answer?.text || "",
                  processing_steps: ragResult.processing_steps || [],
                  evidence_bundle: ragResult.evidence_bundle || [],
                  citations: ragResult.citations || [],
                },
              },
              viewType: "RAG",
            } : turn));
            return;
          }
          if (ragResult.status === "CONFLICT" || (ragResult.status === "NO_EVIDENCE" && agentMode === "INTERNAL_GUIDELINE")) {
            const summary = ragResult.status === "CONFLICT"
              ? "문서 기준 충돌이 확인되었습니다."
              : "관련 내부지침 근거를 찾지 못했습니다.";
            setTurns((prev) => prev.map((turn) => turn.turnId === optimisticTurn.turnId ? {
              ...turn,
              run: {
                ...transientRun(normalized, "success"),
                summary,
                rag: {
                  status: ragResult.status,
                  answer_id: ragResult.answer_id || "",
                  processing_steps: ragResult.processing_steps || [],
                  evidence_bundle: ragResult.evidence_bundle || [],
                  conflicts: ragResult.conflicts || [],
                },
              },
              viewType: "RAG",
            } : turn));
            return;
          }
        } catch (ragError) {
          if (agentMode === "INTERNAL_GUIDELINE") throw ragError;
        }
      }
      const headTurnId = turns.length > 0 ? turns.at(-1)?.turnId : undefined;
      let cmdResponse;
      try {
        cmdResponse = await analysisClient.submitTurnCommand(activeConvId, {
          ...(action || {}),
          user_message: normalized,
          expected_head_turn_id: headTurnId && !headTurnId.startsWith("temp-") ? headTurnId : null,
          idempotency_key: commandIdempotencyKey,
        }, commandOptions);
      } catch (cmdErr) {
        if (cmdErr instanceof AnalysisApiError && cmdErr.status === 409) {
          // stale head는 서버 이력으로 복원만 한다. 새 head에 같은 명령을 자동
          // 재제출하면 사용자가 보지 못한 Turn 뒤에서 의도가 달라질 수 있다.
          const serverTurns = await analysisClient.getConversationTurns(activeConvId);
          if (requestGeneration.current !== generation) return;
          setTurns(hydrateTurnsFromServer(serverTurns));
          setQuestion(normalized);
          window.sessionStorage.setItem(QUESTION_DRAFT_KEY, normalized);
          throw cmdErr;
        } else if (cmdErr instanceof AnalysisApiError && cmdErr.status === 404) {
          activeConvId = await initConversation(generation);
          if (!activeConvId || requestGeneration.current !== generation) return;
          cmdResponse = await analysisClient.submitTurnCommand(activeConvId, {
            ...(action || {}),
            user_message: normalized,
            expected_head_turn_id: null,
            idempotency_key: commandIdempotencyKey,
          }, commandOptions);
        } else {
          throw cmdErr;
        }
      }
      if (requestGeneration.current !== generation) return;

      const data = cmdResponse?.data || cmdResponse;
      const serverTurn = data?.turn;
      const analysisRaw = data?.analysis_response;
      const isPresentation = serverTurn?.route === "PRESENTATION";
      const isReportAction = serverTurn?.route === "REPORT_ACTION";

      let finalRun;
      if (analysisRaw && analysisRaw.data) {
        finalRun = normalizeApiResponse(analysisRaw, normalized);
      } else if (["BLOCKED", "FAILED", "PARTIAL", "CANCELLED"].includes(data?.status)) {
        finalRun = commandErrorRun(normalized, data);
      } else if (data?.status === "CLARIFICATION_REQUIRED" || serverTurn?.resolved_slots?.ambiguity_status === "NEEDS_CLARIFICATION") {
        const options = data?.disambiguation_options || serverTurn?.resolved_slots?.disambiguation_options || [];
        const clarType = commandClarificationType(data, serverTurn);
        finalRun = {
          ...transientRun(normalized, "blocked"),
          disambiguationOptions: options,
          error: {
            code: "CONTEXT_INCOMPLETE",
            message: commandClarificationMessage(data, clarType),
            clarification_type: clarType,
            disambiguation_options: options,
            suggestions: options.map((o) => o.label || o.value || o.metric_id),
            retryable: false,
            required_action: "PROVIDE_CONTEXT",
          },
        };
      } else if (isPresentation) {
        const sourceArtifactId = sourceRun?.artifact?.artifactId;
        const sourceQueryId = sourceRun?.artifact?.queryId;
        const responseArtifact = analysisRaw?.data?.artifact;
        const responseEvidence = analysisRaw?.data?.result?.evidence;
        const responseArtifactMatches = !responseArtifact || (
          responseArtifact.artifact_id === sourceArtifactId
          && responseArtifact.query_id === sourceQueryId
        );
        const responseEvidenceMatches = !responseEvidence || (
          responseEvidence.artifact_id === sourceArtifactId
          && responseEvidence.query_id === sourceQueryId
        );
        if (
          !hasReusablePresentationArtifact(sourceRun)
          || !serverTurn?.artifact_id
          || sourceArtifactId !== serverTurn.artifact_id
          || !responseArtifactMatches
          || !responseEvidenceMatches
        ) {
          finalRun = commandErrorRun(normalized, {
            code: "INSUFFICIENT_EVIDENCE",
            message: "기존 분석 결과의 연결 정보를 확인할 수 없어 보기를 추가하지 않았습니다.",
            retryable: false,
            required_action: "NONE",
          });
        } else {
          finalRun = { ...sourceRun, question: normalized, status: "success" };
        }
      } else if (isPresentationAction) {
        finalRun = commandErrorRun(normalized, {
          code: "INSUFFICIENT_EVIDENCE",
          message: "서버가 기존 분석 결과의 표현 요청을 확인하지 못해 보기를 추가하지 않았습니다.",
          retryable: false,
          required_action: "NONE",
        });
      } else if (analysisRaw && analysisRaw.data) {
        finalRun = normalizeApiResponse(analysisRaw, normalized);
      } else if (isReportAction) {
        finalRun = {
          ...transientRun(normalized, "success"),
          summary: `분석 대화 결과가 공식 보고서 초안(Draft)으로 결합되었습니다. (/reports에서 확인 가능)`,
          reportDefinitionId: serverTurn?.report_definition_id,
        };
      } else {
        finalRun = commandErrorRun(normalized, {
          code: "INTERNAL_ERROR",
          message: "분석 명령의 결과 상태를 확인하지 못했습니다.",
          retryable: true,
          required_action: "CONTACT_SUPPORT",
        });
      }

      if (requestGeneration.current !== generation) return;
      setTurns((prev) => prev.map((t) => t.turnId === optimisticTurn.turnId ? {
        turnId: serverTurn?.turn_id || optimisticTurn.turnId,
        question: normalized,
        run: finalRun,
        resolvedSlots: serverTurn?.resolved_slots || null,
        viewType: isPresentation
          ? (serverTurn?.view_type || "TABLE")
          : (serverTurn?.view_type || serverTurn?.resolved_slots?.target_chart_type || "SUMMARY"),
        isArtifactReuse: isPresentation && Boolean(finalRun.artifact),
        reusePending: false,
        viewSpecId: isPresentation ? serverTurn?.view_spec_id : null,
      } : t));

      void refreshSaved();
    } catch (error) {
      if (requestGeneration.current !== generation) return;
      setTurns((prev) => prev.map((t) => t.turnId === optimisticTurn.turnId ? {
        ...t,
        isArtifactReuse: false,
        reusePending: false,
        run: {
          ...transientRun(normalized, error instanceof AnalysisApiError && error.status === 403 ? "blocked" : "failed"),
          error: {
            code: error instanceof AnalysisApiError ? error.code : "NETWORK_UNAVAILABLE",
            message: analysisError(error),
            retryable: error instanceof AnalysisApiError ? error.retryable : true,
            required_action: error instanceof AnalysisApiError ? error.requiredAction : "RETRY",
            suggestions: error instanceof AnalysisApiError ? error.suggestions : [],
            missing_requirements: error instanceof AnalysisApiError ? error.missingRequirements : [],
            trace_id: traceId,
          },
        },
      } : t));
    } finally {
      if (requestGeneration.current === generation) {
        if (activeCommandAbortController.current === commandAbortController) activeCommandAbortController.current = null;
        if (activeTraceId.current === traceId) activeTraceId.current = "";
        requestInFlight.current = false;
        setSubmitting(false);
        scrollToLatestTurn();
      }
    }
  };

  const submitQuestion = (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void analyzeQuestion(String(form.get("question") || question).trim());
  };

  const runApprovedPrediction = async (requestedQuestion) => {
    const label = String(requestedQuestion || "").trim();
    if (!label || submitting || requestInFlight.current) return;
    requestInFlight.current = true;
    setSubmitting(true);
    setMessage("");
    setQuestion("");
    const turnId = `ml-${createUuid()}`;
    setTurns((prev) => [
      ...prev,
      { turnId, question: label, run: mlPendingRun(label), viewType: "SUMMARY" },
    ]);
    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) activeConversationId = await initConversation();
      const result = await analysisClient.createMLAnalysis({
        query: label,
        conversation_id: activeConversationId,
      });
      setTurns((prev) => prev.map((turn) => turn.turnId === turnId
        ? { ...turn, run: predictionRun(label, result) }
        : turn));
    } catch (error) {
      const errorMessage = analysisError(error);
      setTurns((prev) => prev.map((turn) => turn.turnId === turnId
        ? {
            ...turn,
            run: {
              ...commandErrorRun(label, { message: errorMessage, retryable: true, required_action: "RETRY" }),
              mlPrediction: { status: "FAILED", request: { query: label }, completedStages: 1, error: errorMessage },
            },
          }
        : turn));
    } finally {
      requestInFlight.current = false;
      setSubmitting(false);
      window.requestAnimationFrame(() => threadEndRef.current?.scrollIntoView({ behavior: "smooth" }));
    }
  };

  const saveAnalysis = async (targetRun) => {
    if (!["success", "partial"].includes(targetRun.status) || !targetRun.requestId || savedBusy) return;
    setSavedBusy(true);
    setMessage("");
    try {
      await analysisClient.createDefinition(targetRun.question, targetRun.requestId);
      setMessage("현재 분석을 저장했습니다.");
      await refreshSaved();
    } catch (error) { setMessage(error instanceof Error ? error.message : "분석을 저장하지 못했습니다."); }
    finally { setSavedBusy(false); }
  };

  const replaySavedDefinition = async (definition) => {
    if (requestInFlight.current || savedBusy) return;
    requestInFlight.current = true;
    setSavedBusy(true);
    setSubmitting(true);
    setEvidenceOpen(false);
    setSelectedEvidenceRun(null);
    setMessage("저장 분석을 현재 권한과 릴리스에서 다시 실행하고 있습니다.");
    try {
      const receipt = await analysisClient.replayDefinition(definition.definition_id, {});
      if (!["SUCCEEDED", "PARTIAL"].includes(receipt.status)) {
        throw new Error("저장 분석 재실행이 완료 상태가 아닙니다.");
      }
      const run = await analysisClient.getRunArtifact(receipt.request_id);
      setConversationId("");
      window.sessionStorage.removeItem(CONVERSATION_KEY);
      setTurns([{
        turnId: `saved-${receipt.request_id}`,
        question: definition.question,
        run: { ...run, question: definition.question },
        resolvedSlots: null,
        viewType: "SUMMARY",
      }]);
      setMessage("저장 분석을 새 실행으로 완료했습니다.");
      await refreshSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "저장 분석을 다시 실행하지 못했습니다.");
    } finally {
      requestInFlight.current = false;
      setSavedBusy(false);
      setSubmitting(false);
      window.requestAnimationFrame(() => threadEndRef.current?.scrollIntoView({ behavior: "smooth" }));
    }
  };

  const createReportDraft = async () => {
    const artId = reportModalRun?.artifact?.artifactId || reportModalRun?.artifact?.artifact_id;
    if (!artId) return;
    setMessage("");
    try {
      await reportClient.createDraftFromArtifact(artId, reportTitle.trim() || reportTitleForAnalysis(reportModalRun));
      setReportModal("");
      onNavigate("/reports");
    } catch (error) { setMessage(error instanceof Error ? error.message : "보고서 초안을 저장하지 못했습니다."); }
  };

  const copyEvidence = async (value) => {
    try {
      await navigator.clipboard.writeText(String(value ?? ""));
      setMessage("식별 정보를 복사했습니다.");
    } catch {
      setMessage("식별 정보를 복사하지 못했습니다.");
    }
  };

  useEffect(() => {
    onAgentModeChange?.(agentMode);
  }, [agentMode, onAgentModeChange]);

  return (
    <div className={`chat-layout ${evidenceOpen ? "evidence-open" : ""}`}>
      {/* 좌측: 저장된 분석 및 대화방 */}
      <aside className="chat-history" inert={Boolean(reportModal)}>
        <button className="new-chat" onClick={handleNewChat}><Plus size={16} />새 분석</button>
        <p>저장된 분석</p>
        <label className="saved-analysis-search">
          <span className="sr-only">저장된 분석 검색</span>
          <input value={definitionQuery} onChange={(e) => { setDefinitionQuery(e.target.value); setVisibleDefinitionCount(10); }} placeholder="저장 분석 검색" />
        </label>
        {visibleDefinitions.length === 0 && <small className="chat-history-empty">아직 저장된 분석이 없습니다.</small>}
        {visibleDefinitions.map((d) => (
          <button disabled={savedBusy} title={d.question} onClick={() => void replaySavedDefinition(d)} key={d.definition_id}>
            <MessageSquareText size={15} /><span>{d.title}<small>다시 분석하기</small></span>
          </button>
        ))}
        {filteredDefinitions.length > visibleDefinitionCount && (
          <button type="button" className="saved-analysis-more" onClick={() => setVisibleDefinitionCount((c) => c + 10)}>더 보기</button>
        )}
      </aside>

      {/* 중앙: 대화 스레드 메인 */}
      <main className="chat-main" inert={Boolean(reportModal)}>
        <nav className="agent-mode-selector" aria-label="질의 에이전트 선택">
          {AGENT_MODES.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={agentMode === value} onClick={() => setAgentMode(value)}>
              {label}
            </button>
          ))}
        </nav>
        {activeEvidenceRun.meta?.asOf && <MetaStrip meta={activeEvidenceRun.meta} verified={Boolean(activeEvidenceRun.artifact && ["success", "partial"].includes(activeEvidenceRun.status))} />}
        
        {turns.length === 0 && !submitting && (agentMode === "INTERNAL_GUIDELINE" ? (
          <RagEmptyState onAsk={analyzeQuestion} />
        ) : (
          <section className="chat-empty-state" aria-labelledby="chat-empty-title">
            <small>대화형 데이터 분석</small>
            <h2 id="chat-empty-title">무엇을 분석할까요?</h2>
            <p>호텔 운영 매출, 객실 지표, 고객 VOC 평점 등 다양한 지표와 기간을 자연어로 분석해 보세요.</p>
            {exampleQuestions.length > 0 && (
              <div aria-label="분석 질문 예시">
                {exampleQuestions.map((ex) => <button key={ex.id} type="button" onClick={() => { void analyzeQuestion(ex.question); }}>{ex.question}</button>)}
              </div>
            )}
          </section>
        ))}

        {turns.length > 0 && (
          <div className="conversation">
            {turns.map((turnItem, idx) => (
              <div key={turnItem.turnId || idx} className="conversation-turn-group">
                <div className="message message--user">
                  <div className="turn-user-bubble">
                    <span className="user-icon">👤</span>
                    <div className="user-content">
                      <p className="user-text">{turnItem.question}</p>
                    </div>
                  </div>
                </div>

                <div className="message message--agent">
                  <span className="agent-avatar"><Sparkles size={16} /></span>
                  <div className="agent-response-container">

                    {turnItem.run.rag ? (
                      <RagAnswerCard
                        rag={turnItem.run.rag}
                        onFollowUp={analyzeQuestion}
                        pdfUrl={turnItem.run.rag.document_id ? analysisClient.manualPdfUrl(turnItem.run.rag.document_id) : ""}
                        pdfSources={(turnItem.run.rag.evidence_bundle || []).map((source) => ({
                          label: source.document_name || source.document_id,
                          url: source.document_id ? analysisClient.manualPdfUrl(source.document_id) : "",
                        }))}
                      />
                    ) : turnItem.run.mlPrediction ? (
                      <MLPredictionCard
                        run={turnItem.run}
                        disabled={submitting}
                        onRetry={() => void runApprovedPrediction(turnItem.question)}
                      />
                    ) : (
                    <AnalysisStatePanel
                      run={turnItem.run}
                      viewType={turnItem.viewType || turnItem.resolvedSlots?.target_chart_type || "SUMMARY"}
                      artifactReuse={turnItem.isArtifactReuse ? {
                        pending: Boolean(turnItem.reusePending),
                        viewSpecId: turnItem.viewSpecId,
                      } : null}
                      processViewModel={turnItem.processViewModel}
                      suggestionsDisabled={submitting}
                      onSuggestion={(sugg) => void analyzeQuestion(clarifiedQuestion(turnItem.question, sugg, turnItem.run.error?.clarification_type))}
                      onQuickView={turnItem.turnId === latestArtifactTurn?.turnId ? (mode) => {
                        const quick = quickViewAction(mode);
                        if (quick) void analyzeQuestion(quick.label, quick.action, turnItem);
                      } : undefined}
                      onRetry={() => void analyzeQuestion(turnItem.question)}
                      onCancel={() => void handleCancelAnalysis(turnItem.turnId)}
                      onSave={["success", "partial"].includes(turnItem.run.status) ? () => void saveAnalysis(turnItem.run) : undefined}
                      saveDisabled={savedBusy}
                      onCreateReportDraft={turnItem.run.artifact && (turnItem.run.rowCount ?? 0) > 0 ? () => {
                        setReportModalRun(turnItem.run);
                        setReportTitle(reportTitleForAnalysis(turnItem.run));
                        setReportModal("draft");
                      } : undefined}
                      onPreview={turnItem.run.artifact && (turnItem.run.rowCount ?? 0) > 0 ? () => {
                        setReportModalRun(turnItem.run);
                        setReportModal("preview");
                      } : undefined}
                      onOpenEvidence={turnItem.run.artifact ? () => {
                        setSelectedEvidenceRun(turnItem.run);
                        setEvidenceOpen(true);
                      } : undefined}
                    />
                    )}
                    {turnItem.run.reportDefinitionId && (
                      <div className="report-action-direct-nav" style={{ marginTop: "8px", display: "flex", justifyContent: "flex-end" }}>
                        <button
                          type="button"
                          className="unified-action-btn unified-action-btn--primary"
                          onClick={() => onNavigate?.("/reports")}
                          title="생성된 보고서 초안으로 이동"
                        >
                          <FilePlus2 size={13} />
                          <span>보고서에서 확인하기 (/reports)</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
            <div ref={threadEndRef} className="conversation-end" aria-hidden="true" />
          </div>
        )}

        {/* 하단 고정 분석 질문 입력창 */}
        <form className="chat-input" onSubmit={submitQuestion}>
          <div className="question-field">
            <input
              aria-label="분석 질문"
              name="question"
              value={question}
              maxLength={MAX_QUESTION_LENGTH}
              onChange={(e) => { setQuestion(e.target.value); setInputError(""); }}
              placeholder={agentMode === "INTERNAL_GUIDELINE"
                ? "내부 업무 기준을 질문하세요"
                : "분석할 지표와 기간을 자연어로 입력하세요"}
              aria-describedby="question-help"
              aria-invalid={Boolean(inputError)}
              disabled={submitting}
              required
            />
            <button type="button" aria-label="ML 예측 실행" title="승인된 ML 모델로 예측" disabled={submitting || !question.trim()} onClick={() => void runApprovedPrediction(question)}><Sparkles size={16} /></button>
            <button aria-label="질문 전송" disabled={submitting || !question.trim()}><Send size={16} /></button>
          </div>
          <small id="question-help">{question.length.toLocaleString("ko-KR")}/{MAX_QUESTION_LENGTH.toLocaleString("ko-KR")}자</small>
          {inputError && <p className="analysis-input-error" role="alert">{inputError}</p>}
        </form>

        {message && <p className="analysis-notice" role="status">{message}</p>}

        {savedRuns.length > 0 && (
          <details className="run-history-panel">
            <summary><History size={15} /><span>최근 실행</span><b>{savedRuns.length}</b></summary>
            <ul>
              {visibleRuns.map((item) => (
                <li key={item.request_id}>
                  <span>
                    <b>{savedRunStatus(item.status)}</b>
                    <small>{formatSeoulDateTime(item.completed_at || item.started_at)}</small>
                    <small>{item.question}</small>
                    <small>{item.period_start && item.period_end_exclusive
                      ? `${item.period_start} ~ ${item.period_end_exclusive} 미포함`
                      : item.snapshot_cutoff && item.snapshot_selection === "max_source_value_lt_as_of"
                        ? `${item.snapshot_cutoff} 이전 최신 스냅샷`
                        : "시간 기준 없음"}</small>
                  </span>
                  {item.artifact_id && (
                    <button type="button" disabled={savedBusy} onClick={() => void replaySavedDefinition(item)}>
                      다시 실행
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {savedRuns.length > visibleRunCount && (
              <button type="button" onClick={() => setVisibleRunCount((c) => c + RUN_HISTORY_PAGE_SIZE)}>더 보기</button>
            )}
          </details>
        )}
      </main>

      {/* 우측 슬라이드: 분석 근거 서랍 */}
      <TurnEvidenceDrawer
        open={evidenceOpen}
        run={activeEvidenceRun}
        onClose={() => {
          setEvidenceOpen(false);
          setSelectedEvidenceRun(null);
        }}
        onCopy={copyEvidence}
      />

      {/* 보고서 초안 생성 모달 */}
      <TurnReportModal
        mode={reportModal}
        run={reportModalRun || activeEvidenceRun}
        title={reportTitle}
        onTitleChange={setReportTitle}
        onConfirm={() => void createReportDraft()}
        onPreviewMode={() => { setReportTitle(reportTitleForAnalysis(reportModalRun || activeEvidenceRun)); setReportModal("draft"); }}
        onClose={() => setReportModal("")}
        isSubmitting={false}
      />
    </div>
  );
}
