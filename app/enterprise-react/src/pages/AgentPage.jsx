import { useEffect, useState } from "react";
import { FilePlus2, MessageSquareText, Plus, Send, Sparkles, TableProperties, X } from "lucide-react";
import { AnalysisRequestError, createAnalysisClient } from "../api/analysisClient";
import { createReportClient } from "../api/reportClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MetaStrip, SectionTitle } from "../components/common/EnterpriseUi";
import { OPENAPI_VERSION } from "../contracts/analysis";
import { createUuid } from "../utils/createUuid";

const ARTIFACT_TABS = [["report", "Report"], ["sources", "Sources"], ["run", "Run history"], ["trace", "Trace"]];
const ACCESS_PROFILES = [
  ["pms_only", "PMS 전용", "PMS"],
  ["crm_only", "CRM 전용", "CRM"],
  ["pms_crm", "PMS + CRM", "PMS · CRM"],
  ["integrated_revenue", "통합 매출", "PMS · CRM · POS"],
  ["integrated_operations", "전체 통합", "PMS · CRM · POS · 시설 · 연회"],
];
const client = createAnalysisClient();
const reportClient = createReportClient();

function createTransientRun(question, conversationId, status = "idle") {
  return {
    conversationId,
    requestId: "—",
    traceId: "—",
    status,
    question,
    metrics: [],
    sources: [],
    meta: {
      asOf: "",
      timezone: "Asia/Seoul",
      synthetic: true,
      seed: "",
      schemaVersion: "",
      contractVersion: OPENAPI_VERSION,
    },
  };
}

