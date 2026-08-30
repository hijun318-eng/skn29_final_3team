/** 검증 실패 시 원본을 보존하는 보고서 문서 생성·삽입·이동·직렬화 연산 모듈이다. */
import {
  A4_PAGE_LAYOUT,
  REPORT_DOCUMENT_SCHEMA_VERSION,
  REPORT_GRID_COLUMNS,
  type ArtifactReportBlock,
  type CreateReportDocumentInput,
  type CurrencyDisplayPolicy,
  type DocumentOperationResult,
  type InsertArtifactInput,
  type PresentationMode,
  type ReportDocumentBlock,
  type ReportDocumentV2,
  type ReportDropPlacement,
  type ReportOrientation,
} from "./reportDocumentTypes.ts";
import { REPORT_ARTIFACT_VIEW_IDS } from "../../contracts/reportContract.ts";
import {
  canonicalArtifactRef,
  canonicalBlock,
  insertDocumentBlockAtPlacement,
  orderedDocumentBlocks,
  pairedSiblingId,
  reflowDocumentBlocks,
} from "./reportDocumentLayout.ts";
import {
  isIntegerBetween,
  isNonEmptyString,
  isOrientation,
  isPresentationMode,
  validateArtifactReference,
  validateReportDocument,
} from "./reportDocumentValidation.ts";

const DEFAULT_CURRENCY_POLICY: CurrencyDisplayPolicy = Object.freeze({
  currencyCode: "KRW",
  displayUnit: "auto",
  unitPlacement: "header",
  maximumFractionDigits: 1,
});

const DEFAULT_ARTIFACT_HEIGHT: Record<PresentationMode, number> = Object.freeze({
  summary: 8,
  standard: 12,
  detail: 16,
});

const MAX_BLOCK_HEIGHT = A4_PAGE_LAYOUT.landscape.contentRows;

function invalid(document: ReportDocumentV2, ...errors: string[]): DocumentOperationResult {
  return { ok: false, document, errors };
}

function valid(document: ReportDocumentV2): DocumentOperationResult {
  return { ok: true, document, errors: [] };
}

/** 검증된 기본 정책으로 비어 있는 versioned 편집 문서를 생성한다. */
export function createReportDocument(input: CreateReportDocumentInput): ReportDocumentV2 {
  const orientation = input.orientation ?? "portrait";
  const presentationMode = input.presentationMode ?? "standard";
  const currencyPolicy = { ...DEFAULT_CURRENCY_POLICY, ...input.currencyPolicy };
  return {
    schemaVersion: REPORT_DOCUMENT_SCHEMA_VERSION,
    id: input.id,
    title: input.title,
    orientation,
    presentationMode,
    currencyPolicy,
    pages: [{ id: `${input.id}:page:1`, index: 0, size: "A4", orientation, blocks: [] }],
  };
}

/** 페이지 빈 공간을 정리하고 검증 실패 시 원본 문서와 오류를 반환한다. */
export function compactReportDocument(document: ReportDocumentV2): DocumentOperationResult {
  const validation = validateReportDocument(document);
  return validation.valid
    ? valid(reflowDocumentBlocks(document, orderedDocumentBlocks(document)))
    : invalid(document, ...validation.errors);
}

/** artifact 참조와 배치를 검증해 새 블록을 삽입하며 실패 시 원본을 보존한다. */
export function insertArtifactBlock(
  document: ReportDocumentV2,
  input: InsertArtifactInput,
): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  if (!isNonEmptyString(input.blockId)
    || orderedDocumentBlocks(document).some((block) => block.id === input.blockId)) {
    return invalid(document, "blockId must be non-empty and unique");
  }
  if (!isNonEmptyString(input.title)) return invalid(document, "title must be a non-empty string");
  const mode = input.presentationMode ?? document.presentationMode;
  if (!isPresentationMode(mode)) return invalid(document, "presentationMode is invalid");
  if (!Array.isArray(input.visibleViews) || input.visibleViews.length !== 1
    || !REPORT_ARTIFACT_VIEW_IDS.includes(input.visibleViews[0])) {
    return invalid(document, "visibleViews must contain exactly one supported atomic view ID");
  }
  const referenceErrors: string[] = [];
  validateArtifactReference(input.artifactRef, "artifactRef", referenceErrors);
  if (referenceErrors.length > 0) return invalid(document, ...referenceErrors);
  const height = input.height ?? DEFAULT_ARTIFACT_HEIGHT[mode];
  if (!isIntegerBetween(height, 1, MAX_BLOCK_HEIGHT)) {
    return invalid(document, `height must be between 1 and ${MAX_BLOCK_HEIGHT}`);
  }
  const width = input.width ?? REPORT_GRID_COLUMNS;
  if (width !== 6 && width !== REPORT_GRID_COLUMNS) return invalid(document, "width must be 6 or 12");

  const block: ArtifactReportBlock = {
    id: input.blockId,
    kind: "artifact",
    title: input.title,
    x: 0,
    y: 0,
    w: width,
    h: height,
    artifactRef: canonicalArtifactRef(input.artifactRef),
    presentationMode: mode,
    visibleViews: [...input.visibleViews],
  };
  const stream = orderedDocumentBlocks(document);
  const inserted = insertDocumentBlockAtPlacement(
    document,
    stream,
    block,
    input.placement ?? { type: "end" },
  );
  return inserted.error
    ? invalid(document, inserted.error)
    : valid(reflowDocumentBlocks(document, inserted.stream!));
}

