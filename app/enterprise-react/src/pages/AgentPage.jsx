import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Eye, FilePlus2, MessageSquareText, Plus, RotateCcw, Send, Sparkles, TableProperties, X } from "lucide-react";
import { createAnalysisClient } from "../api/analysisClient";
import { createReportClient } from "../api/reportClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MetaStrip, SectionTitle } from "../components/common/EnterpriseUi";
import { OPENAPI_VERSION } from "../contracts/analysis";
import { createUuid } from "../utils/createUuid";

const ARTIFACT_TABS = [["report", "Report"], ["sources", "Sources"], ["run", "Run history"]];
const SAVED_ANALYSIS_PAGE_SIZE = 10;
const RUN_HISTORY_PAGE_SIZE = 20;

function transientRun(question, conversationId, status = "idle") {
  return {
    conversationId, requestId: "", traceId: "", status, question,
    metrics: [], sources: [],
    meta: { asOf: "", timezone: "Asia/Seoul", seed: "", schemaVersion: "", contractVersion: OPENAPI_VERSION },
  };
}

export function AgentPage({ authToken, onNavigate }) {
  const analysisClient = useMemo(() => createAnalysisClient(fetch, authToken), [authToken]);
  const reportClient = useMemo(() => createReportClient(undefined, fetch, authToken), [authToken]);
  const [conversationId] = useState(createUuid);
  const [question, setQuestion] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [submittedParameters, setSubmittedParameters] = useState(null);
  const [run, setRun] = useState(() => transientRun("", conversationId));
  const [submitting, setSubmitting] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [artifactTab, setArtifactTab] = useState("report");
  const [reportModal, setReportModal] = useState("");
  const [message, setMessage] = useState("");
  const [inputError, setInputError] = useState("");
  const [savedBusy, setSavedBusy] = useState(false);
  const [definitions, setDefinitions] = useState([]);
  const [savedRuns, setSavedRuns] = useState([]);
  const [visibleDefinitionCount, setVisibleDefinitionCount] = useState(SAVED_ANALYSIS_PAGE_SIZE);
  const [visibleRunCount, setVisibleRunCount] = useState(RUN_HISTORY_PAGE_SIZE);
  const formRef = useRef(null);
  const hasSubmitted = Boolean(submittedQuestion);
  const visibleDefinitions = definitions.slice(0, visibleDefinitionCount);
  const visibleRuns = savedRuns.slice(0, visibleRunCount);

  const refreshSaved = async () => {
    const [nextDefinitions, nextRuns] = await Promise.all([analysisClient.listDefinitions(), analysisClient.listRuns()]);
    setDefinitions(nextDefinitions);
    setSavedRuns(nextRuns);
  };

  useEffect(() => { refreshSaved().catch((error) => setMessage(error instanceof Error ? error.message : "저장된 분석을 불러오지 못했습니다.")); }, []);

  const submitQuestion = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const nextQuestion = String(form.get("question") || question).trim();
    const nextPeriodStart = String(form.get("period_start") || periodStart);
    const nextPeriodEnd = String(form.get("period_end_exclusive") || periodEnd);
    if (!nextQuestion || !nextPeriodStart || !nextPeriodEnd || submitting) return;
    if (nextPeriodStart >= nextPeriodEnd) {
      setInputError("종료일(미포함)은 시작일보다 늦어야 합니다.");
      return;
    }
    const parameters = { period_start: nextPeriodStart, period_end_exclusive: nextPeriodEnd };
    setPeriodStart(nextPeriodStart);
    setPeriodEnd(nextPeriodEnd);
    setSubmitting(true);
    setInputError("");
    setMessage("");
    setEvidenceOpen(false);
    setSubmittedQuestion(nextQuestion);
    setSubmittedParameters(parameters);
    setRun(transientRun(nextQuestion, conversationId, "queued"));
    try {
      setRun(await analysisClient.analyze(nextQuestion, conversationId, parameters));
    } catch (error) {
      setRun({ ...transientRun(nextQuestion, conversationId, "failed"), error: { code: "INTERNAL_ERROR", message: error instanceof Error ? error.message : "분석 요청에 실패했습니다.", retryable: true } });
    } finally { setSubmitting(false); }
  };

  const saveAnalysis = async () => {
    if (run.status !== "success" || !submittedParameters || savedBusy) return;
    setSavedBusy(true);
    setMessage("");
    try {
      const definition = await analysisClient.createDefinition(submittedQuestion, submittedQuestion, submittedParameters);
      setMessage(`저장 완료 · ${definition.definition_id}`);
      await refreshSaved();
    } catch (error) { setMessage(error instanceof Error ? error.message : "분석을 저장하지 못했습니다."); }
    finally { setSavedBusy(false); }
  };

  const replay = async (definitionId) => {
    if (!periodStart || !periodEnd || savedBusy) return;
    if (periodStart >= periodEnd) {
      setInputError("종료일(미포함)은 시작일보다 늦어야 합니다.");
      return;
    }
    setSavedBusy(true);
    setInputError("");
    setMessage("");
    setEvidenceOpen(false);
    const definition = definitions.find((item) => item.definition_id === definitionId);
    const replayQuestion = definition?.title || "저장된 분석";
    setSubmittedQuestion(replayQuestion);
    setSubmittedParameters({ period_start: periodStart, period_end_exclusive: periodEnd });
    setRun(transientRun(replayQuestion, conversationId, "queued"));
    try {
      const result = await analysisClient.replayDefinition(definitionId, { period_start: periodStart, period_end_exclusive: periodEnd });
      setMessage(`재실행 ${result.status} · ${result.request_id}${result.query_id ? ` · query ${result.query_id}` : ""}`);
      if ((result.status === "SUCCEEDED" || result.status === "PARTIAL") && result.artifact_id) {
        setRun(await analysisClient.getRunArtifact(result.request_id, conversationId));
      } else {
        const status = result.status === "BLOCKED" ? "blocked" : "failed";
        setRun({
          ...transientRun(replayQuestion, conversationId, status),
          requestId: result.request_id,
          traceId: result.trace_id,
          error: {
            code: result.status === "BLOCKED" ? "SQL_POLICY_BLOCKED" : "INTERNAL_ERROR",
            message: result.error_type ? `재실행이 완료되지 않았습니다. (${result.error_type})` : "재실행이 완료되지 않았습니다.",
            retryable: result.status !== "BLOCKED",
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
    setRun(transientRun("저장된 분석 결과", conversationId, "queued"));
    try {
      const restored = await analysisClient.getRunArtifact(savedRun.request_id, conversationId);
      setSubmittedQuestion(restored.question);
      setSubmittedParameters(null);
      setRun(restored);
      setMessage(`저장 결과 불러옴 · ${savedRun.request_id}`);
    } catch (error) {
      setRun({
        ...transientRun("저장된 분석 결과", conversationId, "failed"),
        requestId: savedRun.request_id,
        traceId: savedRun.trace_id,
        error: {
          code: "RESULT_EVIDENCE_MISSING",
          message: error instanceof Error ? error.message : "저장된 결과를 불러오지 못했습니다.",
          retryable: true,
        },
      });
    } finally { setSavedBusy(false); }
  };

  const createReportDraft = async () => {
    if (!run.artifact?.artifactId || !run.artifact?.queryId) return;
    setMessage("");
    const blocks = [
      { block_id: createUuid(), type: "text", title: "분석 요약", content: run.summary || "", columns: 12, x: 0, y: 0, w: 12, h: 2 },
      { block_id: createUuid(), type: "table", title: "분석 결과", artifact_id: run.artifact.artifactId, query_id: run.artifact.queryId, columns: 12, x: 0, y: 2, w: 12, h: 4 },
    ];
    if (run.chart) blocks.push({ block_id: createUuid(), type: "chart", title: "분석 차트", artifact_id: run.artifact.artifactId, query_id: run.artifact.queryId, columns: 12, x: 0, y: 6, w: 12, h: 4 });
    try {
      await reportClient.createDefinition({ definition_id: createUuid(), title: run.question, blocks });
      setReportModal("");
      onNavigate("/reports");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Report 초안을 저장하지 못했습니다."); }
  };

  return <div className={`chat-layout ${evidenceOpen ? "evidence-open" : ""}`}>
    <aside className="chat-history">
      <button className="new-chat" onClick={() => { setQuestion(""); setSubmittedQuestion(""); setRun(transientRun("", conversationId)); }}><Plus size={16} />새 분석</button>
      <p>SAVED</p>
      {visibleDefinitions.map((definition) => <button key={definition.definition_id}><MessageSquareText size={15} /><span>{definition.title}<small>v{definition.version}</small></span></button>)}
    </aside>
    <main className="chat-main">
      {run.meta.asOf && <MetaStrip meta={run.meta} />}
      {!hasSubmitted && <section className="chat-empty-state" aria-labelledby="chat-empty-title"><small>CHAT-FIRST ANALYTICS</small><h2 id="chat-empty-title">무엇을 분석할까요?</h2><p>질문과 조회 기간을 직접 입력해 주세요.</p></section>}
      {hasSubmitted && <div className="conversation"><div className="message message--user"><div><b>사용자</b><p>{submittedQuestion}</p></div></div><div className="message message--agent"><span className="agent-avatar"><Sparkles size={17} /></span><div><b>Analysis Agent <em>{run.status}</em></b><AnalysisStatePanel run={run} />{run.artifact && <div className="analysis-report-actions"><button className="primary" type="button" onClick={() => setReportModal("draft")}><FilePlus2 size={15} />Report 초안 추가</button><button type="button" onClick={() => setReportModal("preview")}><Eye size={15} />결과 미리보기</button><button type="button" aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen((open) => !open)}><TableProperties size={15} />Artifacts</button></div>}</div></div></div>}
      <form className="chat-input" onSubmit={submitQuestion} ref={formRef}><div className="question-field"><input aria-label="분석 질문" name="question" value={question} maxLength={1000} onChange={(event) => { setQuestion(event.target.value); setInputError(""); }} placeholder="분석할 내용을 입력하세요." required /><button aria-label="질문 전송" disabled={submitting}><Send size={17} /></button></div><div className="analysis-period-inputs"><label>시작일<input name="period_start" type="date" value={periodStart} onChange={(event) => { setPeriodStart(event.target.value); setInputError(""); }} required /></label><label>종료일(미포함)<input name="period_end_exclusive" type="date" value={periodEnd} onChange={(event) => { setPeriodEnd(event.target.value); setInputError(""); }} required /></label></div>{inputError && <p className="analysis-input-error" role="alert">{inputError}</p>}</form>
      <section className="saved-analysis-panel" aria-label="Saved Analysis"><div><b>Saved Analysis · {definitions.length}</b><button type="button" disabled={run.status !== "success" || savedBusy} onClick={saveAnalysis}>현재 분석 저장</button><button type="button" disabled={savedBusy} onClick={() => refreshSaved().catch((error) => setMessage(error.message))}><RotateCcw size={13} />새로고침</button></div>{message && <p>{message}</p>}<ul>{visibleDefinitions.map((definition) => <li key={definition.definition_id}><span>{definition.title} · v{definition.version}</span><button type="button" disabled={savedBusy || !periodStart || !periodEnd} onClick={() => replay(definition.definition_id)}>입력 기간으로 재실행</button></li>)}</ul>{definitions.length > visibleDefinitionCount && <button type="button" onClick={() => setVisibleDefinitionCount((count) => count + SAVED_ANALYSIS_PAGE_SIZE)}>저장 분석 더 보기</button>}<details><summary>Run History · {savedRuns.length}</summary><ul>{visibleRuns.map((item) => <li key={item.request_id}><span>{item.status} · {item.request_id}{item.query_id ? ` · query ${item.query_id}` : ""}{item.artifact_id ? ` · artifact ${item.artifact_id}` : ""}</span>{item.artifact_id && <button type="button" disabled={savedBusy} onClick={() => void showSavedRun(item)}>결과 보기</button>}</li>)}</ul>{savedRuns.length > visibleRunCount && <button type="button" onClick={() => setVisibleRunCount((count) => count + RUN_HISTORY_PAGE_SIZE)}>Run 더 보기</button>}</details></section>
    </main>
    {evidenceOpen && <aside className="evidence-panel"><div className="evidence-panel-header"><SectionTitle eyebrow="TRACEABILITY" title="Artifacts" /><button type="button" aria-label="Artifacts 닫기" onClick={() => setEvidenceOpen(false)}><X size={18} /></button></div><div className="artifact-tabs" role="tablist">{ARTIFACT_TABS.map(([id, label]) => <button className={artifactTab === id ? "active" : ""} role="tab" aria-selected={artifactTab === id} onClick={() => setArtifactTab(id)} key={id}>{label}</button>)}</div>{artifactTab === "report" && <div className="artifact-report-summary"><small>REPORT ARTIFACT</small><h3>{run.question}</h3><p>{run.summary}</p><dl><div><dt>artifact</dt><dd>{run.artifact?.artifactId || "없음"}</dd></div><div><dt>status</dt><dd>{run.status}</dd></div></dl></div>}{artifactTab === "sources" && <div className="evidence-block"><h3>사용 데이터 자산</h3>{run.sources.map((source) => <article className="evidence-source" key={source.urn}><span><TableProperties size={13} />{source.name}<small>{source.status}</small></span><code>{source.urn}</code></article>)}</div>}{artifactTab === "run" && <div className="evidence-block"><h3>실행 정보</h3><dl><div><dt>conversation</dt><dd>{run.conversationId}</dd></div><div><dt>request</dt><dd>{run.requestId}</dd></div><div><dt>trace</dt><dd>{run.traceId}</dd></div><div><dt>query</dt><dd>{run.artifact?.queryId || run.evidence?.queryId || "없음"}</dd></div></dl></div>}</aside>}
    {reportModal && <div className="report-modal-backdrop" role="presentation" onMouseDown={() => setReportModal("")}><section className={`report-transfer-modal ${reportModal === "preview" ? "report-transfer-modal--preview" : ""}`} role="dialog" aria-modal="true" aria-labelledby="report-modal-title" onMouseDown={(event) => event.stopPropagation()}><header><div><small>ANALYSIS ARTIFACT</small><h2 id="report-modal-title">{reportModal === "draft" ? "Report 초안 구성" : "분석 결과 미리보기"}</h2></div><button aria-label="닫기" onClick={() => setReportModal("")}><X size={18} /></button></header><div className="report-preview-summary"><b>{run.question}</b><p>{run.summary}</p><dl>{run.metrics.map((metric) => <div key={metric.metricId}><dt>{metric.label}</dt><dd>{String(metric.value)} {metric.unit || ""}</dd></div>)}</dl></div><footer><button onClick={() => setReportModal("")}>취소</button>{reportModal === "draft" ? <button className="primary" onClick={() => void createReportDraft()}><Check size={14} />초안 만들기</button> : <button className="primary" onClick={() => setReportModal("draft")}>Report 초안 추가</button>}</footer></section></div>}
  </div>;
}
