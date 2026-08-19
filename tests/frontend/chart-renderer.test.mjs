import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const chartSource = readFileSync(new URL("../../app/frontend/src/components/charts/EnterpriseChart.jsx", import.meta.url), "utf8");
const stylesSource = readFileSync(new URL("../../app/frontend/src/styles.css", import.meta.url), "utf8");
const server = await createServer({
  appType: "custom",
  cacheDir: "node_modules/.vite-chart-test",
  logLevel: "error",
  root: frontendRoot,
  server: { middlewareMode: true, hmr: false },
});

try {
  const { EnterpriseChart, normalizeChartType } = await server.ssrLoadModule("/src/components/charts/EnterpriseChart.jsx");
  const render = (props) => renderToStaticMarkup(createElement(EnterpriseChart, props));
  const base = {
    data: [{ month: "2026-01", revenue: 0 }, { month: "2026-02", revenue: 12_500_000 }],
    series: [{ key: "revenue", label: "객실 매출", unit: "원" }],
    xKey: "month",
    xLabel: "월",
  };

  assert.equal(normalizeChartType("bar"), "bar");
  assert.equal(normalizeChartType("horizontal_bar"), "horizontal-bar");
  assert.equal(normalizeChartType(" STACKED-BAR "), "stacked-bar");
  assert.equal(normalizeChartType("column"), null);
  assert.equal(normalizeChartType(undefined), null);
  assert.match(chartSource, /enterprise-chart-axis--category/);
  assert.match(chartSource, /enterprise-chart-axis--value/);
  assert.match(chartSource, /tick=\{CATEGORY_AXIS_TICK\}/);
  assert.match(chartSource, /tick=\{VALUE_AXIS_TICK\}/);
  assert.match(stylesSource, /enterprise-chart-axis-tick--category/);
  assert.match(stylesSource, /enterprise-chart-axis-tick--value/);
  assert.match(stylesSource, /stroke:var\(--chart-surface\)/);

  for (const type of ["bar", "horizontal-bar", "line", "area", "stacked-bar", "donut", "pie"]) {
    assert.match(render({ ...base, type }), new RegExp(`enterprise-chart--${type}`));
  }

  const zeroAndNull = render({ ...base, data: [{ month: "1월", revenue: 0 }, { month: "2월", revenue: null }], type: "line" });
  assert.match(zeroAndNull, /enterprise-chart--line/);
  assert.doesNotMatch(zeroAndNull, /표시할 수치가 없습니다/);

  const allNull = render({ ...base, data: [{ month: "1월", revenue: null }], type: "bar" });
  assert.match(allNull, /선택한 계열에 표시할 수치가 없습니다/);
  assert.doesNotMatch(allNull, /enterprise-chart--bar/);

  const unknown = render({ ...base, type: "column" });
  assert.match(unknown, /지원하지 않는 차트 형식입니다/);

  const missingCategory = render({ ...base, data: [{ revenue: 1 }], type: "bar" });
  assert.match(missingCategory, /차트 필드 정보를 확인할 수 없습니다/);

  const fiveSeries = render({
    ...base,
    data: [{ month: "1월", a: 1, b: 2, c: 3, d: 4, e: 5 }],
    series: ["a", "b", "c", "d", "e"].map((key, index) => ({ key, label: `계열 ${index + 1}`, unit: "%" })),
    type: "line",
  });
  assert.equal((fiveSeries.match(/role="listitem"/g) ?? []).length, 5);
  assert.match(fiveSeries, /계열 5/);
  assert.doesNotMatch(fiveSeries, /<em>%<\/em>/);
  assert.match(fiveSeries, /단위: %/);

  const longCategory = "온라인 여행사와 공식 홈페이지 직접 예약 채널";
  const donut = render({
    ...base,
    data: [{ channel: longCategory, revenue: 0 }, { channel: "호텔 직접 예약", revenue: 10 }],
    type: "donut",
    xKey: "channel",
    xLabel: "예약 채널",
  });
  assert.match(donut, new RegExp(longCategory));
  assert.match(donut, /0 원/);
  assert.match(donut, /aria-describedby=/);
  assert.match(donut, /sr-only/);

  const ambiguousDonut = render({
    ...base,
    data: [{ month: "1월", revenue: 1, rooms: 2 }],
    series: [...base.series, { key: "rooms", label: "판매 객실", unit: "실" }],
    type: "donut",
  });
  assert.match(ambiguousDonut, /원형 차트에 맞지 않는 데이터입니다/);

  const mixedUnitStack = render({
    ...base,
    data: [{ month: "1월", revenue: 1, occupancy: 2 }],
    series: [...base.series, { key: "occupancy", label: "점유율", unit: "%" }],
    type: "stacked-bar",
  });
  assert.match(mixedUnitStack, /서로 다른 단위는 누적할 수 없습니다/);

  const negativePie = render({ ...base, data: [{ month: "1월", revenue: -1 }], type: "pie" });
  assert.match(negativePie, /전체 대비 비중을 계산할 수 없습니다/);
} finally {
  await server.close();
}

console.log("frontend chart renderer tests passed");
