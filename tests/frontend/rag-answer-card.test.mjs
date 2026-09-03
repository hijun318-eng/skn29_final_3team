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
  const { RagAnswerCard, previewTablesFromHtml } = await server.ssrLoadModule("/src/components/rag/RagAnswerCard.jsx");
  assert.deepEqual(previewTablesFromHtml([
    '<main><table><tr><th>호텔</th><th>객실 매출</th></tr>',
    '<tr><td>GRAND</td><td>4,304,501,150원</td></tr></table></main>',
  ].join('')), [{
    columns: ['호텔', '객실 매출'],
    rows: [['GRAND', '4,304,501,150원']],
  }]);
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
      { documentId: "manual-approved", label: "객실 운영 지침", url: rag.pdf_url },
      { documentId: "manual-approved", label: "중복 링크", url: rag.pdf_url },
    ],
  });
  const html = renderToStaticMarkup(createElement("div", null, card("first"), card("second")));

  assert.match(html, /class="rag-answer-card"/);
  assert.match(html, /핵심 답변/);
  assert.match(html, /class="rag-answer-card__comparison"/);
  assert.match(html, /aria-label="후속 질문"/);
  assert.match(html, /aria-label="출처"/);
  assert.match(html, /승인 절차를 더 알려줘/);
  assert.equal((html.match(/<span>뷰어 열기<\/span>/g) || []).length, 2);
  assert.doesNotMatch(html, /원문 보기/);
  assert.doesNotMatch(html, /PDF 원문 보기/);
  assert.equal((html.match(/aria-label="본문 인용"/g) || []).length, 2);
  assert.doesNotMatch(html, />근거 인용</);
  assert.equal((html.match(/aria-label="1번 인용 근거 보기"/g) || []).length, 2);
  assert.match(html, /객실 운영 지침 · v3 · 객실 정비 인계/);
  assert.match(html, /객실 정비 이력과 당직자 인계 내용을 함께 확인한다/);
  assert.equal((html.match(/class="rag-answer-card__source-strip"/g) || []).length, 2);
  assert.equal((html.match(/객실 운영 지침<\/b>/g) || []).length, 2);
  assert.doesNotMatch(html, /class="rag-answer-card__sources"/);
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
  assert.match(tableHtml, /class="rag-answer-card__lead">전체 취소율은 <strong class="rag-answer-card__metric">17.59%<\/strong>입니다/);
  assert.match(tableHtml, /상세 근거 1건/);
  assert.doesNotMatch(tableHtml, /2026년 8월 \| 객실팀/);

  const monthlyReportHtml = renderToStaticMarkup(createElement(RagAnswerCard, {
    rag: {
      answer_text: [
        "- 운영 결론 판매 객실은 15,717실, 객실 매출은 68.9억원다.",
        "- 객실 운영보고서",
        "- 호텔 운영실적과 원인, 후속 조치를 연결한 월간 보고",
        "- 매출은 그랜드호텔이 가장 높다.",
        "- 2026년 8월 | 객실팀",
        "- 전체 취소율은 17.59%다.",
      ].join("\n"),
      evidence_bundle: [{
        evidence_id: "report-room:1",
        document_id: "report-room",
        document_name: "2026년 8월 객실 운영보고서",
        section: "[DOCX DOCUMENT_START 1] 문서 본문",
        snippet: [
          "[PARAGRAPH style=Title] 객실 운영보고서",
          "[PARAGRAPH style=Subtitle] 호텔 운영실적과 원인, 후속 조치를 연결한 월간 보고",
          "[TABLE index=2 style=UNSTYLED]",
          "[r1c1 span=1] 호텔 | [r1c2 span=1] 판매 가능 객실 | [r1c3 span=1] 판매 객실 | [r1c4 span=1] 객실 매출 | [r1c5 span=1] 판매 가능 객실당 매출",
          "[r2c1 span=1] 더글러스호텔 | [r2c2 span=1] 1,598실 | [r2c3 span=1] 785실 | [r2c4 span=1] 357,944,650원 | [r2c5 span=1] 223,995원",
          "[r3c1 span=1] 그랜드호텔 | [r3c2 span=1] 15,532실 | [r3c3 span=1] 10,592실 | [r3c4 span=1] 4,304,501,150원 | [r3c5 span=1] 277,138원",
          "[r4c1 span=1] 비스타호텔 | [r4c2 span=1] 7,516실 | [r4c3 span=1] 4,340실 | [r4c4 span=1] 2,223,290,000원 | [r4c5 span=1] 295,808원",
          "[/TABLE]",
        ].join("\n"),
      }],
      routing: { snapshot_question: "8월 호텔별 총 운영 매출을 비교해줘" },
    },
  }));
  assert.match(monthlyReportHtml, /68\.9억 원<\/strong>입니다/);
  assert.doesNotMatch(monthlyReportHtml, /억원다|<li>객실 운영보고서<\/li>|<li>2026년 8월 \| 객실팀<\/li>/);
  assert.match(monthlyReportHtml, /class="rag-answer-card__metric">15,717실<\/strong>/);
  assert.match(monthlyReportHtml, /class="rag-answer-card__metric">68\.9억 원<\/strong>/);
  assert.match(monthlyReportHtml, /<small>문서 본문<\/small>/);
  assert.match(monthlyReportHtml, /함께 볼 내용/);
  assert.match(monthlyReportHtml, /보고서 관련 수치/);
  assert.match(monthlyReportHtml, /43\.0억 원/);
  assert.match(monthlyReportHtml, /4,304,501,150원/);
  assert.match(monthlyReportHtml, /295,808원/);
  assert.doesNotMatch(monthlyReportHtml, /<th scope="col">판매 가능 객실<\/th>/);
  assert.equal((monthlyReportHtml.match(/최고/g) || []).length, 3);
  assert.doesNotMatch(monthlyReportHtml, /<small>\[DOCX DOCUMENT_START/);

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
  assert.match(stylesSource, /\.rag-answer-card__metric/);
  assert.match(stylesSource, /\.rag-document-viewer/);
  assert.match(stylesSource, /grid-template-columns: auto minmax\(0, 1fr\)/);

} finally {
  await server.close();
}
