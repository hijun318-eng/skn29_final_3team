export const REPORT_CONTRACT_VERSION = "REPORT-v1.0.0";

export interface ReportBlock {
  readonly id: string;
  readonly title: string;
  readonly artifactId: string;
  readonly queryId?: string;
  readonly question?: string;
  readonly sourceUrns?: readonly string[];
  readonly columns: number;
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
  readonly status: "queued" | "running" | "success" | "partial" | "failed" | "cancelled";
  readonly blocks: readonly ReportBlockRun[];
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
