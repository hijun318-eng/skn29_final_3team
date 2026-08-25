/** 선택한 Artifact를 근거로 보고서 AI 초안 요청과 승인 가능한 새 분석 계획을 표시한다. */
import { memo, useCallback, useState } from "react";
import { Bot, Check, Database, LoaderCircle, Send, ShieldCheck, Sparkles, X } from "lucide-react";

const QUICK_REQUESTS = [
  "요약을 세 줄로 줄여줘",
  "차트를 표보다 위로 올려줘",
  "핵심 인사이트를 더 짧게 정리해줘",
];

/** 실제 assistant API가 반환한 모델·시도 횟수·처리 시간만 성공 영수증으로 표시하며 trace가 없으면 렌더링하지 않는다. */
function AssistantReceipt({ trace }) {
  if (!trace) return null;
  return <div className="report-assistant-receipt">
    <Check size={13} aria-hidden="true" />
    <span><b>AI 초안 반영 완료</b><small>{trace.model_version} · {trace.attempts}회 시도 · {(trace.duration_ms / 1000).toFixed(1)}초</small></span>
  </div>;
}

const WORKFLOW_COPY = {
  running_data_agent: ["Data Agent 실행 중", "승인된 계획으로만 새 Artifact를 생성합니다."],
  waiting_artifact: ["새 Artifact 대기", "승인된 분석 계획과 일치하는 Artifact를 기다립니다."],
  saving_revision: ["Revision 저장 중", "기존 lineage와 새 Artifact를 함께 저장합니다."],
  completed: ["Revision 저장 완료", "검증된 새 보고서 버전을 Canvas에 반영했습니다."],
  failed: ["Assistant 실행 실패", "안전하게 중단했습니다. 새 요청으로 다시 시도해 주세요."],
  cancelled: ["Assistant 실행 취소", "보고서와 Artifact는 변경되지 않았습니다."],
};

/** 승인 카드가 닫힌 뒤에도 서버 terminal phase와 안전한 오류 code를 사용자에게 보여준다. */
function AssistantWorkflowStatus({ status, errorCode }) {
  if (!WORKFLOW_COPY[status] || !["completed", "failed", "cancelled"].includes(status)) return null;
  const [title, detail] = WORKFLOW_COPY[status];
  return <article className={`report-assistant-message assistant workflow-${status}`}>
    <ShieldCheck size={15} aria-hidden="true" />
    <p><b>{title}</b><br />{detail}{errorCode ? <small> · {errorCode}</small> : null}</p>
  </article>;
}

/** 새 데이터 분석 계획과 서버 소유 실행 단계를 표시하고 승인·거절만 사용자에게 위임한다. */
function AssistantApproval({ request, status, onApprove, onReject, pending }) {
  if (!request) return null;
  const waiting = status === "waiting_approval";
  const [title, detail] = WORKFLOW_COPY[status] || ["새 데이터 분석 승인 필요", "승인 전에는 Data Agent를 호출하지 않습니다."];
  return <section className={`report-assistant-approval ${waiting ? "waiting" : "active"}`} aria-label="새 데이터 분석 계획">
    <header><ShieldCheck size={15} aria-hidden="true" /><span><b>{title}</b><small>{detail}</small></span></header>
    <dl>
      <div><dt>질문</dt><dd>{request.question}</dd></div>
      <div><dt>필요 이유</dt><dd>{request.reason}</dd></div>
      <div><dt>조회 범위</dt><dd>{request.scope}</dd></div>
    </dl>
    {(waiting || status === "saving_revision") && <nav aria-label="분석 계획 결정">
      {waiting && <button type="button" onClick={onReject} disabled={pending}><X size={12} />거절</button>}
      <button type="button" className="primary" onClick={onApprove} disabled={pending}><Check size={12} />{waiting ? "승인 후 분석" : "Revision 저장 재개"}</button>
    </nav>}
  </section>;
}

