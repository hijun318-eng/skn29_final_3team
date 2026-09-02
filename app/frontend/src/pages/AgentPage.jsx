/** 대화형 분석 워크스페이스의 세션·멀티턴 상태·증적 서랍·보고서 연계를 통합 관리하는 모듈이다. */
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, FilePlus2, Info, MessageSquareText, Plus, Send, Sparkles } from "lucide-react";
import { AnalysisApiError, createAnalysisClient, SERVICE_FEATURE } from "../api/analysisClient";
import { createReportClient } from "../api/reportClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { AgentCapabilityOverview, AgentExecutionBar } from "../components/agent/AgentIdentity";
import { RagAnswerCard } from "../components/rag/RagAnswerCard";
import { MLPredictionResult } from "../components/ml/MLPredictionWorkspace";
import { TurnEvidenceDrawer } from "../components/TurnEvidenceDrawer";
import { TurnReportModal } from "../components/TurnReportModal";
import { normalizeApiResponse } from "../contracts/analysis";
import { createUuid } from "../utils/createUuid";
import { reportTitleForAnalysis } from "../utils/presentation";
import { attachAgentResults, mlPredictionRun, ragRun } from "./agentResponseMappers";
import { analysisError, clarifiedQuestion, commandClarificationMessage, commandClarificationType, commandErrorRun, hasReusablePresentationArtifact, hydrateTurnsFromServer, presentationViewType, scopeNoticeRun, transientRun } from "./agentPageHelpers";

const REPORT_ARTIFACT_VIEW = Object.freeze({
  SUMMARY: "summary",
  KPI: "kpi",
  TABLE: "table",
  CHART: "chart",
  BAR: "chart",
  LINE: "chart",
  AREA: "chart",
  HORIZONTAL_BAR: "chart",
  PIE: "chart",
  DONUT: "chart",
});

const MAX_QUESTION_LENGTH = 1000;
const QUESTION_DRAFT_KEY = "answervice.questionDraft";
const CONVERSATION_KEY = "answervice.activeConversationId";

