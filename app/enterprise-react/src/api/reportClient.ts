import {
  REPORT_REQUEST_CONTEXT_VERSION,
  assertReportContractVersion,
  normalizeReportDefinition,
  normalizeReportArtifactPreview,
  normalizeReportRun,
  normalizeReportSchedule,
  type ManualRunCommandResponse,
  type ReportBlockRequest,
  type ReportArtifactPreviewResponse,
  type ReportDefinitionListResponse,
  type ReportDefinitionResponse,
  type ReportDefinitionVersion,
  type ReportRun,
  type ReportRunListResponse,
  type ReportRunResponse,
  type ReportSchedule,
  type ReportScheduleListResponse,
  type ReportScheduleResponse,
  type UpsertReportScheduleRequest,
} from "../contracts/report.ts";
import { createUuid } from "../utils/createUuid.ts";
import { getAuthorizationHeader } from "./authSession.ts";

type Fetch = typeof fetch;
const env = import.meta.env ?? {};

export class ReportApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function contextHeaders(hasBody = false): Record<string, string> {
  return {
    Authorization: getAuthorizationHeader(),
    ...(hasBody ? { "Content-Type": "application/json" } : {}),
    "X-As-Of": env.VITE_REPORT_AS_OF || new Date().toISOString().slice(0, 10),
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
  baseUrl = env.VITE_BACKEND_BASE_URL || "http://127.0.0.1:18000",
  request: Fetch = fetch,
) {
  const endpoint = (path: string) => `${baseUrl.replace(/\/$/, "")}${path}`;
  const send = (path: string, method = "GET", body?: unknown) => request(endpoint(path), {
    method,
    headers: contextHeaders(body !== undefined),
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
    async getArtifactPreview(artifactId: string) {
      return normalizeReportArtifactPreview(await parse<ReportArtifactPreviewResponse>(
        await send(`/reports/artifacts/${encodeURIComponent(artifactId)}`),
      ));
    },
    async createManualRun(payload: { definition_id: string; version: number; as_of: string; idempotency_key: string }) {
      const response = await parse<ManualRunCommandResponse>(await send("/reports/runs/manual", "POST", payload));
      assertReportContractVersion(response.contract_version);
      if (response.status !== "queued") throw new Error(`Unexpected manual command status: ${response.status}`);
      return response;
    },
    async listSchedules(): Promise<readonly ReportSchedule[]> {
      const payload = await parse<ReportScheduleListResponse>(await send("/reports/schedules"));
      assertReportContractVersion(payload.contract_version);
      return payload.items.map(normalizeReportSchedule);
    },
    async upsertSchedule(definitionId: string, version: number, payload: UpsertReportScheduleRequest) {
      return normalizeReportSchedule(await parse<ReportScheduleResponse>(
        await send(`/reports/definitions/${encodeURIComponent(definitionId)}/versions/${version}/schedule`, "PUT", payload),
      ));
    },
  };
}
