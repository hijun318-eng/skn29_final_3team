/** 서버가 확정한 감사 추적 묶음과 redacted 이벤트 응답을 검증하는 프런트 계약 모듈이다. */

/** 감사 결과를 성공·정책 거부·실행 실패·진행 상태로 구분하는 공개 값이다. */
export type AuditOutcome =
  | "SUCCEEDED"
  | "FAILED"
  | "DENIED"
  | "CANCELLED"
  | "IN_PROGRESS"
  | "CLARIFICATION_REQUIRED"
  | "UNKNOWN";

/** 서버가 감사 화면에 공개하도록 정규화한 수행자 정보다. */
export interface AuditActor {
  subject: string | null;
  display_name: string;
  role: string;
}

/** 감사 이벤트가 직접 다룬 객체의 종류와 불변 식별자다. */
export interface AuditObjectReference {
  type: string;
  id: string;
}

/** 여러 이벤트를 하나의 trail로 묶은 서버 소유 correlation 기준이다. */
export interface AuditCorrelation {
  type: string;
  id: string;
}

/** 최신순 trail 목록에서 선택에 필요한 최소 공개 필드다. */
export interface AuditTrailSummary {
  trail_id: string;
  headline: string;
  started_at: string;
  ended_at: string | null;
  outcome: AuditOutcome;
  event_count: number;
  actor: AuditActor;
  primary_object: AuditObjectReference;
  correlation: AuditCorrelation;
}

/** 단일 이벤트가 연결할 수 있는 실행·정책·산출물 식별자다. */
export interface AuditEvidence {
  request_id: string | null;
  trace_id: string | null;
  query_execution_id: string | null;
  query_id: string | null;
  artifact_id: string | null;
  report_run_id: string | null;
  context_release_id: string | null;
  model_version_id: string | null;
  sql_policy_version: string | null;
}

/** 서버가 정한 순서와 redacted 근거만 포함하는 감사 이벤트다. */
export interface AuditTrailEvent {
  event_id: string;
  occurred_at: string;
  sequence: number;
  action_code: string;
  action_label: string;
  summary: string;
  outcome: AuditOutcome;
  actor: AuditActor;
  object: AuditObjectReference;
  evidence: AuditEvidence;
  details_redacted: Record<string, unknown>;
}

/** 선택한 trail의 시간 범위와 서버 정렬 이벤트를 포함하는 상세 계약이다. */
export interface AuditTrailDetailData {
  trail_id: string;
  headline: string;
  started_at: string;
  ended_at: string | null;
  outcome: AuditOutcome;
  events: AuditTrailEvent[];
}

/** append-only 목록의 다음 위치를 서버 cursor로만 전달하는 응답 계약이다. */
export interface AuditTrailPage {
  items: AuditTrailSummary[];
  next_cursor: string | null;
}

/** 목록 API가 서버에서 적용할 검색·기간·결과·action 조건이다. */
export interface AuditTrailFilters {
  query: string;
  outcome: "" | AuditOutcome;
  action: string;
  from: string;
  to: string;
}

const OUTCOMES = new Set<AuditOutcome>([
  "SUCCEEDED",
  "FAILED",
  "DENIED",
  "CANCELLED",
  "IN_PROGRESS",
  "CLARIFICATION_REQUIRED",
  "UNKNOWN",
]);

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function normalizeOutcome(value: unknown): AuditOutcome {
  if (typeof value !== "string" || !OUTCOMES.has(value as AuditOutcome)) {
    throw new Error("감사 추적 API가 지원하지 않는 결과 상태를 반환했습니다.");
  }
  return value as AuditOutcome;
}

function normalizeActor(value: unknown): AuditActor {
  if (!isRecord(value)
    || !isNullableString(value.subject)
    || typeof value.display_name !== "string"
    || typeof value.role !== "string") {
    throw new Error("감사 추적 API가 올바르지 않은 수행자 정보를 반환했습니다.");
  }
  return value as unknown as AuditActor;
}

function normalizeObjectReference(value: unknown): AuditObjectReference {
  if (!isRecord(value) || typeof value.type !== "string" || typeof value.id !== "string") {
    throw new Error("감사 추적 API가 올바르지 않은 대상 정보를 반환했습니다.");
  }
  return value as unknown as AuditObjectReference;
}