export function AgentPage() {
  const [conversationId] = useState(createUuid);
  const [question, setQuestion] = useState("");
  const [accessProfile, setAccessProfile] = useState("pms_only");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [run, setRun] = useState(() => createTransientRun("", conversationId));
  const [hasSubmitted, setHasSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [artifactTab, setArtifactTab] = useState("report");
  const [reportTransfer, setReportTransfer] = useState({ status: "idle", message: "" });
  const [recent, setRecent] = useState([]);
  const [profileAvailability, setProfileAvailability] = useState([]);
  const [profileAvailabilityError, setProfileAvailabilityError] = useState("");

  const selectedAvailability = profileAvailability.find((item) => item.profile_id === accessProfile);

  const loadRecent = async () => {
    try { setRecent(await client.listRecent()); } catch { setRecent([]); }
  };

  useEffect(() => {
    void loadRecent();
    void client.listAccessProfiles().then((items) => {
      setProfileAvailability(items);
      setProfileAvailabilityError("");
      setAccessProfile((current) => items.some((item) => item.profile_id === current && item.available)
        ? current
        : items.find((item) => item.available)?.profile_id || current);
    }).catch(() => {
      setProfileAvailability([]);
      setProfileAvailabilityError("데이터 접근 범위의 사용 가능 여부를 확인할 수 없습니다.");
    });
  }, []);
  useEffect(() => {
    const active = recent.find((item) => item.status === "RECEIVED");
    if (!hasSubmitted && active) void restoreRecent(active);
  }, [recent, hasSubmitted]);
  useEffect(() => {
    if (run.restoredStatus !== "RECEIVED") return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const progress = await client.getProgress(run.requestId, run.accessProfile);
        if (cancelled) return;
        if (progress.status === "SUCCEEDED" || progress.status === "PARTIAL") {
          const restored = await client.getResult(run.requestId, run.question, conversationId, run.accessProfile);
          if (!cancelled) setRun({ ...restored, restoredStatus: progress.status, accessProfile: run.accessProfile, progress: progress.events.map(({ sequence, stage, outcome, created_at }) => ({ sequence, stage, outcome, createdAt: created_at })) });
          void loadRecent();
          return;
        }
        setRun((current) => current.requestId !== run.requestId ? current : ({
          ...current,
          status: progress.status === "RECEIVED" ? "running" : "idle",
          restoredStatus: progress.status,
          progress: progress.events.map(({ sequence, stage, outcome, created_at }) => ({ sequence, stage, outcome, createdAt: created_at })),
        }));
        if (progress.status !== "RECEIVED") void loadRecent();
      } catch { /* 기존 화면을 유지하고 다음 polling에서 재시도합니다. */ }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [run.requestId, run.restoredStatus, run.accessProfile]);

  const restoreRecent = async (item) => {
    setAccessProfile(item.access_profile);
    setSubmittedQuestion(item.question_text_redacted);
    setQuestion(item.question_text_redacted);
    setHasSubmitted(true);
    const restored = {
      ...createTransientRun(item.question_text_redacted, conversationId, item.status === "RECEIVED" ? "running" : "idle"),
      requestId: item.request_id,
      traceId: item.trace_id,
      restoredStatus: item.status,
      accessProfile: item.access_profile,
      meta: { asOf: item.as_of, timezone: "Asia/Seoul", synthetic: true, seed: "", schemaVersion: "", contractVersion: OPENAPI_VERSION },
    };
    setRun(restored);
    try {
      const progress = await client.getProgress(item.request_id, item.access_profile);
      const events = progress.events.map(({ sequence, stage, outcome, created_at }) => ({ sequence, stage, outcome, createdAt: created_at }));
      if (item.status === "SUCCEEDED" || item.status === "PARTIAL") {
        const result = await client.getResult(item.request_id, item.question_text_redacted, conversationId, item.access_profile);
        setRun({ ...result, restoredStatus: item.status, accessProfile: item.access_profile, progress: events });
      } else {
        setRun((current) => current.requestId !== item.request_id ? current : ({ ...current, progress: events }));
      }
    } catch (restoreError) {
      if (item.status === "SUCCEEDED" || item.status === "PARTIAL") {
        setRun((current) => current.requestId !== item.request_id ? current : ({
          ...current,
          status: restoreError instanceof AnalysisRequestError && restoreError.code === "ACCESS_DENIED" ? "blocked" : "failed",
          error: {
            code: restoreError instanceof AnalysisRequestError ? restoreError.code : "INTERNAL_ERROR",
            message: restoreError instanceof Error ? restoreError.message : "저장된 Analysis 결과를 복원하지 못했습니다.",
            retryable: restoreError instanceof AnalysisRequestError ? restoreError.retryable : false,
          },
        }));
      }
      /* 최근 목록의 안전 메타데이터는 그대로 표시합니다. */
    }
  };

  const submitQuestion = async (event) => {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion || submitting || !selectedAvailability?.available) return;

    setSubmitting(true);
    setEvidenceOpen(false);
    setHasSubmitted(true);
    setSubmittedQuestion(nextQuestion);
    setReportTransfer({ status: "idle", message: "" });
    setRun(createTransientRun(nextQuestion, conversationId, "queued"));
    try {
      setRun(await client.analyze(nextQuestion, conversationId, accessProfile, setRun));
    } catch (error) {
      const timedOut = error instanceof DOMException && error.name === "TimeoutError";
      setRun((current) => ({
        ...createTransientRun(nextQuestion, conversationId, "failed"),
        requestId: current.requestId,
        traceId: current.traceId,
        progress: current.progress,
        error: {
          code: error instanceof AnalysisRequestError ? error.code : "INTERNAL_ERROR",
          message: error instanceof AnalysisRequestError
            ? error.message
            : timedOut
              ? "분석 요청이 5분 안에 완료되지 않았습니다. 로그인 상태와 RunPod worker 상태를 확인해 주세요."
              : "분석 API 요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
          retryable: error instanceof AnalysisRequestError ? error.retryable : true,
        },
      }));
    } finally {
      setSubmitting(false);
      void loadRecent();
    }
  };

  const addArtifactToReport = async () => {
    if (run.status !== "success" || !run.artifact) return;
    setReportTransfer({ status: "loading", message: "Report 정의를 생성하고 있습니다." });
    try {
      const definition = await reportClient.createDefinition({
        definition_id: createUuid(),
        title: run.question,
        blocks: [{
          block_id: createUuid(),
          title: run.summary || run.question,
          artifact_id: run.artifact.artifactId,
          query_id: run.artifact.queryId,
          columns: 12,
          type: run.chart ? "chart" : "table",
          x: 0,
          y: 0,
          w: 12,
          h: 4,
          content: "",
        }],
      });
      setReportTransfer({ status: "success", message: `Report 정의 v${definition.version} 초안을 생성했습니다.` });
    } catch (error) {
      setReportTransfer({ status: "error", message: error instanceof Error ? error.message : "Report 정의 생성에 실패했습니다." });
    }
  };

  return (
    <div className={`chat-layout ${evidenceOpen ? "evidence-open" : ""}`}>
      <aside className="chat-history">
        <button className="new-chat" onClick={() => { setQuestion(""); setAccessProfile("pms_only"); setHasSubmitted(false); setRun(createTransientRun("", conversationId)); }}><Plus size={16} />새 분석</button>
        <p>RECENT</p>
        {recent.length ? <div className="recent-analysis-list">{recent.map((item) => <button type="button" key={item.request_id} onClick={() => void restoreRecent(item)}><MessageSquareText size={15} /><span>{item.question_text_redacted}<small>{item.status} · {item.access_profile}</small></span></button>)}</div> : <div className="evidence-empty"><MessageSquareText size={15} /> 저장된 분석이 없습니다.</div>}
      </aside>

      <main className="chat-main">
        <MetaStrip meta={run.meta} />
        {!hasSubmitted && <section className="chat-empty-state" aria-labelledby="chat-empty-title"><small>CHAT-FIRST ANALYTICS</small><h2 id="chat-empty-title">무엇을 분석할까요?</h2><p>승인된 데이터에 대해 직접 질문을 입력하세요.</p></section>}
        {hasSubmitted && <div className="conversation">
          <div className="message message--user"><div className="avatar small">J</div><div><b>사용자</b><p>{submittedQuestion}</p></div></div>
          <div className="message message--agent">
            <span className="agent-avatar"><Sparkles size={17} /></span>
            <div>
              <b>Analysis Agent <em>{run.status}</em></b>
              <AnalysisStatePanel run={run} onClarify={(suffix) => setQuestion(`${submittedQuestion} ${suffix}`.trim())} />
              {run.status === "success" && run.artifact && <div className="analysis-report-actions"><button className="primary" type="button" disabled={reportTransfer.status === "loading"} onClick={() => void addArtifactToReport()}><FilePlus2 size={15} />보고서에 담기</button><button type="button" aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen((open) => !open)}><TableProperties size={15} />Artifacts</button></div>}
              {reportTransfer.status !== "idle" && <p className={`artifact-transfer-state ${reportTransfer.status}`} role={reportTransfer.status === "error" ? "alert" : "status"} aria-live="polite">{reportTransfer.message}</p>}
            </div>
          </div>
        </div>}
        <form className="chat-input" onSubmit={submitQuestion}>
          <label className="access-profile-picker" htmlFor="analysis-access-profile"><span>데이터 접근 범위</span><select id="analysis-access-profile" value={accessProfile} disabled={submitting || !profileAvailability.length} aria-describedby="analysis-access-domain" onChange={(event) => setAccessProfile(event.target.value)}>{ACCESS_PROFILES.map(([value, label]) => <option value={value} key={value} disabled={!profileAvailability.find((item) => item.profile_id === value)?.available}>{label}</option>)}</select></label>
          <div className="access-profile-meta" id="analysis-access-domain" aria-live="polite"><span>선택 profile <b>{accessProfile}</b></span><span>접근 Domain <b>{ACCESS_PROFILES.find(([value]) => value === accessProfile)?.[2]}</b></span>{(profileAvailabilityError || selectedAvailability?.reason) && <span role="status">{profileAvailabilityError || selectedAvailability.reason}</span>}</div>
          <div className="question-field"><input aria-label="분석 질문" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="승인된 데이터에 대해 질문하세요..." /><button aria-label="질문 전송" disabled={submitting || !selectedAvailability?.available}><Send size={17} /></button></div>
          <small>화면에는 Analysis API가 반환한 결과만 표시됩니다.</small>
        </form>
      </main>

      {evidenceOpen && <aside className="evidence-panel">
        <div className="evidence-panel-header"><SectionTitle eyebrow="TRACEABILITY" title="Artifacts" /><button type="button" aria-label="Artifacts 닫기" onClick={() => setEvidenceOpen(false)}><X size={18} /></button></div>
        <div className="artifact-tabs" role="tablist" aria-label="Artifact 상세">{ARTIFACT_TABS.map(([id, label]) => <button className={artifactTab === id ? "active" : ""} role="tab" aria-selected={artifactTab === id} onClick={() => setArtifactTab(id)} key={id}>{label}</button>)}</div>
        {artifactTab === "report" && <div className="artifact-report-summary"><small>REPORT ARTIFACT</small><h3>{run.question}</h3><p>{run.summary || "요약이 없습니다."}</p><dl><div><dt>artifact</dt><dd>{run.artifact?.artifactId ?? "—"}</dd></div><div><dt>status</dt><dd>{run.status}</dd></div></dl></div>}
        {artifactTab === "trace" && <div className="evidence-block"><h3>추적 식별자</h3><dl><div><dt>request</dt><dd>{run.requestId}</dd></div><div><dt>trace</dt><dd>{run.traceId}</dd></div><div><dt>context</dt><dd>{run.artifact?.contextHash ?? "—"}</dd></div></dl></div>}
        {artifactTab === "sources" && <div className="evidence-block"><h3>사용 데이터 자산</h3>{run.sources.length ? run.sources.map((source) => <article className="evidence-source" key={source.urn}><span><TableProperties size={13} />{source.name}<small>{source.status}</small></span><code>{source.urn}</code>{source.fqn && <small>{source.fqn} · schema {source.schemaVersion} · seed {source.seedVersion}</small>}</article>) : <p className="evidence-empty">API가 반환한 자산이 없습니다.</p>}</div>}
        {artifactTab === "run" && <div className="evidence-block"><h3>실행 정보</h3><dl><div><dt>conversation</dt><dd>{run.conversationId}</dd></div><div><dt>request</dt><dd>{run.requestId}</dd></div><div><dt>run/trace</dt><dd>{run.traceId}</dd></div><div><dt>artifact</dt><dd>{run.artifact?.artifactId ?? "—"}</dd></div><div><dt>query</dt><dd>{run.artifact?.queryId ?? run.evidence?.queryId ?? "—"}</dd></div><div><dt>as_of</dt><dd>{run.meta.asOf}</dd></div></dl></div>}
      </aside>}
    </div>
  );
}
