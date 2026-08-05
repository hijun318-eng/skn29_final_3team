import { useMemo, useState } from "react";
import { Check, MessageSquareText, Plus, Send, Sparkles, TableProperties } from "lucide-react";
import { createAnalysisClient } from "../api/analysisClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MetaStrip, SectionTitle } from "../components/common/EnterpriseUi";
import { analysisFixtures } from "../data/analysisFixtures";
import { createUuid } from "../utils/createUuid";

const RECENT_ANALYSES = ["객실·예약·연회 통합 분석"];
const client = createAnalysisClient();
const initialRun = analysisFixtures.ready;

export function AgentPage() {
  const [conversationId] = useState(createUuid);
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [run, setRun] = useState(initialRun);
  const [hasSubmitted, setHasSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [artifactNotice, setArtifactNotice] = useState("");
  const viewMeta = useMemo(() => run.meta, [run.meta]);

  const submitQuestion = async (event) => {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion || submitting) return;

    setSubmitting(true);
    setHasSubmitted(true);
    setArtifactNotice("");
    setSubmittedQuestion(nextQuestion);
    setRun({
      ...initialRun,
      status: "queued",
      question: nextQuestion,
      conversationId,
    });
    try {
      setRun(await client.analyze(nextQuestion, conversationId, "ready"));
    } catch {
      setRun({
        ...analysisFixtures.error,
        requestId: createUuid(),
        traceId: createUuid(),
        question: nextQuestion,
        conversationId,
        error: {
          code: "INTERNAL_ERROR",
          message: "Backend API에 연결할 수 없습니다.",
          retryable: true,
        },
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="chat-layout">
      <aside className="chat-history">
        <button className="new-chat"><Plus size={16} />새 분석</button>
        <p>RECENT</p>
        {RECENT_ANALYSES.map((item, index) => (
          <button className={index === 0 ? "selected" : ""} key={item}>
            <MessageSquareText size={15} />
            <span>{item}<small>{index === 0 ? "방금 전" : `${index + 1}일 전`}</small></span>
          </button>
        ))}
      </aside>

      <main className="chat-main">
        <MetaStrip meta={viewMeta} />
        {hasSubmitted && <div className="conversation">
          <div className="message message--user">
            <div className="avatar small">J</div>
            <div><b>사용자</b><p>{submittedQuestion}</p></div>
          </div>
          <div className="message message--agent">
            <span className="agent-avatar"><Sparkles size={17} /></span>
            <div>
              <b>Analysis Agent <em>{run.status}</em></b>
              <AnalysisStatePanel
                run={run}
                onAddArtifact={(artifactId) => {
                  const draftBlock = {
                    artifactId,
                    queryId: run.artifact?.queryId,
                    question: run.question,
                    sourceUrns: run.sources.map((source) => source.urn),
                  };
                  window.sessionStorage.setItem("answervice.report.artifact", JSON.stringify(draftBlock));
                  setArtifactNotice(`Artifact ${artifactId}를 보고서 초안 후보로 선택했습니다.`);
                }}
              />
              {artifactNotice && <p className="artifact-notice" role="status">{artifactNotice}</p>}
            </div>
          </div>
        </div>}
        <form className="chat-input" onSubmit={submitQuestion}>
          <div className="question-field">
            <input
              aria-label="분석 질문"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="승인된 데이터에 대해 질문하세요..."
            />
            <button aria-label="질문 전송" disabled={submitting}><Send size={17} /></button>
          </div>
          <small>중간발표 시연용 합성 데이터 · seed 20260729 · as_of 2026-07-30</small>
        </form>
      </main>

      <aside className="evidence-panel">
        <SectionTitle eyebrow="TRACEABILITY" title="분석 근거" />
        {!hasSubmitted && <p className="evidence-empty">질문을 입력하면 분석 결과와 근거가 표시됩니다.</p>}
        {hasSubmitted && <>
        <div className="execution-list">
          {["분석 요청 확인", "메타데이터 근거 연결", "Artifact 생성"].map((name, index) => (
            <article key={name}>
              <span>{index + 1}</span>
              <div><b>{name}<em><Check size={11} />검증 완료</em></b><small>동일 기준 시각과 합성 데이터 버전을 사용합니다.</small></div>
            </article>
          ))}
        </div>
        <div className="evidence-block">
          <h3>사용 데이터 자산</h3>
          {run.sources.length ? run.sources.map((source) => (
            <article className="evidence-source" key={source.urn}>
              <span><TableProperties size={13} />{source.name}<small>{source.status === "success" ? "정상" : "실패"}</small></span>
              <code>{source.urn}</code>
              {source.fqn && <small>{source.fqn} · schema {source.schemaVersion} · seed {source.seedVersion}</small>}
            </article>
          )) : <p className="evidence-empty">표시 가능한 자산이 없습니다.</p>}
        </div>
        {run.evidence && (
          <div className="evidence-block">
            <h3>조회 조건</h3>
            <dl>
              <div><dt>period</dt><dd>{run.evidence.period ? `${run.evidence.period.start} ~ ${run.evidence.period.endExclusive}` : "—"}</dd></div>
              <div><dt>filter</dt><dd>{Object.entries(run.evidence.filters).map(([key, value]) => `${key}=${String(value)}`).join(", ") || "없음"}</dd></div>
              <div><dt>sampling</dt><dd>{run.evidence.sampling.applied ? "적용" : "미적용"} · {run.evidence.sampling.returnedRows}/{run.evidence.sampling.totalRows ?? "unknown"}</dd></div>
            </dl>
          </div>
        )}
        <div className="evidence-block">
          <h3>실행 정보</h3>
          <dl>
            <div><dt>conversation</dt><dd>{run.conversationId}</dd></div>
            <div><dt>request</dt><dd>{run.requestId}</dd></div>
            <div><dt>run/trace</dt><dd>{run.traceId}</dd></div>
            <div><dt>artifact</dt><dd>{run.artifact?.artifactId ?? "—"}</dd></div>
            <div><dt>query</dt><dd>{run.artifact?.queryId ?? run.evidence?.queryId ?? "—"}</dd></div>
            <div><dt>as_of</dt><dd>{run.meta.asOf}</dd></div>
            <div><dt>timezone</dt><dd>{run.meta.timezone}</dd></div>
          </dl>
        </div>
        </>}
      </aside>
    </div>
  );
}
