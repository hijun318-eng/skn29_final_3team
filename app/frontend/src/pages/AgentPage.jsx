/** 대화형 분석 워크스페이스의 세션·멀티턴 상태·증적 서랍·보고서 연계를 통합 관리하는 모듈이다. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Eye, FilePlus2, History, MessageSquareText, Plus, Save, Send, Sparkles, TableProperties } from "lucide-react";
import { AnalysisApiError, createAnalysisClient } from "../api/analysisClient";
import { createReportClient } from "../api/reportClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MetaStrip } from "../components/common/EnterpriseUi";
import { TurnEvidenceDrawer } from "../components/TurnEvidenceDrawer";
import { TurnReportModal } from "../components/TurnReportModal";
import { normalizeApiResponse } from "../contracts/analysis";
import { createUuid } from "../utils/createUuid";
import { reportTitleForAnalysis } from "../utils/presentation";
import { analysisError, clarifiedQuestion, exampleQuestionsFromDefinitions, formatSeoulDateTime, hydrateTurnsFromServer, quickViewAction, savedRunStatus, transientRun } from "./agentPageHelpers";

const RUN_HISTORY_PAGE_SIZE = 20;
const MAX_QUESTION_LENGTH = 1000;
const QUESTION_DRAFT_KEY = "answervice.questionDraft";
const CONVERSATION_KEY = "answervice.activeConversationId";

/** 대화형 분석 워크스페이스 최상위 화면을 렌더링한다. */
export function AgentPage({ onNavigate }) {
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
  const [reportTitle, setReportTitle] = useState("");
  const [message, setMessage] = useState("");
  const [savedBusy, setSavedBusy] = useState(false);
  const [definitions, setDefinitions] = useState([]);
  const [definitionQuery, setDefinitionQuery] = useState("");
  const [visibleDefinitionCount, setVisibleDefinitionCount] = useState(10);
  const [savedRuns, setSavedRuns] = useState([]);
  const [visibleRunCount, setVisibleRunCount] = useState(RUN_HISTORY_PAGE_SIZE);
  const requestInFlight = useRef(false);
  const activeTraceId = useRef("");
  const threadEndRef = useRef(null);

  const activeEvidenceRun = selectedEvidenceRun || turns.at(-1)?.run || transientRun("");

  const filteredDefinitions = useMemo(() => {
    const normalized = definitionQuery.trim().toLocaleLowerCase("ko-KR");
    return definitions.filter((d) => !normalized || `${d.title} ${d.question}`.toLocaleLowerCase("ko-KR").includes(normalized));
  }, [definitionQuery, definitions]);

  const exampleQuestions = useMemo(() => exampleQuestionsFromDefinitions(definitions), [definitions]);
  const visibleDefinitions = filteredDefinitions.slice(0, visibleDefinitionCount);
  const visibleRuns = savedRuns.slice(0, visibleRunCount);

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
    if (activeTraceId.current) {
      try {
        await analysisClient.cancelAnalysis(activeTraceId.current);
      } catch (err) {
        console.warn("Cancel analysis error:", err);
      }
    }
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
  };

  useEffect(() => {
    if (question) window.sessionStorage.setItem(QUESTION_DRAFT_KEY, question);
    else window.sessionStorage.removeItem(QUESTION_DRAFT_KEY);
  }, [question]);

  const initConversation = async () => {
    try {
      const conv = await analysisClient.createConversation();
      const nextId = conv.conversation_id;
      setConversationId(nextId);
      window.sessionStorage.setItem(CONVERSATION_KEY, nextId);
      setTurns([]);
      return nextId;
    } catch {
      return conversationId;
    }
  };

  const handleNewChat = () => {
    setQuestion("");
    setInputError("");
    setTurns([]);
    void initConversation();
  };

  // action은 UI가 이미 아는 동작을 자연어로 바꾸지 않고 전달하는 typed 신호다(서버가 재검증).
  const analyzeQuestion = async (nextQuestion, action = null) => {
    const normalized = nextQuestion.trim();
    if (!normalized) { setInputError("분석할 질문을 입력해 주세요."); return; }
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    setInputError("");
    setQuestion("");
    setSubmitting(true);
    setMessage("");
    const traceId = createUuid();
    activeTraceId.current = traceId;

    let activeConvId = conversationId || await initConversation();
    const optimisticTurn = {
      turnId: `temp-${Date.now()}`,
      question: normalized,
      run: { ...transientRun(normalized, "running"), traceId },
      resolvedSlots: null,
      viewType: null,
    };
    setTurns((prev) => [...prev, optimisticTurn]);
    window.requestAnimationFrame(() => threadEndRef.current?.scrollIntoView({ behavior: "smooth" }));

    try {
      const headTurnId = turns.length > 0 ? turns.at(-1)?.turnId : undefined;
      let cmdResponse;
      try {
        cmdResponse = await analysisClient.submitTurnCommand(activeConvId, {
          user_message: normalized,
          expected_head_turn_id: headTurnId && !headTurnId.startsWith("temp-") ? headTurnId : undefined,
          ...(action || {}),
        });
      } catch (cmdErr) {
        if (cmdErr instanceof AnalysisApiError && cmdErr.status === 409) {
          // 409 CAS Conflict: 대화방을 리셋하지 않고 서버의 최신 턴 목록을 다시 불러와 동기화 후 재시도
          try {
            const serverTurns = await analysisClient.getConversationTurns(activeConvId);
            const latestServerTurn = serverTurns.at(-1);
            const newHeadId = latestServerTurn?.turn_id;
            cmdResponse = await analysisClient.submitTurnCommand(activeConvId, {
              user_message: normalized,
              expected_head_turn_id: newHeadId,
              ...(action || {}),
            });
          } catch (retryErr) {
            throw retryErr;
          }
        } else if (cmdErr instanceof AnalysisApiError && cmdErr.status === 404) {
          activeConvId = await initConversation();
          cmdResponse = await analysisClient.submitTurnCommand(activeConvId, {
            user_message: normalized,
            ...(action || {}),
          });
        } else {
          throw cmdErr;
        }
      }

      const data = cmdResponse?.data || cmdResponse;
      const serverTurn = data?.turn;
      const analysisRaw = data?.analysis_response;
      const isPresentation = serverTurn?.route === "PRESENTATION";
      const isReportAction = serverTurn?.route === "REPORT_ACTION";

      let finalRun;
      if (analysisRaw && analysisRaw.data) {
        finalRun = normalizeApiResponse(analysisRaw, normalized);
      } else if (data?.status === "CLARIFICATION_REQUIRED" || serverTurn?.resolved_slots?.ambiguity_status === "NEEDS_CLARIFICATION") {
        const options = data?.disambiguation_options || serverTurn?.resolved_slots?.disambiguation_options || [];
        const clarType = serverTurn?.resolved_slots?.clarification_type || "metric";
        finalRun = {
          ...transientRun(normalized, "blocked"),
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
      } else if (isPresentation) {
        finalRun = {
          ...(turns.at(-1)?.run || {}),
          question: normalized,
          status: "success",
          summary: `Trino 원천 쿼리 재실행 없이 ${serverTurn?.view_type || "TABLE"} 뷰로 전환했습니다.`,
          viewSpecId: serverTurn?.view_spec_id,
        };
      } else if (isReportAction) {
        finalRun = {
          ...transientRun(normalized, "success"),
          summary: `분석 대화 결과가 공식 보고서 초안(Draft)으로 결합되었습니다. (/reports에서 확인 가능)`,
          reportDefinitionId: serverTurn?.report_definition_id,
        };
      } else {
        finalRun = {
          ...transientRun(normalized, "failed"),
          error: {
            code: "NO_MATCH",
            message: "질문과 일치하는 분석 결과를 생성하지 못했습니다.",
            retryable: true,
            required_action: "PROVIDE_CONTEXT",
          },
        };
      }

      setTurns((prev) => prev.map((t) => t.turnId === optimisticTurn.turnId ? {
        turnId: serverTurn?.turn_id || optimisticTurn.turnId,
        question: normalized,
        run: finalRun,
        resolvedSlots: serverTurn?.resolved_slots || null,
        viewType: serverTurn?.view_type || serverTurn?.resolved_slots?.target_chart_type || (isPresentation ? "CHART" : "SUMMARY"),
      } : t));

      void refreshSaved();
    } catch (error) {
      setTurns((prev) => prev.map((t) => t.turnId === optimisticTurn.turnId ? {
        ...t,
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
      if (activeTraceId.current === traceId) activeTraceId.current = "";
      requestInFlight.current = false;
      setSubmitting(false);
      window.requestAnimationFrame(() => threadEndRef.current?.scrollIntoView({ behavior: "smooth" }));
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
    setMessage("");
    try {
      await analysisClient.createDefinition(targetRun.question, targetRun.requestId);
      setMessage("현재 분석을 저장했습니다.");
      await refreshSaved();
    } catch (error) { setMessage(error instanceof Error ? error.message : "분석을 저장하지 못했습니다."); }
    finally { setSavedBusy(false); }
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
          <button disabled={savedBusy} title={d.question} onClick={() => void analyzeQuestion(d.question)} key={d.definition_id}>
            <MessageSquareText size={15} /><span>{d.title}<small>다시 분석하기</small></span>
          </button>
        ))}
        {filteredDefinitions.length > visibleDefinitionCount && (
          <button type="button" className="saved-analysis-more" onClick={() => setVisibleDefinitionCount((c) => c + 10)}>더 보기</button>
        )}
      </aside>

      {/* 중앙: 대화 스레드 메인 */}
      <main className="chat-main" inert={Boolean(reportModal)}>
        {activeEvidenceRun.meta?.asOf && <MetaStrip meta={activeEvidenceRun.meta} verified={Boolean(activeEvidenceRun.artifact && ["success", "partial"].includes(activeEvidenceRun.status))} />}
        
        {turns.length === 0 && !submitting && (
          <section className="chat-empty-state" aria-labelledby="chat-empty-title">
            <small>대화형 데이터 분석</small>
            <h2 id="chat-empty-title">무엇을 분석할까요?</h2>
            <p>호텔 운영 매출, 고객 VOC 리뷰, 연회 취소 행사 등 다양한 지표와 기간을 자연어로 분석해 보세요.</p>
            {exampleQuestions.length > 0 && (
              <div aria-label="분석 질문 예시">
                {exampleQuestions.map((ex) => <button key={ex.id} type="button" onClick={() => { void analyzeQuestion(ex.question); }}>{ex.question}</button>)}
              </div>
            )}
          </section>
        )}

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

                    <AnalysisStatePanel
                      run={turnItem.run}
                      viewType={turnItem.viewType || turnItem.resolvedSlots?.target_chart_type || "SUMMARY"}
                      suggestionsDisabled={submitting}
                      onSuggestion={(sugg) => void analyzeQuestion(clarifiedQuestion(turnItem.question, sugg, turnItem.run.error?.clarification_type))}
                      onQuickView={(mode) => {
                        const quick = quickViewAction(mode, {
                          hasChart: Boolean(turnItem.run.chart),
                          hasTable: Boolean(turnItem.run.table?.rows?.length),
                        });
                        // 이미 응답에 포함된 차트·표 data는 재조회 없이 뷰만 전환한다.
                        if (quick) void analyzeQuestion(quick.label, quick.action);
                        else setTurns((prev) => prev.map((t) => t.turnId === turnItem.turnId ? { ...t, viewType: mode } : t));
                      }}
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
            <div ref={threadEndRef} />
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
              placeholder="분석할 지표와 기간을 자연어로 입력하세요"
              aria-describedby="question-help"
              aria-invalid={Boolean(inputError)}
              disabled={submitting}
              required
            />
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
                    <small>{item.period_start && item.period_end_exclusive ? `${item.period_start} ~ ${item.period_end_exclusive} 미포함` : "기간 없음"}</small>
                  </span>
                  {item.artifact_id && (
                    <button type="button" disabled={savedBusy} onClick={() => void analyzeQuestion(item.question)}>
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
        onClose={() => setEvidenceOpen(false)}
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
