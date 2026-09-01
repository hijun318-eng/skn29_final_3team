/** 보고서 정의·실행·schedule·최종 asset HTTP 포트를 fail-closed로 제공하는 모듈이다. */
import {
  REPORT_REQUEST_CONTEXT_VERSION,
  assertReportCurrencyDisplayUnit,
  assertReportContractVersion,
  assertReportOrientation,
  normalizeReportDefinition,
  normalizeReportDefinitionLifecycle,
  normalizeReportDocument,
  normalizeReportRun,
  type ManualRunCommandResponse,
  type ReportBlockRequest,
  type ReportDefinitionListResponse,
  type ReportDefinitionLifecycleResponse,
  type ReportDefinitionPermanentDeleteResponse,
  type ReportDefinitionResponse,
  type ReportDefinitionVersion,
  type ReportDocument,
  type ReportDocumentResponse,
  type ReportCurrencyDisplayUnit,
  type ReportOrientation,
  type ReportRun,
  type ReportRunListResponse,
  type ReportRunResponse,
  type ReportScheduleListResponse,
  type ReportScheduleResponse,
  type RunDueReportScheduleResponse,
  type ReportAssistantPhase,
  type ReportAssistantOperationScope,
  type ReportAssistantProposalResponse,
  type ReportAssistantReviewResponse,
  type ReportAssistantSessionResponse,
  type ReportAssistantEvaluationResponse,
  type ReportAssistantFailureListResponse,
  type ReportAssistantOperationsSummaryResponse,
  type ReportAssistantExternalProviderRoute,
  type ReportAssistantExternalTransferDisclosure,
  type ReportAssistantExternalTransferConsentResponse,
  type ReportAssistantExternalTransferScope,
} from "../contracts/report.ts";
import { createUuid } from "../utils/createUuid.ts";

type Fetch = typeof fetch;
const env = import.meta.env ?? {};
const ASSISTANT_PHASES: readonly ReportAssistantPhase[] = [
  "ready", "waiting_patch_approval", "waiting_approval", "running_data_agent", "waiting_artifact",
  "saving_revision", "completed", "failed", "cancelled",
];
const ASSISTANT_REQUIRED_ACTIONS = [
  "NONE", "RETRY", "REFRESH", "REAUTHENTICATE", "REOPEN_LATEST_REPORT", "CONTACT_ADMIN",
  "REVIEW_EXTERNAL_TRANSFER",
] as const;
const ASSISTANT_OPERATION_SCOPES: readonly ReportAssistantOperationScope[] = ["full_report", "report_title"];
const ASSISTANT_PATCH_IMPACT_CATEGORIES = ["CONTENT", "LAYOUT", "DESTRUCTIVE"] as const;

function assertNullableAssistantPageCount(
  value: unknown,
  label: string,
  maximum?: number,
): asserts value is number | null {
  if (value !== null && (
    !Number.isSafeInteger(value)
    || Number(value) < 1
    || (maximum !== undefined && Number(value) > maximum)
  )) {
    const range = maximum === undefined ? "1 이상의 안전한 정수" : `1~${maximum} 사이의 정수`;
    throw new Error(`Report Assistant ${label}는 ${range} 또는 null이어야 합니다.`);
  }
}

