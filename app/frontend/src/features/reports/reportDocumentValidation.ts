/** unknown 편집 문서의 schema·grid·artifact 참조를 경로별로 검증하는 모듈이다. */
import {
  A4_PAGE_LAYOUT,
  CURRENCY_DISPLAY_UNITS,
  PRESENTATION_MODES,
  REPORT_DOCUMENT_SCHEMA_VERSION,
  REPORT_GRID_COLUMNS,
  type ArtifactReference,
  type CurrencyDisplayUnit,
  type PresentationMode,
  type ReportDocumentBlock,
  type ReportDocumentV2,
  type ReportOrientation,
  type ValidationResult,
} from "./reportDocumentTypes.ts";
import { REPORT_ARTIFACT_VIEW_IDS } from "../../contracts/reportContract.ts";

const MAX_BLOCK_HEIGHT = A4_PAGE_LAYOUT.landscape.contentRows;

/** unknown 입력이 공백이 아닌 문자열인지 좁힌다. */
export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/** unknown 입력이 포함 범위의 정수인지 좁힌다. */
export function isIntegerBetween(value: unknown, min: number, max: number): value is number {
  return Number.isInteger(value) && Number(value) >= min && Number(value) <= max;
}

/** unknown 입력이 허용된 artifact 표현 모드인지 좁힌다. */
export function isPresentationMode(value: unknown): value is PresentationMode {
  return PRESENTATION_MODES.includes(value as PresentationMode);
}

/** unknown 입력이 지원되는 A4 방향인지 좁힌다. */
export function isOrientation(value: unknown): value is ReportOrientation {
  return value === "portrait" || value === "landscape";
}

function blocksOverlap(left: ReportDocumentBlock, right: ReportDocumentBlock): boolean {
  return left.x < right.x + right.w && left.x + left.w > right.x
    && left.y < right.y + right.h && left.y + left.h > right.y;
}

/** artifact 참조의 ID·version·checksum 타입 오류를 지정 경로로 누적한다. */
export function validateArtifactReference(reference: unknown, path: string, errors: string[]): void {
  if (!reference || typeof reference !== "object") {
    errors.push(`${path} is required`);
    return;
  }
  const value = reference as Partial<ArtifactReference>;
  if (!isNonEmptyString(value.artifactId)) errors.push(`${path}.artifactId must be a non-empty string`);
  if (
    value.version !== undefined
    && !(isNonEmptyString(value.version) || (Number.isInteger(value.version) && Number(value.version) >= 0))
  ) {
    errors.push(`${path}.version must be a non-empty string or non-negative integer`);
  }
  if (value.checksum !== undefined && !isNonEmptyString(value.checksum)) {
    errors.push(`${path}.checksum must be a non-empty string`);
  }
}

