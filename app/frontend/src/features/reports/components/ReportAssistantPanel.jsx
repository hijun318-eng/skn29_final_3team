/** 선택한 Artifact를 근거로 보고서 AI 초안 요청과 승인 가능한 새 분석 계획을 표시한다. */
import { memo, useCallback, useEffect, useState } from "react";
import { Bot, Check, Database, LoaderCircle, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import { reportEvidenceLabel } from "../../../contracts/report";

/** 실제 assistant API가 반환한 모델·시도 횟수·처리 시간만 성공 영수증으로 표시하며 trace가 없으면 렌더링하지 않는다. */
function AssistantReceipt({ trace }) {
  if (!trace) return null;
  return <div className="report-assistant-receipt">
    <Check size={13} aria-hidden="true" />
    <span><b>AI 초안 반영 완료</b><small>{trace.model_version} · {trace.attempts}회 시도 · {(trace.duration_ms / 1000).toFixed(1)}초</small></span>
  </div>;
}

const WORKFLOW_COPY = {
  waiting_patch_approval: ["AI 변경안 검토 필요", "적용 전에는 보고서 Revision을 저장하지 않습니다."],
  running_data_agent: ["Data Agent 실행 중", "승인된 계획으로만 새 Artifact를 생성합니다."],
  waiting_artifact: ["새 Artifact 대기", "승인된 분석 계획과 일치하는 Artifact를 기다립니다."],
  saving_revision: ["Revision 저장 중", "기존 lineage와 새 Artifact를 함께 저장합니다."],
  completed: ["Revision 저장 완료", "검증된 새 보고서 버전을 Canvas에 반영했습니다."],
  failed: ["Assistant 실행 실패", "안전하게 중단했습니다. 새 요청으로 다시 시도해 주세요."],
  cancelled: ["Assistant 실행 취소", "보고서와 Artifact는 변경되지 않았습니다."],
};

const REQUIRED_ACTION_COPY = {
  NONE: "요청을 다시 확인해 주세요.",
  RETRY: "새 세션에서 지시를 다시 입력할 수 있습니다.",
  REFRESH: "페이지를 새로고침해 최신 상태를 확인해 주세요.",
  REAUTHENTICATE: "다시 로그인한 뒤 권한을 확인해 주세요.",
  REOPEN_LATEST_REPORT: "최신 보고서 Revision을 다시 열어 주세요.",
  CONTACT_ADMIN: "Artifact 또는 권한 확인을 위해 관리자에게 문의해 주세요.",
};

const PATCH_OPERATION_LABEL = {
  set_report_title: "보고서 제목 변경",
  add_text: "텍스트 블록 추가",
  update_text: "텍스트 블록 수정",
  add_artifact_view: "Artifact 보기 추가",
  reposition_block: "블록 위치 변경",
  remove_block: "블록 삭제",
  duplicate_block: "블록 복제",
  restore_previous_revision: "직전 Revision 복원",
};

const REVIEW_CATEGORY_LABEL = {
  duplicate_text: "중복 문장",
  verbose_summary: "긴 요약",
  title_mismatch: "제목 불일치",
  inconsistent_metric_expression: "지표 표현 불일치",
  unsupported_claim: "근거 확인 필요",
};

/** 품질 finding을 보여 주되 선택은 입력창에 수정 지시만 채우고 저장이나 모델 호출을 하지 않는다. */
function AssistantQualityReview({ review, onSelect, pending }) {
  if (!review) return null;
  return <section className="report-assistant-approval waiting" aria-label="AI 보고서 품질 검토">
    <header><ShieldCheck size={15} aria-hidden="true" /><span><b>비저장 품질 검토</b><small>{review.summary}</small></span></header>
    {review.findings.length
      ? <dl>{review.findings.map((finding, index) => <div key={`${finding.category}-${finding.block_id || "report"}-${index}`}>
          <dt>{REVIEW_CATEGORY_LABEL[finding.category] || finding.category}</dt>
          <dd>{finding.title} · {finding.detail}</dd>
          <dd><button type="button" onClick={() => onSelect(finding.suggested_instruction)} disabled={pending}>이 항목 수정하기</button></dd>
        </div>)}</dl>
      : <p>현재 지원하는 범위에서 발견된 품질 문제가 없습니다.</p>}
  </section>;
}

/** 승인 카드가 닫힌 뒤에도 서버 terminal phase와 안전한 오류 code를 사용자에게 보여준다. */
function AssistantWorkflowStatus({ status, errorCode, requiredAction, retryable, onRetry, pending }) {
  if (!WORKFLOW_COPY[status] || !["completed", "failed", "cancelled"].includes(status)) return null;
  const [title, detail] = WORKFLOW_COPY[status];
  return <article className={`report-assistant-message assistant workflow-${status}`}>
    <ShieldCheck size={15} aria-hidden="true" />
    <p><b>{title}</b><br />{detail}{errorCode ? <small> · {errorCode}</small> : null}
      {status === "failed" ? <small> · {REQUIRED_ACTION_COPY[requiredAction] || REQUIRED_ACTION_COPY.NONE}</small> : null}
      {status === "failed" && retryable
        ? <button type="button" onClick={onRetry} disabled={pending}>새 세션으로 다시 시도</button>
        : null}
    </p>
  </article>;
}

/** 서버가 허용한 대기 phase만 취소하고 실행·저장 중에는 새로고침 안내만 표시한다. */
function AssistantCancelAction({ status, onCancel, pending }) {
  if (["ready", "waiting_patch_approval", "waiting_approval"].includes(status)) {
    return <button type="button" className="report-assistant-cancel" onClick={onCancel} disabled={pending}>
      <X size={12} aria-hidden="true" />Assistant 요청 취소
    </button>;
  }
  if (["running_data_agent", "waiting_artifact", "saving_revision"].includes(status)) {
    return <p className="report-assistant-processing-note">처리 중에는 취소할 수 없습니다. 잠시 후 서버 상태를 새로 확인해 주세요.</p>;
  }
  return null;
}

/** 현재 사용자 요청의 안전한 서버 평가만 표시하고 전체 사용자 비용·원문 trace는 노출하지 않는다. */
function AssistantEvaluationReceipt({ evaluation }) {
  if (!evaluation) return null;
  const route = evaluation.route === "new_data"
    ? "신규 데이터 분석"
    : evaluation.route === "existing_artifact" ? "기존 Artifact 편집" : "분류 없음";
  return <article className="report-assistant-message assistant">
    <ShieldCheck size={15} aria-hidden="true" />
    <p><b>실행 검증 완료</b><br />{route} · 계약 {evaluation.contract_valid ? "통과" : "실패"} · Revision {evaluation.revision_created ? "생성" : "미생성"}
      {evaluation.latency_ms == null ? null : <small> · {Math.round(evaluation.latency_ms)}ms</small>}
      {evaluation.error_code ? <small> · {evaluation.error_code}</small> : null}
    </p>
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

/** 서버가 검증·dry-run한 제한 patch의 요약과 연산을 적용 전에 표시한다. */
function AssistantPatchApproval({ preview, status, onApprove, onReject, pending }) {
  const [selectedIndexes, setSelectedIndexes] = useState([]);
  useEffect(() => {
    if (!preview) {
      setSelectedIndexes([]);
      return;
    }
    setSelectedIndexes(
      preview.approvedIndexes?.length
        ? [...preview.approvedIndexes]
        : preview.items.map((item) => item.index),
    );
  }, [preview?.requestId]);
  if (!preview) return null;
  const waiting = status === "waiting_patch_approval";
  const toggleOperation = (index) => setSelectedIndexes((current) => (
    current.includes(index)
      ? current.filter((item) => item !== index)
      : [...current, index].sort((left, right) => left - right)
  ));
  return <section className={`report-assistant-approval ${waiting ? "waiting" : "active"}`} aria-label="AI 보고서 변경안">
    <header><ShieldCheck size={15} aria-hidden="true" /><span><b>{waiting ? "AI 변경안 검토 필요" : "Revision 저장 재개"}</b><small>승인 전에는 현재 보고서를 변경하지 않습니다.</small></span></header>
    <dl>
      <div><dt>변경 요약</dt><dd>{preview.summary}</dd></div>
      <div><dt>적용 작업</dt><dd>{preview.operations.map((operation) => PATCH_OPERATION_LABEL[operation] || operation).join(" · ")}</dd></div>
      {preview.evidenceRefs?.length
        ? <div><dt>사용 근거</dt><dd>{preview.evidenceRefs.map(reportEvidenceLabel).join(" · ")}</dd></div>
        : null}
    </dl>
    <div className="report-assistant-patch-items" aria-label="적용할 변경 선택">
      {preview.items.map((item) => <label key={`${preview.requestId}-${item.index}`}>
        <input
          type="checkbox"
          checked={selectedIndexes.includes(item.index)}
          disabled={!waiting || pending}
          onChange={() => toggleOperation(item.index)}
        />
        <span><b>{PATCH_OPERATION_LABEL[item.operation] || item.operation} · {item.target}</b>
          {item.before == null ? null : <small><em>변경 전</em>{item.before}</small>}
          {item.after == null ? null : <small><em>변경 후</em>{item.after}</small>}
        </span>
      </label>)}
    </div>
    <nav aria-label="AI 변경안 결정">
      {waiting && <button type="button" onClick={onReject} disabled={pending}><X size={12} />취소</button>}
      <button type="button" className="primary" onClick={() => onApprove(selectedIndexes)} disabled={pending || !selectedIndexes.length}><Check size={12} />{waiting ? `선택 ${selectedIndexes.length}개 적용` : "Revision 저장 재개"}</button>
    </nav>
  </section>;
}

/** 실제 assistant API 성공 여부만 대화 이력에 반영하고 입력·빠른 요청·처리 근거를 함께 제공한다. */
export const ReportAssistantPanel = memo(function ReportAssistantPanel({
  approvalRequest = null,
  artifact,
  artifactOptions = [],
  artifactTitle = "",
  assistantArtifactIds = [],
  canEdit,
  evaluation = null,
  instruction,
  onApproveDataRequest,
  onApprovePatch,
  onCancel,
  onInstructionChange,
  onRejectDataRequest,
  onRejectPatch,
  onReview,
  onRetry,
  onSubmit,
  onToggleArtifact,
  pending,
  patchPreview = null,
  review = null,
  suggestions = [],
  selectedBlock,
  trace,
  workflowStatus = "",
  workflowError = "",
  workflowRequiredAction = "NONE",
  workflowRetryable = false,
}) {
  const [messages, setMessages] = useState([]);
  const waiting = pending === "assistant";
  const workflowActive = Boolean(approvalRequest || patchPreview);
  const canRefinePatch = Boolean(patchPreview) && workflowStatus === "waiting_patch_approval";
  const composerBlocked = workflowActive && !canRefinePatch;
  const disabled = !canEdit || !artifact || !instruction.trim() || Boolean(pending) || composerBlocked;

  const submitInstruction = useCallback(async (event) => {
    event.preventDefault();
    const text = instruction.trim();
    if (!text || !artifact || !canEdit || pending) return;
    setMessages((current) => [...current, { role: "user", text }]);
    const result = await onSubmit(text);
    setMessages((current) => [...current, result
      ? result.status === "approval_required"
        ? { role: "assistant", text: "현재 Artifact만으로는 요청을 완료할 수 없어 분석 계획을 준비했습니다." }
        : result.status === "patch_approval_required"
          ? { role: "assistant", text: "현재 Artifact 근거로 만들 수 있는 변경안을 준비했습니다. 적용 전에 검토해 주세요." }
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
      <span><b>{artifactTitle || "분석 Artifact를 선택해 주세요"}</b><small>{artifact ? "승인된 분석 결과를 근거로 초안을 다시 구성합니다." : "블록 라이브러리에서 분석 결과를 먼저 선택하세요."}</small></span>
    </div>
    {artifactOptions.length > 1 && <fieldset className="report-assistant-context" disabled={!canEdit || Boolean(pending) || workflowActive}>
      <legend>종합 편집 근거 · 최대 5개</legend>
      {artifactOptions.map((option) => {
        const primary = option.artifactId === assistantArtifactIds[0];
        const checked = assistantArtifactIds.includes(option.artifactId);
        return <label key={option.artifactId}>
          <input
            type="checkbox"
            checked={checked}
            disabled={primary || (!checked && assistantArtifactIds.length >= 5)}
            onChange={() => onToggleArtifact(option.artifactId)}
          />
          {option.title || "승인 Artifact"}{primary ? " · 대표 근거" : ""}
        </label>;
      })}
    </fieldset>}

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
      <AssistantPatchApproval
        preview={patchPreview}
        status={workflowStatus}
        onApprove={onApprovePatch}
        onReject={onRejectPatch}
        pending={Boolean(pending)}
      />
      <AssistantQualityReview review={review} onSelect={onInstructionChange} pending={Boolean(pending)} />
      <AssistantWorkflowStatus
        status={workflowStatus}
        errorCode={workflowError}
        requiredAction={workflowRequiredAction}
        retryable={workflowRetryable}
        onRetry={onRetry}
        pending={Boolean(pending)}
      />
      <AssistantCancelAction status={workflowStatus} onCancel={onCancel} pending={Boolean(pending)} />
      <AssistantEvaluationReceipt evaluation={evaluation} />
      {waiting && <article className="report-assistant-message assistant pending"><LoaderCircle size={15} aria-hidden="true" /><p>근거를 유지하며 초안을 구성하고 있습니다.</p></article>}
    </div>

    <div className="report-assistant-quick" aria-label="빠른 요청">
      <button type="button" onClick={onReview} disabled={!canEdit || !artifact || Boolean(pending) || workflowActive}>보고서 품질 검토</button>
      {suggestions.map((request) => <button type="button" onClick={() => onInstructionChange(request)} disabled={!canEdit || !artifact || Boolean(pending) || composerBlocked} key={request}>{request}</button>)}
    </div>

    <form className="report-assistant-composer" onSubmit={submitInstruction}>
      <label htmlFor="report-assistant-instruction">{canRefinePatch ? "변경안을 어떻게 다듬을까요?" : "보고서를 어떻게 바꿀까요?"}</label>
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
          placeholder={canRefinePatch ? "예: 차트 위치는 유지하고 요약만 두 문장으로 바꿔줘" : artifact ? "예: 핵심 요약을 세 문장으로 정리해줘" : "분석 Artifact를 선택하면 요청할 수 있습니다."}
          disabled={!canEdit || !artifact || Boolean(pending) || composerBlocked}
        />
        <button type="submit" aria-label={canRefinePatch ? "변경안 수정 요청" : "AI 초안 요청 보내기"} disabled={disabled}>{waiting ? <LoaderCircle size={16} /> : <Send size={16} />}</button>
      </div>
      <small>생성 결과는 AI 초안이며 확정 전에 검토가 필요합니다.</small>
    </form>
  </aside>;
});