function assertAssistantSession(
  session: ReportAssistantSessionResponse,
): ReportAssistantSessionResponse {
  if (!ASSISTANT_PHASES.includes(session.phase)) {
    throw new Error(`지원하지 않는 Report Assistant phase입니다: ${session.phase}`);
  }
  if (!ASSISTANT_OPERATION_SCOPES.includes(session.operation_scope)) {
    throw new Error(`지원하지 않는 Report Assistant 작업 범위입니다: ${session.operation_scope}`);
  }
  if (!Array.isArray(session.turn_history)
    || session.turn_history.length > 12
    || session.turn_history.length % 2 !== 0
    || session.turn_history.some((turn, index) => (
      !turn
      || turn.role !== (index % 2 === 0 ? "user" : "assistant")
      || typeof turn.content !== "string"
      || !turn.content.trim()
      || turn.content.length > 1000
    ))) {
    throw new Error("Report Assistant 대화 이력 계약이 올바르지 않습니다.");
  }
  if (session.definition_version < 1 || session.base_revision < 1) {
    throw new Error("Report Assistant revision은 1 이상이어야 합니다.");
  }
  if (!Array.isArray(session.artifact_ids)
    || session.artifact_ids.length < 1
    || session.artifact_ids.length > 6
    || session.artifact_ids[0] !== session.artifact_id
    || new Set(session.artifact_ids).size !== session.artifact_ids.length) {
    throw new Error("Report Assistant Artifact 결속 계약이 올바르지 않습니다.");
  }
  assertNullableAssistantPageCount(session.exact_page_count, "요청 페이지 수", 20);
  assertNullableAssistantPageCount(session.verified_page_count, "검증 페이지 수");
  if (session.phase === "waiting_patch_approval" && session.verified_page_count === null) {
    throw new Error("patch 승인 대기 세션에는 렌더 페이지 검증 결과가 필요합니다.");
  }
  if (["ready", "waiting_approval", "running_data_agent", "waiting_artifact"].includes(session.phase)
    && session.verified_page_count !== null) {
    throw new Error("변경안 생성 전에는 렌더 페이지 검증 결과가 없어야 합니다.");
  }
  if (["saving_revision", "completed"].includes(session.phase)
    && session.exact_page_count !== null
    && session.verified_page_count !== session.exact_page_count) {
    throw new Error("저장 phase의 실제 페이지 수가 요청한 페이지 수와 일치하지 않습니다.");
  }
  if (["waiting_approval", "running_data_agent", "waiting_artifact", "saving_revision"].includes(session.phase)
    && !session.analysis_plan && !session.patch_request_id) {
    throw new Error("실행 phase에는 분석 계획 또는 patch 요청이 필요합니다.");
  }
  if (session.phase === "waiting_patch_approval"
    && (!session.patch_request_id || !session.patch_summary || !session.patch_operations?.length)) {
    throw new Error("patch 승인 대기 세션에는 변경 미리보기가 필요합니다.");
  }
  const patchPreview = Array.isArray(session.patch_preview)
    ? session.patch_preview
    : (session.patch_operations || []).map((operation, index) => ({
        index,
        depends_on_indexes: [],
        page_index: null,
        operation,
        target: operation,
        before: null,
        after: null,
      }));
  const approvedOperationIndexes = Array.isArray(session.approved_operation_indexes)
    ? session.approved_operation_indexes
    : [];
  if ((session.phase === "waiting_patch_approval"
      && patchPreview.length !== session.patch_operations.length)
    || patchPreview.some((item, index) => (
      item.index !== index
      || item.operation !== session.patch_operations[index]
      || !Array.isArray(item.depends_on_indexes)
      || item.depends_on_indexes.some((dependencyIndex, position, dependencies) => (
        !Number.isInteger(dependencyIndex)
        || dependencyIndex < 0
        || dependencyIndex >= index
        || (position > 0 && dependencies[position - 1] >= dependencyIndex)
      ))
      || (item.page_index !== null
        && (!Number.isInteger(item.page_index) || item.page_index < 1))
      || typeof item.target !== "string"
      || !item.target.trim()
      || !ASSISTANT_PATCH_IMPACT_CATEGORIES.includes(item.impact_category)
      || typeof item.evidence_required !== "boolean"
      || !Number.isInteger(item.evidence_count)
      || item.evidence_count < 0
      || item.evidence_count > 16
      || item.evidence_required !== (item.evidence_count > 0)
    ))
    || approvedOperationIndexes.some((index, position, indexes) => (
      !Number.isInteger(index)
      || index < 0
      || index >= session.patch_operations.length
      || (position > 0 && indexes[position - 1] >= index)
    ))) {
    throw new Error("Report Assistant patch 미리보기·선택 계약이 올바르지 않습니다.");
  }
  if (!Array.isArray(session.patch_evidence_refs)) {
    throw new Error("Report Assistant 근거 참조 계약이 올바르지 않습니다.");
  }
  if (!ASSISTANT_REQUIRED_ACTIONS.includes(session.required_action)) {
    throw new Error(`지원하지 않는 Report Assistant 조치입니다: ${session.required_action}`);
  }
  if (session.retryable && (session.phase !== "failed" || session.required_action !== "RETRY")) {
    throw new Error("재시도 가능한 Report Assistant 세션 계약이 올바르지 않습니다.");
  }
  return {
    ...session,
    patch_preview: patchPreview,
    approved_operation_indexes: approvedOperationIndexes,
  };
}

