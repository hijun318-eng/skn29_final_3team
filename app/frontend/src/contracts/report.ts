export const REPORT_CONTRACT_VERSION = "REPORT-v1.0.0";
export const REPORT_REQUEST_CONTEXT_VERSION = "OPENAPI-v1.0.0";
export const REPORT_RUN_STATUSES = ["queued", "running", "success", "partial", "failed", "cancelled"] as const;
export type ReportRunStatus = typeof REPORT_RUN_STATUSES[number];
export const REPORT_BLOCK_FAILURE_CODES = [
  "AUTHENTICATION_REQUIRED", "ACCESS_DENIED", "CONTEXT_INCOMPLETE",
  "CONTEXT_SOURCE_FAILED", "DATA_ASSET_NOT_FOUND",
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
export type ReportBlockFailureCode = typeof REPORT_BLOCK_FAILURE_CODES[number];

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
export const REPORT_BLOCK_TYPES = ["table", "chart", "text", "artifact"] as const;
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

export function reorderDraftBlocks(
  blocks: readonly ReportBlock[],
  sourceId: string,
  targetId: string,
): readonly DraftLayoutBlock[] {
  const sourceIndex = blocks.findIndex((block) => block.id === sourceId);
  const targetIndex = blocks.findIndex((block) => block.id === targetId);
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) {
    return normalizeDraftLayout(blocks);
  }
  const reordered = [...blocks];
  const [source] = reordered.splice(sourceIndex, 1);
  reordered.splice(targetIndex, 0, source);
  return normalizeDraftLayout(reordered);
}

function minimumDraftWidth(block: ReportBlock): number {
  return block.type === "text" ? 4 : 6;
}

function normalizedDraftBlock(block: ReportBlock): DraftLayoutBlock {
  const w = Math.min(12, Math.max(minimumDraftWidth(block), block.w ?? block.columns));
  return {
    ...block,
    columns: w,
    x: Math.min(12 - w, Math.max(0, block.x ?? 0)),
    y: Math.max(0, block.y ?? 0),
    w,
    h: Math.max(1, block.h ?? 1),
  };
}

function minimumDraftHeight(block: ReportBlock): number {
  return block.type === "artifact" ? 12 : block.type === "chart" ? 7 : block.type === "table" ? 5 : 4;
}

export function isDraftLayoutValid(blocks: readonly ReportBlock[]): boolean {
  const positioned = blocks.map((block) => ({
    ...block,
    x: block.x,
    y: block.y,
    w: block.w,
    h: block.h,
  }));
  if (positioned.some((block) => (
    typeof block.x !== "number"
    || typeof block.y !== "number"
    || typeof block.w !== "number"
    || typeof block.h !== "number"
    || !Number.isInteger(block.x)
    || !Number.isInteger(block.y)
    || !Number.isInteger(block.w)
    || !Number.isInteger(block.h)
    || Number(block.x) < 0
    || Number(block.y) < 0
    || Number(block.w) < 1
    || Number(block.h) < 1
    || Number(block.x) + Number(block.w) > 12
  ))) return false;
  for (let left = 0; left < positioned.length; left += 1) {
    for (let right = left + 1; right < positioned.length; right += 1) {
      const a = positioned[left];
      const b = positioned[right];
      const [ax, ay, aw, ah] = [Number(a.x), Number(a.y), Number(a.w), Number(a.h)];
      const [bx, by, bw, bh] = [Number(b.x), Number(b.y), Number(b.w), Number(b.h)];
      if (ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by) return false;
    }
  }
  return true;
}

/**
 * Keeps a valid server layout byte-for-byte equivalent on open. Invalid or
 * legacy unpositioned rows are repaired explicitly instead of silently
 * compacting every saved report during read.
 */
export function restoreDraftLayout(blocks: readonly ReportBlock[]): readonly DraftLayoutBlock[] {
  if (isDraftLayoutValid(blocks)) {
    return blocks.map((block) => ({
      ...block,
      columns: block.w as number,
      x: block.x as number,
      y: block.y as number,
      w: block.w as number,
      h: block.h as number,
    }));
  }
  return compactDraftLayout(blocks.map((block) => ({
    ...block,
    h: Math.max(block.h ?? 1, minimumDraftHeight(block)),
  })));
}

/**
 * Packs the dashboard from top to bottom without arbitrary vertical holes.
 * Blocks keep their visual order and preferred width. An unfinished row gives
 * its remaining columns to the last block, and every block in a row shares the
 * same height, so no blank band or middle gap remains in the document.
 */