/** 편집 문서 전체의 schema·grid·artifact 참조를 검사하고 모든 오류를 반환한다. */
export function validateReportDocument(document: unknown): ValidationResult {
  const errors: string[] = [];
  if (!document || typeof document !== "object") return { valid: false, errors: ["document must be an object"] };
  const value = document as Partial<ReportDocumentV2>;
  if (value.schemaVersion !== REPORT_DOCUMENT_SCHEMA_VERSION) {
    errors.push(`schemaVersion must be ${REPORT_DOCUMENT_SCHEMA_VERSION}`);
  }
  if (!isNonEmptyString(value.id)) errors.push("id must be a non-empty string");
  if (!isNonEmptyString(value.title)) errors.push("title must be a non-empty string");
  if (!isOrientation(value.orientation)) errors.push("orientation must be portrait or landscape");
  if (!isPresentationMode(value.presentationMode)) errors.push("presentationMode is invalid");

  const currency = value.currencyPolicy;
  if (!currency || typeof currency !== "object") {
    errors.push("currencyPolicy is required");
  } else {
    if (!/^[A-Z]{3}$/.test(currency.currencyCode ?? "")) {
      errors.push("currencyPolicy.currencyCode must be an ISO-style 3-letter code");
    }
    if (!CURRENCY_DISPLAY_UNITS.includes(currency.displayUnit as CurrencyDisplayUnit)) {
      errors.push("currencyPolicy.displayUnit is invalid");
    }
    if (currency.unitPlacement !== "header" && currency.unitPlacement !== "value") {
      errors.push("currencyPolicy.unitPlacement is invalid");
    }
    if (!isIntegerBetween(currency.maximumFractionDigits, 0, 4)) {
      errors.push("currencyPolicy.maximumFractionDigits must be between 0 and 4");
    }
  }

  if (!Array.isArray(value.pages) || value.pages.length === 0) {
    errors.push("pages must contain at least one page");
    return { valid: false, errors };
  }

  const pageIds = new Set<string>();
  const blockIds = new Set<string>();
  value.pages.forEach((page, pageIndex) => {
    const path = `pages[${pageIndex}]`;
    if (!isNonEmptyString(page?.id)) errors.push(`${path}.id must be a non-empty string`);
    else if (pageIds.has(page.id)) errors.push(`${path}.id must be unique`);
    else pageIds.add(page.id);
    if (page?.index !== pageIndex) errors.push(`${path}.index must equal ${pageIndex}`);
    if (page?.size !== "A4") errors.push(`${path}.size must be A4`);
    if (page?.orientation !== value.orientation) errors.push(`${path}.orientation must match document orientation`);
    if (!Array.isArray(page?.blocks)) {
      errors.push(`${path}.blocks must be an array`);
      return;
    }
    const pageRows = isOrientation(value.orientation)
      ? A4_PAGE_LAYOUT[value.orientation].contentRows
      : A4_PAGE_LAYOUT.portrait.contentRows;
    page.blocks.forEach((block, blockIndex) => {
      const blockPath = `${path}.blocks[${blockIndex}]`;
      if (!isNonEmptyString(block?.id)) errors.push(`${blockPath}.id must be a non-empty string`);
      else if (blockIds.has(block.id)) errors.push(`${blockPath}.id must be unique across the document`);
      else blockIds.add(block.id);
      if (!isNonEmptyString(block?.title)) errors.push(`${blockPath}.title must be a non-empty string`);
      if (!isIntegerBetween(block?.x, 0, REPORT_GRID_COLUMNS - 1)) {
        errors.push(`${blockPath}.x is outside the 12-column grid`);
      }
      if (!isIntegerBetween(block?.w, 1, REPORT_GRID_COLUMNS)
        || Number(block?.x) + Number(block?.w) > REPORT_GRID_COLUMNS) {
        errors.push(`${blockPath}.w is outside the 12-column grid`);
      }
      if (!isIntegerBetween(block?.y, 0, pageRows - 1)) {
        errors.push(`${blockPath}.y is outside the A4 content area`);
      }
      if (!isIntegerBetween(block?.h, 1, MAX_BLOCK_HEIGHT) || Number(block?.y) + Number(block?.h) > pageRows) {
        errors.push(`${blockPath}.h is outside the A4 content area`);
      }
      if (block?.kind === "artifact") {
        validateArtifactReference(block.artifactRef, `${blockPath}.artifactRef`, errors);
        if (!isPresentationMode(block.presentationMode)) errors.push(`${blockPath}.presentationMode is invalid`);
        if (!Array.isArray(block.visibleViews) || block.visibleViews.length !== 1
          || !REPORT_ARTIFACT_VIEW_IDS.includes(block.visibleViews[0])) {
          errors.push(`${blockPath}.visibleViews must contain exactly one supported atomic view ID`);
        }
      } else if (block?.kind === "markdown") {
        if (typeof block.markdown !== "string") errors.push(`${blockPath}.markdown must be a string`);
      } else if (block?.kind === "pageBreak") {
        if (block.x !== 0 || block.w !== REPORT_GRID_COLUMNS || block.h !== 1) {
          errors.push(`${blockPath} pageBreak must be a full-width one-row block`);
        }
      } else {
        errors.push(`${blockPath}.kind is invalid`);
      }
    });
    for (let left = 0; left < page.blocks.length; left += 1) {
      for (let right = left + 1; right < page.blocks.length; right += 1) {
        if (blocksOverlap(page.blocks[left], page.blocks[right])) {
          errors.push(`${path} blocks ${page.blocks[left].id} and ${page.blocks[right].id} overlap`);
        }
      }
    }
  });
  return { valid: errors.length === 0, errors };
}
