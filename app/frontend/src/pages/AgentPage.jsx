import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Eye, FilePlus2, History, MessageSquareText, Plus, Save, Send, Sparkles, TableProperties, X } from "lucide-react";
import { AnalysisApiError, createAnalysisClient } from "../api/analysisClient";
import { createReportClient } from "../api/reportClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MetaStrip, SectionTitle } from "../components/common/EnterpriseUi";
import { OPENAPI_VERSION } from "../contracts/analysis";
import { createUuid } from "../utils/createUuid";
import { reportTitleForAnalysis } from "../utils/presentation";

const ARTIFACT_TABS = [["report", "보고서"], ["sources", "데이터 출처"], ["run", "실행 정보"]];
const RUN_HISTORY_PAGE_SIZE = 20;
const MAX_QUESTION_LENGTH = 1000;
const QUESTION_DRAFT_KEY = "answervice.questionDraft";
const APPROVED_QUESTIONS = [
  "2026년 6월 GOLD 고객의 인식 객실 매출을 월별로 보여줘.",
  "2026년 5월과 6월 GOLD 고객의 객실·식음 통합 매출을 비교해 줘.",
  "이번 달 식음 순매출을 일별로 분석해 줘.",
];

function transientRun(question, status = "idle") {
  return {
    requestId: "", traceId: "", status, question,
    metrics: [], sources: [],
    meta: { asOf: "", timezone: "Asia/Seoul", seed: "", schemaVersion: "", contractVersion: OPENAPI_VERSION },
  };
}

function resolvedPeriodParameters(run) {
  const period = run.evidence?.period;
  return period ? {
    period_start: period.start,
    period_end_exclusive: period.endExclusive,
  } : null;
}

function clarifiedQuestion(question, suggestion, clarificationType) {
  const label = clarificationType === "period" ? "기간" : "지표";
  return `${question.trim()} (선택한 ${label}: ${suggestion})`;
}

function savedRunStatus(status) {
  return ({ SUCCESS: "완료", SUCCEEDED: "완료", PARTIAL: "일부 완료", BLOCKED: "완료되지 않음", FAILED: "실패", RECEIVED: "처리 중", QUEUED: "대기 중", RUNNING: "처리 중", CANCELLED: "취소됨" })[status] || "확인 필요";
}

function analysisError(error) {
  if (error instanceof AnalysisApiError) return error.message;
  if (error instanceof TypeError) return "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.";
  return error instanceof Error ? error.message : "분석 요청에 실패했습니다.";
}

