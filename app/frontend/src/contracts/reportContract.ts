/** 보고서 API의 versioned 명령·응답·도메인 타입을 정의하는 계약 모듈이다. */
/** 보고서 응답·명령의 호환성 버전이다. */ export const REPORT_CONTRACT_VERSION = "REPORT-v1.0.0";
/** 보고서 요청 header가 선언하는 OpenAPI 버전이다. */ export const REPORT_REQUEST_CONTEXT_VERSION = "OPENAPI-v1.0.0";
/** 서버 보고서 실행에서 허용되는 상태 집합이다. */ export const REPORT_RUN_STATUSES = ["queued", "running", "success", "partial", "failed", "cancelled"] as const;
/** 보고서 실행 상태의 리터럴 타입이다. */ export type ReportRunStatus = typeof REPORT_RUN_STATUSES[number];

/** 블록별 실행이 반환할 수 있는 정규화 실패 코드 집합이다. */ export const REPORT_BLOCK_FAILURE_CODES = [
  "AUTHENTICATION_REQUIRED", "ACCESS_DENIED", "CONTEXT_INCOMPLETE",
  "CONTEXT_SOURCE_FAILED", "SEMANTIC_CONTRACT_INVALID", "DATA_ASSET_NOT_FOUND",
  "MODEL_CONTRACT_INVALID", "MODEL_TIMEOUT", "MODEL_ENDPOINT_UNAVAILABLE",
  "MODEL_OUTPUT_UNGROUNDED", "CIRCUIT_OPEN", "INSUFFICIENT_CONTEXT",
  "UNREPAIRABLE", "SQL_POLICY_BLOCKED",
  "SQL_REPAIR_FAILED", "TRINO_CONNECTION_FAILED", "QUERY_TIMEOUT",
  "QUERY_SOURCE_FAILED", "RESULT_VALIDATION_FAILED",
  "RESULT_EVIDENCE_MISSING", "ARTIFACT_PERSIST_FAILED", "PARTIAL_FAILURE",
  "INSUFFICIENT_EVIDENCE", "RATE_LIMITED", "REQUEST_CANCELLED",
  "CONTRACT_VERSION_MISMATCH", "SCHEMA_VERSION_MISMATCH",
  "RESOURCE_NOT_FOUND", "RESOURCE_CONFLICT", "DEPENDENCY_UNAVAILABLE",
  "DEFINITION_NOT_FOUND", "REPLAY_UNAVAILABLE", "INTERNAL_ERROR",
] as const;
/** 블록 실행 실패 코드의 리터럴 타입이다. */ export type ReportBlockFailureCode = typeof REPORT_BLOCK_FAILURE_CODES[number];

/** 서울 wall-clock 입력을 실제 ISO instant로 변환하며 유효하지 않은 시각은 예외로 거부한다. */
export function seoulWallClockToIso(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw new Error("서울 실행 시각은 YYYY-MM-DDTHH:mm 형식이어야 합니다.");
  const [, yearText, monthText, dayText, hourText, minuteText] = match;
  const [year, month, day, hour, minute] = [yearText, monthText, dayText, hourText, minuteText].map(Number);
  const wallClock = new Date(Date.UTC(year, month - 1, day, hour, minute));
  if (
    wallClock.getUTCFullYear() !== year
    || wallClock.getUTCMonth() !== month - 1
    || wallClock.getUTCDate() !== day
    || wallClock.getUTCHours() !== hour
    || wallClock.getUTCMinutes() !== minute
  ) throw new Error("유효한 서울 실행 시각을 입력해 주세요.");
  return new Date(wallClock.getTime() - 9 * 60 * 60 * 1000).toISOString();
}

/** 보고서 API가 영속화하는 블록 타입 집합이다. */ export const REPORT_BLOCK_TYPES = ["table", "chart", "text", "artifact"] as const;
/** 영속 블록 타입의 리터럴 타입이다. */ export type ReportBlockType = typeof REPORT_BLOCK_TYPES[number];

/** 보고서 정의에 저장되는 블록과 선택적 grid 좌표 계약이다. */ export interface ReportBlock {
  readonly id: string;
  readonly title: string;
  readonly artifactId?: string;
  readonly queryId?: string;
  readonly question?: string;
  readonly sourceUrns?: readonly string[];
  readonly columns: number;
  readonly type?: ReportBlockType;
  readonly content?: string;
  readonly x?: number;
  readonly y?: number;
  readonly w?: number;
  readonly h?: number;
}

