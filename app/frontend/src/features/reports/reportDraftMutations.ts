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

/** grid 범위·충돌을 검증해 지정 블록 크기를 바꾸고 불가능하면 원본을 반환한다. */
export function resizeDraftBlocks(
  current: readonly DraftReportBlock[],
  blockId: string,
  requestedWidth: number,
  requestedHeight: number | undefined,
  orientation: "portrait" | "landscape",
): ResizeDraftBlockResult | null {
  const source = current.find((block) => block.id === blockId);
  if (!source) return null;
  const minimumWidth = source.type === "text" ? 4 : 6;
  const width = Math.max(minimumWidth, Math.min(12, requestedWidth));
  const textMinimum = source.type === "text"
    ? frontendTextBlockLayout({ ...source, w: width, columns: width, h: 4 }, orientation).minimumHeight
    : 4;
  const minimumHeight = source.type === "artifact" ? 5 : source.type === "chart" ? 7 : source.type === "table" ? 5 : textMinimum;
  const maximumHeight = ["artifact", "chart", "table"].includes(source.type ?? "") ? 18 : 14;
  const height = requestedHeight === undefined
    ? Math.max(source.h, minimumHeight)
    : Math.max(minimumHeight, Math.min(maximumHeight, requestedHeight));
  if (width === source.w && height === source.h) return null;
  const resizeRow = requestedHeight !== undefined && height !== source.h;
  const resized = current.map((block) => {
    if (block.id === blockId) return {
      ...block,
      columns: width,
      w: width,
      h: height,
      x: Math.min(block.x, 12 - width),
      ...(["artifact", "chart", "table"].includes(block.type ?? "")
        ? { content: JSON.stringify({ ...readDraftBlockSettings(block), sizeMode: "manual" }) }
        : {}),
    };
    return resizeRow && block.y === source.y ? { ...block, h: height } : block;
  });
  return {
    blocks: compactDraftLayout(resized) as readonly DraftReportBlock[],
    announcement: `${source.title || "제목 없음"} 블록 크기를 너비 ${width}/12, 높이 ${height}단으로 변경했습니다.`,
  };
}