function assertAssistantSessionRequest(
  session: ReportAssistantSessionResponse,
  assistantRequestId: string,
): ReportAssistantSessionResponse {
  const checked = assertAssistantSession(session);
  if (checked.assistant_request_id !== assistantRequestId) {
    throw new Error("Report Assistant 응답의 세션 ID가 요청과 일치하지 않습니다.");
  }
  return checked;
}

function assertAssistantSuggestions(value: unknown): asserts value is readonly string[] {
  if (!Array.isArray(value)
    || value.length > 3
    || value.some((item) => typeof item !== "string" || !item.trim() || item.length > 500)
    || new Set(value).size !== value.length) {
    throw new Error("Report Assistant 후속 제안 계약이 올바르지 않습니다.");
  }
}

function isNonEmptyString(value: unknown, maximum = 500): value is string {
  return typeof value === "string" && Boolean(value.trim()) && value.length <= maximum;
}

const EXTERNAL_TRANSFER_NODES = ["report_assistant", "report_assistant_turn", "report_assistant_review"] as const;
const EXTERNAL_TRANSFER_SCOPES: readonly ReportAssistantExternalTransferScope[] = [
  "user_instruction", "assistant_turn_history", "report_metadata_layout", "report_block_content",
  "selected_artifact_metadata", "selected_artifact_narrative", "selected_artifact_metrics", "selected_artifact_chart_spec",
  "selected_artifact_table_snapshot", "pending_patch", "approved_new_analysis_artifact",
];
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

function isCanonicalHttpsOrigin(value: unknown): value is string {
  if (!isNonEmptyString(value, 255)) return false;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:"
      && !parsed.username
      && !parsed.password
      && parsed.pathname === "/"
      && !parsed.search
      && !parsed.hash
      && parsed.origin === value;
  } catch {
    return false;
  }
}

function assertExternalProviderRoutes(value: unknown): asserts value is readonly ReportAssistantExternalProviderRoute[] {
  if (!Array.isArray(value)
    || value.length < 1
    || value.length > 3
    || value.some((route) => (
      !route
      || !EXTERNAL_TRANSFER_NODES.includes(route.node)
      || !isNonEmptyString(route.route_id, 64)
      || !isNonEmptyString(route.route_label, 120)
      || !isNonEmptyString(route.provider, 64)
      || !isNonEmptyString(route.model, 255)
      || !["external", "internal"].includes(route.data_boundary)
      || !isCanonicalHttpsOrigin(route.destination_origin)
    ))) {
    throw new Error("Report Assistant 외부 처리 경로 공개 계약이 올바르지 않습니다.");
  }
}

function assertExternalDataScope(
  value: unknown,
  label: string,
  allowedValues?: readonly string[],
): asserts value is readonly string[] {
  if (!Array.isArray(value)
    || value.length < 1
    || value.length > 11
    || new Set(value).size !== value.length
    || value.some((item) => !isNonEmptyString(item, 300) || (allowedValues && !allowedValues.includes(item)))) {
    throw new Error(`Report Assistant ${label} 공개 계약이 올바르지 않습니다.`);
  }
}

function assertExternalTransferDisclosure(
  value: unknown,
  assistantRequestId?: string,
): ReportAssistantExternalTransferDisclosure {
  const disclosure = value as ReportAssistantExternalTransferDisclosure;
  if (!disclosure
    || !isUuid(disclosure.disclosure_id)
    || !isUuid(disclosure.assistant_request_id)
    || (assistantRequestId !== undefined && disclosure.assistant_request_id !== assistantRequestId)
    || !isNonEmptyString(disclosure.policy_version, 96)
    || !/^[0-9a-f]{64}$/.test(disclosure.disclosure_hash)
    || !isNonEmptyString(disclosure.expires_at, 100)
    || !Number.isFinite(Date.parse(disclosure.expires_at))
    || !isNonEmptyString(disclosure.content_warning, 500)
    || disclosure.consent_required !== true) {
    throw new Error("Report Assistant 외부 전송 공개문 계약이 올바르지 않습니다.");
  }
  assertExternalProviderRoutes(disclosure.provider_routes);
  if (!disclosure.provider_routes.some((route) => route.data_boundary === "external")) {
    throw new Error("Report Assistant 외부 전송 공개문에 외부 처리 경로가 없습니다.");
  }
  assertExternalDataScope(disclosure.data_scopes, "전송 범위", EXTERNAL_TRANSFER_SCOPES);
  assertExternalDataScope(disclosure.excluded_data, "비전송 범위");
  return disclosure;
}

