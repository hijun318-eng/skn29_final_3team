import { useMemo, useState } from "react";
import { Check, Eye, FilePlus2, MessageSquareText, Plus, Send, Sparkles, TableProperties, X } from "lucide-react";
import { createMockAnalysisClient } from "../api/analysisClient";
import { AnalysisStatePanel } from "../components/analysis/AnalysisStatePanel";
import { MetaStrip, SectionTitle } from "../components/common/EnterpriseUi";
import { analysisFixtures } from "../data/analysisFixtures";
import { createUuid } from "../utils/createUuid";

const RECENT_ANALYSES = ["객실·예약·연회 통합 분석"];
const REPORT_SECTIONS = ["분석 요약", "핵심 KPI", "매출·점유율 비교 차트", "PMS·CRM·Banquet 근거"];
const client = createMockAnalysisClient();
const initialRun = analysisFixtures.ready;

export function AgentPage({ onNavigate }) {
  const [conversationId] = useState(createUuid);
  const [question, setQuestion] = useState("7월 마지막 주 객실 매출 감소 원인을 예약 채널과 연회 일정 변화까지 함께 비교해줘");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [run, setRun] = useState(initialRun);
  const [hasSubmitted, setHasSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [reportModal, setReportModal] = useState("");
  const [reportSections, setReportSections] = useState(REPORT_SECTIONS);
  const viewMeta = useMemo(() => run.meta, [run.meta]);

  const submitQuestion = async (event) => {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion || submitting) return;

    setSubmitting(true);
    setHasSubmitted(true);
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
        ...analysisFixtures.ready,
        question: nextQuestion,
        conversationId,
      });
    } finally {
      setSubmitting(false);
    }
  };

  const createReportDraft = () => {
    const artifactId = run.artifact?.artifactId;
    if (!artifactId) return;
    const includes = (section) => reportSections.includes(section);
    const blocks = [
      { id: `artifact-${artifactId}-title`, type: "heading", title: "보고서 제목", content: "7월 마지막 주 객실 매출 감소 통합 분석", w: 12, h: 2 },
      includes("분석 요약") && { id: `artifact-${artifactId}-summary`, type: "summary", title: "AI 분석 요약", content: `${run.summary}\n\n※ 같은 기간에 함께 관측된 변화이며 인과관계 확정을 위해 관리자 검토가 필요합니다.`, w: 12, h: 4 },
      includes("핵심 KPI") && { id: `artifact-${artifactId}-kpi`, type: "kpi", title: "핵심 KPI", content: "객실 매출 4,520→4,010만원\n점유율 76.1→68.6%\n직접 예약 43.5→38.2%\n연회 변경 2건\n객실 취소 62박", w: 6, h: 3 },
      includes("매출·점유율 비교 차트") && { id: `artifact-${artifactId}-chart`, type: "chart", title: "매출·점유율 비교", values: [45.2, 40.1, 76.1, 68.6], labels: ["4,520", "4,010", "76.1", "68.6"], caption: "객실 매출(만원) 4,520→4,010 · 점유율(%) 76.1→68.6", w: 6, h: 4 },
      includes("PMS·CRM·Banquet 근거") && { id: `artifact-${artifactId}-evidence`, type: "text", title: "데이터 출처 및 분석 기준", content: `Hotel PMS · pms.public.pms_stays\nMembership CRM · crm.dbo.crm_member_grade_history\nBanquet Sales · banquet.public.banquet_bookings\nArtifact ${artifactId} · Query ${run.artifact?.queryId ?? "—"}\nsynthetic · seed ${run.meta.seed} · schema ${run.meta.schemaVersion} · as_of ${run.meta.asOf}`, w: 6, h: 4 },
      { id: `artifact-${artifactId}-review`, type: "quote", title: "관리자 검토 필요", content: "연회 일정 변경과 객실 매출 감소는 같은 기간에 관측됐지만 인과관계로 확정하지 않습니다. 보고서 확정 전 관리자가 해석과 조치 문구를 검토해야 합니다.", w: 6, h: 4 },
    ].filter(Boolean);
    window.sessionStorage.setItem("answervice.report.artifact", JSON.stringify({ artifactId, queryId: run.artifact?.queryId, question: run.question, title: blocks[0].content, blocks }));
    window.sessionStorage.setItem("answervice.report.importNotice", `분석 결과 ${blocks.length}개 블록을 보고서 초안에 추가했습니다.`);
    onNavigate("/reports");
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
              />
              {run.artifact && <><div className="demo-steps" aria-label="시연 진행 단계"><b className="done"><Check size={12} />분석 완료</b><span>→</span><b className="active">초안 반영</b><span>→</span><b>편집</b><span>→</span><b>확정</b></div><div className="analysis-report-actions"><button className="primary" type="button" onClick={() => setReportModal("draft")}><FilePlus2 size={15} />보고서 초안에 추가</button><button type="button" onClick={() => setReportModal("preview")}><Eye size={15} />결과 미리보기</button></div></>}
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
      {reportModal && <div className="report-modal-backdrop" role="presentation" onMouseDown={() => setReportModal("")}><section className="report-transfer-modal" role="dialog" aria-modal="true" aria-labelledby="report-modal-title" onMouseDown={(event) => event.stopPropagation()}><header><div><small>SYNTHETIC ANALYSIS ARTIFACT</small><h2 id="report-modal-title">{reportModal === "draft" ? "보고서 초안 구성" : "분석 결과 미리보기"}</h2></div><button aria-label="닫기" onClick={() => setReportModal("")}><X size={18} /></button></header><div className="report-preview-summary"><b>7월 마지막 주 객실 매출 감소 통합 분석</b><p>{run.summary}</p><dl><div><dt>객실 매출</dt><dd>4,520 → 4,010만원</dd></div><div><dt>점유율</dt><dd>76.1 → 68.6%</dd></div><div><dt>직접 예약</dt><dd>43.5 → 38.2%</dd></div><div><dt>연회 변경</dt><dd>2건 · 62박 취소</dd></div></dl><em>관측 결과이며 인과관계 확정을 위해 관리자 검토가 필요합니다.</em></div>{reportModal === "draft" && <div className="report-section-options"><p>초안에 포함할 항목</p>{REPORT_SECTIONS.map((section) => <label key={section}><input type="checkbox" checked={reportSections.includes(section)} onChange={() => setReportSections((current) => current.includes(section) ? current.filter((item) => item !== section) : [...current, section])} /><span><Check size={12} /></span>{section}</label>)}</div>}<footer><button onClick={() => setReportModal("")}>취소</button>{reportModal === "draft" ? <button className="primary" disabled={!reportSections.length} onClick={createReportDraft}>선택한 내용으로 초안 만들기</button> : <button className="primary" onClick={() => setReportModal("draft")}>보고서 초안에 추가</button>}</footer></section></div>}
    </div>
  );
}
