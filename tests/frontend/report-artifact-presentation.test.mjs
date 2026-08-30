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
  const { ReportWholeArtifactBlock } = await server.ssrLoadModule(
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
  assert.match(legacyBundleHtml, /이전 합본 분석 요소는 표시할 수 없습니다/);
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
