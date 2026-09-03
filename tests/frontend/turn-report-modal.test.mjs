import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const modalSource = readFileSync(new URL("../../app/frontend/src/components/TurnReportModal.jsx", import.meta.url), "utf8");
const modalStyles = readFileSync(new URL("../../app/frontend/src/components/TurnReportModal.css", import.meta.url), "utf8");
const globalStyles = readFileSync(new URL("../../app/frontend/src/styles.css", import.meta.url), "utf8");
const server = await createServer({
  appType: "custom",
  cacheDir: "node_modules/.vite-turn-report-modal-test",
  logLevel: "error",
  root: frontendRoot,
  server: { middlewareMode: true, hmr: false },
});

try {
  const { TurnReportModal } = await server.ssrLoadModule("/src/components/TurnReportModal.jsx");
  const run = {
    question: "표로 보여줘",
    requestId: "request-table-preview",
    status: "success",
    rowCount: 3,
    summary: "2026-05-01부터 2026-06-01 전까지의 Room Revenue 합계 계산 결과는 6,114,218,700 KRW입니다.",
    metrics: [{
      metricId: "room_revenue",
      resultField: "room_revenue",
      label: "Room Revenue",
      displayLabel: "객실 매출",
      value: 6114218700,
      unit: "KRW",
      displayUnit: "원",
    }],
    evidence: {
      period: { start: "2026-05-01", endExclusive: "2026-06-01" },
      metrics: [],
    },
    table: {
      columns: ["hotel_code", "room_revenue"],
      rows: [
        { hotel_code: "DOUGLAS", room_revenue: 2760000000 },
        { hotel_code: "GRAND", room_revenue: 18470000000 },
        { hotel_code: "VISTA", room_revenue: 10840000000 },
      ],
    },
  };
  const html = renderToStaticMarkup(createElement(TurnReportModal, {
    mode: "draft",
    run,
    viewType: "TABLE",
    title: "2026년 5월 객실 매출 분석 보고서",
    onTitleChange: () => {},
    onConfirm: () => {},
    onPreviewMode: () => {},
    onClose: () => {},
    isSubmitting: false,
  }));

  assert.match(html, /aria-modal="true"/);
  assert.match(html, /aria-labelledby="[^"]+"/);
  assert.match(html, /class="report-transfer-modal__body"/);
  assert.match(html, /보고서 제목/);
  assert.match(html, /선택한 분석/);
  assert.match(html, /2026년 5월 객실 매출 분석/);
  assert.doesNotMatch(html, /표로 보여줘/);
  assert.match(html, /객실 매출/);
  assert.match(html, /호텔/);
  assert.match(html, /DOUGLAS 호텔/);
  assert.match(html, /184\.7/);
  assert.match(html, /억 원/);
  assert.match(html, /3개 행/);
  assert.doesNotMatch(html, /1개 지표/);
  assert.doesNotMatch(html, /class="analysis-kpi-section"/);
  assert.doesNotMatch(html, /Room Revenue|KRW|style=/);

  assert.match(modalSource, /import "\.\/TurnReportModal\.css"/);
  assert.match(modalSource, /<AnalysisStatePanel run=\{run\} viewType=\{viewType\}/);
  assert.doesNotMatch(modalSource, /style=\{\{|<dt>\{metric\.label\}|metric\.unit \|\| ""/);
  assert.match(modalStyles, /\.report-transfer-modal\{[\s\S]*--report-modal-bg:/);
  assert.match(modalStyles, /\.report-title-field input:focus-visible/);
  assert.match(modalStyles, /\.ppt-theme \.report-transfer-modal\{/);
  assert.match(modalStyles, /@media\(max-width:650px\)/);
  assert.doesNotMatch(globalStyles, /report-transfer-modal|report-modal-backdrop|report-preview-summary|report-analysis-preview|report-section-options/);

  console.log("frontend turn report modal tests passed");
} finally {
  await server.close();
}
