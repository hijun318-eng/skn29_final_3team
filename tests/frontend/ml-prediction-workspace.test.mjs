import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const source = readFileSync(
  new URL("../../app/frontend/src/components/ml/MLPredictionWorkspace.jsx", import.meta.url),
  "utf8",
);
const styles = readFileSync(
  new URL("../../app/frontend/src/components/ml/MLPredictionWorkspace.css", import.meta.url),
  "utf8",
);

test("ML 예측 결과는 핵심 KPI와 날짜별 누적 전망을 먼저 보여주고 기술 정보만 접어 둔다", async () => {
  const server = await createServer({
    appType: "custom",
    cacheDir: "node_modules/.vite-ml-prediction-workspace-test",
    logLevel: "error",
    root: frontendRoot,
    server: { middlewareMode: true, hmr: false },
  });
  try {
    const {
      default: MLPredictionWorkspace,
      MLPredictionResult,
      mlResponseErrorMessage,
    } = await server.ssrLoadModule(
      "/src/components/ml/MLPredictionWorkspace.jsx",
    );
    assert.equal(renderToStaticMarkup(createElement(MLPredictionWorkspace)), "");
    assert.equal(mlResponseErrorMessage({
      detail: { code: "ML_RELEASE_NOT_PRODUCTION_APPROVED", reason: "운영 승인 전 모델입니다." },
    }), "운영 승인 전 모델입니다.");
    assert.equal(mlResponseErrorMessage({ detail: { code: "UNKNOWN" } }), "ML 요청을 처리하지 못했습니다.");
    const html = renderToStaticMarkup(createElement(MLPredictionResult, {
      result: {
        property_id: "GRAND",
        as_of: "2026-08-30",
        feature_as_of: "2026-08-29",
        model_version: "room-demand-hgbr-v2.2.0",
        provenance: { trino_query_id: "query-approved-1" },
        daily_forecasts: [
          {
            target_date: "2026-08-31",
            total_available_rooms: 100,
            predicted_occupied_rooms: 70,
            predicted_available_rooms: 30,
            predicted_occupancy_rate: 0.7,
          },
          {
            target_date: "2026-09-01",
            total_available_rooms: 100,
            predicted_occupied_rooms: 80,
            predicted_available_rooms: 20,
            predicted_occupancy_rate: 0.8,
          },
        ],
      },
    }));

    assert.match(html, /GRAND 호텔 객실 수요 예측/);
    assert.match(html, /2026\.08\.31\. ~ 2026\.09\.01\. · 2일 전망/);
    assert.match(html, /기간 예상 점유율<\/span><strong>75%/);
    assert.match(html, /누적 예상 객실 판매량<\/span><strong>150 객실/);
    assert.doesNotMatch(html, /<article><span>예측 기간<\/span>/);
    assert.match(html, /예측 기준 2026\.08\.30\./);
    assert.match(html, /실적 기준 2026\.08\.29\./);
    assert.match(html, /날짜별 판매 및 점유율/);
    assert.match(html, /누적 예상 판매/);
    assert.match(html, /누적 점유율/);
    assert.match(html, /class="ml-workspace__daily-cards"/);
    assert.match(html, /<time dateTime="2026-08-31">2026\.08\.31\.<\/time>/);
    assert.match(html, /예상 판매<\/span><strong>70 객실<\/strong>/);
    assert.match(html, /<dt>누적 예상 판매<\/dt><dd>70 객실<\/dd>/);
    assert.match(html, /<dt>누적 예상 판매<\/dt><dd>150 객실<\/dd>/);
    assert.match(html, /<dt>누적 점유율<\/dt><dd>75%<\/dd>/);
    assert.doesNotMatch(html, /\s박<|\d실</);
    assert.match(html, /2026\.08\.30\./);
    assert.doesNotMatch(html, /role="img"|예상 점유율 추이|ml-workspace__chart/);
    assert.doesNotMatch(html, />2026-08-31</);
    assert.match(html, /room-demand-hgbr-v2\.2\.0/);
    assert.doesNotMatch(html, /예측 한계|불확실성 구간/);
    assert.doesNotMatch(html, /<details class="ml-workspace__details">/);
    assert.match(html, /<section class="ml-workspace__daily"/);
    assert.doesNotMatch(html, /<table>/);
    assert.match(html, /<details class="ml-workspace__technical-details">/);
    assert.match(html, /<dt>사용 모델<\/dt><dd>room-demand-hgbr-v2\.2\.0<\/dd>/);
    assert.doesNotMatch(html, /<details[^>]+open/);
    assert.doesNotMatch(html, /RAG 호출|Trino query/);

    const invalidHtml = renderToStaticMarkup(createElement(MLPredictionResult, {
      result: {
        daily_forecasts: [{
          target_date: "2026-08-31",
          total_available_rooms: 100,
          predicted_occupied_rooms: null,
          predicted_available_rooms: 30,
          predicted_occupancy_rate: null,
        }],
      },
    }));
    assert.match(invalidHtml, /role="alert"/);
    assert.match(invalidHtml, /예측 결과 형식을 확인할 수 없습니다/);
    assert.doesNotMatch(invalidHtml, /0%|0객실박|role="img"/);

    const emptyHtml = renderToStaticMarkup(createElement(MLPredictionResult, {
      result: { daily_forecasts: [] },
    }));
    assert.match(emptyHtml, /role="status"/);
    assert.match(emptyHtml, /표시할 예측 결과가 없습니다/);
    assert.doesNotMatch(emptyHtml, /0%|0객실박/);
  } finally {
    await server.close();
  }
});

test("ML 예측 drawer는 viewport와 키보드 접근성 계약을 갖는다", () => {
  assert.match(source, /horizon_days: Number\(horizon\)/);
  assert.match(source, /max=\{capability\?\.max_horizon_days \|\| 1\}/);
  assert.match(source, /현재 모델은/);
  assert.doesNotMatch(source, /\[1, 3, 7\]/);
  assert.match(styles, /\.ml-workspace__field-hint\s*\{[^}]*font-size:\s*0\.75rem;[^}]*line-height:\s*1\.5;/s);
  assert.match(source, /aria-controls=\{DIALOG_ID\}/);
  assert.match(source, /role="dialog"/);
  assert.match(source, /aria-modal="true"/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /event\.key !== "Tab"/);
  assert.match(source, /triggerRef\.current\?\.focus\(\)/);
  assert.match(source, /const previousBodyOverflow = document\.body\.style\.overflow/);
  assert.match(source, /document\.body\.style\.overflow = "hidden"/);
  assert.match(source, /document\.body\.style\.overflow = previousBodyOverflow/);
  assert.match(styles, /\.ml-workspace__panel\s*\{[^}]*position:\s*fixed;/s);
  assert.match(styles, /@media \(max-width:\s*650px\)[\s\S]*height:\s*100dvh;/);
  assert.match(styles, /overscroll-behavior:\s*contain/);
  assert.doesNotMatch(styles, /font-family:\s*"Pretendard"/);
  assert.doesNotMatch(styles, /font-size:\s*(?:[0-9]|1[01])px/);
});
