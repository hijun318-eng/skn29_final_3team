import {
  REPORT_REQUEST_CONTEXT_VERSION,
  assertReportContractVersion,
  normalizeReportDefinition,
  normalizeReportRun,
  type ManualRunCommandResponse,
  type ReportBlockRequest,
  type ReportDefinitionListResponse,
  type ReportDefinitionResponse,
  type ReportDefinitionVersion,
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

function seoulToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

export class ReportApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function contextHeaders(hasBody = false, explicitToken = ""): Record<string, string> {
  const token = explicitToken;
  if (!token) throw new Error("Report 인증 세션이 없습니다.");
  return {
    Authorization: `Bearer ${token}`,
    ...(hasBody ? { "Content-Type": "application/json" } : {}),
    "X-As-Of": env.VITE_REPORT_AS_OF || seoulToday(),
    "X-Contract-Version": REPORT_REQUEST_CONTEXT_VERSION,
    "X-Timezone": "Asia/Seoul",
    "X-Trace-Id": createUuid(),
  };
}

async function parse<T>(response: Response): Promise<T> {
  const payload: any = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = payload?.error?.code || `HTTP_${response.status}`;
    const message = payload?.error?.message || payload?.detail || "Report API 요청에 실패했습니다.";
    throw new ReportApiError(response.status, code, message);
  }
  return payload as T;
}

export function createReportClient(
  baseUrl = env.VITE_BACKEND_BASE_URL,
  request: Fetch = fetch,
  authToken = "",
) {
  if (!baseUrl) throw new Error("VITE_BACKEND_BASE_URL is required");
  const endpoint = (path: string) => `${baseUrl.replace(/\/$/, "")}${path}`;
  const send = (path: string, method = "GET", body?: unknown) => request(endpoint(path), {
    method,
    headers: contextHeaders(body !== undefined, authToken),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  return {
    async createDefinition(payload: { definition_id: string; title: string; blocks: readonly ReportBlockRequest[] }) {
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send("/reports/definitions", "POST", payload),
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
    async approveDefinition(definitionId: string, version: number, approvedAt: string) {
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/approve`, "POST", { approved_at: approvedAt }),
      ));
    },
    async createNextDraft(definitionId: string, version: number) {
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/drafts`, "POST"),
      ));
    },
    async replaceDraftBlocks(definitionId: string, version: number, blocks: readonly ReportBlockRequest[]) {
      return normalizeReportDefinition(await parse<ReportDefinitionResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/blocks`, "PUT", { blocks }),
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
    async createManualRun(payload: { definition_id: string; version: number; as_of: string; idempotency_key: string }) {
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
