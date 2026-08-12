import { useState } from "react";
import { FilePlus2, MessageSquareText, Plus, Send, Sparkles, TableProperties, X } from "lucide-react";
import { createAnalysisClient } from "../api/analysisClient";
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

  const submitQuestion = async (event) => {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion || submitting) return;

    setSubmitting(true);
    setEvidenceOpen(false);
    setHasSubmitted(true);
    setSubmittedQuestion(nextQuestion);
    setReportTransfer({ status: "idle", message: "" });
    setRun(createTransientRun(nextQuestion, conversationId, "queued"));
    try {
      setRun(await client.analyze(nextQuestion, conversationId, accessProfile));
    } catch {
      setRun({
        ...createTransientRun(nextQuestion, conversationId, "failed"),
        error: {
          code: "INTERNAL_ERROR",
          message: "분석 API 요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
          retryable: true,
        },
      });
    } finally {
      setSubmitting(false);
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
        <div className="evidence-empty"><MessageSquareText size={15} /> 저장된 대화가 없습니다.</div>
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
              <AnalysisStatePanel run={run} />
              {run.status === "success" && run.artifact && <div className="analysis-report-actions"><button className="primary" type="button" disabled={reportTransfer.status === "loading"} onClick={() => void addArtifactToReport()}><FilePlus2 size={15} />보고서에 담기</button><button type="button" aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen((open) => !open)}><TableProperties size={15} />Artifacts</button></div>}
              {reportTransfer.status !== "idle" && <p className={`artifact-transfer-state ${reportTransfer.status}`} role={reportTransfer.status === "error" ? "alert" : "status"} aria-live="polite">{reportTransfer.message}</p>}
            </div>
          </div>
        </div>}
        <form className="chat-input" onSubmit={submitQuestion}>
          <label className="access-profile-picker" htmlFor="analysis-access-profile"><span>데이터 접근 범위</span><select id="analysis-access-profile" value={accessProfile} disabled={submitting} aria-describedby="analysis-access-domain" onChange={(event) => setAccessProfile(event.target.value)}>{ACCESS_PROFILES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <div className="access-profile-meta" id="analysis-access-domain" aria-live="polite"><span>선택 profile <b>{accessProfile}</b></span><span>접근 Domain <b>{ACCESS_PROFILES.find(([value]) => value === accessProfile)?.[2]}</b></span></div>
          <div className="question-field"><input aria-label="분석 질문" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="승인된 데이터에 대해 질문하세요..." /><button aria-label="질문 전송" disabled={submitting}><Send size={17} /></button></div>
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
