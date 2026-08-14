import {
  A4_PAGE_LAYOUT,
  REPORT_DOCUMENT_SCHEMA_VERSION,
  createReportDocument,
  deleteReportBlock,
  insertArtifactBlock,
  moveReportBlock,
  setReportOrientation,
  validateReportDocument,
} from "./reportDocument.ts";

export const FRONTEND_REPORT_DRAFT_VERSION = "ANSWER-REPORT-DRAFT-v2";
export const WHOLE_ARTIFACT_VIEWS = Object.freeze(["summary", "kpi", "chart", "table"]);
export const DEFAULT_FRONTEND_CURRENCY_POLICY = Object.freeze({
  currencyCode: "KRW",
  displayUnit: "auto",
  unitPlacement: "header",
  maximumFractionDigits: 1,
});

const WHOLE_ARTIFACT_SETTINGS_VERSION = "ANSWER-ARTIFACT-BLOCK-v1";

function orderedBlocks(blocks) {
  return [...blocks].sort((left, right) => (
    (left.y ?? 0) - (right.y ?? 0) || (left.x ?? 0) - (right.x ?? 0)
  ));
}

function readJson(value) {
  try { return JSON.parse(value || "{}"); } catch { return {}; }
}

export function wholeArtifactSettings(block) {
  if (block?.type !== "artifact") return null;
  const settings = readJson(block.content);
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

/**
 * 분석 서비스가 명시적으로 계산해 전달한 KPI만 반환한다.
 * 표의 마지막 행·합계·최댓값을 임의로 KPI로 추론하면 보고서 수치가 사실과 달라질 수 있으므로,
 * 명시 KPI가 없는 Artifact는 KPI 영역을 비워 두고 요약·차트·표만 표시한다.
 */
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

/**
 * 브라우저 DOM을 읽지 않고 Artifact의 데이터 밀도와 용지 방향으로 초기 블록 크기를 계산한다.
 * 이 계산은 새 블록 삽입, 자동 크기 모드, 사용자가 선택한 `내용에 맞춤` 동작에만 적용한다.
 * 사용자가 직접 조절한 블록은 수동 크기로 유지하여 재진입이나 방향 전환이 편집 의도를 덮어쓰지 않게 한다.
 */
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
  // Artifact 응답을 기다리는 동안에도 전체 보기의 안정적인 공간을 먼저 확보한다.
  // 이렇게 해야 드래그 미리보기와 실제 삽입 위치가 응답 전후로 흔들리거나 아래 블록을 밀어내지 않는다.
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
    ? 2 + Math.max(0, Math.ceil(visibleMetricCount / kpiColumns) - 1) * 2 + (metrics.length > visibleMetricCount ? 1 : 0)
    : 0;
  const chartHeight = has("chart") ? (orientation === "portrait" ? 6 : 5) + (chartSeries > 2 ? 1 : 0) : 0;
  const visibleRowLimit = width === 6 ? 3 : 4;
  const tableHeight = has("table")
    ? 4 + Math.ceil(Math.min(tableRows || 1, visibleRowLimit) / 2) + (tableColumns > 6 ? 1 : 0)
    : 0;
  const dataHeight = has("chart") && has("table")
    ? orientation === "portrait" || width <= 6 ? chartHeight + tableHeight : Math.max(chartHeight, tableHeight)
    : chartHeight + tableHeight;
  const modeAdjustment = options.presentationMode === "detail" ? 1 : options.presentationMode === "summary" ? -1 : 0;
  const sectionGap = views.length > 1 ? 1 : 0;
  const minimum = has("chart") ? 8 : has("table") ? 7 : has("kpi") ? 6 : 5;
  const maximum = Math.min(18, A4_PAGE_LAYOUT[orientation].contentRows);
  // 기본 2행은 편집기 블록 제목과 Artifact 제목 영역을 확보한다.
  // 나머지 가중치는 실제 A4 DOM 실측값을 기준으로 보정했으며, 가로 12행 블록에
  // 요약·KPI 2개·차트·표 4행을 표시한 뒤에도 한 행가량의 안전 여백이 남도록 계산한다.
  const height = Math.max(minimum, Math.min(maximum, 2 + summaryHeight + kpiHeight + dataHeight + sectionGap + modeAdjustment));
  return { width, height };
}