/** 편집기에서 모든 grid 좌표가 확정된 블록이다. */ export type DraftLayoutBlock = ReportBlock & Required<Pick<ReportBlock, "x" | "y" | "w" | "h">>;

/** 서버가 지원하는 A4 방향 집합이다. */ export const REPORT_ORIENTATIONS = ["portrait", "landscape"] as const;
/** 보고서 방향의 리터럴 타입이다. */ export type ReportOrientation = typeof REPORT_ORIENTATIONS[number];
/** 서버와 공유하는 통화 표시 단위 집합이다. */ export const REPORT_CURRENCY_DISPLAY_UNITS = [
  "auto", "one", "thousand", "million", "hundredMillion", "billion",
] as const;
/** 통화 표시 단위의 리터럴 타입이다. */ export type ReportCurrencyDisplayUnit = typeof REPORT_CURRENCY_DISPLAY_UNITS[number];

/** 알 수 없는 문서 방향을 저장 API로 보내기 전에 예외로 차단한다. */
export function assertReportOrientation(value: unknown): asserts value is ReportOrientation {
  if (typeof value !== "string" || !(REPORT_ORIENTATIONS as readonly string[]).includes(value)) {
    throw new Error(`지원하지 않는 Report 용지 방향입니다: ${String(value)}`);
  }
}

/** 알 수 없는 통화 단위를 저장 API로 보내기 전에 예외로 차단한다. */
export function assertReportCurrencyDisplayUnit(value: unknown): asserts value is ReportCurrencyDisplayUnit {
  if (typeof value !== "string" || !(REPORT_CURRENCY_DISPLAY_UNITS as readonly string[]).includes(value)) {
    throw new Error(`지원하지 않는 Report 금액 표시 단위입니다: ${String(value)}`);
  }
}

/** 정규화된 immutable 보고서 정의 버전이다. */ export interface ReportDefinitionVersion {
  readonly definitionId: string;
  readonly version: number;
  readonly status: "draft" | "approved";
  readonly title: string;
  readonly blocks: readonly ReportBlock[];
  readonly orientation: ReportOrientation;
  readonly currencyDisplayUnit: ReportCurrencyDisplayUnit;
  readonly approvedAt?: string;
}

/** 정의 버전에 연결된 immutable 분석 artifact 참조다. */ export interface ReportArtifactVersion {
  readonly artifactId: string;
  readonly artifactChecksum: string;
  readonly queryId: string;
}

/** 승인된 정의에서 생성된 최종 A4 문서 메타데이터다. */ export interface ReportDocument {
  readonly definitionId: string;
  readonly definitionVersion: number;
  readonly orientation: ReportOrientation;
  readonly currencyDisplayUnit: ReportCurrencyDisplayUnit;
  readonly rendererVersion: string;
  readonly sourceChecksum: string;
  readonly htmlChecksum: string;
  readonly pdfChecksum: string;
  readonly artifactVersions: readonly ReportArtifactVersion[];
  readonly confirmedAt: string;
}

/** 실행 중 개별 블록의 상태·오류·결과 참조다. */ export interface ReportBlockRun {
  readonly blockId: string;
  readonly artifactId?: string;
  readonly queryId?: string;
  readonly snapshotChecksum?: string;
  readonly status: "success" | "partial" | "failed" | "cancelled";
  readonly requestId?: string;
  readonly failureCode?: ReportBlockFailureCode;
  readonly failureMessage?: string;
}

/** 보고서 실행과 블록 실행을 묶은 정규화 모델이다. */ export interface ReportRun {
  readonly runId: string;
  readonly definitionId: string;
  readonly definitionVersion: number;
  readonly asOf: string;
  readonly policyVersion: string;
  readonly contextHash: string;
  readonly watermark: Readonly<Record<string, string>>;
  readonly status: ReportRunStatus;
  readonly blocks: readonly ReportBlockRun[];
}

/** 정의 목록 API의 versioned wire envelope다. */ export interface ReportDefinitionListResponse {
  readonly contract_version: string;
  readonly items: readonly ReportDefinitionResponse[];
}

/** 단일 정의 API의 versioned wire envelope다. */ export interface ReportDefinitionResponse {
  readonly contract_version: string;
  readonly definition_id: string;
  readonly version: number;
  readonly status: "draft" | "approved";
  readonly title: string;
  readonly blocks: readonly ReportBlockResponse[];
  readonly orientation: ReportOrientation;
  readonly currency_display_unit: ReportCurrencyDisplayUnit;
  readonly approved_at: string | null;
}

