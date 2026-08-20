/** 보고서 정의·실행·schedule·최종 asset HTTP 포트를 fail-closed로 제공하는 모듈이다. */
import {
  REPORT_REQUEST_CONTEXT_VERSION,
  assertReportCurrencyDisplayUnit,
  assertReportContractVersion,
  assertReportOrientation,
  normalizeReportDefinition,
  normalizeReportDocument,
  normalizeReportRun,
  type ManualRunCommandResponse,
  type ReportBlockRequest,
  type ReportDefinitionListResponse,
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
  type ReportAssistantDraftResponse,
} from "../contracts/report.ts";
import { createUuid } from "../utils/createUuid.ts";

type Fetch = typeof fetch;
const env = import.meta.env ?? {};

/** 초안 블록 교체와 함께 원자적으로 저장할 문서 표시 옵션이다. */
export interface ReplaceDraftBlocksOptions {
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

  constructor(status: number, code: string, message: string, options: {
    retryable?: boolean;
    requiredAction?: string;
    suggestions?: string[];
    missingRequirements?: string[];
    traceId?: string;
  } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryable = options.retryable ?? false;
    this.requiredAction = options.requiredAction ?? "NONE";
    this.suggestions = options.suggestions ?? [];
    this.missingRequirements = options.missingRequirements ?? [];
    this.traceId = options.traceId ?? "";
  }
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
    const code = payload?.error?.code || `HTTP_${response.status}`;
    const message = payload?.error?.message || "Report API 요청에 실패했습니다.";
    if (response.status === 401 && typeof window !== "undefined") window.dispatchEvent(new CustomEvent("answervice:session-expired"));
    throw new ReportApiError(response.status, code, message, {
      retryable: Boolean(payload?.error?.retryable),
      requiredAction: payload?.error?.required_action,
      suggestions: payload?.error?.suggestions,
      missingRequirements: payload?.error?.missing_requirements,
      traceId: payload?.error?.trace_id,
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
    async listDefinitions(): Promise<readonly ReportDefinitionVersion[]> {
      const payload = await parse<ReportDefinitionListResponse>(await send("/reports/definitions"));
      assertReportContractVersion(payload.contract_version);
      return payload.items.map(normalizeReportDefinition);
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
      options: ReplaceDraftBlocksOptions = {},
    ) {
      if (options.orientation !== undefined) assertReportOrientation(options.orientation);
      if (options.currencyDisplayUnit !== undefined) {
        assertReportCurrencyDisplayUnit(options.currencyDisplayUnit);
      }
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/blocks`, "PUT", {
          blocks,
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
    async createAssistantDraft(artifactId: string, instruction: string) {
      const response = await parse<ReportAssistantDraftResponse>(await send(
        "/reports/assistant/drafts",
        "POST",
        { artifact_id: artifactId, instruction },
      ));
      return {
        requestId: response.assistant_request_id,
        definition: normalizeReportDefinition(response.definition),
        trace: response.trace,
      };
    },
  };
}
