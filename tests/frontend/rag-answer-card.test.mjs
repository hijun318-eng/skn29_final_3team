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
    citations: [{ evidence_id: "manual-approved:3", citation: "객실 운영 지침 p.3" }],
    evidence_bundle: [{
      evidence_id: "manual-approved:3",
      document_id: "manual-approved",
      document_name: "객실 운영 지침",
      document_version: "v3",
      section: "객실 정비 인계",
      snippet: "객실 정비 이력과 당직자 인계 내용을 함께 확인한다.",
      score: 0.92,
    }, {
      evidence_id: "manual-approved:4",
      document_id: "manual-approved",
      document_name: "객실 운영 지침",
      document_version: "v3",
      section: "승인 절차",
      snippet: "승인 담당자가 후속 기록을 확인한다.",
      score: 0.89,
    }],
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
  assert.match(html, /핵심 답변/);
  assert.match(html, /class="rag-answer-card__comparison"/);
  assert.match(html, /aria-label="후속 질문"/);
  assert.match(html, /aria-label="근거 문서"/);
  assert.match(html, /승인 절차를 더 알려줘/);
  assert.equal((html.match(/PDF 원문 보기/g) || []).length, 2);
  assert.equal((html.match(/근거 인용/g) || []).length, 2);
  assert.equal((html.match(/aria-label="1번 인용 근거 보기"/g) || []).length, 2);
  assert.match(html, /객실 운영 지침 · v3 · 객실 정비 인계/);
  assert.match(html, /객실 정비 이력과 당직자 인계 내용을 함께 확인한다/);
  assert.equal((html.match(/class="rag-answer-card__source-strip"/g) || []).length, 2);
  assert.equal((html.match(/객실 운영 지침<\/b>/g) || []).length, 2);
  assert.doesNotMatch(html, /style=/);

  const parserMarkerHtml = renderToStaticMarkup(createElement(RagAnswerCard, {
    rag: { answer_text: "- 전체 취소율은 17.59%입니다.\n- 일정 변경 비중은 53.95%입니다.\n- [SECTION_BOUNDARY index=1 type=nextPage]" },
  }));
  assert.match(parserMarkerHtml, /class="rag-answer-card__lead"/);
  assert.match(parserMarkerHtml, /class="rag-answer-card__points"/);
  assert.doesNotMatch(parserMarkerHtml, /SECTION_BOUNDARY|nextPage/);

  const tableHtml = renderToStaticMarkup(createElement(RagAnswerCard, {
    rag: {
      answer_text: [
        "- 2026년 8월 | 객실팀",
        "- 전체 취소율은 17.59%입니다.",
        "- 주요 취소 사유 | 건수 | 비중",
        "- 일정 변경 | 894건 | 53.95%",
        "- 가격 민감 | 763건 | 46.05%",
        "- 호텔별 취소 규모도 함께 관리합니다.",
      ].join("\n"),
      routing: { snapshot_question: "2026년 8월 객실운영보고서에서 전체 취소율과 가장 큰 취소 사유를 알려줘" },
    },
  }));
  assert.match(tableHtml, /<table>/);
  assert.match(tableHtml, /<th scope="col">주요 취소 사유<\/th>/);
  assert.match(tableHtml, /<th scope="row">일정 변경<\/th><td>894건<\/td><td>53.95%<\/td>/);
  assert.match(tableHtml, /class="rag-answer-card__lead">전체 취소율은 17.59%입니다/);
  assert.match(tableHtml, /상세 근거 2건/);
  assert.equal((tableHtml.match(/2026년 8월 \| 객실팀/g) || []).length, 1);

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