function safeExternalTransferDisclosure(value: unknown): ReportAssistantExternalTransferDisclosure | null {
  try {
    return assertExternalTransferDisclosure(value);
  } catch {
    return null;
  }
}

function assertExternalTransferConsent(
  value: unknown,
  assistantRequestId: string,
): ReportAssistantExternalTransferConsentResponse {
  const receipt = value as ReportAssistantExternalTransferConsentResponse;
  if (!receipt
    || !isUuid(receipt.consent_id)
    || receipt.assistant_request_id !== assistantRequestId
    || !isNonEmptyString(receipt.policy_version, 96)
    || !isNonEmptyString(receipt.consented_at, 100)
    || !Number.isFinite(Date.parse(receipt.consented_at))) {
    throw new Error("Report Assistant 외부 전송 동의 receipt 계약이 올바르지 않습니다.");
  }
  assertExternalProviderRoutes(receipt.provider_routes);
  assertExternalDataScope(receipt.data_scopes, "동의 범위", EXTERNAL_TRANSFER_SCOPES);
  return receipt;
}

/** 초안 블록 교체와 함께 원자적으로 저장할 문서 표시 옵션이다. */
export interface ReplaceDraftBlocksOptions {
  readonly title?: string;
  readonly expectedDraftRevision: number;
  readonly orientation?: ReportOrientation;
  readonly currencyDisplayUnit?: ReportCurrencyDisplayUnit;
}

/** 보고서 HTTP 실패의 정책 조치와 trace를 손실 없이 전달하는 공개 오류 타입이다. */
export class ReportApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly requiredAction: string;
  readonly suggestions: string[];
  readonly missingRequirements: string[];
  readonly traceId: string;
  readonly exactPageCount: number | null;
  readonly verifiedPageCount: number | null;
  readonly assistantRequestId: string;
  readonly externalTransferDisclosure: ReportAssistantExternalTransferDisclosure | null;

  constructor(status: number, code: string, message: string, options: {
    retryable?: boolean;
    requiredAction?: string;
    suggestions?: string[];
    missingRequirements?: string[];
    traceId?: string;
    exactPageCount?: number | null;
    verifiedPageCount?: number | null;
    assistantRequestId?: string;
    externalTransferDisclosure?: ReportAssistantExternalTransferDisclosure | null;
  } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryable = options.retryable ?? false;
    this.requiredAction = options.requiredAction ?? "NONE";
    this.suggestions = options.suggestions ?? [];
    this.missingRequirements = options.missingRequirements ?? [];
    this.traceId = options.traceId ?? "";
    this.exactPageCount = options.exactPageCount ?? null;
    this.verifiedPageCount = options.verifiedPageCount ?? null;
    this.assistantRequestId = options.assistantRequestId ?? "";
    this.externalTransferDisclosure = options.externalTransferDisclosure ?? null;
  }
}

function safeErrorPageCount(value: unknown, maximum?: number): number | null {
  return Number.isSafeInteger(value)
    && Number(value) >= 1
    && (maximum === undefined || Number(value) <= maximum)
    ? Number(value)
    : null;
}

function contextHeaders(hasBody = false, explicitToken = ""): Record<string, string> {
  const token = explicitToken;
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(hasBody ? { "Content-Type": "application/json" } : {}),
    "X-Contract-Version": REPORT_REQUEST_CONTEXT_VERSION,
    "X-Timezone": "Asia/Seoul",
    "X-Trace-Id": createUuid(),
  };
}

