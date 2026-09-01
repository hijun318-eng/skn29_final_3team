/** 책임: 인용 가능한 내부 문서 답변과 후속 질문·PDF 근거를 접근 가능한 카드로 표시한다. */
import { useId } from "react";
import { FileText } from "lucide-react";

import "./RagAnswerCard.css";

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

function evidenceSources(rag) {
  const items = Array.isArray(rag?.evidence_bundle) ? rag.evidence_bundle : [];
  return Array.from(new Map(items
    .filter((item) => item && typeof item.evidence_id === 'string' && item.evidence_id)
    .map((item) => [item.evidence_id, item])).values());
}

function citationReferences(rag, sources) {
  const sourceById = new Map(sources.map((item) => [item.evidence_id, item]));
  const citations = Array.isArray(rag?.citations) ? rag.citations : [];
  return Array.from(new Map(citations
    .filter((item) => item && typeof item.evidence_id === 'string' && item.evidence_id)
    .map((item) => [item.evidence_id, {
      citation: typeof item.citation === 'string' ? item.citation : '',
      evidence: sourceById.get(item.evidence_id) || null,
    }])).values());
}

function evidenceLabel(item) {
  return [item?.document_name, item?.document_version, item?.section]
    .filter((value) => typeof value === 'string' && value.trim())
    .join(' · ') || '근거 문서';
}

/** RAG 답변을 비교형 본문, 후속 질문과 중복 제거된 PDF 링크로 렌더링한다. */
export function RagAnswerCard({ rag, pdfUrl = '', pdfSources = [], onFollowUp }) {
  const titleId = useId();
  const answerText = getAnswerText(rag);
  const sourcePdfUrl = pdfUrl || getPdfUrl(rag);
  const pdfLinks = Array.from(new Map(
    [...pdfSources, ...(!pdfSources.length && sourcePdfUrl ? [{ label: rag?.document_name || '근거 문서', url: sourcePdfUrl }] : [])]
      .filter((item) => item.url)
      .map((item) => [item.url, item]),
  ).values());
  const comparison = compareContent(answerText, rag?.answer_type);
  const paragraphs = comparison?.prose || answerText.split(/\n\s*\n/).filter(Boolean);
  const sources = evidenceSources(rag);
  const citationRefs = citationReferences(rag, sources);
  const responseStatus = String(rag?.status || rag?.response_status || '').toUpperCase();
  const isTerminalFailure = ['NO_EVIDENCE', 'ERROR', 'FAILED', 'GENERATION_FAILED'].includes(responseStatus);
  const candidateFollowUps = rag?.status === 'NEEDS_CLARIFICATION'
    ? rag?.clarification_options
    : rag?.follow_up_questions;
  const followUpQuestions = isTerminalFailure || !Array.isArray(candidateFollowUps)
    ? []
    : candidateFollowUps.filter((question) => typeof question === 'string' && question.trim());

  return (
    <article aria-labelledby={titleId} className="rag-answer-card">
      <div id={titleId} className="rag-answer-card__label">답변</div>
      <div className="rag-answer-card__body">
        {paragraphs.map((paragraph, index) => (
          <p key={`${index}-${paragraph.slice(0, 20)}`}>
            {paragraph}
          </p>
        ))}
        {comparison && (
          <div className="rag-answer-card__comparison">
            {comparison.sections.map(([heading, ...items]) => (
              <section key={heading} className="rag-answer-card__comparison-item">
                <h3>{heading.replace(/^#+\s*/, '')}</h3>
                <ul>
                  {items.map((item) => <li key={item}>{item.replace(/^[-*•]\s*/, '')}</li>)}
                </ul>
              </section>
            ))}
          </div>
        )}
        {citationRefs.length > 0 && (
          <div className="rag-answer-card__citations" aria-label="본문 인용">
            <span>근거 인용</span>
            <div>
              {citationRefs.map((reference, index) => (
                <details key={reference.evidence?.evidence_id || `${reference.citation}-${index}`}>
                  <summary aria-label={`${index + 1}번 인용 근거 보기`}>[{index + 1}]</summary>
                  <div className="rag-answer-card__citation-preview">
                    <strong>{evidenceLabel(reference.evidence)}</strong>
                    {reference.citation && <small>{reference.citation}</small>}
                    {reference.evidence?.snippet && <p>{reference.evidence.snippet}</p>}
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}
      </div>
      {onFollowUp && followUpQuestions.length > 0 && (
        <section className="rag-answer-card__followups" aria-label="후속 질문">
          <p>추가로 확인할 수 있어요</p>
          <div className="rag-answer-card__chips">
            {followUpQuestions.map((question) => (
              <button key={question} type="button" onClick={() => onFollowUp(question)}>
                {question}
              </button>
            ))}
          </div>
        </section>
      )}
      {sources.length > 0 && (
        <section className="rag-answer-card__source-strip" aria-label="출처">
          <p>출처</p>
          <div>
            {sources.map((item) => (
              <span key={item.evidence_id} title={item.snippet || undefined}>
                <FileText size={14} aria-hidden="true" />
                <b>{item.document_name || '근거 문서'}</b>
                {item.section && <small>{item.section}</small>}
              </span>
            ))}
          </div>
        </section>
      )}
      {pdfLinks.length > 0 && (
        <nav className="rag-answer-card__sources" aria-label="근거 문서">
          {pdfLinks.map((item) => (
            <a key={item.url} href={item.url} target="_blank" rel="noreferrer noopener">
              PDF 원문 보기 · {item.label}
            </a>
          ))}
        </nav>
      )}
    </article>
  );
}