export function compactDraftLayout(blocks: readonly ReportBlock[]): readonly DraftLayoutBlock[] {
  const normalized = blocks.map((block, index) => ({ block: normalizedDraftBlock(block), index }));
  const ordered = [...normalized].sort((left, right) => (
    left.block.y - right.block.y || left.block.x - right.block.x || left.index - right.index
  ));
  const resolved = new Map<string, DraftLayoutBlock>();
  let row: DraftLayoutBlock[] = [];
  let rowY = 0;
  let rowX = 0;
  let rowHeight = 0;

  const finishRow = () => {
    if (row.length && rowX < 12) {
      const lastIndex = row.length - 1;
      const last = row[lastIndex];
      const width = last.w + (12 - rowX);
      row[lastIndex] = { ...last, columns: width, w: width };
    }
    for (const block of row) resolved.set(block.id, { ...block, h: rowHeight });
    rowY += rowHeight;
    row = [];
    rowX = 0;
    rowHeight = 0;
  };

  for (const { block } of ordered) {
    const width = block.w;
    if (rowX > 0 && width > 12 - rowX) finishRow();

    const placed = { ...block, columns: width, x: rowX, y: rowY, w: width };
    row.push(placed);
    rowX += width;
    rowHeight = Math.max(rowHeight, placed.h);
    if (rowX === 12) finishRow();
  }
  if (row.length) finishRow();

  return normalized.map(({ block }) => resolved.get(block.id) ?? block);
}

export function placeDraftBlock(
  blocks: readonly ReportBlock[],
  blockId: string,
  requestedX: number,
  requestedY: number,
): readonly DraftLayoutBlock[] {
  const normalized = blocks.map(normalizedDraftBlock);
  const source = normalized.find((block) => block.id === blockId);
  if (!source) return compactDraftLayout(normalized);

  const rawX = Math.max(0, Math.round(requestedX));
  const rawY = Math.max(0, Math.round(requestedY));
  const target = normalized
    .filter((block) => block.id !== blockId && block.w === 12)
    .filter((block) => rawY < block.y + block.h && rawY + source.h > block.y)
    .sort((left, right) => Math.abs(left.y - rawY) - Math.abs(right.y - rawY))[0];

  let candidate = {
    ...source,
    x: Math.min(12 - source.w, rawX),
    y: rawY,
  };
  let adjusted = normalized;
  const sourceRowMates = normalized
    .filter((block) => block.id !== blockId && block.y === source.y)
    .sort((left, right) => left.x - right.x);
  const remainingSourceRowWidth = sourceRowMates.reduce((total, block) => total + block.w, 0);
  if (sourceRowMates.length && remainingSourceRowWidth < 12) {
    const filler = sourceRowMates.at(-1)!;
    adjusted = normalized.map((block) => block.id === filler.id
      ? { ...block, columns: block.w + (12 - remainingSourceRowWidth), w: block.w + (12 - remainingSourceRowWidth) }
      : block);
  }
  if (target) {
    const sourceOnLeft = rawX < 6;
    candidate = { ...candidate, columns: 6, w: 6, x: sourceOnLeft ? 0 : 6, y: target.y };
    adjusted = adjusted.map((block) => block.id === target.id
      ? { ...block, columns: 6, w: 6, x: sourceOnLeft ? 6 : 0 }
      : block);
  }
  return compactDraftLayout(adjusted.map((block) => block.id === blockId ? candidate : block));
}

export function serializeDraftLayout(blocks: readonly ReportBlock[]): string {
  return JSON.stringify(normalizeDraftLayout(blocks));
}

export const REPORT_ORIENTATIONS = ["portrait", "landscape"] as const;
export type ReportOrientation = typeof REPORT_ORIENTATIONS[number];
export const REPORT_CURRENCY_DISPLAY_UNITS = [
  "auto", "one", "thousand", "million", "hundredMillion", "billion",
] as const;
export type ReportCurrencyDisplayUnit = typeof REPORT_CURRENCY_DISPLAY_UNITS[number];

export function assertReportOrientation(value: unknown): asserts value is ReportOrientation {
  if (typeof value !== "string" || !(REPORT_ORIENTATIONS as readonly string[]).includes(value)) {
    throw new Error(`지원하지 않는 Report 용지 방향입니다: ${String(value)}`);
  }
}

export function assertReportCurrencyDisplayUnit(value: unknown): asserts value is ReportCurrencyDisplayUnit {
  if (typeof value !== "string" || !(REPORT_CURRENCY_DISPLAY_UNITS as readonly string[]).includes(value)) {
    throw new Error(`지원하지 않는 Report 금액 표시 단위입니다: ${String(value)}`);
  }
}

