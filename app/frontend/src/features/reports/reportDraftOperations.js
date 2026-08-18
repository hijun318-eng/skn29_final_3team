/** API draft block과 versioned frontend document 사이의 변환·layout 연산 모듈이다. */
import {
  A4_PAGE_LAYOUT,
  createReportDocument,
  deleteReportBlock,
  insertArtifactBlock,
  moveReportBlock,
  setReportOrientation,
  validateReportDocument,
} from "./reportDocument.ts";
import {
  DEFAULT_FRONTEND_CURRENCY_POLICY,
  WHOLE_ARTIFACT_SETTINGS_VERSION,
  WHOLE_ARTIFACT_VIEWS,
  estimateArtifactBlockLayout,
  wholeArtifactSettings,
} from "./reportArtifactLayout.js";

function orderedBlocks(blocks) {
  return [...blocks].sort((left, right) => (
    (left.y ?? 0) - (right.y ?? 0) || (left.x ?? 0) - (right.x ?? 0)
  ));
}

/** Markdown 길이와 A4 방향으로 text block의 최소 grid 높이를 계산한다. */
export function frontendTextBlockLayout(block, orientation = "landscape") {
  if (block?.type !== "text") {
    const height = Math.max(1, Math.round(block?.h ?? 1));
    return { minimumHeight: height, height, overflow: false };
  }
  const width = Math.min(12, Math.max(4, Math.round(block.w ?? block.columns ?? 12)));
  const fullWidthCharacters = orientation === "portrait" ? 62 : 86;
  const charactersPerLine = Math.max(18, Math.floor(fullWidthCharacters * width / 12));
  const visualLines = String(block.content || "")
    .split("\n")
    .reduce((count, line) => count + Math.max(1, Math.ceil([...line].length / charactersPerLine)), 0);
  const requiredHeight = Math.max(4, 3 + Math.ceil(visualLines * 0.72));
  const maximumHeight = 14;
  const minimumHeight = Math.min(maximumHeight, requiredHeight);
  return {
    minimumHeight,
    height: Math.max(minimumHeight, Math.min(maximumHeight, Math.round(block.h ?? 4))),
    overflow: requiredHeight > maximumHeight,
  };
}

/** 키보드 삽입이 현재 page 끝에서 사용할 충돌 없는 grid 위치를 찾는다. */
export function keyboardEndDropPosition(blocks, { pageId, width = 12, height = 4 }) {
  const w = Math.min(12, Math.max(1, Math.round(width)));
  const h = Math.max(1, Math.round(height));
  const y = blocks.reduce((bottom, block) => Math.max(bottom, (block.y ?? 0) + (block.h ?? 1)), 0);
  return {
    pageId,
    x: 0,
    requestedX: 0,
    y,
    w,
    h,
    placement: { type: "end", ...(pageId ? { pageId } : {}) },
  };
}

function modelBlock(block) {
  const base = {
    id: block.id,
    title: block.title,
    x: Math.max(0, Math.round(block.x ?? 0)),
    y: 0,
    w: Math.min(12, Math.max(1, Math.round(block.w ?? block.columns ?? 12))),
    h: Math.min(18, Math.max(1, Math.round(block.h ?? 4))),
  };
  if (block.type === "text") return { ...base, kind: "markdown", markdown: block.content || "" };
  if (!block.artifactId) return null;
  const settings = wholeArtifactSettings(block);
  return {
    ...base,
    kind: "artifact",
    artifactRef: {
      artifactId: block.artifactId,
      ...(block.artifactVersion === undefined ? {} : { version: block.artifactVersion }),
      ...(block.artifactChecksum ? { checksum: block.artifactChecksum } : {}),
    },
    presentationMode: settings?.presentationMode || "standard",
    visibleViews: settings?.visibleViews || [block.type === "chart" ? "chart" : "table"],
  };
}