/** 최종 문서 API의 versioned wire envelope다. */ export interface ReportDocumentResponse {
  readonly definition_id: string;
  readonly definition_version: number;
  readonly orientation: ReportOrientation;
  readonly currency_display_unit: ReportCurrencyDisplayUnit;
  readonly renderer_version: string;
  readonly source_checksum: string;
  readonly html_checksum: string;
  readonly pdf_checksum: string;
  readonly artifact_versions: readonly {
    readonly artifact_id: string;
    readonly artifact_checksum: string;
    readonly query_id: string;
  }[];
  readonly confirmed_at: string;
}

/** 보고서 블록 wire 표현이다. */ export interface ReportBlockResponse {
  readonly block_id: string;
  readonly title: string;
  readonly artifact_id: string | null;
  readonly query_id: string | null;
  readonly columns: number;
  readonly type: ReportBlockType;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  readonly content: string;
}

/** 실행 목록 API의 versioned wire envelope다. */ export interface ReportRunListResponse {
  readonly contract_version: string;
  readonly items: readonly ReportRunResponse[];
}

/** 단일 실행 API의 versioned wire envelope다. */ export interface ReportRunResponse {
  readonly contract_version: string;
  readonly run_id: string;
  readonly definition_id: string;
  readonly definition_version: number;
  readonly as_of: string;
  readonly policy_version: string;
  readonly context_hash: string;
  readonly watermark: Readonly<Record<string, string>>;
  readonly status: ReportRunStatus;
  readonly blocks: readonly ReportBlockRunResponse[];
}

/** 블록 실행의 wire 상태·결과·실패 표현이다. */ export interface ReportBlockRunResponse {
  readonly block_id: string;
  readonly artifact_id: string | null;
  readonly query_id: string | null;
  readonly snapshot_checksum: string | null;
  readonly status: "success" | "partial" | "failed" | "cancelled";
  readonly request_id: string | null;
  readonly failure_code: ReportBlockFailureCode | null;
  readonly failure_message: string | null;
}

/** 수동 실행 명령 수락 결과 계약이다. */ export interface ManualRunCommandResponse {
  readonly contract_version: string;
  readonly command_id: string;
  readonly definition_id: string;
  readonly version: number;
  readonly as_of: string;
  readonly idempotency_key: string;
  readonly status: ReportRunStatus;
  readonly run_id?: string | null;
}

/** 서버가 계산한 다음 실행 시각을 포함하는 schedule 계약이다. */ export interface ReportScheduleResponse {
  readonly schedule_id: string;
  readonly definition_id: string;
  readonly version: number;
  readonly cadence: "daily" | "weekly" | "monthly";
  readonly next_run_at: string;
  readonly timezone: "Asia/Seoul";
  readonly enabled: boolean;
  readonly last_run_id: string | null;
}

/** schedule 목록의 versioned wire envelope다. */ export interface ReportScheduleListResponse {
  readonly items: readonly ReportScheduleResponse[];
}

/** due schedule 실행 명령 결과 계약이다. */ export interface RunDueReportScheduleResponse {
  readonly schedule: ReportScheduleResponse;
  readonly executed: boolean;
  readonly run: ReportRunResponse | null;
}

/** 근거 artifact에서 생성된 assistant 초안과 trace 계약이다. */ export interface ReportAssistantDraftResponse {
  readonly assistant_request_id: string;
  readonly status: "success";
  readonly definition: ReportDefinitionResponse;
  readonly trace: {
    readonly model_version: string;
    readonly prompt_id: string;
    readonly prompt_version: string;
    readonly prompt_hash: string;
    readonly attempts: number;
    readonly duration_ms: number;
  };
}

/** 보고서 블록 저장 명령의 wire 입력 계약이다. */ export interface ReportBlockRequest {
  readonly block_id: string;
  readonly title: string;
  readonly artifact_id?: string;
  readonly query_id?: string;
  readonly columns: number;
  readonly type: ReportBlockType;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  readonly content: string;
}

/** 서버 응답 계약 버전 불일치를 즉시 예외로 차단한다. */
export function assertReportContractVersion(value: string): void {
  if (value !== REPORT_CONTRACT_VERSION) throw new Error(`지원하지 않는 Report 계약입니다: ${value}`);
}
