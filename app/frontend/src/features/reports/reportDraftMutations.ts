/** draft block 복제·설정·resize를 불변 갱신하는 순수 mutation helper 모듈이다. */
import { compactDraftLayout, isDraftLayoutValid } from "../../contracts/report.ts";
import { createUuid } from "../../utils/createUuid.ts";
import {
  ARTIFACT_BLOCK_SETTINGS_VERSION,
  ATOMIC_ARTIFACT_VIEWS,
  DEFAULT_FRONTEND_CURRENCY_POLICY,
  analysisArtifactTitle,
  artifactViewTitle,
  availableArtifactViews,
  estimateArtifactBlockLayout,
  estimateArtifactViewBlockLayout,
  fitFrontendArtifactBlock,
  fitFrontendArtifactViewBlock,
  frontendTextBlockLayout,
} from "./reportDraftV2.js";
import type {
  DraftArtifactData,
  DraftArtifactSource,
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
    block.artifactId && artifacts[block.artifactId]
      ? block.type === "artifact"
        ? fitFrontendArtifactBlock(block, artifacts[block.artifactId], { orientation })
        : ["chart", "table"].includes(block.type ?? "")
          ? fitFrontendArtifactViewBlock(block, artifacts[block.artifactId], { orientation })
          : block
      : block
  ))) as readonly DraftReportBlock[];
}

function legacyCompositeViews(block: DraftReportBlock): readonly string[] {
  if (block.type !== "artifact") return [];
  const settings = readDraftBlockSettings(block);
  const requested = settings.visibleViews;
  if (!Array.isArray(requested) || requested.length < 2) return [];
  const supportedViews = new Set<string>(ATOMIC_ARTIFACT_VIEWS);
  const views = requested.filter((view): view is string => (
    typeof view === "string" && supportedViews.has(view)
  ));
  return views.length === requested.length && new Set(views).size === views.length
    ? views
    : [];
}

function atomicArtifactSettings(
  view: string,
  legacySettings: Record<string, unknown>,
): Record<string, unknown> {
  if (view === "chart") {
    return {
      visibleViews: [view],
      sizeMode: "auto",
      showLegend: legacySettings.showLegend !== false,
      ...(typeof legacySettings.chartType === "string"
        ? { chartType: legacySettings.chartType }
        : {}),
    };
  }
  if (view === "table") {
    return {
      visibleViews: [view],
      sizeMode: "auto",
      density: legacySettings.density === "compact" ? "compact" : "comfortable",
      showRowNumbers: legacySettings.showRowNumbers === true,
    };
  }
  return {
    schemaVersion: ARTIFACT_BLOCK_SETTINGS_VERSION,
    presentationMode: ["summary", "standard", "detail"].includes(
      String(legacySettings.presentationMode),
    ) ? legacySettings.presentationMode : "standard",
    visibleViews: [view],
    sizeMode: "auto",
    ...(legacySettings.origin && typeof legacySettings.origin === "object"
      ? { origin: legacySettings.origin }
      : {}),
  };
}

/**
 * 이전 합본 Artifact를 실제 payload에 존재하는 원자 view 블록으로 분리한다.
 *
 * 합본 블록은 원자 view와 동일한 저장 정체성이 아니므로 각 view에 새 UUID를 사용한다.
 * 손상되었거나 지원하지 않는 view가 섞인 설정은 조용히 추측하지 않고 원본을 보존한다.
 */
export function splitLegacyCompositeArtifactBlocks(
  inputBlocks: readonly DraftReportBlock[],
  artifacts: Readonly<Record<string, DraftArtifactData | undefined>>,
  artifactSources: readonly DraftArtifactSource[],
  orientation: "portrait" | "landscape",
  createBlockId: () => string = createUuid,
): { readonly blocks: readonly DraftReportBlock[]; readonly migratedSourceCount: number } {
  let migratedSourceCount = 0;
  const sourceTitles = new Map(artifactSources.flatMap((source) => {
    const title = String(source.title || source.definitionTitle || "").trim();
    return source.artifactId && title ? [[source.artifactId, title]] : [];
  }));
  const expanded = inputBlocks.flatMap((block) => {
    const requestedViews = legacyCompositeViews(block);
    const artifact = block.artifactId ? artifacts[block.artifactId] : undefined;
    if (!requestedViews.length || !artifact) return [block];
    const available = new Set<string>(availableArtifactViews(artifact));
    const views = requestedViews.filter((view) => available.has(view));
    if (!views.length) return [block];
    migratedSourceCount += 1;
    const legacySettings = readDraftBlockSettings(block);
    // Artifact payload의 저장용 title(예: "Analysis result")이나 과거 블록에
    // 복제된 보고서 제목을 표시 이름으로 재사용하지 않는다. library가 계산한
    // 사용자용 제목을 우선하고, 없으면 동일한 지표·기간 규칙으로 복구한다.
    const sourceTitle = sourceTitles.get(block.artifactId ?? "")
      || analysisArtifactTitle(artifact);
    return views.map((view) => {
      const type = view === "summary" || view === "kpi" ? "artifact" : view;
      const layout = type === "artifact"
        ? estimateArtifactBlockLayout(artifact, { orientation, visibleViews: [view] })
        : estimateArtifactViewBlockLayout(
            { type, w: block.w, columns: block.columns },
            artifact,
            { orientation, autoWidth: true },
          );
      return {
        ...block,
        id: createBlockId(),
        title: artifactViewTitle(sourceTitle, view),
        type,
        content: JSON.stringify(atomicArtifactSettings(view, legacySettings)),
        viewSpecId: undefined,
        columns: layout.width,
        x: 0,
        w: layout.width,
        h: layout.height,
      } as DraftReportBlock;
    });
  });
  return {
    blocks: migratedSourceCount
      ? compactDraftLayout(expanded) as readonly DraftReportBlock[]
      : inputBlocks,
    migratedSourceCount,
  };
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
  requestedPosition?: { readonly x: number; readonly y: number },
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
  if (width === source.w && height === source.h) return null;
  const resizeRow = !requestedPosition && requestedHeight !== undefined && height !== source.h;
  const resized = current.map((block) => {
    if (block.id === blockId) return {
      ...block,
      columns: width,
      w: width,
      h: height,
      x: Math.min(12 - width, Math.max(0, Math.round(requestedPosition?.x ?? block.x))),
      y: Math.max(0, Math.round(requestedPosition?.y ?? block.y)),
      ...(["artifact", "chart", "table"].includes(block.type ?? "")
        ? { content: JSON.stringify({ ...readDraftBlockSettings(block), sizeMode: "manual" }) }
        : {}),
    };
    return block;
  });
  if (requestedPosition && !isDraftLayoutValid(resized)) return null;
  return {
    blocks: requestedPosition
      ? resized as readonly DraftReportBlock[]
      : compactDraftLayout(resized) as readonly DraftReportBlock[],
    announcement: `${source.title || "제목 없음"} 블록 크기를 너비 ${width}/12, 높이 ${height}단으로 변경했습니다.`,
  };
}
