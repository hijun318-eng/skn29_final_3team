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
  canonicalReportDocument,
  orderedDocumentBlocks,
  pairedSiblingId,
  reflowDocumentBlocks,
  resolveDocumentPageCollisions,
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

function insertBlockPreservingLayout(
  original: ReportDocumentV2,
  block: ReportDocumentBlock,
  placement: ReportDropPlacement,
): DocumentOperationResult {
  let document = canonicalReportDocument(original);
  let pageIndex = placement.type === "end" && placement.pageId
    ? document.pages.findIndex((page) => page.id === placement.pageId)
    : document.pages.length - 1;
  let targetIndex = -1;
  if (placement.type !== "end") {
    pageIndex = document.pages.findIndex((page) => (
      page.blocks.some((candidate) => candidate.id === placement.targetBlockId)
    ));
    if (pageIndex >= 0) {
      targetIndex = document.pages[pageIndex].blocks.findIndex(
        (candidate) => candidate.id === placement.targetBlockId,
      );
    }
  }
  if (pageIndex < 0) return invalid(original, "target page or block does not exist");
  if (placement.type === "end" && !placement.pageId) {
    const lastPage = document.pages[pageIndex];
    const bottom = lastPage.blocks.reduce(
      (value, item) => Math.max(value, item.y + item.h),
      0,
    );
    if (bottom + block.h > A4_PAGE_LAYOUT[document.orientation].contentRows) {
      const nextIndex = document.pages.length;
      document = {
        ...document,
        pages: [...document.pages, {
          id: `${document.id}:page:${nextIndex + 1}`,
          index: nextIndex,
          size: "A4",
          orientation: document.orientation,
          blocks: [],
        }],
      };
      pageIndex = nextIndex;
    }
  }
  const page = document.pages[pageIndex];
  const blocks = [...page.blocks];
  let candidate = canonicalBlock(block);
  if (placement.type === "end") {
    candidate = canonicalBlock({
      ...candidate,
      x: 0,
      y: blocks.reduce((bottom, item) => Math.max(bottom, item.y + item.h), 0),
    } as ReportDocumentBlock);
  } else {
    const target = blocks[targetIndex];
    if (!target) return invalid(original, "target block does not exist");
    if (placement.type === "side") {
      if (target.kind === "pageBreak" || candidate.kind === "pageBreak" || target.w !== REPORT_GRID_COLUMNS) {
        return invalid(original, "side drop requires a full-width content block");
      }
      const targetX = placement.edge === "left" ? 6 : 0;
      blocks[targetIndex] = canonicalBlock({ ...target, x: targetX, w: 6 } as ReportDocumentBlock);
      candidate = canonicalBlock({
        ...candidate,
        x: placement.edge === "left" ? 0 : 6,
        y: target.y,
        w: 6,
      } as ReportDocumentBlock);
    } else {
      candidate = canonicalBlock({
        ...candidate,
        x: 0,
        y: placement.type === "before" ? target.y : target.y + target.h,
      } as ReportDocumentBlock);
    }
  }
  const nextBlocks = resolveDocumentPageCollisions([...blocks, candidate], candidate.id);
  const rowLimit = A4_PAGE_LAYOUT[document.orientation].contentRows;
  const pages = document.pages.map((item) => ({ ...item, blocks: [...item.blocks] }));
  pages[pageIndex] = { ...pages[pageIndex], blocks: nextBlocks };
  for (let index = pageIndex; index < pages.length; index += 1) {
    const overflow = pages[index].blocks
      .filter((item) => item.y + item.h > rowLimit)
      .sort((left, right) => left.y - right.y || left.x - right.x);
    if (!overflow.length) continue;
    const overflowIds = new Set(overflow.map((item) => item.id));
    pages[index] = {
      ...pages[index],
      blocks: pages[index].blocks.filter((item) => !overflowIds.has(item.id)),
    };
    for (const item of overflow) {
      let nextIndex = index + 1;
      while (true) {
        if (!pages[nextIndex]) {
          pages.push({
            id: `${document.id}:page:${nextIndex + 1}`,
            index: nextIndex,
            size: "A4",
            orientation: document.orientation,
            blocks: [],
          });
        }
        const bottom = pages[nextIndex].blocks.reduce(
          (value, existing) => Math.max(value, existing.y + existing.h),
          0,
        );
        if (bottom + item.h <= rowLimit) {
          pages[nextIndex].blocks.push(canonicalBlock({ ...item, y: bottom } as ReportDocumentBlock));
          break;
        }
        nextIndex += 1;
      }
    }
  }
  const next = canonicalReportDocument({
    ...document,
    pages,
  });
  const validation = validateReportDocument(next);
  return validation.valid ? valid(next) : invalid(original, ...validation.errors);
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
  return insertBlockPreservingLayout(document, block, input.placement ?? { type: "end" });
}

/** 지정 블록만 삭제하고 나머지 좌표와 빈 공간을 보존한다. */
export function deleteReportBlock(document: ReportDocumentV2, blockId: string): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  if (!orderedDocumentBlocks(document).some((block) => block.id === blockId)) {
    return invalid(document, "block does not exist");
  }
  const siblingId = pairedSiblingId(document, blockId);
  const next = canonicalReportDocument({
    ...document,
    pages: document.pages.map((page) => ({
      ...page,
      blocks: page.blocks
        .filter((block) => block.id !== blockId)
        .map((block) => siblingId === block.id
          ? canonicalBlock({ ...block, x: 0, w: REPORT_GRID_COLUMNS } as ReportDocumentBlock)
          : block),
    })),
  });
  return valid(next);
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
  const source = orderedDocumentBlocks(document).find((block) => block.id === blockId);
  if (!source) return invalid(document, "block does not exist");
  let block = source;
  const siblingId = pairedSiblingId(document, blockId);
  const withoutSource = canonicalReportDocument({
    ...document,
    pages: document.pages.map((page) => ({
      ...page,
      blocks: page.blocks
        .filter((candidate) => candidate.id !== blockId)
        .map((candidate) => siblingId === candidate.id
          ? canonicalBlock({ ...candidate, x: 0, w: REPORT_GRID_COLUMNS } as ReportDocumentBlock)
          : candidate),
    })),
  });
  if (siblingId) block = canonicalBlock({ ...block, x: 0, w: REPORT_GRID_COLUMNS } as ReportDocumentBlock);
  return insertBlockPreservingLayout(withoutSource, block, placement);
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
    return valid(canonicalReportDocument(document));
  }
  return valid(reflowDocumentBlocks({ ...document, orientation }, orderedDocumentBlocks(document)));
}

/** 검증된 canonical 문서만 결정론적 JSON으로 직렬화한다. */
export function serializeReportDocument(document: ReportDocumentV2): string {
  const validation = validateReportDocument(document);
  if (!validation.valid) throw new TypeError(validation.errors.join("; "));
  return JSON.stringify(canonicalReportDocument(document));
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
  return {
    ok: true,
    document: canonicalReportDocument(parsed as ReportDocumentV2),
    errors: [],
  };
}
