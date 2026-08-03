export const UI_CONTRACT_VERSION = "UI-v1.0.0";
export const OPENAPI_VERSION = "OPENAPI-v1.0.0";

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
  | "INSUFFICIENT_EVIDENCE"
  | "RATE_LIMITED"
  | "CONTRACT_VERSION_MISMATCH"
  | "SCHEMA_VERSION_MISMATCH"
  | "INTERNAL_ERROR";

export type BackendAnalysisStatus =
  | "RECEIVED"
  | "ROUTED"
  | "SUCCEEDED"
  | "BLOCKED"
  | "PARTIAL"
  | "FAILED"
  | "CANCELLED";

export type AnalysisValue = string | number | boolean | null;

export interface AnalysisMetric {
  metricId: string;
  label: string;
  value: AnalysisValue;
  unit: string | null;
}

export interface AnalysisTable {
  columns: string[];
  rows: Array<Record<string, AnalysisValue>>;
}

export interface AnalysisChart {
  chartType: string;
  xField: string;
  yFields: string[];
}

export interface AnalysisArtifact {
  artifactId: string;
  queryId: string;
  contextHash: string;
}

export interface AnalysisEvidence {
  artifactId?: string | null;
  queryId?: string | null;
  asOf: string;
  period?: {
    start: string;
    endExclusive: string;
  } | null;
  filters: Record<string, AnalysisValue>;
  cached: boolean;
  sampling: {
    applied: boolean;
    returnedRows: number;
    totalRows: number | null;
  };
}

export interface AnalysisApiResponse {
  data: {
    status?: BackendAnalysisStatus;
    transitions?: BackendAnalysisStatus[];
    artifact?: {
      artifact_id: string;
      query_id: string;
      context_hash: string;
    } | null;
    result?: {
      summary?: string;
      metrics?: Array<{
        metric_id: string;
        label: string;
        value: AnalysisValue;
        unit?: string | null;
      }>;
      table?: {
        columns: string[];
        rows: Array<Record<string, AnalysisValue>>;
      } | null;
      chart?: {
        chart_type: string;
        x_field: string;
        y_fields: string[];
      } | null;
      evidence: {
        artifact_id?: string | null;
        query_id?: string | null;
        as_of: string;
        period?: {
          start: string;
          end_exclusive: string;
        } | null;
        filters?: Record<string, AnalysisValue>;
        cached?: boolean;
        sampling?: {
          applied?: boolean;
          returned_rows?: number;
          total_rows?: number | null;
        };
        sources?: Array<{
          name: string;
          urn: string;
          fqn: string;
          schema_version: string;
          seed_version: string;
        }>;
      };
    } | null;
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
  fqn?: string;
  schemaVersion?: string;
  seedVersion?: string;
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
  artifact?: AnalysisArtifact;
  metrics: AnalysisMetric[];
  table?: AnalysisTable | null;
  chart?: AnalysisChart | null;
  evidence?: AnalysisEvidence;
  error?: {
    code: AnalysisErrorCode;
    message: string;
    retryable?: boolean;
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
  if (
    run.status === "failed"
    && (run.error?.code === "RESULT_EVIDENCE_MISSING" || run.error?.code === "INSUFFICIENT_EVIDENCE")
  ) {
    return "INSUFFICIENT_EVIDENCE";
  }
  if (run.status === "failed") return "ERROR";
  if (run.status === "blocked" && run.error?.code === "CONTEXT_INCOMPLETE") return "EMPTY";
  if (run.status === "blocked" && run.error?.code === "ACCESS_DENIED") return "FORBIDDEN";
  if (
    run.status === "blocked"
    && (run.error?.code === "RESULT_EVIDENCE_MISSING" || run.error?.code === "INSUFFICIENT_EVIDENCE")
  ) {
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
  CANCELLED: "cancelled",
};

export function normalizeApiResponse(
  response: AnalysisApiResponse,
  question: string,
  conversationId: string,
): AnalysisRun {
  const status = response.data.status
    ? BACKEND_STATUS_MAP[response.data.status]
    : response.error?.code === "CONTEXT_INCOMPLETE" || response.error?.code === "ACCESS_DENIED"
      ? "blocked"
      : "failed";
  const result = response.data.result ?? undefined;
  const evidence = result?.evidence;
  const sources = evidence?.sources ?? [];
  const sampling = evidence?.sampling;
  return {
    conversationId,
    requestId: response.meta.request_id,
    traceId: response.meta.trace_id,
    status,
    question,
    summary: result?.summary,
    rowCount: sampling?.returned_rows,
    evidenceReady: result ? Boolean(evidence) : undefined,
    artifact: response.data.artifact ? {
      artifactId: response.data.artifact.artifact_id,
      queryId: response.data.artifact.query_id,
      contextHash: response.data.artifact.context_hash,
    } : undefined,
    metrics: (result?.metrics ?? []).map((metric) => ({
      metricId: metric.metric_id,
      label: metric.label,
      value: metric.value,
      unit: metric.unit ?? null,
    })),
    table: result?.table,
    chart: result?.chart ? {
      chartType: result.chart.chart_type,
      xField: result.chart.x_field,
      yFields: result.chart.y_fields,
    } : undefined,
    evidence: evidence ? {
      artifactId: evidence.artifact_id,
      queryId: evidence.query_id,
      asOf: evidence.as_of,
      period: evidence.period ? {
        start: evidence.period.start,
        endExclusive: evidence.period.end_exclusive,
      } : undefined,
      filters: evidence.filters ?? {},
      cached: evidence.cached ?? false,
      sampling: {
        applied: sampling?.applied ?? false,
        returnedRows: sampling?.returned_rows ?? 0,
        totalRows: sampling?.total_rows ?? null,
      },
    } : undefined,
    error: response.error ?? undefined,
    sources: sources.map((source) => ({
      name: source.name,
      urn: source.urn,
      fqn: source.fqn,
      schemaVersion: source.schema_version,
      seedVersion: source.seed_version,
      status: "success",
    })),
    meta: {
      asOf: response.meta.as_of,
      timezone: "Asia/Seoul",
      synthetic: true,
      seed: sources[0]?.seed_version ?? "—",
      schemaVersion: sources[0]?.schema_version ?? "—",
      contractVersion: response.meta.contract_version,
    },
  };
}
