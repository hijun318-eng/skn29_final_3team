/** versioned 보고서 문서의 canonical 순서·reflow·상대 삽입을 담당하는 모듈이다. */
import {
  A4_PAGE_LAYOUT,
  REPORT_DOCUMENT_SCHEMA_VERSION,
  REPORT_GRID_COLUMNS,
  type ArtifactReference,
  type CurrencyDisplayPolicy,
  type ReportDocumentBlock,
  type ReportDocumentPage,
  type ReportDocumentV2,
  type ReportDropPlacement,
} from "./reportDocumentTypes.ts";

/** artifact 참조를 ID·version·checksum의 canonical 필드만 남겨 복제한다. */
export function canonicalArtifactRef(reference: ArtifactReference): ArtifactReference {
  return {
    artifactId: reference.artifactId,
    ...(reference.version === undefined ? {} : { version: reference.version }),
    ...(reference.checksum === undefined ? {} : { checksum: reference.checksum }),
  };
}

/** block kind별 허용 필드만 유지해 직렬화 순서를 안정화한다. */
export function canonicalBlock(block: ReportDocumentBlock): ReportDocumentBlock {
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
  if (block.kind === "markdown") return { ...base, kind: "markdown", markdown: block.markdown };
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

/** 유효한 page와 block 좌표를 바꾸지 않고 canonical 필드만 복제한다. */
export function canonicalReportDocument(document: ReportDocumentV2): ReportDocumentV2 {
  return {
    schemaVersion: REPORT_DOCUMENT_SCHEMA_VERSION,
    id: document.id,
    title: document.title,
    orientation: document.orientation,
    presentationMode: document.presentationMode,
    currencyPolicy: canonicalCurrencyPolicy(document.currencyPolicy),
    pages: [...document.pages]
      .sort((left, right) => left.index - right.index)
      .map((page, index) => ({
        id: page.id,
        index,
        size: "A4",
        orientation: document.orientation,
        blocks: page.blocks
          .map(canonicalBlock)
          .sort((left, right) => left.y - right.y || left.x - right.x),
      })),
  };
}

function documentBlocksOverlap(left: ReportDocumentBlock, right: ReportDocumentBlock): boolean {
  return left.x < right.x + right.w
    && left.x + left.w > right.x
    && left.y < right.y + right.h
    && left.y + left.h > right.y;
}

/** 한 page 안에서 anchor 좌표를 유지하고 실제 충돌 block만 아래로 이동한다. */
export function resolveDocumentPageCollisions(
  blocks: readonly ReportDocumentBlock[],
  anchorId: string,
): ReportDocumentBlock[] {
  const canonical = blocks.map(canonicalBlock);
  const anchor = canonical.find((block) => block.id === anchorId);
  if (!anchor) return canonical;
  const order = new Map(canonical.map((block, index) => [block.id, index]));
  const ordered = canonical
    .filter((block) => block.id !== anchorId)
    .sort((left, right) => (
      left.y - right.y || left.x - right.x
      || (order.get(left.id) ?? 0) - (order.get(right.id) ?? 0)
    ));
  const placed = [anchor];
  const resolved = new Map<string, ReportDocumentBlock>([[anchor.id, anchor]]);
  for (const block of ordered) {
    let candidate = block;
    while (true) {
      const collisions = placed.filter((placedBlock) => documentBlocksOverlap(candidate, placedBlock));
      if (!collisions.length) break;
      candidate = canonicalBlock({
        ...candidate,
        y: Math.max(...collisions.map((placedBlock) => placedBlock.y + placedBlock.h)),
      } as ReportDocumentBlock);
    }
    placed.push(candidate);
    resolved.set(candidate.id, candidate);
  }
  return canonical.map((block) => resolved.get(block.id) ?? block);
}

/** 페이지·grid 좌표 순으로 새 블록 배열을 반환하며 문서를 변경하지 않는다. */
export function orderedDocumentBlocks(document: ReportDocumentV2): ReportDocumentBlock[] {
  return [...document.pages]
    .sort((left, right) => left.index - right.index)
    .flatMap((page) => [...page.blocks]
      .sort((left, right) => left.y - right.y || left.x - right.x)
      .map(canonicalBlock));
}

function pageIdAt(document: ReportDocumentV2, index: number): string {
  return document.pages[index]?.id ?? `${document.id}:page:${index + 1}`;
}

/** 블록 순서를 A4 row 한도 안에서 재배치하고 page break를 보존한다. */
export function reflowDocumentBlocks(
  document: ReportDocumentV2,
  blocks: ReportDocumentBlock[],
): ReportDocumentV2 {
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
      pageBlocks.push(canonicalBlock({ ...block, x, y: pageY } as ReportDocumentBlock));
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

function streamEndIndex(
  document: ReportDocumentV2,
  pageId: string | undefined,
  excludedBlockId?: string,
): number | null {
  if (pageId === undefined) {
    return orderedDocumentBlocks(document).filter((block) => block.id !== excludedBlockId).length;
  }
  const pagePosition = document.pages.findIndex((page) => page.id === pageId);
  if (pagePosition < 0) return null;
  return document.pages.slice(0, pagePosition + 1).reduce(
    (count, page) => count + page.blocks.filter((block) => block.id !== excludedBlockId).length,
    0,
  );
}

/** 반쪽 폭 블록과 같은 row를 공유하는 형제 ID를 찾고 없으면 null을 반환한다. */
export function pairedSiblingId(document: ReportDocumentV2, blockId: string): string | null {
  for (const page of document.pages) {
    const block = page.blocks.find((candidate) => candidate.id === blockId);
    if (!block || block.w !== 6) continue;
    const sibling = page.blocks.find(
      (candidate) => candidate.id !== blockId && candidate.y === block.y && candidate.w === 6
        && candidate.h === block.h
        && ((candidate.x === 0 && block.x === 6) || (candidate.x === 6 && block.x === 0)),
    );
    if (sibling) return sibling.id;
  }
  return null;
}

/** 상대 drop 명령에 따라 블록을 삽입한 뒤 전체 문서를 다시 흐르게 한다. */
export function insertDocumentBlockAtPlacement(
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
