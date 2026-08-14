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
  | "CONTEXT_SOURCE_FAILED"
  | "DATA_ASSET_NOT_FOUND"
  | "AUTHENTICATION_REQUIRED"
  | "ACCESS_DENIED"
  | "MODEL_CONTRACT_INVALID"
  | "MODEL_TIMEOUT"
  | "MODEL_ENDPOINT_UNAVAILABLE"
  | "MODEL_OUTPUT_UNGROUNDED"
  | "CIRCUIT_OPEN"
  | "INSUFFICIENT_CONTEXT"
  | "UNREPAIRABLE"
  | "SQL_POLICY_BLOCKED"
  | "SQL_REPAIR_FAILED"
  | "TRINO_CONNECTION_FAILED"
  | "QUERY_TIMEOUT"
  | "QUERY_SOURCE_FAILED"
  | "RESULT_VALIDATION_FAILED"
  | "RESULT_EVIDENCE_MISSING"
  | "ARTIFACT_PERSIST_FAILED"
  | "NETWORK_UNAVAILABLE"
  | "PARTIAL_FAILURE"
  | "INSUFFICIENT_EVIDENCE"
  | "RATE_LIMITED"
  | "REQUEST_CANCELLED"
  | "CONTRACT_VERSION_MISMATCH"
  | "SCHEMA_VERSION_MISMATCH"
  | "RESOURCE_NOT_FOUND"
  | "RESOURCE_CONFLICT"
  | "DEPENDENCY_UNAVAILABLE"
  | "INTERNAL_ERROR";

export type RequiredAction =
  | "NONE"
  | "RETRY"
  | "AUTHENTICATE"
  | "REQUEST_ACCESS"
  | "PROVIDE_CONTEXT"
  | "MODIFY_REQUEST"
  | "CONTACT_SUPPORT";

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
  resultField: string;
  label: string;
  definition: string;
  value: AnalysisValue;
  unit: string | null;
}

export interface AnalysisMetricReference {
  metricId: string;
  resultField: string;
  label: string;
  definition: string;
  unit: string | null;
}

export interface AnalysisModelEvidence {
  node: string;
  modelVersion: string;
  promptId: string;
  promptVersion: string;
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
  contextHash?: string;
}

export interface AnalysisEvidence {
  artifactId?: string | null;
  queryId?: string | null;
  asOf: string;
  timezone?: string | null;
  period?: {
    start: string;
    endExclusive: string;
  } | null;
  filters: Record<string, AnalysisValue>;
  contextRelease?: string | null;
  policyVersion?: string | null;
  modelVersion?: string | null;
  metrics: AnalysisMetricReference[];
  models: AnalysisModelEvidence[];
  gates?: { g1: string; g2: string; g3: string } | null;
  gateHistory?: { g1: string[]; g2: string[]; g3: string[] } | null;
  cached: boolean;
  sampling: {
    applied: boolean;
    returnedRows: number;
    totalRows: number | null;
  };
  masking: {
    applied: boolean;
    fields: string[];
  };
}