export interface ReportDefinitionVersion {
  readonly definitionId: string;
  readonly version: number;
  readonly status: "draft" | "approved";
  readonly title: string;
  readonly blocks: readonly ReportBlock[];
  readonly orientation: ReportOrientation;
  readonly currencyDisplayUnit: ReportCurrencyDisplayUnit;
  readonly approvedAt?: string;
}

export interface ReportArtifactVersion {
  readonly artifactId: string;
  readonly artifactChecksum: string;
  readonly queryId: string;
}

export interface ReportDocument {
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

export interface ReportBlockRun {
  readonly blockId: string;
  readonly artifactId?: string;
  readonly queryId?: string;
  readonly snapshotChecksum?: string;
  readonly status: "success" | "partial" | "failed" | "cancelled";
  readonly requestId?: string;
  readonly failureCode?: ReportBlockFailureCode;
  readonly failureMessage?: string;
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
  readonly orientation: ReportOrientation;
  readonly currency_display_unit: ReportCurrencyDisplayUnit;
  readonly approved_at: string | null;
}

export interface ReportDocumentResponse {
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

export interface ReportBlockRunResponse {
  readonly block_id: string;
  readonly artifact_id: string | null;
  readonly query_id: string | null;
  readonly snapshot_checksum: string | null;
  readonly status: "success" | "partial" | "failed" | "cancelled";
  readonly request_id: string | null;
  readonly failure_code: ReportBlockFailureCode | null;
  readonly failure_message: string | null;
}

export interface ManualRunCommandResponse {
  readonly contract_version: string;
  readonly command_id: string;
  readonly definition_id: string;
  readonly version: number;
  readonly as_of: string;
  readonly idempotency_key: string;
  readonly status: ReportRunStatus;
  readonly run_id?: string | null;
}

export interface ReportScheduleResponse {
  readonly schedule_id: string;
  readonly definition_id: string;
  readonly version: number;
  readonly cadence: "daily" | "weekly" | "monthly";
  readonly next_run_at: string;
  readonly timezone: "Asia/Seoul";
  readonly enabled: boolean;
  readonly last_run_id: string | null;
}

export interface ReportScheduleListResponse {
  readonly items: readonly ReportScheduleResponse[];
}

export interface RunDueReportScheduleResponse {
  readonly schedule: ReportScheduleResponse;
  readonly executed: boolean;
  readonly run: ReportRunResponse | null;
}

export interface ReportAssistantDraftResponse {
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
  assertReportOrientation(response.orientation);
  assertReportCurrencyDisplayUnit(response.currency_display_unit);
  return {
    definitionId: response.definition_id,
    version: response.version,
    status: response.status,
    title: response.title,
    blocks: response.blocks.map(normalizeBlock),
    orientation: response.orientation,
    currencyDisplayUnit: response.currency_display_unit,
    approvedAt: response.approved_at ?? undefined,
  };
}

export function normalizeReportDocument(response: ReportDocumentResponse): ReportDocument {
  assertReportOrientation(response.orientation);
  assertReportCurrencyDisplayUnit(response.currency_display_unit);
  return {
    definitionId: response.definition_id,
    definitionVersion: response.definition_version,
    orientation: response.orientation,
    currencyDisplayUnit: response.currency_display_unit,
    rendererVersion: response.renderer_version,
    sourceChecksum: response.source_checksum,
    htmlChecksum: response.html_checksum,
    pdfChecksum: response.pdf_checksum,
    artifactVersions: response.artifact_versions.map((artifact) => ({
      artifactId: artifact.artifact_id,
      artifactChecksum: artifact.artifact_checksum,
      queryId: artifact.query_id,
    })),
    confirmedAt: response.confirmed_at,
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
      artifactId: block.artifact_id ?? undefined,
      queryId: block.query_id ?? undefined,
      snapshotChecksum: block.snapshot_checksum ?? undefined,
      status: block.status,
      requestId: block.request_id ?? undefined,
      failureCode: block.failure_code ?? undefined,
      failureMessage: block.failure_message ?? undefined,
    })),
  });
}

export function toReportBlockRequest(block: ReportBlock): ReportBlockRequest {
  const type = block.type ?? "text";
  if (!REPORT_BLOCK_TYPES.includes(type)) throw new Error(`API mode에서 지원하지 않는 block type입니다: ${type}`);
  if (["table", "chart", "artifact"].includes(type) && !block.artifactId) {
    throw new Error("table·chart·artifact block은 Artifact가 필요합니다.");
  }
  if (type === "artifact" && !block.queryId) throw new Error("artifact block은 Query 참조가 필요합니다.");
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
    orientation: approved.orientation,
    currencyDisplayUnit: approved.currencyDisplayUnit,
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