export function fitFrontendArtifactBlock(block, artifact, options = {}) {
  if (block?.type !== "artifact") return block;
  const rawSettings = { ...readJson(block.content), ...(options.settings || {}) };
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

export function artifactViewBlockSettings(block) {
  if (!['chart', 'table'].includes(block?.type)) return null;
  const settings = readJson(block.content);
  const legacyDefaultHeight = block.type === 'chart' ? 7 : 5;
  const sizeMode = settings.sizeMode === 'auto' || settings.sizeMode === 'manual'
    ? settings.sizeMode
    : block.type === 'table'
      ? Math.round(block.h ?? legacyDefaultHeight) <= 7 ? 'auto' : 'manual'
      : Math.round(block.h ?? legacyDefaultHeight) === legacyDefaultHeight ? 'auto' : 'manual';
  return { ...settings, sizeMode };
}

export function estimateArtifactViewBlockLayout(block, artifact, options = {}) {
  const type = block?.type === 'chart' ? 'chart' : 'table';
  const orientation = options.orientation === 'portrait' ? 'portrait' : 'landscape';
  const width = Math.min(12, Math.max(6, Math.round(block?.w ?? block?.columns ?? 12)));
  const rowCount = Array.isArray(artifact?.table?.rows) ? artifact.table.rows.length : 0;
  const columnCount = Array.isArray(artifact?.table?.columns) ? artifact.table.columns.length : 0;
  const seriesCount = Array.isArray(artifact?.chart?.y_fields)
    ? artifact.chart.y_fields.length
    : Array.isArray(artifact?.chart?.yFields) ? artifact.chart.yFields.length : 0;
  let height;
  if (type === 'chart') {
    height = 8
      + (orientation === 'portrait' ? 1 : 0)
      + Math.max(0, Math.ceil((seriesCount - 2) / 2))
      + (rowCount > 12 ? 1 : 0);
  } else {
    const widthColumnCapacity = width <= 6 ? 2 : 4;
    height = 3
      + Math.ceil(rowCount * 0.75)
      + (rowCount > 4 ? 1 : 0)
      + (orientation === 'portrait' ? 1 : 0)
      + (width <= 6 ? 1 : 0)
      + (width > 6 ? 2 : 0)
      + Math.max(0, Math.ceil((columnCount - widthColumnCapacity) / 2));
    if (artifactViewBlockSettings(block)?.density === 'compact') height -= 1;
    height = Math.max(5, height);
  }
  return { width, height: Math.min(18, height) };
}

export function fitFrontendArtifactViewBlock(block, artifact, options = {}) {
  const candidate = options.settings
    ? { ...block, content: JSON.stringify({ ...readJson(block.content), ...options.settings }) }
    : block;
  const settings = artifactViewBlockSettings(candidate);
  if (!settings || (!options.force && settings.sizeMode !== 'auto')) return block;
  const layout = estimateArtifactViewBlockLayout(candidate, artifact, options);
  return {
    ...block,
    content: JSON.stringify({ ...readJson(block.content), ...(options.settings || {}), sizeMode: 'auto' }),
    columns: layout.width,
    w: layout.width,
    h: layout.height,
    x: Math.min(block.x ?? 0, 12 - layout.width),
  };
}

function analysisPeriodLabel(period = {}) {
  const start = String(period.start || period.period_start || "").slice(0, 10);
  const end = String(period.endExclusive || period.end_exclusive || period.period_end_exclusive || "").slice(0, 10);
  return start && end ? `${start}–${end}` : "";
}

export function analysisArtifactTitle(artifact, preferredTitle = "", fallbackPeriod = {}) {
  const savedTitle = String(preferredTitle || "").trim();
  if (savedTitle) return savedTitle;
  const definitions = artifact?.metrics?.length ? artifact.metrics : artifact?.evidence?.metrics || [];
  const labels = [...new Set(definitions.map((metric) => String(metric.label || "").trim()).filter(Boolean))];
  const metricLabel = labels.length > 1 ? `${labels[0]} 외 ${labels.length - 1}개 지표` : labels[0] || "주요 지표";
  const periodLabel = analysisPeriodLabel(artifact?.evidence?.period || fallbackPeriod);
  return `${periodLabel ? `${periodLabel} ` : ""}${metricLabel} 분석`;
}

export function analysisRunArtifactSources(runs = [], definitions = []) {
  const exactTitles = new Map(definitions.map((definition) => [
    `${definition.definition_id}:${definition.version}`,
    String(definition.title || "").trim(),
  ]));
  const currentTitles = new Map(definitions.map((definition) => [
    definition.definition_id,
    String(definition.title || "").trim(),
  ]));
  const seen = new Set();
  return [...runs]
    .filter((run) => ["SUCCEEDED", "PARTIAL"].includes(run?.status) && run.request_id && run.artifact_id)
    .sort((left, right) => String(right.completed_at || right.started_at || "")
      .localeCompare(String(left.completed_at || left.started_at || "")))
    .flatMap((run) => {
      if (seen.has(run.artifact_id)) return [];
      seen.add(run.artifact_id);
      const definitionTitle = exactTitles.get(`${run.definition_id}:${run.definition_version}`)
        || currentTitles.get(run.definition_id)
        || "";
      return [{
        id: `analysis-run:${run.request_id}`,
        type: "artifact",
        sourceKind: "analysisRun",
        artifactId: run.artifact_id,
        queryId: run.query_id || undefined,
        requestId: run.request_id,
        analysisDefinitionId: run.definition_id,
        analysisDefinitionVersion: run.definition_version,
        definitionTitle,
        title: analysisArtifactTitle(null, definitionTitle, run),
        periodStart: run.period_start || undefined,
        periodEndExclusive: run.period_end_exclusive || undefined,
      }];
    });
}

function analysisMetricToReport(metric) {
  return {
    metric_id: metric.metricId,
    result_field: metric.resultField,
    label: metric.label,
    definition: metric.definition,
    value: metric.value,
    unit: metric.unit ?? null,
  };
}

function analysisMetricReferenceToReport(metric) {
  const { value: _value, ...reference } = analysisMetricToReport(metric);
  return reference;
}

export function adaptAnalysisRunArtifact(run) {
  if (!["success", "partial"].includes(run?.status) || run.evidenceReady !== true) return null;
  const artifactId = run.artifact?.artifactId;
  const queryId = run.artifact?.queryId;
  const evidence = run.evidence;
  if (!artifactId || !queryId || evidence?.artifactId !== artifactId || evidence?.queryId !== queryId) return null;
  return {
    contract_version: run.meta?.contractVersion,
    request_id: run.requestId,
    trace_id: run.traceId,
    status: run.status.toUpperCase(),
    artifact_id: artifactId,
    query_id: queryId,
    summary: run.summary || "",
    metrics: (run.metrics || []).map(analysisMetricToReport),
    table: run.table ? { columns: [...run.table.columns], rows: run.table.rows.map((row) => ({ ...row })) } : null,
    chart: run.chart ? {
      chart_type: run.chart.chartType,
      type: run.chart.chartType,
      x_field: run.chart.xField,
      y_fields: [...run.chart.yFields],
    } : null,
    evidence: {
      artifact_id: evidence.artifactId,
      query_id: evidence.queryId,
      as_of: evidence.asOf,
      timezone: evidence.timezone,
      period: evidence.period ? { start: evidence.period.start, end_exclusive: evidence.period.endExclusive } : null,
      filters: { ...(evidence.filters || {}) },
      context_release: evidence.contextRelease,
      policy_version: evidence.policyVersion,
      model_version: evidence.modelVersion,
      metrics: (evidence.metrics || []).map(analysisMetricReferenceToReport),
      models: (evidence.models || []).map((model) => ({
        node: model.node,
        model_version: model.modelVersion,
        prompt_id: model.promptId,
        prompt_version: model.promptVersion,
      })),
      gates: evidence.gates ? { ...evidence.gates } : null,
      gate_history: evidence.gateHistory ? {
        g1: [...evidence.gateHistory.g1], g2: [...evidence.gateHistory.g2], g3: [...evidence.gateHistory.g3],
      } : null,
      cached: Boolean(evidence.cached),
      sampling: evidence.sampling ? {
        applied: Boolean(evidence.sampling.applied),
        returned_rows: evidence.sampling.returnedRows,
        total_rows: evidence.sampling.totalRows,
      } : null,
      masking: evidence.masking ? {
        applied: Boolean(evidence.masking.applied),
        fields: [...evidence.masking.fields],
      } : null,
      sources: (run.sources || []).map((source) => ({
        name: source.name,
        urn: source.urn,
        fqn: source.fqn,
        schema_version: source.schemaVersion,
        seed_version: source.seedVersion,
        synthetic: typeof source.synthetic === "boolean" ? source.synthetic : undefined,
      })),
    },
  };
}

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
      return { ok: false, errors: ["데이터 블록에 Artifact 참조가 없습니다."] };
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
  return validation.valid ? { ok: true, document, errors: [] } : { ok: false, errors: validation.errors };
}

