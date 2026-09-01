/** draft block 복제·설정·resize를 불변 갱신하는 순수 mutation helper 모듈이다. */
import { compactDraftLayout } from "../../contracts/report.ts";
import { createUuid } from "../../utils/createUuid.ts";
import {
  DEFAULT_FRONTEND_CURRENCY_POLICY,
  fitFrontendArtifactViewBlock,
  frontendTextBlockLayout,
} from "./reportDraftV2.js";
import type {
  DraftArtifactData,
  DraftBlockTemplate,
  DraftCurrencyPolicy,
  DraftInsertPosition,
  DraftReportBlock,
} from "./reportDraftStateTypes.ts";

/** draft 블록과 중첩 표시 설정을 복제해 history 간 참조 공유를 막는다. */
export function copyDraftBlocks(
  blocks: readonly DraftReportBlock[],
): readonly DraftReportBlock[] {
  return blocks.map((block) => ({ ...block }));
}

/** 부분 통화 정책을 기본 정책과 병합하되 허용되지 않은 배율은 auto로 닫는다. */
export function mergeDraftCurrencyPolicy(
  input?: Partial<DraftCurrencyPolicy>,
): DraftCurrencyPolicy {
  return { ...DEFAULT_FRONTEND_CURRENCY_POLICY, ...input } as DraftCurrencyPolicy;
}