function formatSeoulDateTime(value) {
  if (!value) return "시각 정보 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

function evidenceValue(value) {
  return value === true ? "적용" : value === false ? "미적용" : String(value ?? "없음");
}

function publicFilterSummary(filters = {}) {
  const labels = {
    property_id: "호텔", membership_grade_code: "고객 등급", grade_code: "고객 등급",
    room_type_code: "객실 유형", stay_status: "투숙 상태",
  };
  const hiddenPolicyKeys = new Set(["void_flag", "is_forecast", "house_use_flag", "complimentary_flag"]);
  const visible = Object.entries(filters).flatMap(([field, value]) => {
    const key = field.split(".").at(-1);
    if (hiddenPolicyKeys.has(key)) return [];
    return [`${labels[key] || "추가 조건"}: ${String(value ?? "없음")}`];
  });
  if (Object.keys(filters).some((field) => hiddenPolicyKeys.has(field.split(".").at(-1)))) visible.push("기본 제외 정책 적용");
  return visible.length ? [...new Set(visible)].join(" · ") : "추가 필터 없음";
}

function gateEvidence(run) {
  const history = run.evidence?.gateHistory;
  const final = run.evidence?.gates;
  if (!history && !final) return "없음";
  return ["g1", "g2", "g3"].map((gate) => {
    const outcomes = history?.[gate]?.length ? history[gate] : [final?.[gate]];
    return `${gate.toUpperCase()} ${outcomes.filter(Boolean).join(" → ")}`;
  }).join(" · ");
}

function reportTitleForRun(run) {
  return reportTitleForAnalysis(run);
}

export function AgentPage({ onNavigate }) {
  const analysisClient = useMemo(() => createAnalysisClient(fetch), []);
  const reportClient = useMemo(() => createReportClient(undefined, fetch), []);
  const [question, setQuestion] = useState(() => window.sessionStorage.getItem(QUESTION_DRAFT_KEY) || "");
  const [inputError, setInputError] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [submittedParameters, setSubmittedParameters] = useState(null);
  const [run, setRun] = useState(() => transientRun(""));
  const [submitting, setSubmitting] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [artifactTab, setArtifactTab] = useState("report");
  const [reportModal, setReportModal] = useState("");
  const [reportTitle, setReportTitle] = useState("");
  const [message, setMessage] = useState("");
  const [savedBusy, setSavedBusy] = useState(false);
  const [definitions, setDefinitions] = useState([]);
  const [definitionQuery, setDefinitionQuery] = useState("");
  const [visibleDefinitionCount, setVisibleDefinitionCount] = useState(10);
  const [savedRuns, setSavedRuns] = useState([]);
  const [visibleRunCount, setVisibleRunCount] = useState(RUN_HISTORY_PAGE_SIZE);
  const [cancelRequested, setCancelRequested] = useState(false);
  const requestInFlight = useRef(false);
  const activeTraceId = useRef("");
  const reportModalRef = useRef(null);
  const reportModalReturnFocusRef = useRef(null);
  const evidenceReturnFocusRef = useRef(null);
  const hasSubmitted = Boolean(submittedQuestion);
  const filteredDefinitions = useMemo(() => {
    const normalized = definitionQuery.trim().toLocaleLowerCase("ko-KR");
    return definitions.filter((definition) => !normalized || `${definition.title} ${definition.question}`.toLocaleLowerCase("ko-KR").includes(normalized));
  }, [definitionQuery, definitions]);
  const visibleDefinitions = filteredDefinitions.slice(0, visibleDefinitionCount);
  const visibleRuns = savedRuns.slice(0, visibleRunCount);

  const refreshSaved = async () => {
    const [nextDefinitions, nextRuns] = await Promise.all([analysisClient.listDefinitions(), analysisClient.listRuns()]);
    setDefinitions(nextDefinitions);
    setSavedRuns(nextRuns);
  };

  useEffect(() => { refreshSaved().catch((error) => setMessage(error instanceof Error ? error.message : "저장된 분석을 불러오지 못했습니다.")); }, []);

  useEffect(() => {
    if (question) window.sessionStorage.setItem(QUESTION_DRAFT_KEY, question);
    else window.sessionStorage.removeItem(QUESTION_DRAFT_KEY);
  }, [question]);

  useEffect(() => {
    const clearDraft = () => window.sessionStorage.removeItem(QUESTION_DRAFT_KEY);
    window.addEventListener("answervice:clear-drafts", clearDraft);
    return () => window.removeEventListener("answervice:clear-drafts", clearDraft);
  }, []);

  useEffect(() => {
    if (!reportModal) return undefined;
    const modal = reportModalRef.current;
    const previousFocus = reportModalReturnFocusRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusableSelector = "input:not([disabled]), button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])";
    const focusFrame = window.requestAnimationFrame(() => {
      (modal?.querySelector("input:not([disabled])") || modal?.querySelector(focusableSelector))?.focus();
    });
    const handleModalKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setReportModal("");
        return;
      }
      if (event.key !== "Tab" || !modal) return;
      const focusable = [...modal.querySelectorAll(focusableSelector)];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleModalKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleModalKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus?.();
    };
  }, [reportModal]);

  useEffect(() => {
    if (!evidenceOpen) return undefined;
    const close = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setEvidenceOpen(false);
      window.requestAnimationFrame(() => evidenceReturnFocusRef.current?.focus?.());
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [evidenceOpen]);

  const closeEvidence = () => {
    setEvidenceOpen(false);
    window.requestAnimationFrame(() => evidenceReturnFocusRef.current?.focus?.());
  };

  const analyzeQuestion = async (nextQuestion) => {
    const normalizedQuestion = nextQuestion.trim();
    if (!normalizedQuestion) {
      setInputError("분석할 질문을 입력해 주세요.");
      return;
    }
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    setInputError("");
    setQuestion(normalizedQuestion);
    setSubmitting(true);
    setMessage("");
    setEvidenceOpen(false);
    setSubmittedQuestion(normalizedQuestion);
    setSubmittedParameters(null);
    setCancelRequested(false);
    const traceId = createUuid();
    activeTraceId.current = traceId;
    setRun({ ...transientRun(normalizedQuestion, "queued"), traceId });
    try {
      const result = await analysisClient.analyze(normalizedQuestion, {}, {
        traceId,
        onProgress: (progress) => {
          if (activeTraceId.current !== traceId) return;
          setCancelRequested(progress.cancel_requested);
          setRun((current) => ({
            ...current,
            requestId: progress.request_id,
            traceId: progress.trace_id,
            status: progress.status === "RECEIVED" ? "queued" : "running",
            elapsedSeconds: progress.elapsed_seconds,
            trace: progress.trace.map(({ stage, outcome, detail }) => ({ stage, outcome, detail })),
          }));
        },
      });
      setSubmittedParameters(["success", "partial"].includes(result.status) && result.evidenceReady ? resolvedPeriodParameters(result) : null);
      setRun((current) => ({ ...result, elapsedSeconds: current.elapsedSeconds }));
    } catch (error) {
      setRun({
        ...transientRun(normalizedQuestion, error instanceof AnalysisApiError && error.status === 403 ? "blocked" : "failed"),
        error: {
          code: error instanceof AnalysisApiError ? error.code : "NETWORK_UNAVAILABLE",
          message: analysisError(error),
          retryable: error instanceof AnalysisApiError ? error.retryable : true,
          required_action: error instanceof AnalysisApiError ? error.requiredAction : "RETRY",
          suggestions: error instanceof AnalysisApiError ? error.suggestions : [],
          missing_requirements: error instanceof AnalysisApiError ? error.missingRequirements : [],
          trace_id: error instanceof AnalysisApiError ? error.traceId : traceId,
        },
      });
    } finally {
      if (activeTraceId.current === traceId) activeTraceId.current = "";
      requestInFlight.current = false;
      setSubmitting(false);
      setCancelRequested(false);
    }
  };

  const cancelAnalysis = async () => {
    const traceId = activeTraceId.current;
    if (!traceId || cancelRequested) return;
    setCancelRequested(true);
    try {
      const progress = await analysisClient.cancelAnalysis(traceId);
      setRun((current) => ({ ...current, elapsedSeconds: progress.elapsed_seconds }));
    } catch (error) {
      setCancelRequested(false);
      setMessage(error instanceof Error ? error.message : "분석 취소 요청을 전달하지 못했습니다.");
    }
  };

  const submitQuestion = (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void analyzeQuestion(String(form.get("question") || question).trim());
  };

  const saveAnalysis = async () => {
    if (!["success", "partial"].includes(run.status) || !run.requestId || savedBusy) return;
    setSavedBusy(true);
    setMessage("");
    try {
      await analysisClient.createDefinition(submittedQuestion, run.requestId);
      setMessage("현재 분석을 저장했습니다.");
      await refreshSaved();
    } catch (error) { setMessage(error instanceof Error ? error.message : "분석을 저장하지 못했습니다."); }
    finally { setSavedBusy(false); }
  };

  const replay = async (definitionId) => {
    if (savedBusy) return;
    setSavedBusy(true);
    setMessage("");
    setEvidenceOpen(false);
    const definition = definitions.find((item) => item.definition_id === definitionId);
    const replayQuestion = definition?.question || definition?.title || "저장된 분석";
    setSubmittedQuestion(replayQuestion);
    setSubmittedParameters(null);
    setRun(transientRun(replayQuestion, "queued"));
    try {
      const result = await analysisClient.replayDefinition(definitionId, {});
      setMessage(result.status === "SUCCEEDED" ? "저장된 조건의 결과를 불러왔습니다." : "저장된 조건으로 분석했지만 결과를 완성하지 못했습니다.");
      if ((result.status === "SUCCEEDED" || result.status === "PARTIAL") && result.artifact_id) {
        const restored = await analysisClient.getRunArtifact(result.request_id);
        setSubmittedParameters(resolvedPeriodParameters(restored));
        setRun(restored);
      } else {
        const status = result.status === "BLOCKED" ? "blocked" : "failed";
        setRun({
          ...transientRun(replayQuestion, status),
          requestId: result.request_id,
          traceId: result.trace_id,
          error: {
            code: result.status === "BLOCKED" ? "SQL_POLICY_BLOCKED" : "INTERNAL_ERROR",
            message: result.error_type ? `재실행이 완료되지 않았습니다. (${result.error_type})` : "재실행이 완료되지 않았습니다.",
            retryable: result.status !== "BLOCKED",
            required_action: result.status !== "BLOCKED" ? "RETRY" : "MODIFY_REQUEST",
          },
        });
      }
      await refreshSaved();
    } catch (error) { setMessage(error instanceof Error ? error.message : "재실행에 실패했습니다."); }
    finally { setSavedBusy(false); }
  };

  const showSavedRun = async (savedRun) => {
    if (!savedRun.artifact_id || savedBusy) return;
    setSavedBusy(true);
    setMessage("");
    setEvidenceOpen(false);
    const historicalQuestion = savedRun.question || "저장된 분석 결과";
    setSubmittedQuestion(historicalQuestion);
    setSubmittedParameters(null);
    setRun(transientRun(historicalQuestion, "queued"));
    try {
      const restored = await analysisClient.getRunArtifact(savedRun.request_id);
      setSubmittedQuestion(restored.question);
      setSubmittedParameters(resolvedPeriodParameters(restored));
      setRun(restored);
      setMessage("이전 분석 결과를 불러왔습니다.");
    } catch (error) {
      setRun({
        ...transientRun("저장된 분석 결과", "failed"),
        requestId: savedRun.request_id,
        traceId: savedRun.trace_id,
        error: {
          code: "RESULT_EVIDENCE_MISSING",
          message: error instanceof Error ? error.message : "저장된 결과를 불러오지 못했습니다.",
          retryable: true,
          required_action: "RETRY",
        },
      });
    } finally { setSavedBusy(false); }
  };

  const createReportDraft = async () => {
    if (!run.artifact?.artifactId || !run.artifact?.queryId) return;
    setMessage("");
    try {
      await reportClient.createDraftFromArtifact(run.artifact.artifactId, reportTitle.trim() || reportTitleForRun(run));
      setReportModal("");
      onNavigate("/reports");
    } catch (error) { setMessage(error instanceof Error ? error.message : "보고서 초안을 저장하지 못했습니다."); }
  };

  const openReportDraftModal = () => {
    if (!reportModal) reportModalReturnFocusRef.current = document.activeElement;
    setReportTitle(reportTitleForRun(run));
    setReportModal("draft");
  };

  const openReportPreviewModal = () => {
    reportModalReturnFocusRef.current = document.activeElement;
    setReportModal("preview");
  };

  const closeReportModal = () => setReportModal("");
  const copyEvidence = async (value) => {
    try {
      await navigator.clipboard.writeText(String(value ?? ""));
      setMessage("식별 정보를 복사했습니다.");
    } catch {
      setMessage("식별 정보를 복사하지 못했습니다. 브라우저 권한을 확인해 주세요.");
    }
  };
  const selectArtifactTab = (id) => {
    setArtifactTab(id);
    window.requestAnimationFrame(() => document.getElementById(`evidence-tab-${id}`)?.focus());
  };
  const handleArtifactTabKeyDown = (event, index) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0
      : event.key === "End" ? ARTIFACT_TABS.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + ARTIFACT_TABS.length) % ARTIFACT_TABS.length;
    selectArtifactTab(ARTIFACT_TABS[nextIndex][0]);
  };

  return <div className={`chat-layout ${evidenceOpen ? "evidence-open" : ""}`}>
    <aside className="chat-history" inert={Boolean(reportModal)}>
      <button className="new-chat" onClick={() => { setQuestion(""); setInputError(""); setSubmittedQuestion(""); setRun(transientRun("")); }}><Plus size={16} />새 분석</button>
      <p>저장된 분석</p>
      <label className="saved-analysis-search"><span className="sr-only">저장된 분석 검색</span><input value={definitionQuery} onChange={(event) => { setDefinitionQuery(event.target.value); setVisibleDefinitionCount(10); }} placeholder="저장 분석 검색" /></label>
      {visibleDefinitions.length === 0 && <small className="chat-history-empty">아직 저장된 분석이 없습니다.</small>}
      {visibleDefinitions.map((definition) => <button disabled={savedBusy} title={definition.question} onClick={() => void replay(definition.definition_id)} key={definition.definition_id}><MessageSquareText size={15} /><span>{definition.title}<small>다시 분석하기</small></span></button>)}
      {filteredDefinitions.length > visibleDefinitionCount && <button type="button" className="saved-analysis-more" onClick={() => setVisibleDefinitionCount((count) => count + 10)}>더 보기</button>}
    </aside>
    <main className="chat-main" inert={Boolean(reportModal)}>
      {run.meta.asOf && <MetaStrip meta={run.meta} verified={Boolean(run.artifact && ["success", "partial"].includes(run.status))} />}
      {!hasSubmitted && <section className="chat-empty-state" aria-labelledby="chat-empty-title"><small>대화형 데이터 분석</small><h2 id="chat-empty-title">무엇을 분석할까요?</h2><p>분석할 지표와 기간을 자연어 질문에 함께 적어 주세요.</p><div aria-label="분석 질문 예시">{APPROVED_QUESTIONS.map((example) => <button type="button" key={example} onClick={() => { setQuestion(example); setInputError(""); }}>{example}</button>)}</div></section>}
      {hasSubmitted && <div className="conversation"><div className="message message--user"><div><b>사용자</b><p>{submittedQuestion}</p></div></div><div className="message message--agent"><span className="agent-avatar"><Sparkles size={17} /></span><div><b>분석 결과</b><AnalysisStatePanel run={run} suggestionsDisabled={submitting} onSuggestion={(suggestion) => void analyzeQuestion(clarifiedQuestion(submittedQuestion, suggestion, run.error?.clarification_type))} onRetry={() => void analyzeQuestion(submittedQuestion)} onCancel={() => void cancelAnalysis()} cancelRequested={cancelRequested} />{run.artifact && (run.rowCount ?? 0) > 0 && <div className="analysis-report-actions"><button className="primary" type="button" onClick={openReportDraftModal}><FilePlus2 size={15} />보고서 초안 만들기</button><button type="button" onClick={openReportPreviewModal}><Eye size={15} />결과 미리보기</button><button type="button" aria-controls="analysis-evidence-panel" aria-expanded={evidenceOpen} onClick={(event) => { evidenceReturnFocusRef.current = event.currentTarget; setEvidenceOpen((open) => !open); }}><TableProperties size={15} />분석 근거</button>{["success", "partial"].includes(run.status) && submittedParameters && <button type="button" disabled={savedBusy} onClick={() => void saveAnalysis()}><Save size={15} />분석 저장</button>}</div>}</div></div></div>}
      <form className="chat-input" onSubmit={submitQuestion}><div className="question-field"><input aria-label="분석 질문" name="question" value={question} maxLength={MAX_QUESTION_LENGTH} onChange={(event) => { setQuestion(event.target.value); setInputError(""); }} placeholder="예: 2026년 6월 객실 매출을 일별로 분석해 줘." aria-describedby="question-help" aria-invalid={Boolean(inputError)} required /><button aria-label="질문 전송" disabled={submitting}><Send size={17} /></button></div><small id="question-help">{question.length.toLocaleString("ko-KR")}/{MAX_QUESTION_LENGTH.toLocaleString("ko-KR")}자</small>{inputError && <p className="analysis-input-error" role="alert">{inputError}</p>}</form>
      {message && <p className="analysis-notice" role="status">{message}</p>}
      {savedRuns.length > 0 && <details className="run-history-panel"><summary><History size={15} /><span>최근 실행</span><b>{savedRuns.length}</b></summary><ul>{visibleRuns.map((item) => <li key={item.request_id}><span><b>{savedRunStatus(item.status)}</b><small>{formatSeoulDateTime(item.completed_at || item.started_at)}</small><small>{item.question}</small><small>{item.period_start && item.period_end_exclusive ? `${item.period_start} ~ ${item.period_end_exclusive} 미포함` : "기간 없음"}</small><details className="run-history-ids"><summary>식별 정보</summary><code>요청 ID {item.request_id}</code><code>조회 ID {item.query_id || "없음"}</code><code>결과 ID {item.artifact_id || "없음"}</code></details></span>{item.artifact_id && <button type="button" disabled={savedBusy} onClick={() => void showSavedRun(item)}>결과 열기</button>}</li>)}</ul>{savedRuns.length > visibleRunCount && <button type="button" onClick={() => setVisibleRunCount((count) => count + RUN_HISTORY_PAGE_SIZE)}>더 보기</button>}</details>}
    </main>
    {evidenceOpen && <aside id="analysis-evidence-panel" className="evidence-panel" inert={Boolean(reportModal)} aria-label="분석 근거"><div className="evidence-panel-header"><SectionTitle eyebrow="검증 근거" title="분석 근거" /><button type="button" aria-label="분석 근거 닫기" onClick={closeEvidence}><X size={18} /></button></div><div className="artifact-tabs" role="tablist" aria-label="분석 근거 종류">{ARTIFACT_TABS.map(([id, label], index) => <button id={`evidence-tab-${id}`} className={artifactTab === id ? "active" : ""} role="tab" aria-selected={artifactTab === id} aria-controls={`evidence-panel-${id}`} tabIndex={artifactTab === id ? 0 : -1} onKeyDown={(event) => handleArtifactTabKeyDown(event, index)} onClick={() => selectArtifactTab(id)} key={id}>{label}</button>)}</div>
      {artifactTab === "report" && <div id="evidence-panel-report" role="tabpanel" aria-labelledby="evidence-tab-report" tabIndex={0} className="artifact-report-summary"><small>보고서에 사용할 분석 결과</small><h3>{run.question}</h3><p>{run.summary}</p>{run.evidence?.metrics.map((metric) => <article className="evidence-metric" key={metric.metricId}><b>{metric.label}</b><p>{metric.definition}</p></article>)}</div>}
      {artifactTab === "sources" && <div id="evidence-panel-sources" role="tabpanel" aria-labelledby="evidence-tab-sources" tabIndex={0} className="evidence-block"><h3>사용한 데이터</h3>{run.sources.map((source) => <article className="evidence-source" key={source.urn}><span><TableProperties size={13} />{source.name}</span><dl><div><dt>Schema</dt><dd>{source.schemaVersion || "없음"}</dd></div><div><dt>Snapshot</dt><dd>{source.seedVersion || "없음"}</dd></div></dl><details><summary>데이터 식별 정보</summary><label>DataHub URN<button type="button" onClick={() => void copyEvidence(source.urn)}>복사</button></label><code>{source.urn}</code><label>Trino FQN<button type="button" onClick={() => void copyEvidence(source.fqn)}>복사</button></label><code>{source.fqn || "없음"}</code></details></article>)}</div>}
      {artifactTab === "run" && <div id="evidence-panel-run" role="tabpanel" aria-labelledby="evidence-tab-run" tabIndex={0} className="evidence-block"><h3>실행 정보</h3><dl><div><dt>상태</dt><dd>{savedRunStatus(run.status.toUpperCase())}</dd></div><div><dt>기간</dt><dd>{run.evidence?.period ? `${run.evidence.period.start} ~ ${run.evidence.period.endExclusive} 미포함` : "없음"}</dd></div><div><dt>기준일·시간대</dt><dd>{run.evidence?.asOf || run.meta.asOf || "없음"} · {run.evidence?.timezone || run.meta.timezone}</dd></div><div><dt>필터</dt><dd>{publicFilterSummary(run.evidence?.filters)}</dd></div><div><dt>Gate</dt><dd>{gateEvidence(run)}</dd></div><div><dt>캐시</dt><dd>{evidenceValue(run.evidence?.cached)}</dd></div><div><dt>Sampling</dt><dd>{evidenceValue(run.evidence?.sampling.applied)} · {run.evidence?.sampling.returnedRows ?? 0}/{run.evidence?.sampling.totalRows ?? "전체 미제공"}행</dd></div><div><dt>Masking</dt><dd>{evidenceValue(run.evidence?.masking.applied)}{run.evidence?.masking.fields.length ? ` · ${run.evidence.masking.fields.join(", ")}` : ""}</dd></div></dl><details className="technical-details"><summary>모델 및 기술 정보</summary><h3>모델 호출</h3>{run.evidence?.models.length ? run.evidence.models.map((model, index) => <article className="evidence-model" key={`${model.node}-${index}`}><b>{model.node}</b><span>{model.modelVersion}</span><code>{model.promptId}@{model.promptVersion}</code></article>) : <p>기록 없음</p>}<dl><div><dt>Artifact</dt><dd>{run.artifact?.artifactId || run.evidence?.artifactId || "없음"}</dd></div><div><dt>Query</dt><dd>{run.artifact?.queryId || run.evidence?.queryId || "없음"}</dd></div><div><dt>Request</dt><dd>{run.requestId}</dd></div><div><dt>Trace</dt><dd>{run.traceId}</dd></div><div><dt>Context</dt><dd>{run.evidence?.contextRelease || "없음"}</dd></div><div><dt>Policy</dt><dd>{run.evidence?.policyVersion || "없음"}</dd></div><div><dt>Result model</dt><dd>{run.evidence?.modelVersion || "없음"}</dd></div></dl></details></div>}
    </aside>}
    {reportModal && <div className="report-modal-backdrop" role="presentation" onMouseDown={closeReportModal}><section ref={reportModalRef} className={`report-transfer-modal ${reportModal === "preview" ? "report-transfer-modal--preview" : ""}`} role="dialog" aria-modal="true" aria-labelledby="report-modal-title" aria-describedby="report-modal-description" onMouseDown={(event) => event.stopPropagation()}><header><div><small>분석 결과</small><h2 id="report-modal-title">{reportModal === "draft" ? "보고서 초안 구성" : "분석 결과 미리보기"}</h2></div><button aria-label="닫기" onClick={closeReportModal}><X size={18} /></button></header><p id="report-modal-description" className="sr-only">{reportModal === "draft" ? "현재 분석 결과를 새 보고서 초안으로 저장합니다." : "현재 분석의 범위, 요약, 지표, 차트와 상세 데이터를 검토합니다."}</p>{reportModal === "draft" && <label className="report-title-field"><span>보고서 제목</span><input value={reportTitle} maxLength={120} onChange={(event) => setReportTitle(event.target.value)} /></label>}{reportModal === "preview" ? <div className="report-analysis-preview"><AnalysisStatePanel run={run} /></div> : <div className="report-preview-summary"><small>분석 질문</small><b>{run.question}</b><p>{run.summary}</p><dl>{run.metrics.map((metric) => <div key={metric.metricId}><dt>{metric.label}</dt><dd>{typeof metric.value === "number" ? metric.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : String(metric.value ?? "없음")} {metric.unit || ""}</dd></div>)}</dl></div>}<footer><button onClick={closeReportModal}>취소</button>{reportModal === "draft" ? <button className="primary" disabled={!reportTitle.trim()} onClick={() => void createReportDraft()}><Check size={14} />초안 만들기</button> : <button className="primary" onClick={openReportDraftModal}>보고서 초안 만들기</button>}</footer></section></div>}
  </div>;
}