/** 편집기 블록을 versioned 문서 모델로 변환하고 유효하지 않으면 오류를 반환한다. */
export function frontendBlocksToDocument({ definitionId, title, orientation, currencyPolicy, blocks }) {
  const document = createReportDocument({
    id: definitionId,
    title,
    orientation,
    currencyPolicy: currencyPolicy || DEFAULT_FRONTEND_CURRENCY_POLICY,
  });
  const pageRows = A4_PAGE_LAYOUT[orientation]?.contentRows || A4_PAGE_LAYOUT.landscape.contentRows;
  const rows = orderedBlocks(blocks).reduce((groups, block) => {
    const y = block.y ?? 0;
    const current = groups.at(-1);
    if (current?.sourceY === y) current.blocks.push(block);
    else groups.push({ sourceY: y, blocks: [block] });
    return groups;
  }, []);
  const pages = [];
  let page = null;
  let cursorY = 0;
  const startPage = () => {
    page = {
      id: `${definitionId}:page:${pages.length + 1}`,
      index: pages.length,
      size: "A4",
      orientation,
      blocks: [],
    };
    pages.push(page);
    cursorY = 0;
  };
  for (const row of rows) {
    const converted = row.blocks.map(modelBlock);
    if (converted.some((block) => !block)) {
      return { ok: false, errors: ["\ub370\uc774\ud130 \ube14\ub85d\uc5d0 Artifact \ucc38\uc870\uac00 \uc5c6\uc2b5\ub2c8\ub2e4."] };
    }
    const height = Math.max(...converted.map((block) => block.h));
    if (!page || (page.blocks.length && cursorY + height > pageRows)) startPage();
    let rowX = 0;
    for (const block of converted) {
      const width = Math.min(block.w, 12 - rowX);
      page.blocks.push({ ...block, x: rowX, y: cursorY, w: width, h: height });
      rowX += width;
    }
    cursorY += height;
  }
  if (!pages.length) startPage();
  document.pages = pages;
  const validation = validateReportDocument(document);
  return validation.valid
    ? { ok: true, document, errors: [] }
    : { ok: false, errors: validation.errors };
}

/** versioned 문서를 editor 블록으로 복원하며 artifact 출처 메타데이터를 재연결한다. */
export function frontendBlocksFromDocument(document, sourceBlocks) {
  const sources = new Map(sourceBlocks.map((block) => [block.id, block]));
  const pageRows = A4_PAGE_LAYOUT[document.orientation].contentRows;
  return document.pages.flatMap((page) => page.blocks.map((block) => {
    const source = sources.get(block.id);
    const fallbackType = block.kind === "markdown"
      ? "text"
      : block.visibleViews.length > 1
        ? "artifact"
        : block.visibleViews[0] === "chart" ? "chart" : "table";
    return {
      ...(source || {
        id: block.id,
        title: block.title,
        type: fallbackType,
        artifactId: block.kind === "artifact" ? block.artifactRef.artifactId : undefined,
        content: block.kind === "markdown" ? block.markdown : "",
      }),
      columns: block.w,
      x: block.x,
      y: page.index * pageRows + block.y,
      w: block.w,
      h: block.h,
    };
  }));
}

function operationResult(result, sourceBlocks) {
  return result.ok
    ? {
        ok: true,
        blocks: frontendBlocksFromDocument(result.document, sourceBlocks),
        document: result.document,
        errors: [],
      }
    : { ok: false, blocks: sourceBlocks, errors: result.errors };
}