/** 실제 assistant API 성공 여부만 대화 이력에 반영하고 입력·빠른 요청·처리 근거를 함께 제공한다. */
export const ReportAssistantPanel = memo(function ReportAssistantPanel({
  approvalRequest = null,
  artifact,
  canEdit,
  instruction,
  onApproveDataRequest,
  onInstructionChange,
  onRejectDataRequest,
  onSubmit,
  pending,
  quickRequests = QUICK_REQUESTS,
  selectedBlock,
  trace,
  workflowStatus = "",
  workflowError = "",
}) {
  const [messages, setMessages] = useState([]);
  const waiting = pending === "assistant";
  const workflowActive = Boolean(approvalRequest);
  const disabled = !canEdit || !artifact || !instruction.trim() || Boolean(pending) || workflowActive;

  const submitInstruction = useCallback(async (event) => {
    event.preventDefault();
    const text = instruction.trim();
    if (!text || !artifact || !canEdit || pending) return;
    setMessages((current) => [...current, { role: "user", text }]);
    const result = await onSubmit(text);
    setMessages((current) => [...current, result
      ? result.status === "approval_required"
        ? { role: "assistant", text: "현재 Artifact만으로는 요청을 완료할 수 없어 분석 계획을 준비했습니다." }
        : result.message
          ? { role: "assistant", text: result.message }
          : { role: "assistant", trace: { requestId: result.requestId, ...result.trace } }
      : { role: "error" }]);
  }, [artifact, canEdit, instruction, onSubmit, pending]);

  return <aside className="report-assistant-panel" aria-label="보고서 AI Assistant">
    <header>
      <span className="report-assistant-mark"><Sparkles size={15} aria-hidden="true" /></span>
      <div><p>REPORT ASSISTANT</p><h2>보고서 AI Assistant</h2><small>선택된 블록 · {selectedBlock?.title || "선택 없음"}</small></div>
    </header>

    <div className="report-assistant-context">
      <Database size={14} aria-hidden="true" />
      <span><b>{artifact?.title || "분석 Artifact를 선택해 주세요"}</b><small>{artifact ? "승인된 분석 결과를 근거로 초안을 다시 구성합니다." : "블록 라이브러리에서 분석 결과를 먼저 선택하세요."}</small></span>
    </div>

    <div className="report-assistant-thread" aria-live="polite">
      <article className="report-assistant-message assistant">
        <Bot size={15} aria-hidden="true" />
        <p>보고서 초안을 열었습니다. 요약 수정, 블록 구성, 데이터 표현 방식을 요청할 수 있습니다.</p>
      </article>
      {!messages.length && trace && <article className="report-assistant-message assistant"><AssistantReceipt trace={trace} /></article>}
      {messages.map((message, index) => message.role === "user"
        ? <article className="report-assistant-message user" key={`user-${index}`}><p>{message.text}</p></article>
        : <article className="report-assistant-message assistant" key={`assistant-${index}`}>
          {message.role === "error"
            ? <p>요청을 반영하지 못했습니다. 편집 화면의 오류 안내를 확인해 주세요.</p>
            : message.text ? <p>{message.text}</p> : <AssistantReceipt trace={message.trace} />}
        </article>)}
      <AssistantApproval
        request={approvalRequest}
        status={workflowStatus}
        onApprove={onApproveDataRequest}
        onReject={onRejectDataRequest}
        pending={Boolean(pending)}
      />
      <AssistantWorkflowStatus status={workflowStatus} errorCode={workflowError} />
      {waiting && <article className="report-assistant-message assistant pending"><LoaderCircle size={15} aria-hidden="true" /><p>근거를 유지하며 초안을 구성하고 있습니다.</p></article>}
    </div>

    <div className="report-assistant-quick" aria-label="빠른 요청">
      {quickRequests.map((request) => <button type="button" onClick={() => onInstructionChange(request)} disabled={!canEdit || !artifact || Boolean(pending) || workflowActive} key={request}>{request}</button>)}
    </div>

    <form className="report-assistant-composer" onSubmit={submitInstruction}>
      <label htmlFor="report-assistant-instruction">보고서를 어떻게 바꿀까요?</label>
      <div>
        <textarea
          id="report-assistant-instruction"
          value={instruction}
          onChange={(event) => onInstructionChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          maxLength={500}
          placeholder={artifact ? "예: 핵심 요약을 세 문장으로 정리해줘" : "분석 Artifact를 선택하면 요청할 수 있습니다."}
          disabled={!canEdit || !artifact || Boolean(pending) || workflowActive}
        />
        <button type="submit" aria-label="AI 초안 요청 보내기" disabled={disabled}>{waiting ? <LoaderCircle size={16} /> : <Send size={16} />}</button>
      </div>
      <small>생성 결과는 AI 초안이며 확정 전에 검토가 필요합니다.</small>
    </form>
  </aside>;
});
