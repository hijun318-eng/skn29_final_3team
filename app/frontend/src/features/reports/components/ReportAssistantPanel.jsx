/** 선택한 Artifact를 근거로 보고서 AI 초안 요청과 승인 가능한 새 분석 계획을 표시한다. */
import { memo, useCallback, useEffect, useId, useReducer, useRef, useState } from "react";
import { Bot, Check, Database, LoaderCircle, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import { reportEvidenceLabel } from "../../../contracts/report";
import { analysisTimeLabel } from "../reportAnalysisArtifacts";
import {
  INITIAL_REPORT_ASSISTANT_SCOPE_STATE,
  hydrateReportAssistantMessages,
  reduceReportAssistantScope,
  reportAssistantMessagesFromTurnHistory,
} from "../reportAssistantUiState";
import {
  closeReportPatchSelection,
  groupReportPatchItemsByPage,
  removeReportPatchSelection,
} from "../reportAssistantPatchSelection";
import { formatSeoulTime } from "../reportPageLabels";

/** 내부 실행 정보는 기본 대화에서 숨기고 사용자가 펼친 경우에만 확인할 수 있게 한다. */
function AssistantTechnicalDetails({ children }) {
  return <details className="report-assistant-technical-detail">
    <summary>기술 상세</summary>
    <div>{children}</div>
  </details>;
}

/** 실제 assistant API 성공을 사용자 문구로 표시하며 세부 trace는 접힌 영역에만 둔다. */
function AssistantReceipt({ trace }) {
  if (!trace) return null;
  return <div className="report-assistant-receipt">
    <Check size={13} aria-hidden="true" />
    <div><b>보고서 변경을 반영했습니다.</b><small>새 버전에서 변경 내용을 확인할 수 있습니다.</small>
      <AssistantTechnicalDetails>
        <dl>
          <div><dt>사용 모델</dt><dd>{trace.model_version || "정보 없음"}</dd></div>
          <div><dt>처리 시도</dt><dd>{trace.attempts ?? "정보 없음"}</dd></div>
          <div><dt>처리 시간</dt><dd>{Number.isFinite(trace.duration_ms) ? `${(trace.duration_ms / 1000).toFixed(1)}초` : "정보 없음"}</dd></div>
        </dl>
      </AssistantTechnicalDetails>
    </div>
  </div>;
}

const WORKFLOW_COPY = {
  waiting_patch_approval: ["AI 변경안 검토 필요", "적용 전에는 보고서 새 버전을 저장하지 않습니다."],
  running_data_agent: ["분석 실행 중", "승인된 계획으로만 새 분석 결과를 만듭니다."],
  waiting_artifact: ["새 분석 결과 대기", "승인된 분석 계획과 일치하는 결과를 기다립니다."],
  saving_revision: ["새 버전 저장 중", "기존 근거와 새 분석 결과를 함께 저장합니다."],
  completed: ["새 버전 저장 완료", "검증된 새 보고서 버전을 편집 화면에 반영했습니다."],
  failed: ["Assistant 실행 실패", "안전하게 중단했습니다. 새 요청으로 다시 시도해 주세요."],
  cancelled: ["Assistant 실행 취소", "보고서와 분석 결과는 변경되지 않았습니다."],
};

const REQUIRED_ACTION_COPY = {
  NONE: "요청을 다시 확인해 주세요.",
  RETRY: "새 세션에서 지시를 다시 입력할 수 있습니다.",
  REFRESH: "페이지를 새로고침해 최신 상태를 확인해 주세요.",
  REAUTHENTICATE: "다시 로그인한 뒤 권한을 확인해 주세요.",
  REOPEN_LATEST_REPORT: "최신 보고서 버전을 다시 열어 주세요.",
  CONTACT_ADMIN: "근거 자료 또는 권한 확인을 위해 관리자에게 문의해 주세요.",
  REVIEW_EXTERNAL_TRANSFER: "외부 모델로 전송할 범위를 확인하고 동의 여부를 선택해 주세요.",
};

const EXTERNAL_TRANSFER_SCOPE_LABEL = {
  user_instruction: "사용자가 입력한 변경 지시",
  assistant_turn_history: "현재 Assistant 대화 이력",
  report_metadata_layout: "보고서 제목·페이지·레이아웃 정보",
  report_block_content: "보고서 블록 내용",
  selected_artifact_metadata: "선택한 분석 결과의 제목·사용 가능한 보기",
  selected_artifact_narrative: "선택한 분석 결과의 설명",
  selected_artifact_metrics: "선택한 분석 결과의 지표",
  selected_artifact_chart_spec: "선택한 분석 결과의 차트 설정",
  selected_artifact_table_snapshot: "선택한 분석 결과의 표 스냅샷",
  pending_patch: "검토 중인 변경안",
  approved_new_analysis_artifact: "승인 후 생성된 새 분석 결과",
};

function externalTransferScopeLabel(scope) {
  return EXTERNAL_TRANSFER_SCOPE_LABEL[scope] || "서버에서 승인한 보고서 처리 범위";
}

const PATCH_OPERATION_LABEL = {
  set_report_title: "보고서 제목 변경",
  set_report_orientation: "용지 방향 변경",
  set_currency_display_unit: "통화 표시 단위 변경",
  compact_report_layout: "전체 레이아웃 정리",
  add_report_page: "빈 페이지 추가",
  update_block_title: "블록 제목 변경",
  resize_block: "블록 크기 변경",
  update_chart_settings: "차트 설정 변경",
  update_table_settings: "표 설정 변경",
  set_block_size_mode: "블록 크기 모드 변경",
  add_text: "텍스트 블록 추가",
  update_text: "텍스트 블록 수정",
  add_artifact_view: "분석 결과 보기 추가",
  reposition_block: "블록 위치 변경",
  remove_block: "블록 삭제",
  duplicate_block: "블록 복제",
  restore_previous_revision: "직전 버전 복원",
};

const PATCH_IMPACT_LABEL = {
  CONTENT: "내용 변경",
  LAYOUT: "구성 변경",
  DESTRUCTIVE: "삭제·복원 포함",
};

const REVIEW_CATEGORY_LABEL = {
  duplicate_text: "중복 문장",
  verbose_summary: "긴 요약",
  title_mismatch: "제목 불일치",
  inconsistent_metric_expression: "지표 표현 불일치",
  unsupported_claim: "근거 확인 필요",
};

const REPORT_TITLE_SUGGESTION_INSTRUCTION = "승인된 보고서 내용과 근거를 바탕으로 간결하고 구체적인 보고서 제목을 제안해 주세요.";
const PAGE_CONSTRAINT_ERROR = "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED";

function assistantConversationMessage(result, titleOnly = false) {
  if (!result) return { role: "error" };
  if (result.status === "external_transfer_declined") {
    return { role: "assistant", text: result.message };
  }
  if (result.status === "approval_required") {
    return { role: "assistant", text: "현재 분석 결과만으로는 요청을 완료할 수 없어 분석 계획을 준비했습니다." };
  }
  if (result.status === "patch_approval_required") {
    return {
      role: "assistant",
      text: titleOnly
        ? "보고서 제목 제안을 준비했습니다. 적용 전에 확인해 주세요."
        : "현재 근거 자료로 만들 수 있는 변경안을 준비했습니다. 적용 전에 검토해 주세요.",
    };
  }
  if (result.message) return { role: "assistant", text: result.message };
  return { role: "assistant", trace: { requestId: result.requestId, ...result.trace } };
}

/** 동일 제목·기간의 승인 Artifact를 내부 ID 없이 구분할 수 있는 표시 근거를 만든다. */
function assistantArtifactOptionDisplay(option) {
  const title = option.title || "승인된 분석 결과";
  const period = analysisTimeLabel({}, option);
  const completed = option.completedAt ? `${formatSeoulTime(option.completedAt)} 생성` : "";
  return { period, completed, key: `${title}|${period}|${completed}` };
}

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

/** 승인 카드가 닫힌 뒤 terminal phase는 사용자 문구로, 오류 code는 접힌 기술 상세로 표시한다. */
function AssistantWorkflowStatus({ status, errorCode, requiredAction, retryable, onRetry, pending }) {
  if (!WORKFLOW_COPY[status] || !["completed", "failed", "cancelled"].includes(status)) return null;
  const [title, detail] = WORKFLOW_COPY[status];
  return <article className={`report-assistant-message assistant workflow-${status}`}>
    <ShieldCheck size={15} aria-hidden="true" />
    <p><b>{title}</b><br />{detail}
      {status === "failed" ? <small>{REQUIRED_ACTION_COPY[requiredAction] || REQUIRED_ACTION_COPY.NONE}</small> : null}
      {status === "failed" && retryable
        ? <button type="button" onClick={onRetry} disabled={pending}>새 세션으로 다시 시도</button>
        : null}
    </p>
    {errorCode ? <AssistantTechnicalDetails><code>{errorCode}</code></AssistantTechnicalDetails> : null}
  </article>;
}

/** 서버가 허용한 대기 phase만 취소하고 실행·저장 중에는 새로고침 안내만 표시한다. */
function AssistantCancelAction({ status, onCancel, pending }) {
  if (["ready", "waiting_patch_approval", "waiting_approval"].includes(status)) {
    return <button type="button" className="report-assistant-cancel" onClick={onCancel} disabled={pending}>
      <X size={12} aria-hidden="true" />요청 취소
    </button>;
  }
  if (["running_data_agent", "waiting_artifact", "saving_revision"].includes(status)) {
    return <p className="report-assistant-processing-note">처리 중에는 취소할 수 없습니다. 잠시 후 서버 상태를 새로 확인해 주세요.</p>;
  }
  return null;
}

/** 사용자에게는 처리 결과만 표시하고 계약·지연·오류 code는 접힌 기술 상세로 분리한다. */
function AssistantEvaluationReceipt({ evaluation }) {
  if (!evaluation) return null;
  const route = evaluation.route === "new_data"
    ? "신규 데이터 분석"
    : evaluation.route === "existing_artifact" ? "기존 분석 결과 편집" : "분류 없음";
  return <article className="report-assistant-message assistant">
    <ShieldCheck size={15} aria-hidden="true" />
    <p><b>요청 처리를 확인했습니다.</b><br />{route} · 보고서 새 버전 {evaluation.revision_created ? "생성" : "미생성"}</p>
    <AssistantTechnicalDetails>
      <dl>
        <div><dt>형식 검증</dt><dd>{evaluation.contract_valid ? "통과" : "실패"}</dd></div>
        {evaluation.latency_ms == null ? null : <div><dt>처리 시간</dt><dd>{Math.round(evaluation.latency_ms)}ms</dd></div>}
        {evaluation.error_code ? <div><dt>오류 코드</dt><dd><code>{evaluation.error_code}</code></dd></div> : null}
      </dl>
    </AssistantTechnicalDetails>
  </article>;
}

/** 서버가 확정한 외부 provider·전송·비전송 범위만 표시하고 명시적 체크 전에는 승인하지 않는다. */
function ExternalTransferConsentDialog({ disclosure, onAccept, onDecline, pending }) {
  const [accepted, setAccepted] = useState(false);
  const dialogRef = useRef(null);
  const checkboxRef = useRef(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    setAccepted(false);
    const dialog = dialogRef.current;
    if (!disclosure || !dialog || dialog.open) return;
    const returnFocus = document.activeElement;
    dialog.showModal();
    requestAnimationFrame(() => checkboxRef.current?.focus());
    return () => {
      if (dialog.open) dialog.close();
      requestAnimationFrame(() => {
        if (returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus();
      });
    };
  }, [disclosure?.disclosure_hash, disclosure?.disclosure_id]);
  if (!disclosure) return null;
  return <dialog
    ref={dialogRef}
    className="report-assistant-consent-dialog"
    aria-labelledby={titleId}
    aria-describedby={descriptionId}
    onCancel={(event) => {
      event.preventDefault();
      if (!pending) onDecline();
    }}
  >
    <header>
      <span><ShieldCheck size={17} aria-hidden="true" /></span>
      <div><small>외부 모델 전송 동의</small><h3 id={titleId}>요청을 계속하기 전에 전송 범위를 확인해 주세요</h3></div>
      <button type="button" aria-label="외부 전송 동의 닫기" onClick={onDecline} disabled={pending}><X size={16} /></button>
    </header>
    <p id={descriptionId}>아래 범위만 표시된 처리 경로로 전송합니다. 비전송 항목은 모델 요청에 포함하지 않습니다.</p>
    <div className="report-assistant-consent-body">
      <section aria-labelledby={`${titleId}-routes`}>
        <h4 id={`${titleId}-routes`}>처리 경로</h4>
        <ul className="report-assistant-consent-routes">
          {disclosure.provider_routes.map((route) => <li key={`${route.node}:${route.route_id}`}>
            <span>
              <b>{route.route_label}</b>
              <small>{route.provider} · {route.model}</small>
              <small className="report-assistant-consent-origin">전송 목적지 {route.destination_origin}</small>
            </span>
            <em>{route.data_boundary === "external" ? "외부 전송" : "내부 처리"}</em>
          </li>)}
        </ul>
      </section>
      <div className="report-assistant-consent-scopes">
        <section aria-labelledby={`${titleId}-included`}>
          <h4 id={`${titleId}-included`}>전송하는 정보</h4>
          {disclosure.data_scopes.length
            ? <ul>{disclosure.data_scopes.map((scope) => <li key={scope}>{externalTransferScopeLabel(scope)}</li>)}</ul>
            : <p>전송 범위 없음</p>}
        </section>
        <section aria-labelledby={`${titleId}-excluded`}>
          <h4 id={`${titleId}-excluded`}>전송하지 않는 정보</h4>
          {disclosure.excluded_data.length
            ? <ul>{disclosure.excluded_data.map((scope) => <li key={scope}>{scope}</li>)}</ul>
            : <p>별도 제외 항목 없음</p>}
        </section>
      </div>
      <p className="report-assistant-consent-warning" role="note">
        <ShieldCheck size={14} aria-hidden="true" />
        <span><b>콘텐츠의 민감정보를 확인해 주세요.</b><small>{disclosure.content_warning}</small></span>
      </p>
      <label className="report-assistant-consent-check">
        <input
          ref={checkboxRef}
          type="checkbox"
          checked={accepted}
          onChange={(event) => setAccepted(event.target.checked)}
          disabled={pending}
        />
        <span><b>이 Report Assistant 세션에서 동일 보고서 버전·근거·전송 범위의 외부 처리를 허용합니다.</b><small>보고서 버전·근거·전송 범위 또는 처리 경로가 바뀌면 다시 동의해야 합니다. 동의하지 않으면 요청을 실행하지 않습니다.</small></span>
      </label>
      <small className="report-assistant-consent-policy">정책 {disclosure.policy_version} · 동의 선택 가능 기한 {formatSeoulTime(disclosure.expires_at)}</small>
    </div>
    <footer>
      <button type="button" onClick={onDecline} disabled={pending}>취소</button>
      <button type="button" className={`primary ${pending ? "pending" : ""}`} onClick={onAccept} disabled={!accepted || pending}>
        {pending ? <LoaderCircle size={14} aria-hidden="true" /> : <Check size={14} aria-hidden="true" />}
        동의하고 요청 계속
      </button>
    </footer>
  </dialog>;
}

/** 새 데이터 분석 계획과 서버 소유 실행 단계를 표시하고 승인·거절만 사용자에게 위임한다. */
function AssistantApproval({ request, status, onApprove, onReject, pending, mutationBlocked }) {
  if (!request) return null;
  const waiting = status === "waiting_approval";
  const [title, detail] = WORKFLOW_COPY[status] || ["새 데이터 분석 승인 필요", "승인 전에는 분석을 실행하지 않습니다."];
  return <section className={`report-assistant-approval ${waiting ? "waiting" : "active"}`} aria-label="새 데이터 분석 계획">
    <header><ShieldCheck size={15} aria-hidden="true" /><span><b>{title}</b><small>{detail}</small></span></header>
    <dl>
      <div><dt>질문</dt><dd>{request.question}</dd></div>
      <div><dt>필요 이유</dt><dd>{request.reason}</dd></div>
      <div><dt>조회 범위</dt><dd>{request.scope}</dd></div>
    </dl>
    {waiting && <nav aria-label="분석 계획 결정">
      <button type="button" onClick={onReject} disabled={pending}><X size={12} />거절</button>
      <button type="button" className="primary" onClick={onApprove} disabled={pending || mutationBlocked}><Check size={12} />승인 후 분석</button>
    </nav>}
  </section>;
}

const PATCH_VALUE_PREVIEW_LENGTH = 160;

/** 긴 변경 내용은 네이티브 details로 접어 승인 카드와 작은 화면의 가독성을 유지한다. */
function PatchValue({ label, value }) {
  if (value.length <= PATCH_VALUE_PREVIEW_LENGTH) return <small><em>{label}</em>{value}</small>;
  const summary = `${value.slice(0, PATCH_VALUE_PREVIEW_LENGTH - 1).trimEnd()}…`;
  return <details className="report-assistant-patch-detail">
    <summary><em>{label}</em><span>{summary}</span><b>내용 펼치기</b></summary>
    <small>{value}</small>
  </details>;
}

/** 서버가 검증·dry-run한 제한 patch의 요약과 연산을 적용 전에 표시한다. */
function AssistantPatchApproval({ preview, status, errorCode, errorPageCounts, onApprove, onReject, pending, mutationBlocked }) {
  const [selectedIndexes, setSelectedIndexes] = useState([]);
  const [errorSelectionKey, setErrorSelectionKey] = useState(null);
  const approvalRef = useRef(null);
  const operationIdPrefix = useId();
  useEffect(() => {
    if (!preview) {
      setSelectedIndexes([]);
      return;
    }
    const initialIndexes = (
      preview.approvedIndexes?.length
        ? [...preview.approvedIndexes]
        : preview.items
            .filter((item) => item.impact_category !== "DESTRUCTIVE")
            .map((item) => item.index)
    );
    setSelectedIndexes(closeReportPatchSelection(preview.items, initialIndexes));
  }, [preview?.requestId]);
  useEffect(() => {
    if (preview && errorCode) approvalRef.current?.focus();
  }, [errorCode, preview?.requestId]);
  useEffect(() => {
    setErrorSelectionKey(errorCode ? selectedIndexes.join(",") : null);
  }, [errorCode, errorPageCounts?.exactPageCount, errorPageCounts?.verifiedPageCount, preview?.requestId]);
  if (!preview) return null;
  const waiting = status === "waiting_patch_approval";
  const titleOnly = preview.items.length === 1 && preview.items[0].operation === "set_report_title";
  const allIndexes = preview.items.map((item) => item.index);
  const selectedItems = preview.items.filter((item) => selectedIndexes.includes(item.index));
  const impactCategories = [...new Set(selectedItems.map((item) => item.impact_category))];
  const evidenceRequired = selectedItems.filter((item) => item.evidence_required).length;
  const evidenceCited = selectedItems.filter((item) => item.evidence_required && item.evidence_count > 0).length;
  const hasDestructiveItems = preview.items.some((item) => item.impact_category === "DESTRUCTIVE");
  const hasExactPageConstraint = Number.isInteger(preview.exactPageCount);
  const allOperationsSelected = selectedIndexes.length === allIndexes.length
    && allIndexes.every((index) => selectedIndexes.includes(index));
  const pageConstraintNeedsRevalidation = hasExactPageConstraint && !allOperationsSelected;
  const pageConstraintSatisfied = hasExactPageConstraint
    && allOperationsSelected
    && preview.verifiedPageCount === preview.exactPageCount;
  const pageConstraintMismatched = hasExactPageConstraint
    && allOperationsSelected
    && !pageConstraintSatisfied;
  const pageConstraintError = errorCode === PAGE_CONSTRAINT_ERROR
    && errorSelectionKey === selectedIndexes.join(",");
  const pageConstraintErrorReceipt = pageConstraintError
    && Number.isSafeInteger(errorPageCounts?.exactPageCount)
    && Number.isSafeInteger(errorPageCounts?.verifiedPageCount)
    ? errorPageCounts
    : null;
  const pageGroups = groupReportPatchItemsByPage(preview.items);
  const toggleOperation = (index) => setSelectedIndexes((current) => (
    current.includes(index)
      ? removeReportPatchSelection(preview.items, current, index)
      : closeReportPatchSelection(preview.items, [...current, index])
  ));
  return <section ref={approvalRef} tabIndex={-1} className={`report-assistant-approval ${waiting ? "waiting" : "active"}`} aria-label={titleOnly ? "AI 보고서 제목 제안" : "AI 보고서 변경안"}>
    <header><ShieldCheck size={15} aria-hidden="true" /><span><b>{waiting ? titleOnly ? "제목 제안 확인" : "AI 변경안 검토 필요" : "저장 재개"}</b><small>승인 전에는 현재 보고서를 변경하지 않습니다.</small></span></header>
    <dl>
      <div><dt>변경 요약</dt><dd>{preview.summary}</dd></div>
      <div><dt>적용 작업</dt><dd>{preview.operations.map((operation) => PATCH_OPERATION_LABEL[operation] || operation).join(" · ")}</dd></div>
      {preview.evidenceRefs?.length
        ? <div><dt>사용 근거</dt><dd>{preview.evidenceRefs.map(reportEvidenceLabel).join(" · ")}</dd></div>
        : null}
    </dl>
    {hasExactPageConstraint ? <div
      className={`report-assistant-page-check ${pageConstraintNeedsRevalidation ? "pending" : pageConstraintSatisfied ? "matched" : "mismatched"}`}
      role="status"
      aria-label={`페이지 수 검증: 요청 ${preview.exactPageCount}페이지, 전체 변경안 렌더 ${preview.verifiedPageCount}페이지, ${pageConstraintNeedsRevalidation ? "선택 항목은 승인 시 다시 검증" : pageConstraintSatisfied ? "일치" : "조정 필요"}`}
    >
      <span><small>요청</small><b>{preview.exactPageCount}페이지</b></span>
      <span aria-hidden="true">→</span>
      <span><small>전체안 렌더</small><b>{preview.verifiedPageCount}페이지</b></span>
      <strong>{pageConstraintNeedsRevalidation ? "승인 시 재검증" : pageConstraintSatisfied ? "일치" : "조정 필요"}</strong>
    </div> : null}
    {pageConstraintError ? <p className="report-assistant-page-error" role="alert">
      {pageConstraintErrorReceipt
        ? `선택한 변경안을 렌더한 결과가 요청 ${pageConstraintErrorReceipt.exactPageCount}페이지가 아닌 ${pageConstraintErrorReceipt.verifiedPageCount}페이지여서 저장하지 않았습니다. 변경안을 조정한 뒤 다시 검토해 주세요.`
        : "요청한 페이지 수와 실제 렌더 결과가 일치하지 않아 저장하지 않았습니다. 변경안을 조정한 뒤 다시 검토해 주세요."}
    </p> : null}
    <dl className="report-assistant-patch-impact" aria-label="선택한 변경 영향">
      <div><dt>변경 영향</dt><dd>{selectedItems.length}개 작업 · {impactCategories.map((category) => PATCH_IMPACT_LABEL[category]).join(" · ") || "선택 없음"}</dd></div>
      <div><dt>근거 연결</dt><dd>{evidenceRequired ? `${evidenceCited}/${evidenceRequired}개 연결` : "필요 없음"}</dd></div>
      <div><dt>복구</dt><dd>새 버전으로 저장되어 이전 버전을 유지합니다.</dd></div>
      {impactCategories.includes("DESTRUCTIVE")
        ? <div className="warning"><dt>주의</dt><dd>선택 항목에 블록 삭제 또는 이전 버전 복원이 포함됩니다.</dd></div>
        : null}
    </dl>
    {!titleOnly && <div className="report-assistant-patch-selection" role="group" aria-label="변경 선택 도구">
      <span aria-live="polite">{selectedIndexes.length} / {preview.items.length}개 선택</span>
      <button type="button" onClick={() => setSelectedIndexes(allIndexes)} disabled={!waiting || pending || selectedIndexes.length === allIndexes.length}>{hasDestructiveItems ? "모두 선택(삭제 포함)" : "전체 선택"}</button>
      <button type="button" onClick={() => setSelectedIndexes([])} disabled={!waiting || pending || !selectedIndexes.length}>전체 해제</button>
    </div>}
    {hasDestructiveItems && waiting ? <p className="report-assistant-patch-safety-note"><ShieldCheck size={13} aria-hidden="true" />삭제·복원 작업은 안전을 위해 자동 선택하지 않습니다. 적용할 항목을 직접 확인해 주세요.</p> : null}
    <div className="report-assistant-patch-items" aria-label="적용할 변경 선택">
      {pageGroups.map((group) => <section className="report-assistant-patch-page" key={group.key}>
        <header><b>{group.pageIndex == null ? "보고서 전체" : `${group.pageIndex}페이지`}</b><small>{group.items.length}개 변경</small></header>
        <div>
          {group.items.map((item) => {
            const inputId = `${operationIdPrefix}-operation-${item.index}`;
            return <div className="report-assistant-patch-item" key={`${preview.requestId}-${item.index}`}>
              <input
                id={inputId}
                type="checkbox"
                checked={selectedIndexes.includes(item.index)}
                disabled={titleOnly || !waiting || pending}
                onChange={() => toggleOperation(item.index)}
              />
              <label htmlFor={inputId}><span><b>{PATCH_OPERATION_LABEL[item.operation] || item.operation} · {item.target}</b>
                {item.depends_on_indexes.length > 0 ? <small className="report-assistant-patch-dependency">필요한 선행 작업 {item.depends_on_indexes.length}개가 함께 적용됩니다.</small> : null}
                {item.before == null ? null : <PatchValue label="변경 전" value={item.before} />}
                {item.after == null ? null : <PatchValue label="변경 후" value={item.after} />}
              </span>
              </label>
            </div>;
          })}
        </div>
      </section>)}
    </div>
    <nav aria-label={titleOnly ? "제목 제안 결정" : "AI 변경안 결정"}>
      {waiting && <button type="button" onClick={onReject} disabled={pending}><X size={12} />취소</button>}
      <button
        type="button"
        className="primary"
        onClick={() => onApprove(selectedIndexes)}
        disabled={pending || mutationBlocked || !selectedIndexes.length || pageConstraintMismatched}
      ><Check size={12} />{waiting
          ? pageConstraintMismatched
            ? "분량 조정 필요"
            : titleOnly ? "제목 적용" : `선택 ${selectedIndexes.length}개 적용`
          : "저장 재개"}</button>
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
  externalTransferDisclosure = null,
  externalTransferConsentPending = false,
  hasUnsavedChanges = false,
  instruction,
  onApproveDataRequest,
  onApprovePatch,
  onAcceptExternalTransfer,
  onCancel,
  onInstructionChange,
  onDeclineExternalTransfer,
  onRejectDataRequest,
  onRejectPatch,
  onReview,
  onRetry,
  onSelectArtifacts,
  onSuggestTitle,
  onSubmit,
  pending,
  patchPreview = null,
  review = null,
  sessionId = "",
  sessionOperationScope = "full_report",
  sessionTurnHistory = [],
  suggestions = [],
  selectedBlock,
  trace,
  workflowStatus = "",
  workflowError = "",
  workflowErrorPageCounts = null,
  workflowRequiredAction = "NONE",
  workflowRetryable = false,
}) {
  const [messages, setMessages] = useState(
    () => reportAssistantMessagesFromTurnHistory(sessionTurnHistory),
  );
  const [evidencePickerOpen, setEvidencePickerOpen] = useState(false);
  const [evidencePickerPending, setEvidencePickerPending] = useState(false);
  const [draftArtifactIds, setDraftArtifactIds] = useState(assistantArtifactIds);
  const [scopeState, dispatchScope] = useReducer(
    reduceReportAssistantScope,
    INITIAL_REPORT_ASSISTANT_SCOPE_STATE,
  );
  const evidencePickerRef = useRef(null);
  const evidencePickerTitleId = useId();
  const waiting = pending === "assistant";
  const workflowActive = Boolean(approvalRequest || patchPreview);
  const titleOnlyPatch = Boolean(
    patchPreview?.items?.length === 1 && patchPreview.items[0].operation === "set_report_title",
  );
  const canRefinePatch = Boolean(patchPreview) && !titleOnlyPatch && workflowStatus === "waiting_patch_approval";
  const composerBlocked = workflowActive && !canRefinePatch;
  const disabled = !canEdit
    || !artifact
    || !instruction.trim()
    || Boolean(pending)
    || composerBlocked
    || hasUnsavedChanges;
  const artifactOptionDisplays = artifactOptions.map(assistantArtifactOptionDisplay);

  useEffect(() => {
    if (!evidencePickerOpen) setDraftArtifactIds(assistantArtifactIds);
  }, [assistantArtifactIds, evidencePickerOpen]);

  useEffect(() => {
    dispatchScope({
      type: "session",
      sessionId,
      status: workflowStatus,
      operationScope: sessionOperationScope,
    });
  }, [sessionId, sessionOperationScope, workflowStatus]);

  useEffect(() => {
    if (!sessionTurnHistory.length) return;
    setMessages((current) => hydrateReportAssistantMessages(current, sessionTurnHistory));
  }, [sessionId, sessionTurnHistory]);

  useEffect(() => {
    const picker = evidencePickerRef.current;
    if (evidencePickerOpen && picker && !picker.open) picker.showModal();
  }, [evidencePickerOpen]);

  const openEvidencePicker = useCallback(() => {
    setDraftArtifactIds(assistantArtifactIds);
    setEvidencePickerOpen(true);
  }, [assistantArtifactIds]);

  const toggleDraftArtifact = useCallback((artifactId) => {
    if (!artifactId || artifactId === assistantArtifactIds[0]) return;
    setDraftArtifactIds((current) => current.includes(artifactId)
      ? current.filter((item) => item !== artifactId)
      : current.length < 5 ? [...current, artifactId] : current);
  }, [assistantArtifactIds]);

  const applyEvidenceSelection = useCallback(async () => {
    if (!onSelectArtifacts || evidencePickerPending) return;
    setEvidencePickerPending(true);
    try {
      const applied = await onSelectArtifacts(draftArtifactIds);
      if (applied) setEvidencePickerOpen(false);
    } finally {
      setEvidencePickerPending(false);
    }
  }, [draftArtifactIds, evidencePickerPending, onSelectArtifacts]);

  const submitInstruction = useCallback(async (event) => {
    event.preventDefault();
    const text = instruction.trim();
    if (!text || !artifact || !canEdit || pending || hasUnsavedChanges) return;
    const operationScope = scopeState.operationScope;
    setMessages((current) => [...current, { role: "user", text }]);
    const result = await onSubmit(text, operationScope);
    dispatchScope({ type: "message-result", operationScope, status: result?.status });
    setMessages((current) => [...current, assistantConversationMessage(result)]);
  }, [artifact, canEdit, hasUnsavedChanges, instruction, onSubmit, pending, scopeState.operationScope]);

  const requestTitleSuggestion = useCallback(async () => {
    if (!artifact || !canEdit || pending || workflowActive || !onSuggestTitle || hasUnsavedChanges) return;
    const preservedInstruction = instruction;
    dispatchScope({ type: "title-request" });
    setMessages((current) => [...current, { role: "user", text: "보고서 제목을 제안해 주세요." }]);
    let result;
    try {
      result = await onSuggestTitle(REPORT_TITLE_SUGGESTION_INSTRUCTION);
    } finally {
      onInstructionChange(preservedInstruction);
    }
    dispatchScope({ type: "message-result", operationScope: "report_title", status: result?.status });
    setMessages((current) => [...current, assistantConversationMessage(result, true)]);
  }, [artifact, canEdit, hasUnsavedChanges, instruction, onInstructionChange, onSuggestTitle, pending, workflowActive]);

  return <aside className="report-assistant-panel" aria-label="보고서 도우미">
    <header>
      <span className="report-assistant-mark"><Sparkles size={15} aria-hidden="true" /></span>
      <div><p>REPORT ASSISTANT</p><h2>보고서 AI Assistant</h2><small title={selectedBlock?.title || "선택 없음"}>선택된 블록 · {selectedBlock?.title || "선택 없음"}</small></div>
    </header>

    <div className="report-assistant-context">
      <Database size={14} aria-hidden="true" />
      <span><b title={artifactTitle || "분석 결과를 선택해 주세요"}>{artifactTitle || "분석 결과를 선택해 주세요"}</b><small>{artifact ? "승인된 분석 결과를 근거로 초안을 다시 구성합니다." : "블록 라이브러리에서 분석 결과를 먼저 선택하세요."}</small></span>
      {artifactOptions.length > 1 && <button
        type="button"
        onClick={openEvidencePicker}
        disabled={!canEdit || Boolean(pending) || workflowActive}
      >근거 변경{assistantArtifactIds.length > 1 ? ` · ${assistantArtifactIds.length}` : ""}</button>}
    </div>

    <ExternalTransferConsentDialog
      disclosure={externalTransferDisclosure}
      onAccept={onAcceptExternalTransfer}
      onDecline={onDeclineExternalTransfer}
      pending={externalTransferConsentPending}
    />

    {evidencePickerOpen && <dialog
      ref={evidencePickerRef}
      className="report-assistant-evidence-picker"
      aria-labelledby={evidencePickerTitleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!evidencePickerPending) setEvidencePickerOpen(false);
      }}
      onClose={() => setEvidencePickerOpen(false)}
    >
      <header>
        <div><small>검증된 근거 자료</small><h3 id={evidencePickerTitleId}>종합 편집 근거 선택</h3></div>
        <button type="button" aria-label="근거 선택 닫기" onClick={() => setEvidencePickerOpen(false)} disabled={evidencePickerPending}><X size={16} /></button>
      </header>
      <p>대표 근거를 포함해 최대 5개까지 선택할 수 있습니다. 선택한 근거만 검증해 Assistant에 전달합니다.</p>
      <div className="report-assistant-evidence-options">
        {artifactOptions.map((option, optionIndex) => {
          const primary = option.artifactId === assistantArtifactIds[0];
          const checked = draftArtifactIds.includes(option.artifactId);
          const display = artifactOptionDisplays[optionIndex];
          const matchingOptions = artifactOptionDisplays.filter((candidate) => candidate.key === display.key);
          const duplicateOrder = matchingOptions.length > 1
            ? artifactOptionDisplays.slice(0, optionIndex + 1)
                .filter((candidate) => candidate.key === display.key).length
            : 0;
          const duplicateLabel = duplicateOrder
            ? `동일 조건 ${duplicateOrder}/${matchingOptions.length}`
            : "";
          const detail = [display.period, display.completed, duplicateLabel].filter(Boolean).join(" · ");
          return <label key={option.artifactId} title={option.title || "승인된 분석 결과"}>
            <input
              type="checkbox"
              checked={checked}
              disabled={primary || evidencePickerPending || (!checked && draftArtifactIds.length >= 5)}
              onChange={() => toggleDraftArtifact(option.artifactId)}
            />
            <span><b>{option.title || "승인된 분석 결과"}</b><small>{primary ? "대표 근거 · 필수" : detail || "승인된 분석 결과"}</small></span>
          </label>;
        })}
      </div>
      <footer>
        <span>{draftArtifactIds.length} / 5개 선택</span>
        <button type="button" onClick={() => setEvidencePickerOpen(false)} disabled={evidencePickerPending}>취소</button>
        <button type="button" className="primary" onClick={applyEvidenceSelection} disabled={evidencePickerPending || !draftArtifactIds.length}>{evidencePickerPending ? <LoaderCircle size={14} /> : <Check size={14} />}선택 적용</button>
      </footer>
    </dialog>}

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
        mutationBlocked={hasUnsavedChanges}
      />
      <AssistantPatchApproval
        preview={patchPreview}
        status={workflowStatus}
        errorCode={workflowError}
        errorPageCounts={workflowErrorPageCounts}
        onApprove={onApprovePatch}
        onReject={onRejectPatch}
        pending={Boolean(pending)}
        mutationBlocked={hasUnsavedChanges}
      />
      <AssistantQualityReview review={review} onSelect={onInstructionChange} pending={Boolean(pending)} />
      <AssistantWorkflowStatus
        status={workflowStatus}
        requiredAction={workflowRequiredAction}
        retryable={workflowRetryable}
        onRetry={onRetry}
        pending={Boolean(pending)}
      />
      <AssistantCancelAction status={workflowStatus} onCancel={onCancel} pending={Boolean(pending)} />
      <AssistantEvaluationReceipt evaluation={evaluation} />
      {waiting && <article className="report-assistant-message assistant pending"><LoaderCircle size={15} aria-hidden="true" /><p>근거를 유지하며 검토할 변경안을 준비하고 있습니다.</p></article>}
    </div>

    <div className="report-assistant-quick" aria-label="빠른 요청">
      <button type="button" onClick={requestTitleSuggestion} disabled={!canEdit || !artifact || Boolean(pending) || workflowActive || hasUnsavedChanges}>제목 제안</button>
      <button type="button" onClick={onReview} disabled={!canEdit || !artifact || Boolean(pending) || workflowActive || hasUnsavedChanges}>보고서 품질 검토</button>
      {suggestions.map((request) => <button type="button" title={request} onClick={() => onInstructionChange(request)} disabled={!canEdit || !artifact || Boolean(pending) || composerBlocked} key={request}>{request}</button>)}
    </div>

    {hasUnsavedChanges && <p className="report-assistant-save-first" role="status">현재 편집 내용을 저장하면 AI 제목 제안, 품질 검토와 변경안 적용을 사용할 수 있습니다.</p>}

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
          placeholder={canRefinePatch ? "예: 차트 위치는 유지하고 요약만 두 문장으로 바꿔줘" : artifact ? "예: 핵심 요약을 세 문장으로 정리해줘" : "분석 결과를 선택하면 요청할 수 있습니다."}
          disabled={!canEdit || !artifact || Boolean(pending) || composerBlocked}
        />
        <button type="submit" aria-label={canRefinePatch ? "변경안 수정 요청" : "AI 변경안 요청 보내기"} disabled={disabled}>{waiting ? <LoaderCircle size={16} /> : <Send size={16} />}</button>
      </div>
      <small>생성 결과는 적용 전 변경안이며, 승인해야 새 버전으로 저장됩니다.</small>
    </form>
  </aside>;
});
