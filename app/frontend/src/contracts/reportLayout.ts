/** 보고서 draft의 12열 grid 배치·충돌·직렬화를 순수 함수로 제공하는 모듈이다. */
import type { DraftLayoutBlock, ReportBlock } from "./reportContract.ts";

/** 저장 블록을 12열 grid 좌표로 정규화하며 원본 배열을 변경하지 않는다. */
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

/** 대상 좌표 기준으로 블록을 재배치하고 충돌 블록을 안정적으로 아래로 밀어낸다. */
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

/** 모든 좌표 범위와 블록 간 겹침이 유효한지 순수 함수로 검사한다. */
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

/** 유효한 서버 layout은 그대로 보존하고, 좌표가 없거나 잘못된 legacy 블록만 명시적으로 복구한다. */
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

/** 시각 순서·선호 폭을 유지하면서 빈 세로 공간 없이 위에서 아래로 grid를 compact한다. */
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

/** 새 블록의 사용 가능한 첫 grid 위치를 계산하고 불가능하면 기존 배열을 반환한다. */
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

/** 정규화된 grid 필드만 결정론적 JSON으로 직렬화한다. */
export function serializeDraftLayout(blocks: readonly ReportBlock[]): string {
  return JSON.stringify(normalizeDraftLayout(blocks));
}
