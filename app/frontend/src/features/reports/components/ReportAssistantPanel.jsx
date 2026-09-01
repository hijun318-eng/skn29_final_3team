/** 선택한 Artifact를 근거로 보고서 AI 초안 요청과 승인 가능한 새 분석 계획을 표시한다. */
import { memo, useCallback, useState } from "react";
import { Bot, Check, Database, LoaderCircle, Send, ShieldCheck, Sparkles, X } from "lucide-react";

const QUICK_REQUESTS = [
  "요약을 3문장으로 정리",
  "차트를 표 위로 이동",
  "핵심 내용을 간결하게 정리",
];

/** 실제 assistant API가 반환한 모델·시도 횟수·처리 시간만 성공 영수증으로 표시하며 trace가 없으면 렌더링하지 않는다. */
function AssistantReceipt({ trace }) {
  if (!trace) return null;
  return <div className="report-assistant-receipt">
    <Check size={13} aria-hidden="true" />
    <span><b>초안 반영 완료</b><small>변경 내용을 확인해 주세요.</small></span>
  </div>;
}

const WORKFLOW_COPY = {
  waiting_patch_approval: ["변경안 확인 필요", "적용 전에는 보고서가 바뀌지 않습니다."],
  running_data_agent: ["데이터 분석 중", "승인한 계획으로 새 분석 결과를 만들고 있습니다."],
  waiting_artifact: ["분석 결과 준비 중", "승인한 범위의 결과를 기다리고 있습니다."],
  saving_revision: ["새 버전 저장 중", "분석 결과와 보고서를 함께 저장하고 있습니다."],
  completed: ["새 버전 저장 완료", "편집 화면에 반영했습니다."],
  failed: ["요청을 처리하지 못했습니다", "새 요청으로 다시 시도해 주세요."],
  cancelled: ["요청 취소", "보고서는 변경되지 않았습니다."],
};

const REQUIRED_ACTION_COPY = {
  NONE: "요청을 다시 확인해 주세요.",
  RETRY: "새 세션에서 지시를 다시 입력할 수 있습니다.",
  REFRESH: "페이지를 새로고침해 최신 상태를 확인해 주세요.",
  REAUTHENTICATE: "다시 로그인한 뒤 권한을 확인해 주세요.",
  REOPEN_LATEST_REPORT: "최신 보고서 버전을 다시 열어 주세요.",
  CONTACT_ADMIN: "분석 결과 또는 권한 확인을 위해 관리자에게 문의해 주세요.",
};

const PATCH_OPERATION_LABEL = {
  set_report_title: "보고서 제목 변경",
  add_text: "텍스트 블록 추가",
  update_text: "텍스트 블록 수정",
  add_artifact_view: "분석 결과 보기 추가",
  reposition_block: "블록 위치 변경",
  remove_block: "블록 삭제",
  duplicate_block: "블록 복제",
  restore_previous_revision: "직전 버전 복원",
};

/** 승인 카드가 닫힌 뒤에도 서버 terminal phase와 안전한 오류 code를 사용자에게 보여준다. */
function AssistantWorkflowStatus({ status, requiredAction, retryable, onRetry, pending }) {
  if (!WORKFLOW_COPY[status] || !["completed", "failed", "cancelled"].includes(status)) return null;
  const [title, detail] = WORKFLOW_COPY[status];
  return <article className={`report-assistant-message assistant workflow-${status}`}>
    <ShieldCheck size={15} aria-hidden="true" />
    <p><b>{title}</b><br />{detail}
      {status === "failed" ? <small> · {REQUIRED_ACTION_COPY[requiredAction] || REQUIRED_ACTION_COPY.NONE}</small> : null}
      {status === "failed" && retryable
        ? <button type="button" onClick={onRetry} disabled={pending}>새 세션으로 다시 시도</button>
        : null}
    </p>
  </article>;
}

/** 현재 사용자 요청의 안전한 서버 평가만 표시하고 전체 사용자 비용·원문 trace는 노출하지 않는다. */
function AssistantEvaluationReceipt({ evaluation }) {
  if (!evaluation) return null;
  const route = evaluation.route === "new_data"
    ? "신규 데이터 분석"
    : evaluation.route === "existing_artifact" ? "기존 분석 결과 편집" : "요청 확인";
  return <article className="report-assistant-message assistant">
    <ShieldCheck size={15} aria-hidden="true" />
    <p><b>실행 확인 완료</b><br />{route} · {evaluation.revision_created ? "새 버전을 만들었습니다." : "보고서 버전은 바뀌지 않았습니다."}</p>
  </article>;
}

/** 새 데이터 분석 계획과 서버 소유 실행 단계를 표시하고 승인·거절만 사용자에게 위임한다. */
function AssistantApproval({ request, status, onApprove, onReject, pending }) {
  if (!request) return null;
  const waiting = status === "waiting_approval";
  const [title, detail] = WORKFLOW_COPY[status] || ["새 데이터 분석 승인 필요", "승인 전에는 분석을 시작하지 않습니다."];
  return <section className={`report-assistant-approval ${waiting ? "waiting" : "active"}`} aria-label="새 데이터 분석 계획">
    <header><ShieldCheck size={15} aria-hidden="true" /><span><b>{title}</b><small>{detail}</small></span></header>
    <dl>
      <div><dt>질문</dt><dd>{request.question}</dd></div>
      <div><dt>필요 이유</dt><dd>{request.reason}</dd></div>
      <div><dt>조회 범위</dt><dd>{request.scope}</dd></div>
    </dl>
    {(waiting || status === "saving_revision") && <nav aria-label="분석 계획 결정">
      {waiting && <button type="button" onClick={onReject} disabled={pending}><X size={12} />거절</button>}
      <button type="button" className="primary" onClick={onApprove} disabled={pending}><Check size={12} />{waiting ? "승인 후 분석" : "저장 계속"}</button>
    </nav>}
  </section>;
}

