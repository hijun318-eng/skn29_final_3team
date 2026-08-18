/** artifact 데이터 밀도에서 DOM 비의존 A4 block 크기를 계산하는 모듈이다. */
import { A4_PAGE_LAYOUT } from "./reportDocument.ts";

/** 전체 artifact 블록에서 선택 가능한 governed view 집합이다. */ export const WHOLE_ARTIFACT_VIEWS = Object.freeze(["summary", "kpi", "chart", "table"]);
/** 서버 정책이 아직 없을 때 쓰는 표현 전용 통화 기본값이며 원본 수치를 바꾸지 않는다. */ export const DEFAULT_FRONTEND_CURRENCY_POLICY = Object.freeze({
  currencyCode: "KRW",
  displayUnit: "auto",
  unitPlacement: "header",
  maximumFractionDigits: 1,
});

/** artifact 블록 content 설정의 호환성 버전이다. */ export const WHOLE_ARTIFACT_SETTINGS_VERSION = "ANSWER-ARTIFACT-BLOCK-v1";

/** JSON 설정을 객체로만 읽고 손상 값은 빈 설정으로 닫는다. */
export function readReportBlockSettings(value) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    return {};
  }
}

/** 전체 artifact 블록 설정을 허용된 mode/view/origin 필드로 정규화한다. */
export function wholeArtifactSettings(block) {
  if (block?.type !== "artifact") return null;
  const settings = readReportBlockSettings(block.content);
  const origin = settings.origin?.kind === "analysisRun" && typeof settings.origin.requestId === "string"
    ? {
        kind: "analysisRun",
        requestId: settings.origin.requestId,
        analysisDefinitionId: settings.origin.analysisDefinitionId,
        analysisDefinitionVersion: settings.origin.analysisDefinitionVersion,
      }
    : null;
  return {
    presentationMode: ["summary", "standard", "detail"].includes(settings.presentationMode)
      ? settings.presentationMode
      : "standard",
    visibleViews: Array.isArray(settings.visibleViews) && settings.visibleViews.length
      ? [...new Set(settings.visibleViews.filter((view) => typeof view === "string" && view.trim()))]
      : [...WHOLE_ARTIFACT_VIEWS],
    sizeMode: settings.sizeMode === "auto" ? "auto" : "manual",
    ...(origin ? { origin } : {}),
  };
}

/** 분석 서비스가 명시적으로 식별한 KPI 값만 반환한다. */
export function artifactMetricCards(artifact) {
  for (const metrics of [artifact?.metrics, artifact?.evidence?.metric_values]) {
    if (!Array.isArray(metrics)) continue;
    const explicit = metrics.filter((metric) => (
      metric?.label && metric.value !== undefined && metric.value !== null
    ));
    if (explicit.length) return explicit;
  }
  return [];
}

/** DOM을 읽지 않고 governed 응답 형태만으로 artifact block 크기를 추정한다. */
export function estimateArtifactBlockLayout(artifact, options = {}) {
  const orientation = options.orientation === "portrait" ? "portrait" : "landscape";
  const requestedViews = Array.isArray(options.visibleViews) && options.visibleViews.length
    ? [...new Set(options.visibleViews.filter((view) => WHOLE_ARTIFACT_VIEWS.includes(view)))]
    : [...WHOLE_ARTIFACT_VIEWS];
  const metrics = artifactMetricCards(artifact);
  const tableColumns = Array.isArray(artifact?.table?.columns) ? artifact.table.columns.length : 0;
  const tableRows = Array.isArray(artifact?.table?.rows) ? artifact.table.rows.length : 0;
  const chartSeries = Array.isArray(artifact?.chart?.y_fields)
    ? artifact.chart.y_fields.length
    : Array.isArray(artifact?.chart?.yFields) ? artifact.chart.yFields.length : 0;
  const availability = {
    summary: Boolean(String(artifact?.summary || "").trim()),
    kpi: metrics.length > 0,
    chart: Boolean(artifact?.chart),
    table: Boolean(artifact?.table),
  };
  const effectiveViews = artifact
    ? requestedViews.filter((view) => availability[view])
    : requestedViews;
  const views = effectiveViews.length ? effectiveViews : [requestedViews[0] || "summary"];
  const has = (view) => views.includes(view);
  const denseSingleView = (has("kpi") && metrics.length > 2)
    || (has("chart") && chartSeries > 2)
    || (has("table") && tableColumns > 4);
  const requestedWidth = options.width === 6 || options.width === 12 ? options.width : null;
  const width = requestedWidth ?? (views.length === 1 && !denseSingleView ? 6 : 12);

  const summaryLength = Math.min(240, [...String(artifact?.summary || "")].length);
  const charactersPerLine = width === 6
    ? orientation === "portrait" ? 30 : 40
    : orientation === "portrait" ? 68 : 94;
  const summaryLines = Math.max(1, Math.ceil(summaryLength / charactersPerLine));
  const summaryHeight = has("summary")
    ? Math.max(orientation === "portrait" ? 2 : 1, Math.ceil(summaryLines * (orientation === "portrait" ? 0.8 : 0.6)))
    : 0;
  const kpiColumns = width === 6 ? 2 : 4;
  const visibleMetricCount = Math.min(metrics.length || kpiColumns, kpiColumns);
  const kpiHeight = has("kpi")
    ? 2 + Math.max(0, Math.ceil(visibleMetricCount / kpiColumns) - 1) * 2
      + (metrics.length > visibleMetricCount ? 1 : 0)
    : 0;
  const chartHeight = has("chart") ? (orientation === "portrait" ? 6 : 5) + (chartSeries > 2 ? 1 : 0) : 0;
  const visibleRowLimit = width === 6 ? 3 : 4;
  const tableHeight = has("table")
    ? 4 + Math.ceil(Math.min(tableRows || 1, visibleRowLimit) / 2) + (tableColumns > 6 ? 1 : 0)
    : 0;
  const dataHeight = has("chart") && has("table")
    ? orientation === "portrait" || width <= 6 ? chartHeight + tableHeight : Math.max(chartHeight, tableHeight)
    : chartHeight + tableHeight;
  const modeAdjustment = options.presentationMode === "detail"
    ? 1
    : options.presentationMode === "summary" ? -1 : 0;
  const sectionGap = views.length > 1 ? 1 : 0;
  const minimum = has("chart") ? 8 : has("table") ? 7 : has("kpi") ? 6 : 5;
  const maximum = Math.min(18, A4_PAGE_LAYOUT[orientation].contentRows);
  const height = Math.max(
    minimum,
    Math.min(maximum, 2 + summaryHeight + kpiHeight + dataHeight + sectionGap + modeAdjustment),
  );
  return { width, height };
}