function normalizeSummary(value: unknown): AuditTrailSummary {
  if (!isRecord(value)
    || typeof value.trail_id !== "string"
    || typeof value.headline !== "string"
    || typeof value.started_at !== "string"
    || !isNullableString(value.ended_at)
    || !Number.isInteger(value.event_count)
    || value.event_count < 0
    || !isRecord(value.correlation)
    || typeof value.correlation.type !== "string"
    || typeof value.correlation.id !== "string") {
    throw new Error("감사 추적 목록 API가 올바르지 않은 응답을 반환했습니다.");
  }
  return {
    trail_id: value.trail_id,
    headline: value.headline,
    started_at: value.started_at,
    ended_at: value.ended_at,
    outcome: normalizeOutcome(value.outcome),
    event_count: value.event_count,
    actor: normalizeActor(value.actor),
    primary_object: normalizeObjectReference(value.primary_object),
    correlation: value.correlation as unknown as AuditCorrelation,
  };
}

function normalizeEvidence(value: unknown): AuditEvidence {
  const keys: Array<keyof AuditEvidence> = [
    "request_id",
    "trace_id",
    "query_execution_id",
    "query_id",
    "artifact_id",
    "report_run_id",
    "context_release_id",
    "model_version_id",
    "sql_policy_version",
  ];
  if (!isRecord(value) || keys.some((key) => !isNullableString(value[key]))) {
    throw new Error("감사 추적 API가 올바르지 않은 근거 식별자를 반환했습니다.");
  }
  return value as unknown as AuditEvidence;
}

function normalizeEvent(value: unknown): AuditTrailEvent {
  if (!isRecord(value)
    || typeof value.event_id !== "string"
    || typeof value.occurred_at !== "string"
    || !Number.isInteger(value.sequence)
    || value.sequence < 0
    || typeof value.action_code !== "string"
    || typeof value.action_label !== "string"
    || typeof value.summary !== "string"
    || !isRecord(value.details_redacted)) {
    throw new Error("감사 추적 상세 API가 올바르지 않은 이벤트를 반환했습니다.");
  }
  return {
    event_id: value.event_id,
    occurred_at: value.occurred_at,
    sequence: value.sequence,
    action_code: value.action_code,
    action_label: value.action_label,
    summary: value.summary,
    outcome: normalizeOutcome(value.outcome),
    actor: normalizeActor(value.actor),
    object: normalizeObjectReference(value.object),
    evidence: normalizeEvidence(value.evidence),
    details_redacted: value.details_redacted,
  };
}

/** 알 수 없는 목록 payload를 cursor와 trail 요약이 검증된 화면 계약으로 변환한다. */
export function normalizeAuditTrailPage(value: unknown): AuditTrailPage {
  if (!isRecord(value) || !Array.isArray(value.items) || !isNullableString(value.next_cursor)) {
    throw new Error("감사 추적 목록 API가 올바르지 않은 응답을 반환했습니다.");
  }
  return { items: value.items.map(normalizeSummary), next_cursor: value.next_cursor };
}

/** 알 수 없는 상세 payload의 이벤트 필드와 서버 sequence 정렬을 함께 검증한다. */
export function normalizeAuditTrailDetail(value: unknown): AuditTrailDetailData {
  if (!isRecord(value)
    || typeof value.trail_id !== "string"
    || typeof value.headline !== "string"
    || typeof value.started_at !== "string"
    || !isNullableString(value.ended_at)
    || !Array.isArray(value.events)) {
    throw new Error("감사 추적 상세 API가 올바르지 않은 응답을 반환했습니다.");
  }
  const events = value.events.map(normalizeEvent);
  if (events.some((event, index) => index > 0 && events[index - 1].sequence > event.sequence)) {
    throw new Error("감사 추적 상세 API가 이벤트를 올바른 순서로 반환하지 않았습니다.");
  }
  return {
    trail_id: value.trail_id,
    headline: value.headline,
    started_at: value.started_at,
    ended_at: value.ended_at,
    outcome: normalizeOutcome(value.outcome),
    events,
  };
}