/** 서버가 검증·dry-run한 제한 patch의 요약과 연산을 적용 전에 표시한다. */
function AssistantPatchApproval({ preview, status, onApprove, onReject, pending }) {
  if (!preview) return null;
  const waiting = status === "waiting_patch_approval";
  return <section className={`report-assistant-approval ${waiting ? "waiting" : "active"}`} aria-label="보고서 변경안">
    <header><ShieldCheck size={15} aria-hidden="true" /><span><b>{waiting ? "변경안 확인 필요" : "저장 계속"}</b><small>적용 전에는 현재 보고서가 바뀌지 않습니다.</small></span></header>
    <dl>
      <div><dt>변경 요약</dt><dd>{preview.summary}</dd></div>
      <div><dt>적용 작업</dt><dd>{preview.operations.map((operation) => PATCH_OPERATION_LABEL[operation] || operation).join(" · ")}</dd></div>
    </dl>
    <nav aria-label="변경안 결정">
      {waiting && <button type="button" onClick={onReject} disabled={pending}><X size={12} />취소</button>}
      <button type="button" className="primary" onClick={onApprove} disabled={pending}><Check size={12} />{waiting ? "변경안 적용" : "저장 계속"}</button>
    </nav>
  </section>;
}

/** 실제 assistant API 성공 여부만 대화 이력에 반영하고 입력·빠른 요청·처리 근거를 함께 제공한다. */
export const ReportAssistantPanel = memo(function ReportAssistantPanel({
  approvalRequest = null,
  artifact,
  artifactTitle = "",
  canEdit,
  evaluation = null,
  instruction,
  onApproveDataRequest,
  onApprovePatch,
  onInstructionChange,
  onRejectDataRequest,
  onRejectPatch,
  onRetry,
  onSubmit,
  pending,
  patchPreview = null,
  quickRequests = QUICK_REQUESTS,
  selectedBlock,
  trace,
  workflowStatus = "",
  workflowRequiredAction = "NONE",
  workflowRetryable = false,
}) {
  const [messages, setMessages] = useState([]);
  const waiting = pending === "assistant";
  const workflowActive = Boolean(approvalRequest || patchPreview);
  const disabled = !canEdit || !artifact || !instruction.trim() || Boolean(pending) || workflowActive;

  const submitInstruction = useCallback(async (event) => {
    event.preventDefault();
    const text = instruction.trim();
    if (!text || !artifact || !canEdit || pending) return;
    setMessages((current) => [...current, { role: "user", text }]);
    const result = await onSubmit(text);
    setMessages((current) => [...current, result
      ? result.status === "approval_required"
        ? { role: "assistant", text: "새 데이터가 필요해 분석 계획을 준비했습니다." }
        : result.status === "patch_approval_required"
          ? { role: "assistant", text: "변경안이 준비되었습니다. 적용할 내용을 확인하세요." }
        : result.message
          ? { role: "assistant", text: result.message }
          : { role: "assistant", trace: { requestId: result.requestId, ...result.trace } }
      : { role: "error" }]);
  }, [artifact, canEdit, instruction, onSubmit, pending]);

  return <aside className="report-assistant-panel" aria-label="보고서 도우미">
    <header>
      <span className="report-assistant-mark"><Sparkles size={15} aria-hidden="true" /></span>
      <div><p>보고서 편집</p><h2>보고서 도우미</h2><small>선택된 블록 · {selectedBlock?.title || "선택 없음"}</small></div>
    </header>

    <div className="report-assistant-context">
      <Database size={14} aria-hidden="true" />
      <span><b>{artifactTitle || "분석 결과를 선택해 주세요"}</b><small>{artifact ? "선택한 분석 결과로 초안을 구성합니다." : "블록 라이브러리에서 분석 결과를 먼저 선택하세요."}</small></span>
    </div>

    <div className="report-assistant-thread" aria-live="polite">
      <article className="report-assistant-message assistant">
        <Bot size={15} aria-hidden="true" />
        <p>요약, 블록 구성, 데이터 표현 방식을 요청할 수 있습니다.</p>
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
      <AssistantPatchApproval
        preview={patchPreview}
        status={workflowStatus}
        onApprove={onApprovePatch}
        onReject={onRejectPatch}
        pending={Boolean(pending)}
      />
      <AssistantWorkflowStatus
        status={workflowStatus}
        requiredAction={workflowRequiredAction}
        retryable={workflowRetryable}
        onRetry={onRetry}
        pending={Boolean(pending)}
      />
      <AssistantEvaluationReceipt evaluation={evaluation} />
      {waiting && <article className="report-assistant-message assistant pending"><LoaderCircle size={15} aria-hidden="true" /><p>변경안을 만드는 중입니다.</p></article>}
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
          placeholder={artifact ? "예: 핵심 요약을 3문장으로 정리" : "분석 결과를 선택하면 요청할 수 있습니다."}
          disabled={!canEdit || !artifact || Boolean(pending) || workflowActive}
        />
        <button type="submit" aria-label="작성 요청 보내기" disabled={disabled}>{waiting ? <LoaderCircle size={16} /> : <Send size={16} />}</button>
      </div>
      <small>확정 전 변경 내용을 확인하세요.</small>
    </form>
  </aside>;
});
