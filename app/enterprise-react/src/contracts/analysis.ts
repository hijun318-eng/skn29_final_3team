export const UI_CONTRACT_VERSION = "DRAFT-UI-v0.1";
export const OPENAPI_VERSION = "1.0.0-draft";

export type AnalysisRunStatus =
  | "idle"
  | "queued"
  | "running"
  | "success"
  | "blocked"
  | "partial"
  | "failed"
  | "cancelled";

export type AnalysisViewState =
  | "LOADING"
  | "EMPTY"
  | "READY"
  | "DELAYED"
  | "PARTIAL"
  | "ERROR"
  | "FORBIDDEN"
  | "INSUFFICIENT_EVIDENCE"
  | "CANCELLED";

export type AnalysisErrorCode =
  | "CONTEXT_INCOMPLETE"
  | "ACCESS_DENIED"
  | "SQL_POLICY_BLOCKED"
  | "QUERY_SOURCE_FAILED"
  | "RESULT_EVIDENCE_MISSING"
  | "PARTIAL_FAILURE"
  | "INTERNAL_ERROR";

export type BackendAnalysisStatus =
  | "RECEIVED"
  | "ROUTED"
  | "SUCCEEDED"
  | "BLOCKED"
  | "PARTIAL"
  | "FAILED";

export interface AnalysisApiResponse {
  data: {
    status?: BackendAnalysisStatus;
    transitions?: BackendAnalysisStatus[];
    result?: {
      summary?: string;
      assets?: Array<{ name?: string; urn?: string }>;
    };
  };
  meta: {
    request_id: string;
    trace_id: string;
    as_of: string;
    contract_version: string;
    timestamp: string;
  };
  error?: {
    code: AnalysisErrorCode;
    message: string;
    retryable: boolean;
  } | null;
}

export interface AnalysisSource {
  name: string;
  urn: string;
  status: "success" | "failed";
}

export interface AnalysisRun {
  conversationId: string;
  requestId: string;
  traceId: string;
  status: AnalysisRunStatus;
  delayed?: boolean;
  question: string;
  summary?: string;
  rowCount?: number;
  evidenceReady?: boolean;
  error?: {
    code: AnalysisErrorCode;
    message: string;
    retryable: boolean;
  };
  sources: AnalysisSource[];
  meta: {
    asOf: string;
    timezone: "Asia/Seoul";
    synthetic: true;
    seed: string;
    schemaVersion: string;
    contractVersion: string;
  };
}

export function resolveViewState(run: AnalysisRun): AnalysisViewState {
  if (run.status === "queued") return "LOADING";
  if (run.status === "running") return run.delayed ? "DELAYED" : "LOADING";
  if (run.status === "cancelled") return "CANCELLED";
  if (run.status === "partial") return "PARTIAL";
  if (run.status === "failed") return "ERROR";
  if (run.status === "blocked" && run.error?.code === "ACCESS_DENIED") return "FORBIDDEN";
  if (run.status === "blocked" && run.error?.code === "RESULT_EVIDENCE_MISSING") {
    return "INSUFFICIENT_EVIDENCE";
  }
  if (run.status === "blocked") return "ERROR";
  if (run.status === "success" && run.evidenceReady === false) return "INSUFFICIENT_EVIDENCE";
  if (run.status === "success" && run.rowCount === 0) return "EMPTY";
  if (run.status === "success") return "READY";
  return "EMPTY";
}

const BACKEND_STATUS_MAP: Record<BackendAnalysisStatus, AnalysisRunStatus> = {
  RECEIVED: "queued",
  ROUTED: "running",
  SUCCEEDED: "success",
  BLOCKED: "blocked",
  PARTIAL: "partial",
  FAILED: "failed",
};

export function normalizeApiResponse(
  response: AnalysisApiResponse,
  question: string,
  conversationId: string,
): AnalysisRun {
  const status = response.data.status ? BACKEND_STATUS_MAP[response.data.status] : "failed";
  const assets = response.data.result?.assets ?? [];
  return {
    conversationId,
    requestId: response.meta.request_id,
    traceId: response.meta.trace_id,
    status,
    question,
    summary: response.data.result?.summary,
    rowCount: status === "success" ? assets.length : undefined,
    evidenceReady: status === "success" ? assets.length > 0 : undefined,
    error: response.error ?? undefined,
    sources: assets.map((asset) => ({
      name: asset.name ?? "이름 없는 자산",
      urn: asset.urn ?? "urn:unknown",
      status: "success",
    })),
    meta: {
      asOf: response.meta.as_of,
      timezone: "Asia/Seoul",
      synthetic: true,
      seed: "20260729",
      schemaVersion: "1.0.0",
      contractVersion: response.meta.contract_version,
    },
  };
}
