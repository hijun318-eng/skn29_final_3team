import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "../../app/frontend/node_modules/react/index.js";
import { renderToStaticMarkup } from "../../app/frontend/node_modules/react-dom/server.node.js";
import { createServer } from "../../app/frontend/node_modules/vite/dist/node/index.js";

const frontendRoot = fileURLToPath(new URL("../../app/frontend", import.meta.url));
const componentSource = readFileSync(
  new URL("../../app/frontend/src/components/rag/RagAnswerCard.jsx", import.meta.url),
  "utf8",
);
const stylesSource = readFileSync(
  new URL("../../app/frontend/src/components/rag/RagAnswerCard.css", import.meta.url),
  "utf8",
);
const server = await createServer({
  appType: "custom",
  cacheDir: "node_modules/.vite-rag-answer-card-test",
  logLevel: "error",
  root: frontendRoot,
  server: { middlewareMode: true, hmr: false },
});

try {
  const { RagAnswerCard } = await server.ssrLoadModule("/src/components/rag/RagAnswerCard.jsx");
  const rag = {
    answer_text: "현재 상태\n- 객실 정비 이력 확인\n- 당직자 인계 확인\n\n권장 조치\n- 승인 절차 확인\n- 후속 기록 남기기",
    answer_type: ["COMPARE"],
    follow_up_questions: ["승인 절차를 더 알려줘"],
    document_name: "객실 운영 지침",
    pdf_url: "/api/rag/documents/manual-approved/pdf",
  };
  const card = (key) => createElement(RagAnswerCard, {
    key,
    rag,
    onFollowUp: () => {},
    pdfSources: [
      { label: "객실 운영 지침", url: rag.pdf_url },
      { label: "중복 링크", url: rag.pdf_url },
    ],
  });
  const html = renderToStaticMarkup(createElement("div", null, card("first"), card("second")));

  assert.match(html, /class="rag-answer-card"/);
  assert.match(html, /class="rag-answer-card__comparison"/);
  assert.match(html, /aria-label="후속 질문"/);
  assert.match(html, /aria-label="근거 문서"/);
  assert.match(html, /승인 절차를 더 알려줘/);
  assert.equal((html.match(/PDF 원문 보기/g) || []).length, 2);
  assert.doesNotMatch(html, /style=/);

  const labelledBy = [...html.matchAll(/aria-labelledby="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(labelledBy.length, 2);
  assert.equal(new Set(labelledBy).size, 2);
  for (const id of labelledBy) assert.match(html, new RegExp(`id="${id}"`));

  const failureHtml = renderToStaticMarkup(createElement(RagAnswerCard, {
    rag: { status: "NO_EVIDENCE", follow_up_questions: ["노출되면 안 됨"] },
    onFollowUp: () => {},
  }));
  assert.match(failureHtml, /질문과 일치하는 내부 지침 근거를 찾지 못했습니다/);
  assert.doesNotMatch(failureHtml, /노출되면 안 됨|후속 질문/);

  assert.doesNotMatch(componentSource, /const styles\s*=|style=\{/);
  assert.match(stylesSource, /\.ppt-theme \.rag-answer-card/);
  assert.match(stylesSource, /width: min\(100%, 820px\)/);
  assert.match(stylesSource, /@media \(max-width: 650px\)/);
  assert.match(stylesSource, /min-height: 44px/);
  assert.match(stylesSource, /:focus-visible/);

} finally {
  await server.close();
}