/** JSON block 설정을 객체로만 읽고 손상된 값은 빈 설정으로 fail-closed 처리한다. */
export function readDraftBlockSettings(
  block: DraftReportBlock,
): Record<string, unknown> {
  if (block.type === "text" || !block.content) return {};
  try {
    const parsed = JSON.parse(block.content);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

/** auto-size artifact view만 현재 데이터·방향에 맞게 다시 계산한다. */
export function fitAutoArtifactViewLayout(
  inputBlocks: readonly DraftReportBlock[],
  artifacts: Readonly<Record<string, DraftArtifactData | undefined>>,
  orientation: "portrait" | "landscape",
): readonly DraftReportBlock[] {
  const compacted = compactDraftLayout(inputBlocks) as readonly DraftReportBlock[];
  return compactDraftLayout(compacted.map((block) => (
    block.artifactId && artifacts[block.artifactId] && ["chart", "table"].includes(block.type ?? "")
      ? fitFrontendArtifactViewBlock(block, artifacts[block.artifactId], { orientation })
      : block
  ))) as readonly DraftReportBlock[];
}

/** template 문자열을 독립 Markdown draft 블록으로 생성한다. */
export function createTextTemplateBlock(
  template: DraftBlockTemplate,
  position: DraftInsertPosition | null,
  current: readonly DraftReportBlock[],
  orientation: "portrait" | "landscape",
): DraftReportBlock {
  const defaultY = current.reduce(
    (bottom, block) => Math.max(bottom, block.y + block.h),
    0,
  );
  const block = {
    id: createUuid(),
    title: template.blockTitle ?? "새 블록",
    columns: position?.w ?? template.w,
    type: "text" as const,
    content: template.content ?? "",
    x: position?.x ?? 0,
    y: position?.y ?? defaultY,
    w: position?.w ?? template.w,
    h: template.h,
  };
  return { ...block, h: frontendTextBlockLayout(block, orientation).height };
}

/** block resize 결과와 실제 변경 여부를 묶는 반환 계약이다. */ export interface ResizeDraftBlockResult {
  readonly blocks: readonly DraftReportBlock[];
  readonly announcement: string;
}

/** 상·좌 edge resize가 함께 바꾸는 선택 block의 grid 시작 좌표다. */
export interface ResizeDraftBlockPosition {
  readonly x?: number;
  readonly y?: number;
}

function draftBlocksOverlap(left: DraftReportBlock, right: DraftReportBlock): boolean {
  return left.x < right.x + right.w
    && left.x + left.w > right.x
    && left.y < right.y + right.h
    && left.y + left.h > right.y;
}

/** resize된 block은 고정하고 충돌하는 block의 높이 대신 y만 아래로 이동한다. */
function resolveResizeCollisions(
  blocks: readonly DraftReportBlock[],
  resizedBlockId: string,
): readonly DraftReportBlock[] {
  const anchor = blocks.find((block) => block.id === resizedBlockId);
  if (!anchor) return blocks;
  const originalOrder = new Map(blocks.map((block, index) => [block.id, index]));
  const ordered = blocks
    .filter((block) => block.id !== resizedBlockId)
    .sort((left, right) => (
      left.y - right.y
      || left.x - right.x
      || (originalOrder.get(left.id) ?? 0) - (originalOrder.get(right.id) ?? 0)
    ));
  const placed: DraftReportBlock[] = [anchor];
  const resolved = new Map<string, DraftReportBlock>([[anchor.id, anchor]]);
  for (const block of ordered) {
    let candidate = block;
    while (true) {
      const collisions = placed.filter((placedBlock) => draftBlocksOverlap(candidate, placedBlock));
      if (!collisions.length) break;
      candidate = {
        ...candidate,
        y: Math.max(...collisions.map((placedBlock) => placedBlock.y + placedBlock.h)),
      };
    }
    placed.push(candidate);
    resolved.set(candidate.id, candidate);
  }
  return blocks.map((block) => resolved.get(block.id) ?? block);
}

/** grid 범위·충돌을 검증해 지정 블록 크기를 바꾸고 불가능하면 원본을 반환한다. */
export function resizeDraftBlocks(
  current: readonly DraftReportBlock[],
  blockId: string,
  requestedWidth: number,
  requestedHeight: number | undefined,
  orientation: "portrait" | "landscape",
  requestedPosition?: ResizeDraftBlockPosition,
): ResizeDraftBlockResult | null {
  const source = current.find((block) => block.id === blockId);
  if (!source) return null;
  const minimumWidth = source.type === "text" ? 4 : 6;
  let width = Math.max(minimumWidth, Math.min(12, requestedWidth));
  const textMinimum = source.type === "text"
    ? frontendTextBlockLayout({ ...source, w: width, columns: width, h: 4 }, orientation).minimumHeight
    : 4;
  const minimumHeight = source.type === "artifact" ? 5 : source.type === "chart" ? 7 : source.type === "table" ? 5 : textMinimum;
  const maximumHeight = ["artifact", "chart", "table"].includes(source.type ?? "") ? 18 : 14;
  let height = requestedHeight === undefined
    ? Math.max(source.h, minimumHeight)
    : Math.max(minimumHeight, Math.min(maximumHeight, requestedHeight));
  let x = Math.max(0, Math.min(12 - width, Math.round(requestedPosition?.x ?? source.x)));
  let y = Math.max(0, Math.round(requestedPosition?.y ?? source.y));
  if (x < source.x) {
    const right = x + width;
    const leftBoundary = current
      .filter((block) => block.id !== blockId && block.y === source.y && block.x < source.x)
      .filter((block) => block.x < right && block.x + block.w > x)
      .reduce((boundary, block) => Math.max(boundary, block.x + block.w), x);
    if (leftBoundary > x) {
      const availableWidth = right - leftBoundary;
      if (availableWidth >= minimumWidth) {
        x = leftBoundary;
        width = availableWidth;
      } else {
        x = source.x;
        width = source.w;
      }
    }
  }
  if (y < source.y) {
    const bottom = y + height;
    const topBoundary = current
      .filter((block) => block.id !== blockId && block.y < source.y)
      .filter((block) => block.x < x + width && block.x + block.w > x)
      .filter((block) => block.y < bottom && block.y + block.h > y)
      .reduce((boundary, block) => Math.max(boundary, block.y + block.h), y);
    if (topBoundary > y) {
      const availableHeight = bottom - topBoundary;
      if (availableHeight >= minimumHeight) {
        y = topBoundary;
        height = availableHeight;
      } else {
        y = source.y;
        height = source.h;
      }
    }
  }
  if (width === source.w && height === source.h && x === source.x && y === source.y) return null;
  const resized = current.map((block) => {
    if (block.id === blockId) return {
      ...block,
      columns: width,
      w: width,
      h: height,
      x,
      y,
      ...(["artifact", "chart", "table"].includes(block.type ?? "")
        ? { content: JSON.stringify({ ...readDraftBlockSettings(block), sizeMode: "manual" }) }
        : {}),
    };
    return block;
  });
  return {
    blocks: resolveResizeCollisions(resized, blockId),
    announcement: `${source.title || "제목 없음"} 블록 크기가 너비 ${width}, 높이 ${height}로 변경되었습니다.`,
  };
}