/** 지정 블록을 삭제하고 나머지를 재배치하며 알 수 없는 ID는 실패 결과로 닫는다. */
export function deleteReportBlock(document: ReportDocumentV2, blockId: string): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  const stream = orderedDocumentBlocks(document);
  const index = stream.findIndex((block) => block.id === blockId);
  if (index < 0) return invalid(document, "block does not exist");
  const siblingId = pairedSiblingId(document, blockId);
  stream.splice(index, 1);
  if (siblingId) {
    const siblingIndex = stream.findIndex((block) => block.id === siblingId);
    stream[siblingIndex] = canonicalBlock({
      ...stream[siblingIndex],
      w: REPORT_GRID_COLUMNS,
    } as ReportDocumentBlock);
  }
  return valid(reflowDocumentBlocks(document, stream));
}

/** 기존 블록을 상대 위치로 이동해 재배치하고 유효하지 않은 대상은 거부한다. */
export function moveReportBlock(
  document: ReportDocumentV2,
  blockId: string,
  placement: ReportDropPlacement,
): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  if (placement.type !== "end" && placement.targetBlockId === blockId) {
    return invalid(document, "a block cannot target itself");
  }
  const stream = orderedDocumentBlocks(document);
  const sourceIndex = stream.findIndex((block) => block.id === blockId);
  if (sourceIndex < 0) return invalid(document, "block does not exist");
  let [block] = stream.splice(sourceIndex, 1);
  const siblingId = pairedSiblingId(document, blockId);
  if (siblingId) {
    const siblingIndex = stream.findIndex((candidate) => candidate.id === siblingId);
    stream[siblingIndex] = canonicalBlock({
      ...stream[siblingIndex],
      w: REPORT_GRID_COLUMNS,
    } as ReportDocumentBlock);
    block = canonicalBlock({ ...block, w: REPORT_GRID_COLUMNS } as ReportDocumentBlock);
  }
  const inserted = insertDocumentBlockAtPlacement(document, stream, block, placement, blockId);
  return inserted.error
    ? invalid(document, inserted.error)
    : valid(reflowDocumentBlocks(document, inserted.stream!));
}

/** A4 방향을 바꾸고 새 row 한도에 맞춰 전체 블록을 결정론적으로 재배치한다. */
export function setReportOrientation(
  document: ReportDocumentV2,
  orientation: ReportOrientation,
): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  if (!isOrientation(orientation)) return invalid(document, "orientation must be portrait or landscape");
  if (orientation === document.orientation) {
    return valid(reflowDocumentBlocks(document, orderedDocumentBlocks(document)));
  }
  return valid(reflowDocumentBlocks({ ...document, orientation }, orderedDocumentBlocks(document)));
}

/** 검증된 canonical 문서만 결정론적 JSON으로 직렬화한다. */
export function serializeReportDocument(document: ReportDocumentV2): string {
  const compacted = compactReportDocument(document);
  if (!compacted.ok) throw new TypeError(compacted.errors.join("; "));
  return JSON.stringify(compacted.document);
}

/** JSON 편집 문서를 파싱·검증하며 실패 시 예외 대신 원문과 오류 목록을 반환한다. */
export function parseReportDocument(serialized: string):
  | { ok: true; document: ReportDocumentV2; errors: [] }
  | { ok: false; errors: string[] } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(serialized);
  } catch {
    return { ok: false, errors: ["document is not valid JSON"] };
  }
  const validation = validateReportDocument(parsed);
  if (!validation.valid) return { ok: false, errors: validation.errors };
  const compacted = compactReportDocument(parsed as ReportDocumentV2);
  return compacted.ok
    ? { ok: true, document: compacted.document, errors: [] }
    : { ok: false, errors: compacted.errors };
}
