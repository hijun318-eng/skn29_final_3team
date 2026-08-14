export const REPORT_DOCUMENT_SCHEMA_VERSION = "REPORT-DOCUMENT-v2" as const;
export const REPORT_GRID_COLUMNS = 12 as const;

export const A4_PAGE_LAYOUT = Object.freeze({
  portrait: Object.freeze({ widthMm: 210, heightMm: 297, contentRows: 30 }),
  landscape: Object.freeze({ widthMm: 297, heightMm: 210, contentRows: 18 }),
});

export const PRESENTATION_MODES = Object.freeze(["summary", "standard", "detail"] as const);
export const CURRENCY_DISPLAY_UNITS = Object.freeze([
  "auto",
  "one",
  "thousand",
  "million",
  "hundredMillion",
  "billion",
] as const);

export type ReportOrientation = keyof typeof A4_PAGE_LAYOUT;
export type PresentationMode = (typeof PRESENTATION_MODES)[number];
export type CurrencyDisplayUnit = (typeof CURRENCY_DISPLAY_UNITS)[number];

export interface CurrencyDisplayPolicy {
  currencyCode: string;
  displayUnit: CurrencyDisplayUnit;
  unitPlacement: "header" | "value";
  maximumFractionDigits: number;
}

export interface ArtifactReference {
  artifactId: string;
  version?: string | number;
  checksum?: string;
}