/** artifact 또는 template을 draft에 삽입하고 layout 오류를 호출자에게 반환한다. */
export function insertFrontendArtifact(blocks, input, report) {
  const current = frontendBlocksToDocument({ ...report, blocks });
  if (!current.ok) return { ...current, blocks };
  const settings = {
    schemaVersion: WHOLE_ARTIFACT_SETTINGS_VERSION,
    presentationMode: input.presentationMode || "standard",
    visibleViews: Array.isArray(input.visibleViews) && input.visibleViews.length
      ? [...new Set(input.visibleViews.filter((view) => WHOLE_ARTIFACT_VIEWS.includes(view)))]
      : [...WHOLE_ARTIFACT_VIEWS],
    sizeMode: input.sizeMode === "manual" ? "manual" : "auto",
    ...(input.sourceKind === "analysisRun" && input.requestId ? {
      origin: {
        kind: "analysisRun",
        requestId: input.requestId,
        ...(input.analysisDefinitionId ? { analysisDefinitionId: input.analysisDefinitionId } : {}),
        ...(input.analysisDefinitionVersion === undefined
          ? {}
          : { analysisDefinitionVersion: input.analysisDefinitionVersion }),
      },
    } : {}),
  };
  const estimated = estimateArtifactBlockLayout(input.artifact, {
    orientation: report.orientation,
    presentationMode: settings.presentationMode,
    visibleViews: settings.visibleViews,
  });
  const width = input.width ?? estimated.width;
  const height = input.height ?? estimated.height;
  const nextBlock = {
    id: input.blockId,
    title: input.title,
    type: "artifact",
    artifactId: input.artifactId,
    ...(input.artifactVersion === undefined ? {} : { artifactVersion: input.artifactVersion }),
    ...(input.artifactChecksum ? { artifactChecksum: input.artifactChecksum } : {}),
    ...(input.artifactDefinitionId ? { artifactDefinitionId: input.artifactDefinitionId } : {}),
    ...(input.artifactDefinitionVersion === undefined
      ? {}
      : { artifactDefinitionVersion: input.artifactDefinitionVersion }),
    ...(input.sourceKind ? { artifactSourceKind: input.sourceKind } : {}),
    ...(input.requestId ? { artifactRequestId: input.requestId } : {}),
    ...(input.analysisDefinitionId ? { analysisDefinitionId: input.analysisDefinitionId } : {}),
    ...(input.analysisDefinitionVersion === undefined
      ? {}
      : { analysisDefinitionVersion: input.analysisDefinitionVersion }),
    ...(input.queryId ? { queryId: input.queryId } : {}),
    ...(input.question ? { question: input.question } : {}),
    ...(input.sourceUrns ? { sourceUrns: input.sourceUrns } : {}),
    content: JSON.stringify(settings),
    columns: width,
    x: 0,
    y: 0,
    w: width,
    h: height,
  };
  const inserted = insertArtifactBlock(current.document, {
    blockId: nextBlock.id,
    title: nextBlock.title,
    artifactRef: {
      artifactId: nextBlock.artifactId,
      ...(nextBlock.artifactVersion === undefined ? {} : { version: nextBlock.artifactVersion }),
      ...(nextBlock.artifactChecksum ? { checksum: nextBlock.artifactChecksum } : {}),
    },
    presentationMode: settings.presentationMode,
    visibleViews: settings.visibleViews,
    width: nextBlock.w,
    height: nextBlock.h,
    placement: input.placement || { type: "end" },
  });
  return operationResult(inserted, [...blocks, nextBlock]);
}

/** 지정 draft 블록을 상대 위치로 이동하고 문서 검증 실패 시 원본을 보존한다. */
export function moveFrontendBlock(blocks, blockId, placement, report) {
  const current = frontendBlocksToDocument({ ...report, blocks });
  if (!current.ok) return { ...current, blocks };
  return operationResult(moveReportBlock(current.document, blockId, placement), blocks);
}

/** 지정 draft 블록을 삭제하고 나머지 grid를 compact한다. */
export function deleteFrontendBlock(blocks, blockId, report) {
  const current = frontendBlocksToDocument({ ...report, blocks });
  if (!current.ok) return { ...current, blocks };
  return operationResult(deleteReportBlock(current.document, blockId), blocks);
}

/** 방향 변경 후 draft 블록을 새 A4 row 계약에 맞춰 재배치한다. */
export function orientFrontendBlocks(blocks, orientation, report) {
  const current = frontendBlocksToDocument({ ...report, blocks });
  if (!current.ok) return { ...current, blocks };
  return operationResult(setReportOrientation(current.document, orientation), blocks);
}

/** 정의 목록에서 중복 없는 governed artifact library 항목을 추출한다. */
export function reportArtifactLibrarySources(currentDefinition, definitions) {
  const seen = new Set();
  return [currentDefinition, ...definitions]
    .filter(Boolean)
    .flatMap((definition) => definition.blocks.map((block) => {
      const origin = wholeArtifactSettings(block)?.origin;
      return {
        ...block,
        ...(origin ? {
          artifactSourceKind: "analysisRun",
          artifactRequestId: origin.requestId,
          analysisDefinitionId: origin.analysisDefinitionId,
          analysisDefinitionVersion: origin.analysisDefinitionVersion,
        } : {
          definitionId: block.artifactDefinitionId || definition.definitionId,
          definitionVersion: block.artifactDefinitionVersion ?? definition.version,
        }),
        definitionTitle: definition.title,
      };
    }))
    .filter((source) => {
      if (!source.artifactId || seen.has(source.artifactId)) return false;
      seen.add(source.artifactId);
      return true;
    });
}
