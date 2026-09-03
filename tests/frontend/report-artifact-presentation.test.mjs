import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const server = await createServer({
  appType: "custom",
  cacheDir: "node_modules/.vite-report-artifact-presentation-test",
  logLevel: "error",
  root: frontendRoot,
  server: { middlewareMode: true, hmr: false },
});

try {
  const { ReportWholeArtifactBlock, artifactComparisonCards } = await server.ssrLoadModule(
    "/src/features/reports/ReportWholeArtifactBlock.jsx",
  );
  const { ReportArtifactContent } = await server.ssrLoadModule(
    "/src/features/reports/components/ReportArtifactContent.jsx",
  );
  const { ReportEditorBlock } = await server.ssrLoadModule(
    "/src/features/reports/components/ReportEditorBlock.jsx",
  );
  const { reportColumnLabel } = await server.ssrLoadModule(
    "/src/features/reports/components/reportPresentation.js",
  );
  const artifact = {
    summary: "2026년 5월 1일 전부터 2026년 6월 1일 전까지의 Room Revenue 합계 계산 결과는 6,114,218,700 KRW입니다.",
    metrics: [{
      metric_id: "room_revenue",
      result_field: "room_revenue",
      label: "Room Revenue",
      display_label: "객실 매출",
      value: 6114218700,
      unit: "KRW",
      display_unit: "원",
    }],
    table: {
      columns: ["month", "room_revenue"],
      rows: [{ month: "5월", room_revenue: 6114218700 }],
    },
    chart: null,
    evidence: {
      period: { start: "2026-05-01", end_exclusive: "2026-06-01" },
      metrics: [{
        metric_id: "room_revenue",
        result_field: "room_revenue",
        label: "Room Revenue",
        display_label: "객실 매출",
        unit: "KRW",
        display_unit: "원",
      }],
    },
  };
  const html = renderToStaticMarkup(createElement(ReportWholeArtifactBlock, {
    block: { title: "5월 객실 매출", w: 12, type: "artifact", content: '{"visibleViews":["summary"]}' },
    artifact,
    artifactState: { status: "success" },
    currency: { label: "억 원", unit: "billion", policy: {} },
    renderView: (type) => createElement("div", null, `${type} 보기`),
  }));

  assert.equal(reportColumnLabel(artifact, "room_revenue"), "객실 매출");
  assert.equal(reportColumnLabel(artifact, "period"), "기간");
  assert.match(html, /분석 결과/);
  assert.match(html, />요약</);
  assert.match(html, /2026년 5월 1일부터 31일까지/);
  assert.doesNotMatch(html, /Room Revenue|KRW|ANALYSIS ARTIFACT|>KPI|미포함|2026-05-01/);

  const countArtifact = {
    ...artifact,
    summary: "합성 취소 연회 건수는 29 count입니다.",
    metrics: [{
      metric_id: "cancelled_banquet_count",
      result_field: "cancelled_banquet_count",
      label: "합성 취소 연회 건수",
      value: 29,
      unit: "count",
    }],
    table: {
      columns: ["hotel_code", "cancelled_banquet_count"],
      rows: [{ hotel_code: "GRAND", cancelled_banquet_count: 29 }],
    },
    evidence: {
      ...artifact.evidence,
      metrics: [{
        metric_id: "cancelled_banquet_count",
        result_field: "cancelled_banquet_count",
        label: "합성 취소 연회 건수",
        unit: "count",
      }],
    },
  };
  const countKpiHtml = renderToStaticMarkup(createElement(ReportWholeArtifactBlock, {
    block: { title: "연회 취소", w: 12, type: "artifact", content: '{"visibleViews":["kpi"]}' },
    artifact: countArtifact,
    artifactState: { status: "success" },
    currency: { label: "억 원", unit: "billion", policy: {} },
    renderView: (type) => createElement("div", null, `${type} 보기`),
  }));
  const countTableHtml = renderToStaticMarkup(createElement(ReportArtifactContent, {
    block: { title: "연회 취소", type: "table", content: '{"visibleViews":["table"]}' },
    artifact: countArtifact,
    artifactState: { status: "success" },
    currency: { label: "억 원", unit: "billion", policy: {} },
  }));
  assert.match(countKpiHtml, /29 건/);
  assert.match(countTableHtml, /합성 취소 연회 건수.*건/s);
  assert.match(countTableHtml, /report-table-sort-label/);
  assert.doesNotMatch(`${countKpiHtml}${countTableHtml}`, />count<|\(count\)/);

  const occupancyArtifact = {
    ...countArtifact,
    metrics: [{
      metric_id: "occupancy_rate_pct", result_field: "occupancy_rate_pct",
      label: "객실 점유율", value: 63.77, unit: "percent",
    }],
    table: {
      columns: ["hotel_code", "occupancy_rate_pct"],
      rows: [
        { hotel_code: "DOUGLAS 호텔", occupancy_rate_pct: 62.1 },
        { hotel_code: "GRAND 호텔", occupancy_rate_pct: 65.4 },
        { hotel_code: "VISTA 호텔", occupancy_rate_pct: 63.8 },
      ],
    },
  };
  const comparison = artifactComparisonCards(occupancyArtifact, occupancyArtifact.metrics);
  assert.equal(comparison?.rows.length, 3);
  const occupancyKpiHtml = renderToStaticMarkup(createElement(ReportWholeArtifactBlock, {
    block: { title: "호텔별 객실 점유율", w: 12, type: "artifact", content: '{"visibleViews":["kpi"]}' },
    artifact: occupancyArtifact,
    artifactState: { status: "success" },
    currency: { label: "억 원", unit: "billion", policy: {} },
  }));
  assert.match(occupancyKpiHtml, /항목별 주요 지표 비교/);
  assert.match(occupancyKpiHtml, /DOUGLAS 호텔/);
  assert.match(occupancyKpiHtml, /GRAND 호텔/);
  assert.match(occupancyKpiHtml, /VISTA 호텔/);
  assert.match(occupancyKpiHtml, /62\.1%/);
  assert.doesNotMatch(occupancyKpiHtml, /report-whole-artifact-heading/);

  const legacyBundleHtml = renderToStaticMarkup(createElement(ReportWholeArtifactBlock, {
    block: {
      title: "기존 합본", w: 12, type: "artifact",
      content: '{"visibleViews":["summary","kpi"]}',
    },
    artifact,
    artifactState: { status: "success" },
    currency: { label: "억 원", unit: "billion", policy: {} },
    renderView: () => createElement("div", null, "unexpected"),
  }));
  assert.match(legacyBundleHtml, /이전 형식의 합본 분석 요소입니다/);
  assert.match(legacyBundleHtml, /각각 독립 블록으로 정리됩니다/);
  assert.doesNotMatch(legacyBundleHtml, /unexpected|객실 매출|6,114/);
  for (const [artifactState, expected] of [
    [{ status: "error", message: "연결 실패", requiredAction: "RETRY" }, "연결 실패"],
    [{ status: "empty" }, "조건에 맞는 데이터가 없습니다"],
  ]) {
    const terminalHtml = renderToStaticMarkup(createElement(ReportWholeArtifactBlock, {
      block: { title: "원자 요약", w: 6, type: "artifact", content: '{"visibleViews":["summary"]}' },
      artifact,
      artifactState,
      currency: { label: "억 원", unit: "billion", policy: {} },
      onRetry() {},
    }));
    assert.match(terminalHtml, new RegExp(expected));
    assert.doesNotMatch(terminalHtml, /불러오고 있습니다/);
  }

  const editorCallbacks = {
    onSelect() {}, onUpdate() {}, onMove() {}, onResize() {}, onSetting() {},
    onDuplicate() {}, onDelete() {}, onToggleLock() {}, onRetryArtifact() {},
  };
  const artifactEditorHtml = renderToStaticMarkup(createElement(ReportEditorBlock, {
    block: {
      id: "artifact-table", title: "객실 매출 상세", type: "table",
      artifactId: "artifact-one", content: '{"visibleViews":["table"]}', x: 0, y: 0, w: 6, columns: 6, h: 5,
    },
    rowOffset: 0,
    artifact,
    artifactState: { status: "success" },
    currency: { label: "억 원", unit: "billion", policy: {} },
    isDraft: true,
    selected: false,
    primary: false,
    dragging: false,
    groupTransform: null,
    ...editorCallbacks,
  }));
  const textEditorHtml = renderToStaticMarkup(createElement(ReportEditorBlock, {
    block: {
      id: "text-one", title: "사용자 요약", type: "text", content: "작성한 본문",
      x: 0, y: 0, w: 6, columns: 6, h: 4,
    },
    rowOffset: 0,
    artifact: null,
    artifactState: null,
    currency: { label: "억 원", unit: "billion", policy: {} },
    isDraft: true,
    selected: false,
    primary: false,
    dragging: false,
    groupTransform: null,
    ...editorCallbacks,
  }));
  assert.match(artifactEditorHtml, /<h2 class="notion-block-title notion-block-title--readonly">객실 매출 상세<\/h2>/);
  assert.doesNotMatch(artifactEditorHtml, /<input[^>]+class="notion-block-title"/);
  assert.match(textEditorHtml, /<input class="notion-block-title"/);

  console.log("frontend report artifact presentation tests passed");
} finally {
  await server.close();
}
