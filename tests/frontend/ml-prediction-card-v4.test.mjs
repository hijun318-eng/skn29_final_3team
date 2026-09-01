import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";


const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));


test("대화형 ML 카드는 v4 범위·객실 유형·영향 요인을 표시한다", async () => {
  const server = await createServer({
    appType: "custom",
    cacheDir: "node_modules/.vite-ml-card-v4-test",
    logLevel: "error",
    root: frontendRoot,
    server: { middlewareMode: true, hmr: false },
  });
  try {
    const { MLPredictionCard } = await server.ssrLoadModule(
      "/src/components/ml/MLPredictionCard.jsx",
    );
    const html = renderToStaticMarkup(createElement(MLPredictionCard, {
      prediction: {
        execution_id: "00000000-0000-0000-0000-000000000001",
        property_id: "GRAND",
        as_of: "2026-08-24",
        feature_as_of: "2026-08-24",
        model_version: "room-demand-operational-hgbr-v4.0.0",
        provenance: {
          trino_query_id: "history-query",
          signal_query_id: "signal-query",
        },
        daily_forecasts: [{
          target_date: "2026-08-25",
          total_available_rooms: 500,
          predicted_occupied_rooms: 381.4,
          predicted_available_rooms: 118.6,
          predicted_occupancy_rate: 0.7628,
          prediction_interval: {
            lower_80: 379.1,
            upper_80: 383.7,
            lower_95: 377.2,
            upper_95: 385.6,
          },
        }],
        room_type_forecasts: [{
          target_date: "2026-08-25",
          room_type_code: "G_DELUXE",
          predicted_rooms: 220.3,
          quality_scope: { status: "APPROVED" },
          influencing_factors: [{ label: "예약 잔량" }],
        }],
      },
    }));

    assert.match(html, /그랜드 워커힐 서울/);
    assert.match(html, /381\.4/);
    assert.match(html, /377\.2~385\.6실/);
    assert.match(html, /그랜드 딜럭스/);
    assert.match(html, /예약 잔량/);
    assert.match(html, /검증 통과/);
    assert.match(html, /실제값을 확인하고 있습니다/);
    assert.doesNotMatch(html, /Trino query|RAG 미호출/);
  } finally {
    await server.close();
  }
});


test("대화형 ML 카드는 추가 조건 질문을 기존 흐름으로 유지한다", async () => {
  const server = await createServer({
    appType: "custom",
    cacheDir: "node_modules/.vite-ml-card-v4-clarification-test",
    logLevel: "error",
    root: frontendRoot,
    server: { middlewareMode: true, hmr: false },
  });
  try {
    const { MLPredictionCard } = await server.ssrLoadModule(
      "/src/components/ml/MLPredictionCard.jsx",
    );
    const html = renderToStaticMarkup(createElement(MLPredictionCard, {
      prediction: {
        status: "NEEDS_CLARIFICATION",
        answer_text: "예측할 호텔을 지정해 주세요.",
        clarification_options: [{ label: "GRAND 호텔 예측", value: "GRAND 호텔" }],
      },
    }));

    assert.match(html, /예측 조건을 확인해 주세요/);
    assert.match(html, /GRAND 호텔 예측/);
  } finally {
    await server.close();
  }
});
