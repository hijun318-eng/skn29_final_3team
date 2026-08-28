/** 인용 가능한 내부 문서 답변과 PDF 원문 링크를 한 카드로 표시한다. */
const styles = {
  card: {
    marginTop: '8px', padding: '26px 28px 22px', border: '1px solid #1d2b3d',
    borderRadius: '20px', background: 'linear-gradient(180deg, rgba(16,29,46,.98), rgba(11,22,36,.98))',
    boxShadow: '0 18px 60px rgba(0,0,0,.28)', color: '#e7eef8',
  },
  label: { marginBottom: '18px', color: '#c8d5e6', fontSize: '13px', fontWeight: 700 },
  body: { fontSize: '16px', lineHeight: 1.82, wordBreak: 'keep-all', overflowWrap: 'anywhere' },
  compare: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px', margin: '20px 0' },
  compareBox: { padding: '16px', border: '1px solid #1d2b3d', borderRadius: '14px', background: '#0b1727' },
  followup: { marginTop: '22px', paddingTop: '18px', borderTop: '1px solid #1d2b3d' },
  chips: { display: 'flex', flexWrap: 'wrap', gap: '8px' },
  chip: {
    padding: '9px 12px', border: '1px solid #26364d', borderRadius: '999px',
    background: '#142238', color: '#d6e1ef', fontSize: '13px', cursor: 'pointer',
  },
  sources: { display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '18px' },
  pdf: {
    padding: '9px 12px', border: '1px solid #2b3b54', borderRadius: '10px',
    background: '#0a1422', color: '#cbd8e9', fontSize: '12px', textDecoration: 'none',
  },
};

function getAnswerText(rag) {
  const text = rag?.answer_text || rag?.answer?.text || rag?.answer || rag?.body || '';
  const cleaned = String(text)
    .replace(/(?:현장\s*확인내용|객실\s*[·ㆍ]\s*설비)?\s*내부\s*업무지침\s*[·ㆍ]\s*현장\s*실행형\s*[·ㆍ]\s*의미전달\s*검증완료본/g, '')
    .replace(/^\s*자세한 내용은 PDF 원문 보기를 확인하세요\.\s*$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  if (cleaned) return cleaned;
  const status = String(rag?.status || rag?.response_status || '').toUpperCase();
  if (status === 'NO_EVIDENCE') {
    return '질문과 일치하는 내부 지침 근거를 찾지 못했습니다.\n\n업무 영역과 발생 상황을 포함해 다시 질문해 주세요.';
  }
  if (['ERROR', 'FAILED', 'GENERATION_FAILED'].includes(status)) {
    return '내부 지침 검색 중 오류가 발생했습니다. 잠시 후 다시 질문해 주세요.';
  }
  return '답변 내용을 표시하지 못했습니다. 질문을 다시 입력해 주세요.';
}

function getPdfUrl(rag) {
  const evidence = rag?.evidence?.[0] || rag?.citations?.[0] || {};
  return rag?.pdf_url || rag?.source_pdf_url || evidence.pdf_url || evidence.source_pdf_url || '';
}

function compareContent(text, answerType) {
  const types = Array.isArray(answerType) ? answerType : [answerType];
  if (!types.includes('COMPARE')) return null;
  const blocks = text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
  const sections = blocks
    .map((block) => block.split('\n').map((line) => line.trim()).filter(Boolean))
    .filter((lines) => lines.length > 1)
    .slice(0, 2);
  if (sections.length !== 2) return null;
  return { sections, prose: blocks.filter((block) => !sections.some((lines) => block === lines.join('\n'))) };
}

/** RAG 답변을 비교형 본문, 후속 질문과 중복 제거된 PDF 링크로 렌더링한다. */
export function RagAnswerCard({ rag, pdfUrl = '', pdfSources = [], onFollowUp }) {
  const answerText = getAnswerText(rag);
  const sourcePdfUrl = pdfUrl || getPdfUrl(rag);
  const pdfLinks = Array.from(new Map(
    [...pdfSources, ...(!pdfSources.length && sourcePdfUrl ? [{ label: rag?.document_name || '근거 문서', url: sourcePdfUrl }] : [])]
      .filter((item) => item.url)
      .map((item) => [item.url, item]),
  ).values());
  const comparison = compareContent(answerText, rag?.answer_type);
  const paragraphs = comparison?.prose || answerText.split(/\n\s*\n/).filter(Boolean);
  const responseStatus = String(rag?.status || rag?.response_status || '').toUpperCase();
  const isTerminalFailure = ['NO_EVIDENCE', 'ERROR', 'FAILED', 'GENERATION_FAILED'].includes(responseStatus);
  const candidateFollowUps = rag?.status === 'NEEDS_CLARIFICATION'
    ? rag?.clarification_options
    : rag?.follow_up_questions;
  const followUpQuestions = isTerminalFailure || !Array.isArray(candidateFollowUps)
    ? []
    : candidateFollowUps.filter((question) => typeof question === 'string' && question.trim());

  return (
    <article aria-labelledby="rag-answer-title" style={styles.card}>
      <div id="rag-answer-title" style={styles.label}>답변</div>
      <div style={styles.body}>
        {paragraphs.map((paragraph, index) => (
          <p key={`${index}-${paragraph.slice(0, 20)}`} style={{ margin: index ? '16px 0 0' : 0, whiteSpace: 'pre-wrap' }}>
            {paragraph}
          </p>
        ))}
        {comparison && (
          <div style={styles.compare}>
            {comparison.sections.map(([heading, ...items]) => (
              <section key={heading} style={styles.compareBox}>
                <h3 style={{ margin: '0 0 10px', color: '#fff', fontSize: '14px' }}>{heading.replace(/^#+\s*/, '')}</h3>
                <ul style={{ margin: 0, paddingLeft: '18px', color: '#c9d5e5', fontSize: '14px', lineHeight: 1.7 }}>
                  {items.map((item) => <li key={item}>{item.replace(/^[-*•]\s*/, '')}</li>)}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
      {onFollowUp && followUpQuestions.length > 0 && (
        <div style={styles.followup}>
          <div style={{ marginBottom: '10px', color: '#6f8198', fontSize: '12px' }}>추가로 확인할 수 있어요</div>
          <div style={styles.chips}>
            {followUpQuestions.map((question) => (
              <button key={question} type="button" style={styles.chip} onClick={() => onFollowUp(question)}>
                {question}
              </button>
            ))}
          </div>
        </div>
      )}
      {pdfLinks.length > 0 && (
        <div style={styles.sources}>
          {pdfLinks.map((item) => (
            <a key={item.url} href={item.url} target="_blank" rel="noreferrer noopener" style={styles.pdf}>
              PDF 원문 보기 · {item.label}
            </a>
          ))}
        </div>
      )}
    </article>
  );
}