export interface AnalysisApiResponse {
  data: {
    status?: BackendAnalysisStatus;
    transitions?: BackendAnalysisStatus[];
    trace?: Array<{ stage: string; outcome: string; detail?: string | null }>;
    artifact?: {
      artifact_id: string;
      query_id: string;
      context_hash?: string;
    } | null;
    result?: {
      summary?: string;
      metrics?: Array<{
        metric_id: string;
        result_field: string;
        label: string;
        definition: string;
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
        timezone?: string | null;
        period?: {
          start: string;
          end_exclusive: string;
        } | null;
        filters?: Record<string, AnalysisValue>;
        context_release?: string | null;
        policy_version?: string | null;
        model_version?: string | null;
        metrics?: Array<{
          metric_id: string;
          result_field: string;
          label: string;
          definition: string;
          unit?: string | null;
        }>;
        metric_values?: Array<{
          metric_id: string;
          result_field: string;
          label: string;
          definition: string;
          value: AnalysisValue;
          unit?: string | null;
        }>;
        models?: Array<{
          node: string;
          model_version: string;
          prompt_id: string;
          prompt_version: string;
        }>;
        gates?: { g1: string; g2: string; g3: string } | null;
        gate_history?: { g1: string[]; g2: string[]; g3: string[] } | null;
        cached?: boolean;
        sampling?: {
          applied?: boolean;
          returned_rows?: number;
          total_rows?: number | null;
        };
        masking?: {
          applied?: boolean;
          fields?: string[];
        };
        sources?: Array<{
          name: string;
          urn: string;
          fqn: string;
          schema_version: string;
          seed_version: string;
          synthetic?: boolean | null;
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
    required_action: RequiredAction;
    missing_requirements?: string[];
    suggestions?: string[];
    clarification_type?: "metric" | "period" | null;
    trace_id?: string;
  } | null;
}

export interface AnalysisSource {
  name: string;
  urn: string;
  fqn?: string;
  schemaVersion?: string;
  seedVersion?: string;
  synthetic?: boolean;
  status: "success" | "failed" | "partial" | "delayed" | "unknown";
}

export interface AnalysisRun {
  requestId: string;
  traceId: string;
  status: AnalysisRunStatus;
  delayed?: boolean;
  elapsedSeconds?: number;
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
    required_action?: RequiredAction;
    missing_requirements?: string[];
    suggestions?: string[];
    clarification_type?: "metric" | "period" | null;
    trace_id?: string;
  };
  sources: AnalysisSource[];
  trace?: Array<{ stage: string; outcome: string; detail?: string | null }>;
  meta: {
    asOf: string;
    timezone: string;
    seed: string;
    schemaVersion: string;
    contractVersion: string;
  };
}

export function resolveViewState(run: AnalysisRun): AnalysisViewState {
  if (run.status === "queued") return "LOADING";
  if (run.status === "running") return run.delayed ? "DELAYED" : "LOADING";
  if (run.status === "cancelled") return "CANCELLED";
  if ((run.status === "success" || run.status === "partial") && run.evidenceReady === false) {
    return "INSUFFICIENT_EVIDENCE";
  }
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
  const evidenceReady = Boolean(
    evidence?.artifact_id
    && evidence?.query_id
    && evidence?.period
    && sources.length
    && evidence?.gates
    && evidence.gates.g1 === "PASSED"
    && evidence.gates.g2 === "PASSED"
    && evidence.gates.g3 === "PASSED"
    && response.data.artifact?.artifact_id === evidence.artifact_id
    && response.data.artifact?.query_id === evidence.query_id
  );
  const exposeResult = Boolean(result && evidenceReady);
  const error = result && !evidenceReady
    ? {
        code: "INSUFFICIENT_EVIDENCE" as const,
        message: "검증 근거가 완전하지 않아 결과를 표시하지 않습니다.",
        retryable: false,
        required_action: "NONE" as const,
        missing_requirements: ["artifact", "query", "period", "sources", "gates"],
        suggestions: [],
        clarification_type: null,
        trace_id: response.meta.trace_id,
      }
    : response.error ?? undefined;
  return {
    requestId: response.meta.request_id,
    traceId: response.meta.trace_id,
    status,
    question,
    summary: exposeResult ? result?.summary : undefined,
    rowCount: sampling?.returned_rows,
    evidenceReady: result ? evidenceReady : undefined,
    artifact: exposeResult && response.data.artifact ? {
      artifactId: response.data.artifact.artifact_id,
      queryId: response.data.artifact.query_id,
      contextHash: response.data.artifact.context_hash,
    } : undefined,
    metrics: (exposeResult ? result?.metrics ?? [] : []).map((metric) => ({
      metricId: metric.metric_id,
      resultField: metric.result_field,
      label: metric.label,
      definition: metric.definition,
      value: metric.value,
      unit: metric.unit ?? null,
    })),
    table: exposeResult ? result?.table : undefined,
    chart: exposeResult && result?.chart ? {
      chartType: result.chart.chart_type,
      xField: result.chart.x_field,
      yFields: result.chart.y_fields,
    } : undefined,
    evidence: evidence ? {
      artifactId: evidence.artifact_id,
      queryId: evidence.query_id,
      asOf: evidence.as_of,
      timezone: evidence.timezone,
      period: evidence.period ? {
        start: evidence.period.start,
        endExclusive: evidence.period.end_exclusive,
      } : undefined,
      filters: evidence.filters ?? {},
      contextRelease: evidence.context_release,
      policyVersion: evidence.policy_version,
      modelVersion: evidence.model_version,
      metrics: (evidence.metrics ?? []).map((metric) => ({
        metricId: metric.metric_id,
        resultField: metric.result_field,
        label: metric.label,
        definition: metric.definition,
        unit: metric.unit ?? null,
      })),
      models: (evidence.models ?? []).map((model) => ({
        node: model.node,
        modelVersion: model.model_version,
        promptId: model.prompt_id,
        promptVersion: model.prompt_version,
      })),
      gates: evidence.gates,
      gateHistory: evidence.gate_history,
      cached: evidence.cached ?? false,
      sampling: {
        applied: sampling?.applied ?? false,
        returnedRows: sampling?.returned_rows ?? 0,
        totalRows: sampling?.total_rows ?? null,
      },
      masking: {
        applied: evidence.masking?.applied ?? false,
        fields: evidence.masking?.fields ?? [],
      },
    } : undefined,
    error,
    sources: sources.map((source) => ({
      name: source.name,
      urn: source.urn,
      fqn: source.fqn,
      schemaVersion: source.schema_version,
      seedVersion: source.seed_version,
      synthetic: typeof source.synthetic === "boolean" ? source.synthetic : undefined,
      status: status === "partial" ? "unknown" : "success",
    })),
    trace: response.data.trace?.map(({ stage, outcome, detail }) => ({ stage, outcome, detail })) ?? [],
    meta: {
      asOf: response.meta.as_of,
      timezone: evidence?.timezone ?? "Asia/Seoul",
      seed: sources[0]?.seed_version ?? "—",
      schemaVersion: sources[0]?.schema_version ?? "—",
      contractVersion: response.meta.contract_version,
    },
  };
}