async function parse<T>(response: Response): Promise<T> {
  // body가 손상된 오류에서도 상태 코드는 보존하되, 성공 데이터는 normalization/assertion을 우회하지 않는다.
  const payload: any = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.error && typeof payload.error === "object" && !Array.isArray(payload.error)
      ? payload.error
      : payload?.detail && typeof payload.detail === "object" && !Array.isArray(payload.detail)
        ? payload.detail
        : {};
    const disclosure = safeExternalTransferDisclosure(detail.disclosure);
    const code = detail.code || `HTTP_${response.status}`;
    const message = detail.message || "Report API 요청에 실패했습니다.";
    if (response.status === 401 && typeof window !== "undefined") window.dispatchEvent(new CustomEvent("answervice:session-expired"));
    throw new ReportApiError(response.status, code, message, {
      retryable: Boolean(detail.retryable),
      requiredAction: detail.required_action,
      suggestions: detail.suggestions,
      missingRequirements: detail.missing_requirements,
      traceId: detail.trace_id,
      exactPageCount: safeErrorPageCount(detail.exact_page_count, 20),
      verifiedPageCount: safeErrorPageCount(detail.verified_page_count),
      assistantRequestId: isNonEmptyString(detail.assistant_request_id, 200)
        ? detail.assistant_request_id
        : disclosure?.assistant_request_id,
      externalTransferDisclosure: disclosure,
    });
  }
  return payload as T;
}

async function ensureOk(response: Response): Promise<Response> {
  if (!response.ok) await parse<never>(response);
  return response;
}