/** 대화형 분석 워크스페이스를 렌더링하고 Report 작업은 서버 Capability가 있을 때만 노출한다. */
export function AgentPage({ canDraftReport = false, enabledFeatures = [], onNavigate }) {
  const analysisClient = useMemo(() => createAnalysisClient(fetch), []);
  const reportClient = useMemo(() => createReportClient(undefined, fetch), []);
  const [question, setQuestion] = useState(() => window.sessionStorage.getItem(QUESTION_DRAFT_KEY) || "");
  const [inputError, setInputError] = useState("");
  const [conversationId, setConversationId] = useState(() => window.sessionStorage.getItem(CONVERSATION_KEY) || "");
  const [turns, setTurns] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [selectedEvidenceRun, setSelectedEvidenceRun] = useState(null);
  const [reportModal, setReportModal] = useState("");
  const [reportModalRun, setReportModalRun] = useState(null);
  const [reportModalViewType, setReportModalViewType] = useState("SUMMARY");
  const [reportTitle, setReportTitle] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [savedBusy, setSavedBusy] = useState(false);
  const [definitions, setDefinitions] = useState([]);
  const [definitionQuery, setDefinitionQuery] = useState("");
  const [visibleDefinitionCount, setVisibleDefinitionCount] = useState(10);
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

  const visibleDefinitions = filteredDefinitions.slice(0, visibleDefinitionCount);
  const latestArtifactTurn = useMemo(
    () => [...turns].reverse().find((turn) => turn.run?.artifact) || null,
    [turns],
  );
  const internalGuidelineEnabled = enabledFeatures.includes(SERVICE_FEATURE.internalGuideline);
  const mlPredictionEnabled = enabledFeatures.includes(SERVICE_FEATURE.mlPrediction);
  const availableChatCapabilities = useMemo(() => [
    "호텔 운영 데이터 분석",
    internalGuidelineEnabled ? "승인된 내부 업무지침 확인" : null,
    mlPredictionEnabled ? "객실 수요 예측" : null,
    canDraftReport ? "분석 결과의 보고서 작업" : null,
  ].filter(Boolean), [canDraftReport, internalGuidelineEnabled, mlPredictionEnabled]);
  const refreshSaved = async () => {
    const nextDefs = await analysisClient.listDefinitions();
    setDefinitions(nextDefs);
  };

  useEffect(() => {
    refreshSaved().catch((err) => setFeedback({ tone: "error", message: err instanceof Error ? err.message : "저장된 분석을 불러오지 못했습니다." }));

    const storedConvId = window.sessionStorage.getItem(CONVERSATION_KEY);
    if (storedConvId) {
      analysisClient.getConversationTurns(storedConvId)
        .then((serverTurns) => {
          if (Array.isArray(serverTurns) && serverTurns.length > 0) {
            setTurns(hydrateTurnsFromServer(serverTurns));
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
    setFeedback(null);
  };

  // action은 UI가 이미 아는 동작을 자연어로 바꾸지 않고 전달하는 typed 신호다(서버가 재검증).
  const analyzeQuestion = async (nextQuestion, action = null, sourceTurn = null) => {
    const normalized = nextQuestion.trim();
    if (!normalized) { setInputError("메시지를 입력해 주세요."); return; }
    if (requestInFlight.current) return;
    const resolvedAction = action;
    const isPresentationAction = resolvedAction?.requested_route === "PRESENTATION";
    const isInternalGuidelineAction = resolvedAction?.requested_route === "INTERNAL_GUIDELINE";
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
    setFeedback(null);
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
        : { ...transientRun(normalized, "running"), traceId, chatPending: true },
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
      const headTurnId = turns.length > 0 ? turns.at(-1)?.turnId : undefined;
      let cmdResponse;
      try {
        cmdResponse = await analysisClient.submitTurnCommand(activeConvId, {
          ...(resolvedAction || {}),
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
            ...(resolvedAction || {}),
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
      const responseType = data?.type || "ANALYSIS";
      const ragResponse = data?.rag_response || serverTurn?.resolved_slots?.rag;
      const mlPrediction = data?.ml_prediction || serverTurn?.resolved_slots?.ml_prediction;
      const supervisorComposition = data?.composition
        || serverTurn?.resolved_slots?.supervisor_composition;
      const isPresentation = serverTurn?.route === "PRESENTATION";
      const isReportAction = serverTurn?.route === "REPORT_ACTION";

      let finalRun;
      if (responseType === "OUT_OF_SCOPE" || serverTurn?.route === "OUT_OF_SCOPE") {
        finalRun = scopeNoticeRun(
          normalized,
          data?.message || serverTurn?.resolved_slots?.scope_rejection?.message,
        );
      } else if ((responseType === "INTERNAL_GUIDELINE" || serverTurn?.route === "INTERNAL_GUIDELINE") && ragResponse) {
        finalRun = ragRun(normalized, ragResponse);
      } else if ((responseType === "ML_PREDICTION" || serverTurn?.route === "ML_PREDICTION") && mlPrediction) {
        finalRun = mlPredictionRun(normalized, mlPrediction);
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
      } else if (["BLOCKED", "FAILED", "CANCELLED"].includes(data?.status)) {
        finalRun = commandErrorRun(
          normalized,
          data,
          isInternalGuidelineAction ? "INTERNAL_GUIDELINE" : "ANALYSIS",
        );
      } else if (isPresentation) {
        const sourceArtifactId = sourceRun?.artifact?.artifactId;
        const sourceQueryId = sourceRun?.artifact?.queryId;
        const responseArtifact = analysisRaw?.data?.artifact;
        const responseEvidence = analysisRaw?.data?.result?.evidence || analysisRaw?.data?.evidence;
        const turnEvidence = serverTurn?.evidence_json;
        const responseArtifactMatches = !responseArtifact || (
          responseArtifact.artifact_id === sourceArtifactId
          && responseArtifact.query_id === sourceQueryId
        );
        const responseEvidenceMatches = !responseEvidence || (
          responseEvidence.artifact_id === sourceArtifactId
          && responseEvidence.query_id === sourceQueryId
        );
        const turnEvidenceMatches = !turnEvidence || (
          (!turnEvidence.artifact_id || turnEvidence.artifact_id === sourceArtifactId)
          && (!turnEvidence.query_id || turnEvidence.query_id === sourceQueryId)
        );
        if (
          data?.status === "PARTIAL"
          || !hasReusablePresentationArtifact(sourceRun)
          || !serverTurn?.artifact_id
          || sourceArtifactId !== serverTurn.artifact_id
          || !sourceQueryId
          || serverTurn?.query_id !== sourceQueryId
          || !responseArtifactMatches
          || !responseEvidenceMatches
          || !turnEvidenceMatches
          || !serverTurn?.view_spec_id
          || serverTurn.view_spec_id === sourceTurn?.viewSpecId
        ) {
          finalRun = commandErrorRun(normalized, {
            code: "INSUFFICIENT_EVIDENCE",
            message: "기존 분석 결과의 연결 정보를 확인할 수 없어 보기를 추가하지 않았습니다.",
            retryable: false,
            required_action: "NONE",
          });
        } else {
          finalRun = {
            ...sourceRun,
            question: normalized,
            status: "success",
            viewSpecId: serverTurn?.view_spec_id,
          };
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
        if (responseType === "COMPOSITE") {
          finalRun = attachAgentResults(finalRun, normalized, {
            ragResult: ragResponse,
            mlPrediction,
            supervisorComposition,
          });
        }
      } else if (responseType === "COMPOSITE" && (ragResponse || mlPrediction)) {
        const primaryRun = ragResponse
          ? ragRun(normalized, ragResponse)
          : mlPredictionRun(normalized, mlPrediction);
        finalRun = attachAgentResults(primaryRun, normalized, {
          ragResult: ragResponse,
          mlPrediction,
          supervisorComposition,
        });
      } else if (data?.status === "PARTIAL") {
        finalRun = commandErrorRun(
          normalized,
          data,
          isInternalGuidelineAction ? "INTERNAL_GUIDELINE" : "ANALYSIS",
        );
      } else if (isReportAction) {
        finalRun = {
          ...transientRun(normalized, "success"),
          summary: "분석 결과를 보고서 초안에 담았습니다.",
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
        viewType: responseType === "OUT_OF_SCOPE" || serverTurn?.route === "OUT_OF_SCOPE"
          ? "CHAT"
          : isPresentation
          ? presentationViewType(serverTurn)
          : (serverTurn?.resolved_slots?.target_chart_type || "SUMMARY"),
        isArtifactReuse: isPresentation && hasReusablePresentationArtifact(finalRun),
        reusePending: false,
        viewSpecId: isPresentation ? serverTurn?.view_spec_id : null,
        processViewModel: null,
      } : t));

      void refreshSaved();
    } catch (error) {
      if (requestGeneration.current !== generation) return;
      setTurns((prev) => prev.map((t) => t.turnId === optimisticTurn.turnId ? {
        ...t,
        isArtifactReuse: false,
        reusePending: false,
        processViewModel: null,
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
            service_context: isInternalGuidelineAction ? "INTERNAL_GUIDELINE" : "ANALYSIS",
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

  const saveAnalysis = async (targetRun) => {
    if (!["success", "partial"].includes(targetRun.status) || !targetRun.requestId || savedBusy) return;
    setSavedBusy(true);
    setFeedback(null);
    try {
      await analysisClient.createDefinition(targetRun.question, targetRun.requestId);
      setFeedback({ tone: "success", message: "현재 분석을 저장했습니다." });
      await refreshSaved();
    } catch (error) { setFeedback({ tone: "error", message: error instanceof Error ? error.message : "분석을 저장하지 못했습니다." }); }
    finally { setSavedBusy(false); }
  };

  const replaySavedDefinition = async (definition) => {
    if (requestInFlight.current || savedBusy) return;
    requestInFlight.current = true;
    setSavedBusy(true);
    setSubmitting(true);
    setEvidenceOpen(false);
    setSelectedEvidenceRun(null);
    setFeedback({ tone: "info", message: "저장 분석을 현재 권한과 릴리스에서 다시 실행하고 있습니다." });
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
      setFeedback({ tone: "success", message: "저장 분석을 새 실행으로 완료했습니다." });
      await refreshSaved();
    } catch (error) {
      setFeedback({
        tone: "error",
        message: error instanceof AnalysisApiError && error.status === 409
          ? "이 저장 분석은 현재 데이터 릴리스와 맞지 않아 재실행할 수 없습니다. 같은 조건을 새 질문으로 분석해 주세요."
          : error instanceof Error ? error.message : "저장 분석을 다시 실행하지 못했습니다.",
      });
    } finally {
      requestInFlight.current = false;
      setSavedBusy(false);
      setSubmitting(false);
      scrollToLatestTurn();
    }
  };

  const createReportDraft = async () => {
    if (!canDraftReport) return;
    const artId = reportModalRun?.artifact?.artifactId || reportModalRun?.artifact?.artifact_id;
    if (!artId) return;
    setFeedback(null);
    try {
      await reportClient.createDraftFromArtifact(
        artId,
        reportTitle.trim() || reportTitleForAnalysis(reportModalRun),
        REPORT_ARTIFACT_VIEW[String(reportModalViewType).toUpperCase()],
      );
      setReportModal("");
      onNavigate("/reports");
    } catch (error) { setFeedback({ tone: "error", message: error instanceof Error ? error.message : "보고서 초안을 저장하지 못했습니다." }); }
  };

  const copyEvidence = async (value) => {
    try {
      await navigator.clipboard.writeText(String(value ?? ""));
      setFeedback({ tone: "success", message: "식별 정보를 복사했습니다." });
    } catch {
      setFeedback({ tone: "error", message: "식별 정보를 복사하지 못했습니다." });
    }
  };

  return (
    <div className={`chat-layout ${evidenceOpen ? "evidence-open" : ""}`}>
      {/* 좌측: 저장된 분석 및 대화방 */}
      <aside className="chat-history" inert={Boolean(reportModal)}>
        <button className="new-chat" onClick={handleNewChat}><Plus size={16} />새 대화</button>
        <p>저장된 분석</p>
        <label className="saved-analysis-search">
          <span className="sr-only">저장된 분석 검색</span>
          <input value={definitionQuery} onChange={(e) => { setDefinitionQuery(e.target.value); setVisibleDefinitionCount(10); }} placeholder="저장 분석 검색" />
        </label>
        {visibleDefinitions.length === 0 && <small className="chat-history-empty">아직 저장된 분석이 없습니다.</small>}
        {visibleDefinitions.map((d) => (
          <button disabled={savedBusy} title={d.question} onClick={() => void replaySavedDefinition(d)} key={d.definition_id}>
            <MessageSquareText size={15} /><span>{d.question}<small>다시 분석하기</small></span>
          </button>
        ))}
        {filteredDefinitions.length > visibleDefinitionCount && (
          <button type="button" className="saved-analysis-more" onClick={() => setVisibleDefinitionCount((c) => c + 10)}>더 보기</button>
        )}
      </aside>

      {/* 중앙: 대화 스레드 메인 */}
      <main className="chat-main" inert={Boolean(reportModal)}>
        <div className="chat-scroll-region">
        {turns.length === 0 && !submitting && (
          <section className="chat-empty-state" aria-labelledby="chat-empty-title">
            <small>ANSWERVICE AI</small>
            <h2 id="chat-empty-title">무엇을 도와드릴까요?</h2>
            <p>{availableChatCapabilities.join(", ")}을 한 대화에서 이어서 요청할 수 있습니다.</p>
            <AgentCapabilityOverview
              ragEnabled={internalGuidelineEnabled}
              mlEnabled={mlPredictionEnabled}
            />
          </section>
        )}

        {turns.length > 0 && (
          <div className="conversation">
            {turns.map((turnItem, idx) => (
              <div key={turnItem.turnId || idx} className="conversation-turn-group">
                <div className="message message--user" aria-label="사용자 메시지">
                  <div className="turn-user-bubble">
                    <div className="user-content">
                      <p className="user-text">{turnItem.question}</p>
                    </div>
                  </div>
                  <span className="user-icon" aria-hidden="true">나</span>
                </div>

                <div className="message message--agent" aria-label="AI 응답">
                  <span className="agent-avatar"><Sparkles size={16} /></span>
                  <div className="agent-response-container">
                    {!turnItem.run.scopeNotice && !(turnItem.run.chatPending && !turnItem.processViewModel) && (
                      <AgentExecutionBar run={turnItem.run} processViewModel={turnItem.processViewModel} />
                    )}
                    {turnItem.run.scopeNotice ? (
                      <div className="scope-notice-response" role="status">
                        <small>지원 범위 안내</small>
                        <p>{turnItem.run.scopeNotice.message}</p>
                      </div>
                    ) : turnItem.run.rag && !turnItem.run.evidence ? (
                      <>
                        <RagAnswerCard
                          rag={turnItem.run.rag}
                          pdfSources={(turnItem.run.rag.evidence_bundle || []).map((item) => ({
                            label: item.document_name || "근거 문서",
                            url: item.document_id ? analysisClient.manualSourceUrl(item.document_id) : "",
                          }))}
                          onFollowUp={turnItem.turnId === turns.at(-1)?.turnId
                            ? (followUp) => void analyzeQuestion(followUp, {
                                requested_route: "INTERNAL_GUIDELINE",
                                inherit_previous_context: true,
                              })
                            : undefined}
                        />
                        {turnItem.run.mlPrediction && (
                          <section className="composite-agent-result" aria-label="객실 수요 예측">
                            <div className="ml-conversation-result">
                              <MLPredictionResult result={turnItem.run.mlPrediction} />
                            </div>
                          </section>
                        )}
                      </>
                    ) : turnItem.run.mlPrediction && !turnItem.run.evidence ? (
                      <>
                        <div className="ml-conversation-result">
                          <MLPredictionResult result={turnItem.run.mlPrediction} />
                        </div>
                      </>
                    ) : turnItem.run.chatPending && !turnItem.processViewModel ? (
                      <div className="chat-pending-response" role="status" aria-live="polite">
                        <span aria-hidden="true"><i /><i /><i /></span>
                        <p>답변을 준비하고 있어요</p>
                      </div>
                    ) : turnItem.run.chatPending
                      && turnItem.processViewModel?.agentTasks?.length
                      && turnItem.processViewModel.steps.every((step) => step.state === "pending") ? null
                    : <AnalysisStatePanel
                      run={turnItem.run}
                      viewType={turnItem.viewType || turnItem.resolvedSlots?.target_chart_type || "SUMMARY"}
                      artifactReuse={turnItem.isArtifactReuse ? {
                        pending: Boolean(turnItem.reusePending),
                        viewSpecId: turnItem.viewSpecId,
                      } : null}
                      processViewModel={turnItem.processViewModel}
                      suggestionsDisabled={submitting}
                      onSuggestion={(sugg) => void analyzeQuestion(clarifiedQuestion(turnItem.question, sugg, turnItem.run.error?.clarification_type))}
                      onRetry={() => void analyzeQuestion(turnItem.question)}
                      onCancel={() => void handleCancelAnalysis(turnItem.turnId)}
                      onSave={["success", "partial"].includes(turnItem.run.status) && !turnItem.isArtifactReuse ? () => void saveAnalysis(turnItem.run) : undefined}
                      saveDisabled={savedBusy}
                      onCreateReportDraft={canDraftReport && turnItem.run.artifact && (turnItem.run.rowCount ?? 0) > 0 ? () => {
                        setReportModalRun(turnItem.run);
                        setReportModalViewType(turnItem.viewType || turnItem.resolvedSlots?.target_chart_type || "SUMMARY");
                        setReportTitle(reportTitleForAnalysis(turnItem.run));
                        setReportModal("draft");
                      } : undefined}
                      onOpenEvidence={turnItem.run.artifact ? () => {
                        setSelectedEvidenceRun(turnItem.run);
                        setEvidenceOpen(true);
                      } : undefined}
                    />}
                    {turnItem.run.rag && turnItem.run.evidence && (
                      <section className="composite-agent-result" aria-label="내부 문서 근거">
                        <header className="composite-agent-result__header">
                          <small>내부 문서</small>
                          <h3>운영 보고서 참고 내용</h3>
                          <p>분석 결과와 함께 확인할 내부 근거입니다.</p>
                        </header>
                        <RagAnswerCard
                          rag={turnItem.run.rag}
                          pdfSources={(turnItem.run.rag.evidence_bundle || []).map((item) => ({
                            label: item.document_name || "근거 문서",
                            url: item.document_id ? analysisClient.manualSourceUrl(item.document_id) : "",
                          }))}
                        />
                      </section>
                    )}
                    {turnItem.run.mlPrediction && turnItem.run.evidence && (
                      <section className="composite-agent-result" aria-label="객실 수요 예측">
                        <div className="ml-conversation-result">
                          <MLPredictionResult result={turnItem.run.mlPrediction} />
                        </div>
                      </section>
                    )}
                    {canDraftReport && turnItem.run.reportDefinitionId && (
                      <div className="report-action-direct-nav" style={{ marginTop: "8px", display: "flex", justifyContent: "flex-end" }}>
                        <button
                          type="button"
                          className="unified-action-btn unified-action-btn--primary"
                          onClick={() => onNavigate?.("/reports")}
                          title="생성된 보고서 초안으로 이동"
                        >
                          <FilePlus2 size={13} />
                          <span>보고서에서 확인하기</span>
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

        {feedback?.message && <p className={`analysis-notice analysis-notice--${feedback.tone}`} role={feedback.tone === "error" ? "alert" : "status"}>
          {feedback.tone === "error" ? <AlertTriangle size={16} aria-hidden="true" /> : feedback.tone === "success" ? <CheckCircle2 size={16} aria-hidden="true" /> : <Info size={16} aria-hidden="true" />}
          <span>{feedback.message}</span>
        </p>}

        </div>

        {/* 대화 결과를 덮지 않는 중앙 하단 입력 영역 */}
        <form className="chat-input" onSubmit={submitQuestion}>
          <div className="question-field">
            <input
              aria-label="메시지"
              name="question"
              value={question}
              maxLength={MAX_QUESTION_LENGTH}
              onChange={(e) => { setQuestion(e.target.value); setInputError(""); }}
              placeholder="메시지를 입력하세요"
              aria-invalid={Boolean(inputError)}
              disabled={submitting}
              required
            />
            <button aria-label="메시지 전송" disabled={submitting || !question.trim()}><Send size={16} /></button>
          </div>
          {inputError && <p className="analysis-input-error" role="alert">{inputError}</p>}
        </form>
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
      {canDraftReport && <TurnReportModal
        mode={reportModal}
        run={reportModalRun || activeEvidenceRun}
        viewType={reportModalViewType}
        title={reportTitle}
        onTitleChange={setReportTitle}
        onConfirm={() => void createReportDraft()}
        onPreviewMode={() => { setReportTitle(reportTitleForAnalysis(reportModalRun || activeEvidenceRun)); setReportModal("draft"); }}
        onClose={() => setReportModal("")}
        isSubmitting={false}
      />}
    </div>
  );
}
