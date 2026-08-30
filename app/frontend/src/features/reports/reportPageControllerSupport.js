/** 보고서 page controller의 초기 상태·template 크기·focus 계산을 분리한 helper 모듈이다. */
import { compactDraftLayout, restoreDraftLayout } from "../../contracts/report";
import {
  DEFAULT_FRONTEND_CURRENCY_POLICY,
  estimateArtifactBlockLayout,
  estimateArtifactViewBlockLayout,
} from "./reportDraftV2";
import { currencyDisplayLabel, resolveCurrencyDisplayUnit } from "./reportCurrency";
import { artifactCurrencyValues, prepareEditorLayout } from "./components";

/** 서버 정의와 선택적 로컬 복원값을 비교해 초기 draft·dirty 상태를 계산한다. */
export function definitionDraftState(definition, options = {}) {
  const title = options.title ?? definition.title ?? "보고서 초안";
  const savedTitle = options.savedTitle ?? title;
  const orientation = options.orientation || definition.orientation || "landscape";
  const currencyPolicy = options.currencyPolicy || {
    ...DEFAULT_FRONTEND_CURRENCY_POLICY,
    displayUnit: definition.currencyDisplayUnit || DEFAULT_FRONTEND_CURRENCY_POLICY.displayUnit,
  };
  const savedOrientation = options.savedOrientation || orientation;
  const savedCurrencyPolicy = options.savedCurrencyPolicy || currencyPolicy;
  const serverBlocks = compactDraftLayout(restoreDraftLayout(options.serverBlocks || definition.blocks));
  const blocks = prepareEditorLayout(definition.blocks, orientation);
  const dirty = Boolean(options.forceDirty) || (
    definition.status === "draft" && (
      JSON.stringify(blocks) !== JSON.stringify(serverBlocks)
      || title !== savedTitle
    )
  );
  return {
    blocks,
    savedBlocks: dirty ? serverBlocks : blocks,
    title,
    savedTitle,
    orientation,
    savedOrientation,
    currencyPolicy,
    savedCurrencyPolicy,
    selectedBlockId: blocks[0]?.id || "",
    dirty,
  };
}

/** 현재 artifact 수치 전체에서 문서 통화 배율과 라벨을 한 번 계산한다. */
export function reportCurrencyState(artifacts, policy) {
  const unit = resolveCurrencyDisplayUnit(
    Object.values(artifacts).flatMap(artifactCurrencyValues),
    policy,
  );
  return { policy, unit, label: currencyDisplayLabel(unit) };
}

/** 독립 artifact view template을 실제 데이터·A4 방향에 맞는 크기로 조정한다. */
export function artifactViewTemplate(template, source, artifacts, orientation, width = template?.w) {
  if (!template?.id?.startsWith("artifact-")) return template;
  const view = template.view;
  const resolvedWidth = width ?? template.w ?? 12;
  const artifact = source ? artifacts[source.artifactId] : null;
  const layout = ["summary", "kpi"].includes(view)
    ? estimateArtifactBlockLayout(artifact, { orientation, visibleViews: [view], width: resolvedWidth })
    : estimateArtifactViewBlockLayout(
        { type: view === "chart" ? "chart" : "table", w: resolvedWidth, columns: resolvedWidth },
        artifact,
        { orientation },
      );
  return { ...template, w: resolvedWidth, h: layout.height };
}

/** 다음 paint에서 요청 블록을 focus하고 없으면 첫 블록 또는 빈 캔버스 CTA로 이동한다. */
export function focusReportBlock(pageCanvasRefs, blockId) {
  window.requestAnimationFrame(() => {
    const canvases = [...pageCanvasRefs.current.values()].map(({ element }) => element);
    const selected = blockId
      ? canvases.map((canvas) => canvas.querySelector(`[data-block-id="${CSS.escape(blockId)}"]`)).find(Boolean)
      : null;
    (selected
      || canvases.map((canvas) => canvas.querySelector("[data-block-id]")).find(Boolean)
      || canvases.map((canvas) => canvas.querySelector(".report-empty-canvas button")).find(Boolean))
      ?.focus({ preventScroll: true });
  });
}