/** auto-size 전체 artifact 블록만 데이터 밀도와 A4 방향에 맞춰 조정한다. */
export function fitFrontendArtifactBlock(block, artifact, options = {}) {
  if (block?.type !== "artifact") return block;
  const rawSettings = { ...readReportBlockSettings(block.content), ...(options.settings || {}) };
  const settings = wholeArtifactSettings({ ...block, content: JSON.stringify(rawSettings) });
  if (!options.force && settings.sizeMode !== "auto") return block;
  const layout = estimateArtifactBlockLayout(artifact, {
    orientation: options.orientation,
    presentationMode: settings.presentationMode,
    visibleViews: settings.visibleViews,
  });
  return {
    ...block,
    content: JSON.stringify({ ...rawSettings, sizeMode: "auto" }),
    columns: layout.width,
    w: layout.width,
    h: layout.height,
    x: Math.min(block.x ?? 0, 12 - layout.width),
  };
}

/** chart/table 단일 view 블록의 표현·크기 설정을 정규화한다. */
export function artifactViewBlockSettings(block) {
  if (!["chart", "table"].includes(block?.type)) return null;
  const settings = readReportBlockSettings(block.content);
  const legacyDefaultHeight = block.type === "chart" ? 7 : 5;
  const sizeMode = settings.sizeMode === "auto" || settings.sizeMode === "manual"
    ? settings.sizeMode
    : block.type === "table"
      ? Math.round(block.h ?? legacyDefaultHeight) <= 7 ? "auto" : "manual"
      : Math.round(block.h ?? legacyDefaultHeight) === legacyDefaultHeight ? "auto" : "manual";
  return { ...settings, sizeMode };
}

/** 단일 artifact view의 데이터 밀도에서 DOM 비의존 grid 크기를 계산한다. */
export function estimateArtifactViewBlockLayout(block, artifact, options = {}) {
  const type = block?.type === "chart" ? "chart" : "table";
  const orientation = options.orientation === "portrait" ? "portrait" : "landscape";
  const width = Math.min(12, Math.max(6, Math.round(block?.w ?? block?.columns ?? 12)));
  const rowCount = Array.isArray(artifact?.table?.rows) ? artifact.table.rows.length : 0;
  const columnCount = Array.isArray(artifact?.table?.columns) ? artifact.table.columns.length : 0;
  const seriesCount = Array.isArray(artifact?.chart?.y_fields)
    ? artifact.chart.y_fields.length
    : Array.isArray(artifact?.chart?.yFields) ? artifact.chart.yFields.length : 0;
  let height;
  if (type === "chart") {
    height = 8
      + (orientation === "portrait" ? 1 : 0)
      + Math.max(0, Math.ceil((seriesCount - 2) / 2))
      + (rowCount > 12 ? 1 : 0);
  } else {
    const widthColumnCapacity = width <= 6 ? 2 : 4;
    height = 3
      + Math.ceil(rowCount * 0.75)
      + (rowCount > 4 ? 1 : 0)
      + (orientation === "portrait" ? 1 : 0)
      + (width <= 6 ? 1 : 0)
      + (width > 6 ? 2 : 0)
      + Math.max(0, Math.ceil((columnCount - widthColumnCapacity) / 2));
    if (artifactViewBlockSettings(block)?.density === "compact") height -= 1;
    height = Math.max(5, height);
  }
  return { width, height: Math.min(18, height) };
}

/** auto-size chart/table 블록만 계산된 grid 크기로 갱신한다. */
export function fitFrontendArtifactViewBlock(block, artifact, options = {}) {
  const candidate = options.settings
    ? { ...block, content: JSON.stringify({ ...readReportBlockSettings(block.content), ...options.settings }) }
    : block;
  const settings = artifactViewBlockSettings(candidate);
  if (!settings || (!options.force && settings.sizeMode !== "auto")) return block;
  const layout = estimateArtifactViewBlockLayout(candidate, artifact, options);
  return {
    ...block,
    content: JSON.stringify({
      ...readReportBlockSettings(block.content),
      ...(options.settings || {}),
      sizeMode: "auto",
    }),
    columns: layout.width,
    w: layout.width,
    h: layout.height,
    x: Math.min(block.x ?? 0, 12 - layout.width),
  };
}
