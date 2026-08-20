/** 분석 wire 응답을 fail-closed UI 실행 모델로 정의·정규화하는 계약 모듈이다. */
/** 프런트 분석 상태 모델의 호환성 버전이다. */ export const UI_CONTRACT_VERSION = "UI-v1.0.0";
/** 분석 HTTP 요청이 선언하는 OpenAPI 계약 버전이다. */ export const OPENAPI_VERSION = "OPENAPI-v1.0.0";

/** UI가 다루는 정규화된 분석 실행 상태 집합이다. */ export type AnalysisRunStatus =
  | "idle"
  | "queued"
  | "running"
  | "success"
  | "blocked"
  | "partial"
  | "failed"
  | "cancelled";

/** 실행 상태·근거를 사용자 화면 상태로 축약한 집합이다. */ export type AnalysisViewState =
  | "LOADING"
  | "EMPTY"
  | "READY"
  | "DELAYED"
  | "PARTIAL"
  | "ERROR"
  | "FORBIDDEN"
  | "INSUFFICIENT_EVIDENCE"
  | "CANCELLED";

/** 백엔드가 반환할 수 있는 분석 실패 코드 계약이다. */ export type AnalysisErrorCode =
  | "CONTEXT_INCOMPLETE"
  | "CONTEXT_SOURCE_FAILED"
  | "SEMANTIC_CONTRACT_INVALID"
  | "DATA_ASSET_NOT_FOUND"
  | "OUT_OF_DATA_RANGE"
  | "SOURCE_NOT_READY"
  | "GRAIN_VIOLATION"
  | "FILTER_VALUE_NOT_FOUND"
  | "METRIC_NOT_AVAILABLE"
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

/** 실패 후 사용자 또는 시스템이 수행해야 하는 후속 조치다. */ export type RequiredAction =
  | "NONE"
  | "RETRY"
  | "AUTHENTICATE"
  | "REQUEST_ACCESS"
  | "PROVIDE_CONTEXT"
  | "MODIFY_REQUEST"
  | "CONTACT_SUPPORT";

/** 분석 API wire payload의 원본 상태 집합이다. */ export type BackendAnalysisStatus =
  | "RECEIVED"
  | "ROUTED"
  | "SUCCEEDED"
  | "BLOCKED"
  | "PARTIAL"
  | "FAILED"
  | "CANCELLED"
  | "CLARIFICATION_REQUIRED";

/** 모호성 해소를 위해 사용자에게 제시하는 구조화된 선택지 계약이다. */ export interface DisambiguationOption {
  label: string;
  clarification_type: "metric" | "period";
  description?: string | null;
  metric_id?: string | null;
  period_start?: string | null;
  period_end_exclusive?: string | null;
  value?: string | null;
}

/** 표·지표에서 허용되는 직렬화 가능한 원자 값이다. */ export type AnalysisValue = string | number | boolean | null;

/** 값과 거버넌스 정의가 함께 검증된 화면 지표다. */ export interface AnalysisMetric {
  metricId: string;
  resultField: string;
  label: string;
  definition: string;
  value: AnalysisValue;
  unit: string | null;
}

/** 결과 field를 거버넌스 지표 메타데이터에 연결하는 근거다. */ export interface AnalysisMetricReference {
  metricId: string;
  resultField: string;
  label: string;
  definition: string;
  unit: string | null;
}

/** 모델 node·release·prompt 추적 정보다. */ export interface AnalysisModelEvidence {
  node: string;
  modelVersion: string;
  promptId: string;
  promptVersion: string;
}

/** canonical column과 동일 key의 행으로 구성된 분석 표다. */ export interface AnalysisTable {
  columns: string[];
  rows: Array<Record<string, AnalysisValue>>;
}

/** 표 field를 참조하는 검증된 차트 표현 계약이다. */ export interface AnalysisChart {
  chartType: string;
  xField: string;
  yFields: string[];
}

/** 영속 결과·query 식별자와 checksum을 묶는 artifact 계약이다. */ export interface AnalysisArtifact {
  artifactId: string;
  queryId: string;
  contextHash?: string;
}

/** 기간·필터·출처·gate를 포함하는 분석 근거 묶음이다. */ export interface AnalysisEvidence {
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
  productReleaseId?: string | null;
  evidenceCutoff?: string | null;
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

/** OpenAPI 분석 응답의 wire envelope이며 normalizeApiResponse 입력으로만 사용한다. */ export interface AnalysisApiResponse {
  data: {
    status?: BackendAnalysisStatus;
    transitions?: BackendAnalysisStatus[];
    trace?: Array<{ stage: string; outcome: string; detail?: string | null }>;
    disambiguation_options?: DisambiguationOption[];
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
        product_release_id?: string | null;
        evidence_cutoff?: string | null;
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
    disambiguation_options?: DisambiguationOption[];
    clarification_type?: "metric" | "period" | null;
    trace_id?: string;
  } | null;
}

/** 화면에 노출 가능한 governed 데이터 출처 식별 정보다. */ export interface AnalysisSource {
  name: string;
  urn: string;
  fqn?: string;
  schemaVersion?: string;
  seedVersion?: string;
  synthetic?: boolean;
  status: "success" | "failed" | "partial" | "delayed" | "unknown";
}

/** 컴포넌트가 소비하는 완전 정규화 분석 실행 모델이다. */ export interface AnalysisRun {
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
  disambiguationOptions?: DisambiguationOption[];
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
    disambiguation_options?: DisambiguationOption[];
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

/** 근거 준비 여부까지 반영해 실행을 하나의 fail-closed 화면 상태로 결정한다. */
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
  if (
    run.status === "blocked"
    && ["CONTEXT_INCOMPLETE", "INSUFFICIENT_CONTEXT", "DATA_ASSET_NOT_FOUND", "OUT_OF_DATA_RANGE", "FILTER_VALUE_NOT_FOUND", "GRAIN_VIOLATION"].includes(run.error?.code ?? "")
  ) return "EMPTY";
  if (run.status === "blocked" && ["ACCESS_DENIED", "AUTHENTICATION_REQUIRED"].includes(run.error?.code ?? "")) return "FORBIDDEN";
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
  CLARIFICATION_REQUIRED: "blocked",
};

/** wire 응답을 검증·정규화하며 계약 불일치나 근거 누락 시 성공 화면을 만들지 않는다. */
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
  const disambiguationOptions = response.data.disambiguation_options || response.error?.disambiguation_options || [];
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
        disambiguation_options: disambiguationOptions,
        clarification_type: null,
        trace_id: response.meta.trace_id,
      }
    : response.error ? {
        ...response.error,
        disambiguation_options: disambiguationOptions,
      } : undefined;
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
    disambiguationOptions: disambiguationOptions.length > 0 ? disambiguationOptions : undefined,
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
      productReleaseId: evidence.product_release_id,
      evidenceCutoff: evidence.evidence_cutoff,
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