function frontendBlocksFromDocument(document, sourceBlocks) {
  const sources = new Map(sourceBlocks.map((block) => [block.id, block]));
  const pageRows = A4_PAGE_LAYOUT[document.orientation].contentRows;
  return document.pages.flatMap((page) => page.blocks.map((block) => {
    const source = sources.get(block.id);
    const fallbackType = block.kind === "markdown"
      ? "text"
      : block.visibleViews.length > 1 ? "artifact" : block.visibleViews[0] === "chart" ? "chart" : "table";
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
    ? { ok: true, blocks: frontendBlocksFromDocument(result.document, sourceBlocks), document: result.document, errors: [] }
    : { ok: false, blocks: sourceBlocks, errors: result.errors };
}

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
    ...(input.artifactDefinitionVersion === undefined ? {} : { artifactDefinitionVersion: input.artifactDefinitionVersion }),
    ...(input.sourceKind ? { artifactSourceKind: input.sourceKind } : {}),
    ...(input.requestId ? { artifactRequestId: input.requestId } : {}),
    ...(input.analysisDefinitionId ? { analysisDefinitionId: input.analysisDefinitionId } : {}),
    ...(input.analysisDefinitionVersion === undefined ? {} : { analysisDefinitionVersion: input.analysisDefinitionVersion }),
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

export function moveFrontendBlock(blocks, blockId, placement, report) {
  const current = frontendBlocksToDocument({ ...report, blocks });
  if (!current.ok) return { ...current, blocks };
  return operationResult(moveReportBlock(current.document, blockId, placement), blocks);
}

export function deleteFrontendBlock(blocks, blockId, report) {
  const current = frontendBlocksToDocument({ ...report, blocks });
  if (!current.ok) return { ...current, blocks };
  return operationResult(deleteReportBlock(current.document, blockId), blocks);
}

export function orientFrontendBlocks(blocks, orientation, report) {
  const current = frontendBlocksToDocument({ ...report, blocks });
  if (!current.ok) return { ...current, blocks };
  return operationResult(setReportOrientation(current.document, orientation), blocks);
}

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

export function frontendDraftStorageKey(definitionId, version) {
  return `answervice:report-draft:v2:${definitionId}:${version}`;
}

export function createFrontendDraftSnapshot({ definitionId, version, title, orientation, currencyPolicy, blocks }) {
  const converted = frontendBlocksToDocument({ definitionId, title, orientation, currencyPolicy, blocks });
  if (!converted.ok) return converted;
  const normalizedBlocks = frontendBlocksFromDocument(converted.document, blocks);
  return {
    ok: true,
    snapshot: {
      schemaVersion: FRONTEND_REPORT_DRAFT_VERSION,
      definitionRef: { definitionId, version },
      document: converted.document,
      blocks: normalizedBlocks,
    },
  };
}

export function saveFrontendDraft(storage, snapshot) {
  storage.setItem(
    frontendDraftStorageKey(snapshot.definitionRef.definitionId, snapshot.definitionRef.version),
    JSON.stringify(snapshot),
  );
}

export function loadFrontendDraft(storage, definitionId, version) {
  const serialized = storage.getItem(frontendDraftStorageKey(definitionId, version));
  if (!serialized) return null;
  try {
    const snapshot = JSON.parse(serialized);
    if (
      snapshot.schemaVersion !== FRONTEND_REPORT_DRAFT_VERSION
      || snapshot.definitionRef?.definitionId !== definitionId
      || snapshot.definitionRef?.version !== version
      || !Array.isArray(snapshot.blocks)
    ) return null;
    const validation = validateReportDocument(snapshot.document);
    if (!validation.valid || snapshot.document.schemaVersion !== REPORT_DOCUMENT_SCHEMA_VERSION) return null;
    return {
      orientation: snapshot.document.orientation,
      currencyPolicy: snapshot.document.currencyPolicy,
      blocks: frontendBlocksFromDocument(snapshot.document, snapshot.blocks),
    };
  } catch {
    return null;
  }
}
