import { useMemo, useState } from "react";
import { Check, MessageSquareText, Plus, Send, Sparkles, TableProperties } from "lucide-react";
import { createMockAnalysisClient } from "../api/analysisClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MetaStrip, SectionTitle } from "../components/common/EnterpriseUi";
import { analysisFixtures } from "../data/analysisFixtures";

const RECENT_ANALYSES = ["지난달 객실 매출 하락 원인", "다음 30일 객실 수요", "프로모션 효과 분석"];
const SCENARIOS = [
  ["loading", "분석 중"],
  ["ready", "정상 완료"],
  ["empty", "결과 없음"],
  ["delayed", "응답 지연"],
  ["partial", "부분 완료"],
  ["error", "실패"],
  ["forbidden", "접근 불가"],
  ["insufficient_evidence", "근거 부족"],
  ["cancelled", "취소"],
];

const client = createMockAnalysisClient();

export function AgentPage() {
  const [conversationId] = useState(() => crypto.randomUUID());
  const [question, setQuestion] = useState("지난달 객실 매출 하락 원인을 알려줘.");
  const [submittedQuestion, setSubmittedQuestion] = useState(analysisFixtures.ready.question);
  const [scenario, setScenario] = useState("ready");
  const [run, setRun] = useState(analysisFixtures.ready);
  const [submitting, setSubmitting] = useState(false);
  const [artifactNotice, setArtifactNotice] = useState("");
  const viewMeta = useMemo(() => run.meta, [run.meta]);

  const submitQuestion = async (event) => {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion || submitting) return;

    setSubmitting(true);
    setArtifactNotice("");
    setSubmittedQuestion(nextQuestion);
    setRun({ ...analysisFixtures.loading, question: nextQuestion, conversationId });
    const result = await client.analyze(nextQuestion, conversationId, scenario);
    setRun(result);
    setSubmitting(false);
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
        <div className="conversation">
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
                onAddArtifact={(artifactId) => setArtifactNotice(`Artifact ${artifactId}를 보고서 초안 후보로 선택했습니다.`)}
              />
              {artifactNotice && <p className="artifact-notice" role="status">{artifactNotice}</p>}
            </div>
          </div>
        </div>
        <form className="chat-input" onSubmit={submitQuestion}>
          <label className="scenario-picker">
            <span>상태 fixture</span>
            <select value={scenario} onChange={(event) => setScenario(event.target.value)}>
              {SCENARIOS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
          </label>
          <div className="question-field">
            <input
              aria-label="분석 질문"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="승인된 데이터에 대해 질문하세요..."
            />
            <button aria-label="질문 전송" disabled={submitting}><Send size={17} /></button>
          </div>
          <small>표시된 값은 합성 fixture이며 Agent 결과는 자동 실행되지 않습니다.</small>
        </form>
      </main>

      <aside className="evidence-panel">
        <SectionTitle eyebrow="TRACEABILITY" title="분석 근거" />
        <div className="execution-list">
          {["요청 접수", "Controller 상태 확인", "결과·근거 표시"].map((name, index) => (
            <article key={name}>
              <span>{index + 1}</span>
              <div><b>{name}<em><Check size={11} />계약 기반</em></b><small>frontend는 API 상태를 재판정하지 않습니다.</small></div>
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
      </aside>
    </div>
  );
}
