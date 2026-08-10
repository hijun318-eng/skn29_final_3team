import { useMemo, useState } from "react";
import { Check, Send, Sparkles, TableProperties, TrendingUp } from "lucide-react";
import { createAnalysisClient } from "../api/analysisClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MetaStrip, SectionTitle } from "../components/common/EnterpriseUi";
import { analysisFixtures } from "../data/analysisFixtures";
import { createUuid } from "../utils/createUuid";

const client = createAnalysisClient();
const initialRun = analysisFixtures.ready;
const SUGGESTIONS = [
  { icon: TrendingUp, label: "주간 객실 운영", question: "주간 객실 운영 현황을 보여줘" },
];

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
      ...analysisFixtures.loading,
      requestId: "",
      traceId: "",
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
      <section className="chat-main" aria-label="분석 대화">
        <MetaStrip meta={viewMeta} />
        {!hasSubmitted && (
          <section className="chat-hero" aria-labelledby="chat-hero-title">
            <span className="hero-mark"><Sparkles size={22} /></span>
            <p>DATA ANALYSIS COPILOT</p>
            <h2 id="chat-hero-title">무엇을 분석해 볼까요?</h2>
            <span>승인된 합성 데이터와 동일한 기준 시각으로 답변합니다.</span>
            <div className="suggestion-grid">
              {SUGGESTIONS.map(({ icon: Icon, label, question: suggestion }) => (
                <button type="button" key={label} onClick={() => setQuestion(suggestion)}>
                  <Icon size={17} />
                  <span><b>{label}</b><small>{suggestion}</small></span>
                </button>
              ))}
            </div>
          </section>
        )}
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
            <textarea
              aria-label="분석 질문"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return;
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="승인된 데이터에 대해 질문하세요..."
              rows={2}
            />
            <button aria-label="질문 전송" disabled={submitting}><Send size={17} /></button>
          </div>
          <small>중간발표 시연용 합성 데이터 · seed 20260729 · as_of 2026-07-30</small>
        </form>
      </section>

      <aside className="evidence-panel" id="analysis-evidence" aria-label="분석 근거 패널">
        <SectionTitle eyebrow="TRACEABILITY" title="분석 근거" />
        {!hasSubmitted && <p className="evidence-empty">질문을 입력하면 분석 결과와 근거가 표시됩니다.</p>}
        {hasSubmitted && <>
        <div className="execution-list">
          {[
            { name: "분석 요청 확인", complete: Boolean(run.requestId) && run.error?.code !== "INTERNAL_ERROR", note: "Backend가 요청을 수신한 경우에만 완료됩니다." },
            { name: "메타데이터 근거 연결", complete: run.sources.length > 0, note: "API가 반환한 source만 근거로 표시합니다." },
            { name: "Artifact 생성", complete: Boolean(run.artifact?.artifactId), note: "검증된 Artifact가 있을 때만 완료됩니다." },
          ].map(({ name, complete, note }, index) => (
            <article className={complete ? "complete" : "incomplete"} key={name}>
              <span>{index + 1}</span>
              <div><b>{name}<em>{complete && <Check size={11} />}{complete ? "확인됨" : "미완료"}</em></b><small>{note}</small></div>
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