interface ReportBlockBase {
  id: string;
  title: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ArtifactReportBlock extends ReportBlockBase {
  kind: "artifact";
  artifactRef: ArtifactReference;
  presentationMode: PresentationMode;
  visibleViews: string[];
}

export interface MarkdownReportBlock extends ReportBlockBase {
  kind: "markdown";
  markdown: string;
}

export interface PageBreakReportBlock extends ReportBlockBase {
  kind: "pageBreak";
  label?: string;
}

export type ReportDocumentBlock = ArtifactReportBlock | MarkdownReportBlock | PageBreakReportBlock;

export interface ReportDocumentPage {
  id: string;
  index: number;
  size: "A4";
  orientation: ReportOrientation;
  blocks: ReportDocumentBlock[];
}

/** Frontend-owned editing model. It is deliberately separate from the current report API payload. */
export interface ReportDocumentV2 {
  schemaVersion: typeof REPORT_DOCUMENT_SCHEMA_VERSION;
  id: string;
  title: string;
  orientation: ReportOrientation;
  presentationMode: PresentationMode;
  currencyPolicy: CurrencyDisplayPolicy;
  pages: ReportDocumentPage[];
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export type DocumentOperationResult =
  | { ok: true; document: ReportDocumentV2; errors: [] }
  | { ok: false; document: ReportDocumentV2; errors: string[] };

export type ReportDropPlacement =
  | { type: "end"; pageId?: string }
  | { type: "before" | "after"; targetBlockId: string }
  | { type: "side"; targetBlockId: string; edge: "left" | "right" };

export interface InsertArtifactInput {
  blockId: string;
  title: string;
  artifactRef: ArtifactReference;
  presentationMode?: PresentationMode;
  visibleViews: string[];
  width?: 6 | 12;
  height?: number;
  placement?: ReportDropPlacement;
}

export interface CreateReportDocumentInput {
  id: string;
  title: string;
  orientation?: ReportOrientation;
  presentationMode?: PresentationMode;
  currencyPolicy?: Partial<CurrencyDisplayPolicy>;
}

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

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isIntegerBetween(value: unknown, min: number, max: number): value is number {
  return Number.isInteger(value) && Number(value) >= min && Number(value) <= max;
}

function isPresentationMode(value: unknown): value is PresentationMode {
  return PRESENTATION_MODES.includes(value as PresentationMode);
}

function isOrientation(value: unknown): value is ReportOrientation {
  return value === "portrait" || value === "landscape";
}

function blocksOverlap(a: ReportDocumentBlock, b: ReportDocumentBlock): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

function canonicalArtifactRef(reference: ArtifactReference): ArtifactReference {
  return {
    artifactId: reference.artifactId,
    ...(reference.version === undefined ? {} : { version: reference.version }),
    ...(reference.checksum === undefined ? {} : { checksum: reference.checksum }),
  };
}

function canonicalBlock(block: ReportDocumentBlock): ReportDocumentBlock {
  const base = {
    id: block.id,
    kind: block.kind,
    title: block.title,
    x: block.x,
    y: block.y,
    w: block.w,
    h: block.h,
  };
  if (block.kind === "artifact") {
    return {
      ...base,
      kind: "artifact",
      artifactRef: canonicalArtifactRef(block.artifactRef),
      presentationMode: block.presentationMode,
      visibleViews: [...block.visibleViews],
    };
  }
  if (block.kind === "markdown") {
    return { ...base, kind: "markdown", markdown: block.markdown };
  }
  return {
    ...base,
    kind: "pageBreak",
    ...(block.label === undefined ? {} : { label: block.label }),
  };
}

function canonicalCurrencyPolicy(policy: CurrencyDisplayPolicy): CurrencyDisplayPolicy {
  return {
    currencyCode: policy.currencyCode,
    displayUnit: policy.displayUnit,
    unitPlacement: policy.unitPlacement,
    maximumFractionDigits: policy.maximumFractionDigits,
  };
}

function orderedBlocks(document: ReportDocumentV2): ReportDocumentBlock[] {
  return [...document.pages]
    .sort((a, b) => a.index - b.index)
    .flatMap((page) => [...page.blocks].sort((a, b) => a.y - b.y || a.x - b.x).map(canonicalBlock));
}

function pageIdAt(document: ReportDocumentV2, index: number): string {
  return document.pages[index]?.id ?? `${document.id}:page:${index + 1}`;
}

function reflowBlocks(document: ReportDocumentV2, blocks: ReportDocumentBlock[]): ReportDocumentV2 {
  const rows = A4_PAGE_LAYOUT[document.orientation].contentRows;
  const outputPages: ReportDocumentPage[] = [];
  let pageBlocks: ReportDocumentBlock[] = [];
  let pageY = 0;
  let row: ReportDocumentBlock[] = [];
  let rowWidth = 0;

  const finishPage = () => {
    if (pageBlocks.length === 0 && outputPages.length > 0) return;
    const index = outputPages.length;
    outputPages.push({
      id: pageIdAt(document, index),
      index,
      size: "A4",
      orientation: document.orientation,
      blocks: pageBlocks,
    });
    pageBlocks = [];
    pageY = 0;
  };

  const finishRow = () => {
    if (row.length === 0) return;
    const height = Math.max(...row.map((block) => block.h));
    if (pageY + height > rows && pageBlocks.length > 0) finishPage();
    let x = 0;
    for (const block of row) {
      pageBlocks.push(canonicalBlock({ ...block, x, y: pageY, h: height } as ReportDocumentBlock));
      x += block.w;
    }
    pageY += height;
    row = [];
    rowWidth = 0;
  };

  for (const sourceBlock of blocks) {
    const block = canonicalBlock(sourceBlock);
    if (block.kind === "pageBreak") {
      finishRow();
      if (pageY + 1 > rows && pageBlocks.length > 0) finishPage();
      pageBlocks.push({ ...block, x: 0, y: pageY, w: REPORT_GRID_COLUMNS, h: 1 });
      finishPage();
      continue;
    }
    if (rowWidth + block.w > REPORT_GRID_COLUMNS) finishRow();
    row.push(block);
    rowWidth += block.w;
    if (rowWidth === REPORT_GRID_COLUMNS) finishRow();
  }
  finishRow();
  if (pageBlocks.length > 0 || outputPages.length === 0) finishPage();

  return {
    schemaVersion: REPORT_DOCUMENT_SCHEMA_VERSION,
    id: document.id,
    title: document.title,
    orientation: document.orientation,
    presentationMode: document.presentationMode,
    currencyPolicy: canonicalCurrencyPolicy(document.currencyPolicy),
    pages: outputPages,
  };
}

function invalid(document: ReportDocumentV2, ...errors: string[]): DocumentOperationResult {
  return { ok: false, document, errors };
}

function valid(document: ReportDocumentV2): DocumentOperationResult {
  return { ok: true, document, errors: [] };
}

function validateArtifactReference(reference: unknown, path: string, errors: string[]): void {
  if (!reference || typeof reference !== "object") {
    errors.push(`${path} is required`);
    return;
  }
  const value = reference as Partial<ArtifactReference>;
  if (!isNonEmptyString(value.artifactId)) errors.push(`${path}.artifactId must be a non-empty string`);
  if (
    value.version !== undefined &&
    !(isNonEmptyString(value.version) || (Number.isInteger(value.version) && Number(value.version) >= 0))
  ) {
    errors.push(`${path}.version must be a non-empty string or non-negative integer`);
  }
  if (value.checksum !== undefined && !isNonEmptyString(value.checksum)) {
    errors.push(`${path}.checksum must be a non-empty string`);
  }
}

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

export function validateReportDocument(document: unknown): ValidationResult {
  const errors: string[] = [];
  if (!document || typeof document !== "object") return { valid: false, errors: ["document must be an object"] };
  const value = document as Partial<ReportDocumentV2>;
  if (value.schemaVersion !== REPORT_DOCUMENT_SCHEMA_VERSION) errors.push(`schemaVersion must be ${REPORT_DOCUMENT_SCHEMA_VERSION}`);
  if (!isNonEmptyString(value.id)) errors.push("id must be a non-empty string");
  if (!isNonEmptyString(value.title)) errors.push("title must be a non-empty string");
  if (!isOrientation(value.orientation)) errors.push("orientation must be portrait or landscape");
  if (!isPresentationMode(value.presentationMode)) errors.push("presentationMode is invalid");

  const currency = value.currencyPolicy;
  if (!currency || typeof currency !== "object") {
    errors.push("currencyPolicy is required");
  } else {
    if (!/^[A-Z]{3}$/.test(currency.currencyCode ?? "")) errors.push("currencyPolicy.currencyCode must be an ISO-style 3-letter code");
    if (!CURRENCY_DISPLAY_UNITS.includes(currency.displayUnit as CurrencyDisplayUnit)) errors.push("currencyPolicy.displayUnit is invalid");
    if (currency.unitPlacement !== "header" && currency.unitPlacement !== "value") errors.push("currencyPolicy.unitPlacement is invalid");
    if (!isIntegerBetween(currency.maximumFractionDigits, 0, 4)) errors.push("currencyPolicy.maximumFractionDigits must be between 0 and 4");
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
      if (!isIntegerBetween(block?.x, 0, REPORT_GRID_COLUMNS - 1)) errors.push(`${blockPath}.x is outside the 12-column grid`);
      if (!isIntegerBetween(block?.w, 1, REPORT_GRID_COLUMNS) || Number(block?.x) + Number(block?.w) > REPORT_GRID_COLUMNS) {
        errors.push(`${blockPath}.w is outside the 12-column grid`);
      }
      if (!isIntegerBetween(block?.y, 0, pageRows - 1)) errors.push(`${blockPath}.y is outside the A4 content area`);
      if (!isIntegerBetween(block?.h, 1, MAX_BLOCK_HEIGHT) || Number(block?.y) + Number(block?.h) > pageRows) {
        errors.push(`${blockPath}.h is outside the A4 content area`);
      }
      if (block?.kind === "artifact") {
        validateArtifactReference(block.artifactRef, `${blockPath}.artifactRef`, errors);
        if (!isPresentationMode(block.presentationMode)) errors.push(`${blockPath}.presentationMode is invalid`);
        if (!Array.isArray(block.visibleViews) || block.visibleViews.length === 0) {
          errors.push(`${blockPath}.visibleViews must contain at least one view`);
        } else if (block.visibleViews.some((view) => !isNonEmptyString(view)) || new Set(block.visibleViews).size !== block.visibleViews.length) {
          errors.push(`${blockPath}.visibleViews must contain unique non-empty view IDs`);
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

export function compactReportDocument(document: ReportDocumentV2): DocumentOperationResult {
  const validation = validateReportDocument(document);
  return validation.valid ? valid(reflowBlocks(document, orderedBlocks(document))) : invalid(document, ...validation.errors);
}

function streamEndIndex(document: ReportDocumentV2, pageId: string | undefined, excludedBlockId?: string): number | null {
  if (pageId === undefined) return orderedBlocks(document).filter((block) => block.id !== excludedBlockId).length;
  const pagePosition = document.pages.findIndex((page) => page.id === pageId);
  if (pagePosition < 0) return null;
  return document.pages.slice(0, pagePosition + 1).reduce(
    (count, page) => count + page.blocks.filter((block) => block.id !== excludedBlockId).length,
    0,
  );
}

function pairedSiblingId(document: ReportDocumentV2, blockId: string): string | null {
  for (const page of document.pages) {
    const block = page.blocks.find((candidate) => candidate.id === blockId);
    if (!block || block.w !== 6) continue;
    const sibling = page.blocks.find(
      (candidate) => candidate.id !== blockId && candidate.y === block.y && candidate.w === 6 && candidate.h === block.h &&
        ((candidate.x === 0 && block.x === 6) || (candidate.x === 6 && block.x === 0)),
    );
    if (sibling) return sibling.id;
  }
  return null;
}

function insertAtPlacement(
  document: ReportDocumentV2,
  stream: ReportDocumentBlock[],
  block: ReportDocumentBlock,
  placement: ReportDropPlacement,
  excludedBlockId?: string,
): { stream?: ReportDocumentBlock[]; error?: string } {
  if (placement.type === "end") {
    const index = streamEndIndex(document, placement.pageId, excludedBlockId);
    if (index === null) return { error: "target page does not exist" };
    stream.splice(index, 0, block);
    return { stream };
  }
  const targetIndex = stream.findIndex((candidate) => candidate.id === placement.targetBlockId);
  if (targetIndex < 0) return { error: "target block does not exist" };
  if (placement.type === "before" || placement.type === "after") {
    stream.splice(targetIndex + (placement.type === "after" ? 1 : 0), 0, block);
    return { stream };
  }
  const target = stream[targetIndex];
  if (target.kind === "pageBreak" || block.kind === "pageBreak" || target.w !== REPORT_GRID_COLUMNS) {
    return { error: "side drop requires a full-width content block" };
  }
  const targetHalf = canonicalBlock({ ...target, w: 6 } as ReportDocumentBlock);
  const blockHalf = canonicalBlock({ ...block, w: 6 } as ReportDocumentBlock);
  stream.splice(
    targetIndex,
    1,
    ...(placement.edge === "left" ? [blockHalf, targetHalf] : [targetHalf, blockHalf]),
  );
  return { stream };
}

export function insertArtifactBlock(document: ReportDocumentV2, input: InsertArtifactInput): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  if (!isNonEmptyString(input.blockId) || orderedBlocks(document).some((block) => block.id === input.blockId)) {
    return invalid(document, "blockId must be non-empty and unique");
  }
  if (!isNonEmptyString(input.title)) return invalid(document, "title must be a non-empty string");
  const mode = input.presentationMode ?? document.presentationMode;
  if (!isPresentationMode(mode)) return invalid(document, "presentationMode is invalid");
  if (!Array.isArray(input.visibleViews) || input.visibleViews.length === 0 || input.visibleViews.some((view) => !isNonEmptyString(view)) || new Set(input.visibleViews).size !== input.visibleViews.length) {
    return invalid(document, "visibleViews must contain unique non-empty view IDs");
  }
  const referenceErrors: string[] = [];
  validateArtifactReference(input.artifactRef, "artifactRef", referenceErrors);
  if (referenceErrors.length > 0) return invalid(document, ...referenceErrors);
  const height = input.height ?? DEFAULT_ARTIFACT_HEIGHT[mode];
  if (!isIntegerBetween(height, 1, MAX_BLOCK_HEIGHT)) return invalid(document, `height must be between 1 and ${MAX_BLOCK_HEIGHT}`);
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
  const stream = orderedBlocks(document);
  const inserted = insertAtPlacement(document, stream, block, input.placement ?? { type: "end" });
  return inserted.error ? invalid(document, inserted.error) : valid(reflowBlocks(document, inserted.stream!));
}

export function deleteReportBlock(document: ReportDocumentV2, blockId: string): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  const stream = orderedBlocks(document);
  const index = stream.findIndex((block) => block.id === blockId);
  if (index < 0) return invalid(document, "block does not exist");
  const siblingId = pairedSiblingId(document, blockId);
  stream.splice(index, 1);
  if (siblingId) {
    const siblingIndex = stream.findIndex((block) => block.id === siblingId);
    stream[siblingIndex] = canonicalBlock({ ...stream[siblingIndex], w: REPORT_GRID_COLUMNS } as ReportDocumentBlock);
  }
  return valid(reflowBlocks(document, stream));
}

export function moveReportBlock(
  document: ReportDocumentV2,
  blockId: string,
  placement: ReportDropPlacement,
): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  if (placement.type !== "end" && placement.targetBlockId === blockId) return invalid(document, "a block cannot target itself");
  const stream = orderedBlocks(document);
  const sourceIndex = stream.findIndex((block) => block.id === blockId);
  if (sourceIndex < 0) return invalid(document, "block does not exist");
  let [block] = stream.splice(sourceIndex, 1);
  const siblingId = pairedSiblingId(document, blockId);
  if (siblingId) {
    const siblingIndex = stream.findIndex((candidate) => candidate.id === siblingId);
    stream[siblingIndex] = canonicalBlock({ ...stream[siblingIndex], w: REPORT_GRID_COLUMNS } as ReportDocumentBlock);
    block = canonicalBlock({ ...block, w: REPORT_GRID_COLUMNS } as ReportDocumentBlock);
  }
  const inserted = insertAtPlacement(document, stream, block, placement, blockId);
  return inserted.error ? invalid(document, inserted.error) : valid(reflowBlocks(document, inserted.stream!));
}

export function setReportOrientation(
  document: ReportDocumentV2,
  orientation: ReportOrientation,
): DocumentOperationResult {
  const validation = validateReportDocument(document);
  if (!validation.valid) return invalid(document, ...validation.errors);
  if (!isOrientation(orientation)) return invalid(document, "orientation must be portrait or landscape");
  if (orientation === document.orientation) return valid(reflowBlocks(document, orderedBlocks(document)));
  const next = { ...document, orientation } as ReportDocumentV2;
  return valid(reflowBlocks(next, orderedBlocks(document)));
}

export function serializeReportDocument(document: ReportDocumentV2): string {
  const compacted = compactReportDocument(document);
  if (!compacted.ok) throw new TypeError(compacted.errors.join("; "));
  return JSON.stringify(compacted.document);
}

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
