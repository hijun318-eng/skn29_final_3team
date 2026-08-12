export const REPORT_CONTRACT_VERSION = "REPORT-v1.0.0";
export const REPORT_REQUEST_CONTEXT_VERSION = "OPENAPI-v1.0.0";
export const REPORT_RUN_STATUSES = ["queued", "running", "success", "partial", "failed", "cancelled"] as const;
export type ReportRunStatus = typeof REPORT_RUN_STATUSES[number];
export const REPORT_BLOCK_TYPES = ["table", "chart", "text"] as const;
export type ReportBlockType = typeof REPORT_BLOCK_TYPES[number];

export interface ReportBlock {
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

export type DraftLayoutBlock = ReportBlock & Required<Pick<ReportBlock, "x" | "y" | "w" | "h">>;

export function normalizeDraftLayout(blocks: readonly ReportBlock[]): readonly DraftLayoutBlock[] {
  let x = 0;
  let y = 0;
  let rowHeight = 0;
  return blocks.map((block) => {
    const w = Math.min(12, Math.max(1, block.w ?? block.columns));
    const h = Math.max(1, block.h ?? 4);
    if (x + w > 12) {
      x = 0;
      y += rowHeight;
      rowHeight = 0;
    }
    const placed = { ...block, columns: w, x, y, w, h };
    x += w;
    rowHeight = Math.max(rowHeight, h);
    if (x === 12) {
      x = 0;
      y += rowHeight;
      rowHeight = 0;
    }
    return placed;
  });
}

export function serializeDraftLayout(blocks: readonly ReportBlock[]): string {
  return JSON.stringify(normalizeDraftLayout(blocks));
}

export interface ReportDefinitionVersion {
  readonly definitionId: string;
  readonly version: number;
  readonly status: "draft" | "approved";
  readonly title: string;
  readonly blocks: readonly ReportBlock[];
  readonly approvedAt?: string;
}

export interface ReportBlockRun {
  readonly blockId: string;
  readonly artifactId: string;
  readonly queryId: string;
  readonly snapshotChecksum: string;
  readonly status: "success" | "partial" | "failed" | "cancelled";
}

export interface ReportRun {
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

export interface ReportDefinitionListResponse {
  readonly contract_version: string;
  readonly items: readonly ReportDefinitionResponse[];
}

export interface ReportDefinitionResponse {
  readonly contract_version: string;
  readonly definition_id: string;
  readonly version: number;
  readonly status: "draft" | "approved";
  readonly title: string;
  readonly blocks: readonly ReportBlockResponse[];
  readonly approved_at: string | null;
}

export interface ReportBlockResponse {
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

export interface ReportRunListResponse {
  readonly contract_version: string;
  readonly items: readonly ReportRunResponse[];
}

export interface ReportRunResponse {
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

export interface ReportArtifactPreviewResponse {
  readonly contract_version: string;
  readonly artifact_id: string;
  readonly query_id: string;
  readonly snapshot_checksum: string;
  readonly summary: string;
  readonly table: {
    readonly columns: readonly string[];
    readonly rows: readonly Readonly<Record<string, string | number | boolean | null>>[];
  };
  readonly chart: {
    readonly chart_type: string;
    readonly x_field: string;
    readonly y_fields: readonly string[];
  } | null;
}

export interface ReportArtifactPreview {
  readonly artifactId: string;
  readonly queryId: string;
  readonly snapshotChecksum: string;
  readonly summary: string;
  readonly table: ReportArtifactPreviewResponse["table"];
  readonly chart?: { readonly chartType: string; readonly xField: string; readonly yFields: readonly string[] };
}

export interface ReportBlockRunResponse {
  readonly block_id: string;
  readonly artifact_id: string;
  readonly query_id: string;
  readonly snapshot_checksum: string;
  readonly status: "success" | "partial" | "failed" | "cancelled";
}

export interface ManualRunCommandResponse {
  readonly contract_version: string;
  readonly command_id: string;
  readonly definition_id: string;
  readonly version: number;
  readonly as_of: string;
  readonly idempotency_key: string;
  readonly status: "queued";
}

export type ReportScheduleFrequency = "daily" | "weekly" | "monthly";

export interface ReportSchedule {
  readonly scheduleId: string;
  readonly definitionId: string;
  readonly version: number;
  readonly frequency: ReportScheduleFrequency;
  readonly hour: number;
  readonly minute: number;
  readonly timezone: "Asia/Seoul";
  readonly weekday?: number;
  readonly dayOfMonth?: number;
  readonly enabled: boolean;
  readonly nextRunAt?: string;
}

export interface ReportScheduleResponse {
  readonly contract_version: string;
  readonly schedule_id: string;
  readonly definition_id: string;
  readonly version: number;
  readonly frequency: ReportScheduleFrequency;
  readonly hour: number;
  readonly minute: number;
  readonly timezone: "Asia/Seoul";
  readonly weekday: number | null;
  readonly day_of_month: number | null;
  readonly enabled: boolean;
  readonly next_run_at: string | null;
}

export interface ReportScheduleListResponse {
  readonly contract_version: string;
  readonly items: readonly ReportScheduleResponse[];
}

export interface UpsertReportScheduleRequest {
  readonly frequency: ReportScheduleFrequency;
  readonly hour: number;
  readonly minute: number;
  readonly weekday?: number;
  readonly day_of_month?: number;
  readonly enabled: boolean;
}

export interface ReportBlockRequest {
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

export function assertReportContractVersion(value: string): void {
  if (value !== REPORT_CONTRACT_VERSION) throw new Error(`지원하지 않는 Report 계약입니다: ${value}`);
}

function normalizeBlock(block: ReportBlockResponse): DraftLayoutBlock {
  if (!REPORT_BLOCK_TYPES.includes(block.type)) throw new Error(`지원하지 않는 Report block type입니다: ${block.type}`);
  return {
    id: block.block_id,
    title: block.title,
    artifactId: block.artifact_id ?? undefined,
    queryId: block.query_id ?? undefined,
    columns: block.columns,
    type: block.type,
    content: block.content,
    x: block.x,
    y: block.y,
    w: block.w,
    h: block.h,
  };
}

export function normalizeReportDefinition(response: ReportDefinitionResponse): ReportDefinitionVersion {
  assertReportContractVersion(response.contract_version);
  if (!["draft", "approved"].includes(response.status)) throw new Error(`지원하지 않는 Report 상태입니다: ${response.status}`);
  return {
    definitionId: response.definition_id,
    version: response.version,
    status: response.status,
    title: response.title,
    blocks: response.blocks.map(normalizeBlock),
    approvedAt: response.approved_at ?? undefined,
  };
}

export function normalizeReportRun(response: ReportRunResponse): ReportRun {
  assertReportContractVersion(response.contract_version);
  if (!REPORT_RUN_STATUSES.includes(response.status)) throw new Error(`지원하지 않는 Report run 상태입니다: ${response.status}`);
  return createReportRun({
    runId: response.run_id,
    definitionId: response.definition_id,
    definitionVersion: response.definition_version,
    asOf: response.as_of,
    policyVersion: response.policy_version,
    contextHash: response.context_hash,
    watermark: response.watermark,
    status: response.status,
    blocks: response.blocks.map((block) => ({
      blockId: block.block_id,
      artifactId: block.artifact_id,
      queryId: block.query_id,
      snapshotChecksum: block.snapshot_checksum,
      status: block.status,
    })),
  });
}

export function normalizeReportArtifactPreview(response: ReportArtifactPreviewResponse): ReportArtifactPreview {
  assertReportContractVersion(response.contract_version);
  return {
    artifactId: response.artifact_id,
    queryId: response.query_id,
    snapshotChecksum: response.snapshot_checksum,
    summary: response.summary,
    table: response.table,
    chart: response.chart ? {
      chartType: response.chart.chart_type,
      xField: response.chart.x_field,
      yFields: response.chart.y_fields,
    } : undefined,
  };
}

export function normalizeReportSchedule(response: ReportScheduleResponse): ReportSchedule {
  assertReportContractVersion(response.contract_version);
  if (!(["daily", "weekly", "monthly"] as const).includes(response.frequency)) {
    throw new Error(`지원하지 않는 Report schedule 주기입니다: ${response.frequency}`);
  }
  return {
    scheduleId: response.schedule_id,
    definitionId: response.definition_id,
    version: response.version,
    frequency: response.frequency,
    hour: response.hour,
    minute: response.minute,
    timezone: response.timezone,
    weekday: response.weekday ?? undefined,
    dayOfMonth: response.day_of_month ?? undefined,
    enabled: response.enabled,
    nextRunAt: response.next_run_at ?? undefined,
  };
}

export function toReportBlockRequest(block: ReportBlock): ReportBlockRequest {
  const type = block.type ?? "text";
  if (!REPORT_BLOCK_TYPES.includes(type)) throw new Error(`API mode에서 지원하지 않는 block type입니다: ${type}`);
  if ((type === "table" || type === "chart") && !block.artifactId) {
    throw new Error("table·chart block은 Artifact가 필요합니다.");
  }
  const content = block.content ?? "";
  if (type === "text" && !content.trim()) throw new Error("text block 내용은 비어 있을 수 없습니다.");
  const w = block.w ?? block.columns;
  return {
    block_id: block.id,
    title: block.title,
    ...(block.artifactId ? { artifact_id: block.artifactId } : {}),
    ...(block.queryId ? { query_id: block.queryId } : {}),
    columns: w,
    type,
    x: block.x ?? 0,
    y: block.y ?? 0,
    w,
    h: block.h ?? 1,
    content,
  };
}

export function createDraft(approved: ReportDefinitionVersion): ReportDefinitionVersion {
  if (approved.status !== "approved") throw new Error("승인된 Report version만 draft의 기준이 될 수 있습니다.");
  return {
    definitionId: approved.definitionId,
    version: approved.version + 1,
    status: "draft",
    title: approved.title,
    blocks: approved.blocks.map((block) => ({ ...block })),
  };
}

export function approveDraft(
  draft: ReportDefinitionVersion,
  approvedAt: string,
): Readonly<ReportDefinitionVersion> {
  if (draft.status !== "draft") throw new Error("draft Report version만 승인할 수 있습니다.");
  if (draft.blocks.some((block) => block.columns < 1 || block.columns > 12
    || (block.x !== undefined && (block.x < 0 || block.x + (block.w ?? block.columns) > 12))
    || (block.y !== undefined && block.y < 0)
    || (block.w !== undefined && (block.w < 1 || block.w > 12))
    || (block.h !== undefined && block.h < 1))) {
    throw new Error("Report block columns는 1~12 범위여야 합니다.");
  }
  const blocks = Object.freeze(draft.blocks.map((block) => Object.freeze({ ...block })));
  return Object.freeze({
    ...draft,
    version: draft.version,
    status: "approved" as const,
    approvedAt,
    blocks,
  });
}

export function createReportRun(run: ReportRun): Readonly<ReportRun> {
  if (!run.definitionId || run.definitionVersion < 1 || !run.asOf) {
    throw new Error("Report run은 definition version과 as_of를 유지해야 합니다.");
  }
  return Object.freeze({
    ...run,
    watermark: Object.freeze({ ...run.watermark }),
    blocks: Object.freeze(run.blocks.map((block) => Object.freeze({ ...block }))),
  });
}
