/** 보고서 wire 응답을 versioned immutable UI 모델로 검증·정규화하는 모듈이다. */
import {
  REPORT_BLOCK_TYPES,
  REPORT_RUN_STATUSES,
  assertReportContractVersion,
  assertReportCurrencyDisplayUnit,
  assertReportOrientation,
  type DraftLayoutBlock,
  type ReportBlock,
  type ReportBlockRequest,
  type ReportBlockResponse,
  type ReportDefinitionResponse,
  type ReportDefinitionVersion,
  type ReportDocument,
  type ReportDocumentResponse,
  type ReportRun,
  type ReportRunResponse,
} from "./reportContract.ts";

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

/** 정의 wire 응답의 버전·상태·블록을 검증해 immutable 화면 모델로 변환한다. */
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

/** 최종 문서 wire 응답의 checksum·표시 정책을 보존해 immutable 모델로 변환한다. */
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

/** 실행 wire 응답과 블록 결과를 검증된 immutable 모델로 변환한다. */
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

/** 화면 블록을 허용된 wire 필드만 포함하는 저장 요청으로 축소한다. */
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

/** 승인본에서 내용은 복사하되 다음 버전의 독립 draft를 생성한다. */
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

/** draft를 승인본으로 전환하며 승인 시각·방향 계약을 검증한다. */
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

/** 실행·블록 결과를 깊은 복사 후 동결해 이후 상태 오염을 막는다. */
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