/** 명시된 backend origin에 cookie 인증 보고서 요청을 보내며, 원본 계약 검증 실패를 그대로 전파한다. */
export function createReportClient(
  baseUrl = env.VITE_BACKEND_BASE_URL,
  request: Fetch = fetch,
  authToken = "",
) {
  if (!baseUrl) throw new Error("VITE_BACKEND_BASE_URL is required");
  const endpoint = (path: string) => `${baseUrl.replace(/\/$/, "")}${path}`;
  // AbortSignal을 transport까지 전달해야 화면 전환 시 stale 최종문서 요청과 pending 잠금을 함께 해제할 수 있다.
  const send = (path: string, method = "GET", body?: unknown, signal?: AbortSignal) => request(endpoint(path), {
    method,
    credentials: "include",
    headers: contextHeaders(body !== undefined, authToken),
    ...(signal ? { signal } : {}),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  return {
    async createDefinition(payload: { definition_id: string; title: string; blocks: readonly ReportBlockRequest[] }) {
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send("/reports/definitions", "POST", payload),
      ));
    },
    async createDraftFromArtifact(artifactId: string, title: string) {
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send("/reports/drafts/from-analysis-artifact", "POST", { artifact_id: artifactId, title }),
      ));
    },
    async listDefinitions(archived = false): Promise<readonly ReportDefinitionVersion[]> {
      const query = archived ? "?archived=true" : "";
      const payload = await parse<ReportDefinitionListResponse>(await send(`/reports/definitions${query}`));
      assertReportContractVersion(payload.contract_version);
      return payload.items.map(normalizeReportDefinition);
    },
    async archiveDefinition(definitionId: string) {
      const response = await parse<ReportDefinitionLifecycleResponse>(await send(
        `/reports/definitions/${encodeURIComponent(definitionId)}/archive`,
        "POST",
      ));
      const lifecycle = normalizeReportDefinitionLifecycle(response);
      if (lifecycle.definitionId !== definitionId || !lifecycle.archived) {
        throw new Error("Report 보관 응답이 요청과 일치하지 않습니다.");
      }
      return lifecycle;
    },
    async restoreDefinition(definitionId: string) {
      const response = await parse<ReportDefinitionLifecycleResponse>(await send(
        `/reports/definitions/${encodeURIComponent(definitionId)}/restore`,
        "POST",
      ));
      const lifecycle = normalizeReportDefinitionLifecycle(response);
      if (lifecycle.definitionId !== definitionId || lifecycle.archived) {
        throw new Error("Report 복원 응답이 요청과 일치하지 않습니다.");
      }
      return lifecycle;
    },
    async permanentlyDeleteDefinition(definitionId: string) {
      const response = await parse<ReportDefinitionPermanentDeleteResponse>(await send(
        `/reports/definitions/${encodeURIComponent(definitionId)}`,
        "DELETE",
      ));
      assertReportContractVersion(response.contract_version);
      if (response.definition_id !== definitionId || response.permanently_deleted !== true) {
        throw new Error("Report 영구삭제 응답이 요청과 일치하지 않습니다.");
      }
      return response;
    },
    async getDefinition(definitionId: string, version: number) {
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}`),
      ));
    },
    async getArtifact(definitionId: string, version: number, artifactId: string) {
      const payload = await parse<any>(await send(
        `/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/artifacts/${encodeURIComponent(artifactId)}`,
      ));
      assertReportContractVersion(payload.contract_version);
      return payload;
    },
    async approveDefinition(
      definitionId: string,
      version: number,
      approvedAt: string,
      orientation?: ReportOrientation,
    ) {
      if (orientation !== undefined) assertReportOrientation(orientation);
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/approve`, "POST", {
          approved_at: approvedAt,
          ...(orientation === undefined ? {} : { orientation }),
        }),
      ));
    },
    async getFinalDocument(definitionId: string, version: number, signal?: AbortSignal): Promise<ReportDocument> {
      return normalizeReportDocument(await parse<ReportDocumentResponse>(await send(
        `/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/document`,
        "GET",
        undefined,
        signal,
      )));
    },
    async getFinalHtml(definitionId: string, version: number): Promise<string> {
      return (await ensureOk(await send(
        `/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/document.html`,
      ))).text();
    },
    async getFinalPdf(definitionId: string, version: number): Promise<Blob> {
      return (await ensureOk(await send(
        `/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/document.pdf`,
      ))).blob();
    },
    async createNextDraft(definitionId: string, version: number) {
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/drafts`, "POST"),
      ));
    },
    async replaceDraftBlocks(
      definitionId: string,
      version: number,
      blocks: readonly ReportBlockRequest[],
      options: ReplaceDraftBlocksOptions,
    ) {
      const title = options.title?.trim();
      if (options.title !== undefined && (!title || title.length > 255 || /[\u0000-\u001f\u007f]/.test(title))) {
        throw new Error("보고서 제목은 줄바꿈·제어문자 없이 1~255자로 입력해 주세요.");
      }
      if (!Number.isInteger(options.expectedDraftRevision) || options.expectedDraftRevision < 1) {
        throw new Error("보고서 draft revision은 1 이상의 정수여야 합니다.");
      }
      if (options.orientation !== undefined) assertReportOrientation(options.orientation);
      if (options.currencyDisplayUnit !== undefined) {
        assertReportCurrencyDisplayUnit(options.currencyDisplayUnit);
      }
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/blocks`, "PUT", {
          blocks,
          ...(title === undefined ? {} : { title }),
          expected_draft_revision: options.expectedDraftRevision,
          ...(options.orientation === undefined ? {} : { orientation: options.orientation }),
          ...(options.currencyDisplayUnit === undefined
            ? {}
            : { currency_display_unit: options.currencyDisplayUnit }),
        }),
      ));
    },
    async listRuns(definitionId?: string): Promise<readonly ReportRun[]> {
      const query = definitionId ? `?definition_id=${encodeURIComponent(definitionId)}` : "";
      const payload = await parse<ReportRunListResponse>(await send(`/reports/runs${query}`));
      assertReportContractVersion(payload.contract_version);
      return payload.items.map(normalizeReportRun);
    },
    async getRun(runId: string) {
      return normalizeReportRun(await parse<ReportRunResponse>(
        await send(`/reports/runs/${encodeURIComponent(runId)}`),
      ));
    },
    async createManualRun(payload: { definition_id: string; version: number; idempotency_key: string }) {
      const response = await parse<ManualRunCommandResponse>(await send("/reports/runs/manual", "POST", payload));
      assertReportContractVersion(response.contract_version);
      if (!["queued", "success", "partial", "failed"].includes(response.status)) throw new Error(`Unexpected manual command status: ${response.status}`);
      return response;
    },
    async createSchedule(payload: {
      schedule_id: string;
      definition_id: string;
      version: number;
      cadence: "daily" | "weekly" | "monthly";
      next_run_at: string;
      timezone: "Asia/Seoul";
    }): Promise<ReportScheduleResponse> {
      return parse<ReportScheduleResponse>(await send("/reports/schedules", "POST", payload));
    },
    async listSchedules(): Promise<readonly ReportScheduleResponse[]> {
      return (await parse<ReportScheduleListResponse>(await send("/reports/schedules"))).items;
    },
    async setScheduleEnabled(scheduleId: string, enabled: boolean): Promise<ReportScheduleResponse> {
      return parse<ReportScheduleResponse>(await send(
        `/reports/schedules/${encodeURIComponent(scheduleId)}`,
        "PUT",
        { enabled },
      ));
    },
    async runDueSchedule(scheduleId: string): Promise<RunDueReportScheduleResponse> {
      return parse<RunDueReportScheduleResponse>(await send(
        `/reports/schedules/${encodeURIComponent(scheduleId)}/run-due`,
        "POST",
      ));
    },
    async createAssistantSession(
      definitionId: string,
      definitionVersion: number,
      artifactId: string,
      additionalArtifactIds: readonly string[] = [],
    ) {
      return assertAssistantSession(await parse<ReportAssistantSessionResponse>(await send(
        "/reports/assistant/sessions",
        "POST",
        {
          definition_id: definitionId,
          definition_version: definitionVersion,
          artifact_id: artifactId,
          additional_artifact_ids: additionalArtifactIds,
        },
      )));
    },
    async getAssistantSession(assistantRequestId: string) {
      return assertAssistantSessionRequest(await parse<ReportAssistantSessionResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}`,
      )), assistantRequestId);
    },
    async getAssistantExternalTransferDisclosure(assistantRequestId: string) {
      return assertExternalTransferDisclosure(await parse<ReportAssistantExternalTransferDisclosure>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/external-transfer-disclosure`,
      )), assistantRequestId);
    },
    async acceptAssistantExternalTransferConsent(
      assistantRequestId: string,
      disclosureId: string,
      disclosureHash: string,
    ) {
      if (!isUuid(disclosureId) || !/^[0-9a-f]{64}$/.test(disclosureHash)) {
        throw new Error("Report Assistant 외부 전송 공개문 식별자가 올바르지 않습니다.");
      }
      return assertExternalTransferConsent(await parse<ReportAssistantExternalTransferConsentResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/external-transfer-consent`,
        "POST",
        { disclosure_id: disclosureId, disclosure_hash: disclosureHash, accepted: true },
      )), assistantRequestId);
    },
    async cancelAssistantSession(assistantRequestId: string) {
      const session = assertAssistantSessionRequest(await parse<ReportAssistantSessionResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/cancel`,
        "POST",
      )), assistantRequestId);
      if (!["cancelled", "completed", "failed"].includes(session.phase)) {
        throw new Error("취소 응답은 terminal Report Assistant 상태여야 합니다.");
      }
      return session;
    },
    async retryAssistantSession(assistantRequestId: string) {
      const session = assertAssistantSession(await parse<ReportAssistantSessionResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/retry`,
        "POST",
      )));
      if (session.retry_of_assistant_request_id !== assistantRequestId
        || session.assistant_request_id === assistantRequestId) {
        throw new Error("재시도 결과는 원본 lineage를 가진 새 세션이어야 합니다.");
      }
      return session;
    },
    async submitAssistantMessage(
      assistantRequestId: string,
      instruction: string,
      expectedPatchRequestId: string | null = null,
      selectedBlockId: string | null = null,
      operationScope: ReportAssistantOperationScope = "full_report",
    ) {
      if (!["full_report", "report_title"].includes(operationScope)) {
        throw new Error(`지원하지 않는 Report Assistant 작업 범위입니다: ${operationScope}`);
      }
      const proposal = await parse<ReportAssistantProposalResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/messages`,
        "POST",
        {
          instruction,
          expected_patch_request_id: expectedPatchRequestId,
          selected_block_id: selectedBlockId,
          operation_scope: operationScope,
        },
      ));
      if (!["clarification", "existing_artifact", "new_data"].includes(proposal.change_kind)) {
        throw new Error(`지원하지 않는 Report Assistant 변경 종류입니다: ${proposal.change_kind}`);
      }
      if (!proposal.message.trim()) throw new Error("Report Assistant 메시지는 비어 있을 수 없습니다.");
      assertAssistantSuggestions(proposal.suggestions);
      const session = assertAssistantSessionRequest(proposal.session, assistantRequestId);
      if (proposal.change_kind === "clarification" && (session.phase !== "ready" || session.analysis_plan)) {
        throw new Error("명확화 응답은 실행 계획 없는 ready 세션이어야 합니다.");
      }
      if (proposal.change_kind === "new_data" && session.phase !== "waiting_approval") {
        throw new Error("새 데이터 응답은 승인 대기 세션이어야 합니다.");
      }
      if (proposal.change_kind === "existing_artifact" && session.phase !== "waiting_patch_approval") {
        throw new Error("기존 Artifact 변경은 patch 승인 대기여야 합니다.");
      }
      return { ...proposal, session };
    },
    async reviewAssistantSession(assistantRequestId: string, selectedBlockId: string | null = null) {
      const review = await parse<ReportAssistantReviewResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/review`,
        "POST",
        { selected_block_id: selectedBlockId },
      ));
      if (review.assistant_request_id !== assistantRequestId || !review.summary.trim()) {
        throw new Error("Report Assistant 품질 검토 계약이 올바르지 않습니다.");
      }
      if (!Array.isArray(review.findings) || review.findings.some((finding) => (
        !finding.title.trim()
        || !finding.detail.trim()
        || !finding.suggested_instruction.trim()
        || !Array.isArray(finding.evidence_refs)
      ))) {
        throw new Error("Report Assistant 품질 검토 항목이 올바르지 않습니다.");
      }
      assertAssistantSuggestions(review.suggestions);
      return review;
    },
    async approveAssistantPatch(
      assistantRequestId: string,
      requestId: string,
      operationIndexes?: readonly number[],
    ) {
      const session = assertAssistantSessionRequest(await parse<ReportAssistantSessionResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/patch-approval`,
        "POST",
        {
          request_id: requestId,
          approved: true,
          ...(operationIndexes ? { operation_indexes: operationIndexes } : {}),
        },
      )), assistantRequestId);
      if (!["saving_revision", "completed"].includes(session.phase)) {
        throw new Error("승인된 Report Assistant patch가 저장 phase로 전이되지 않았습니다.");
      }
      return session;
    },
    async rejectAssistantPatch(assistantRequestId: string, requestId: string) {
      const session = assertAssistantSessionRequest(await parse<ReportAssistantSessionResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/patch-approval`,
        "POST",
        { request_id: requestId, approved: false },
      )), assistantRequestId);
      if (session.phase !== "ready") throw new Error("취소된 Report Assistant patch는 ready여야 합니다.");
      return session;
    },
    async approveAssistantPlan(assistantRequestId: string, requestId: string) {
      const session = assertAssistantSessionRequest(await parse<ReportAssistantSessionResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/approval`,
        "POST",
        { request_id: requestId, approved: true },
      )), assistantRequestId);
      if (session.phase !== "waiting_patch_approval") {
        throw new Error("승인된 새 데이터 분석은 저장 전 patch 승인 대기로 전이되어야 합니다.");
      }
      return session;
    },
    async rejectAssistantPlan(assistantRequestId: string, requestId: string) {
      const session = assertAssistantSessionRequest(await parse<ReportAssistantSessionResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/approval`,
        "POST",
        { request_id: requestId, approved: false },
      )), assistantRequestId);
      if (session.phase !== "ready") throw new Error("거절된 Report Assistant 계획은 ready여야 합니다.");
      return session;
    },
    async getAssistantEvaluation(assistantRequestId: string) {
      return parse<ReportAssistantEvaluationResponse>(await send(
        `/reports/assistant/sessions/${encodeURIComponent(assistantRequestId)}/evaluation`,
      ));
    },
    async getAssistantOperationsSummary(startAt?: string, endAt?: string) {
      const query = new URLSearchParams();
      if (startAt) query.set("start_at", startAt);
      if (endAt) query.set("end_at", endAt);
      const suffix = query.size ? `?${query.toString()}` : "";
      return parse<ReportAssistantOperationsSummaryResponse>(await send(
        `/reports/assistant/operations/summary${suffix}`,
      ));
    },
    async getAssistantOperationFailures(startAt?: string, endAt?: string) {
      const query = new URLSearchParams();
      if (startAt) query.set("start_at", startAt);
      if (endAt) query.set("end_at", endAt);
      const suffix = query.size ? `?${query.toString()}` : "";
      return parse<ReportAssistantFailureListResponse>(await send(
        `/reports/assistant/operations/failures${suffix}`,
      ));
    },
  };
}
