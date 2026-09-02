/** 책임: 인용 가능한 내부 문서 답변과 후속 질문·PDF 근거를 접근 가능한 카드로 표시한다. */
import { useEffect, useId, useState } from "react";
import { FileText, X } from "lucide-react";

import "./RagAnswerCard.css";

function normalizeAnswerText(text) {
  return String(text)
    .replace(/(\d[\d,.]*)\s*억원다\./g, '$1억 원입니다.')
    .replace(/(\d[\d,.]*)\s*억원/g, '$1억 원');
}

function getAnswerText(rag) {
  const text = rag?.answer_text || rag?.answer?.text || rag?.answer || rag?.body || '';
  const cleaned = String(text)
    .replace(/(?:현장\s*확인내용|객실\s*[·ㆍ]\s*설비)?\s*내부\s*업무지침\s*[·ㆍ]\s*현장\s*실행형\s*[·ㆍ]\s*의미전달\s*검증완료본/g, '')
    .replace(/^\s*자세한 내용은 PDF 원문 보기를 확인하세요\.\s*$/gm, '')
    .replace(/\[SECTION_BOUNDARY\s+[^\]]*\]/g, '')
    .replace(/^\s*[-*•]\s*$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  if (cleaned) return normalizeAnswerText(cleaned);
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

function evidenceItems(rag) {
  const items = Array.isArray(rag?.evidence_bundle) ? rag.evidence_bundle : [];
  return Array.from(new Map(items
    .filter((item) => item && typeof item.evidence_id === 'string' && item.evidence_id)
    .map((item) => [item.evidence_id, item])).values());
}

function documentSources(items) {
  return Array.from(new Map(items.map((item) => [
      [item.document_id, item.document_version].filter(Boolean).join(':') || item.evidence_id,
      item,
    ])).values());
}

function evidenceMetadataPoints(items) {
  const points = new Set();
  items.forEach((item) => {
    const documentName = String(item?.document_name || '').trim();
    if (documentName) {
      points.add(documentName);
      points.add(documentName.replace(/^\d{4}년\s*\d{1,2}월\s*/, '').trim());
    }
    String(item?.snippet || '').split('\n').forEach((line) => {
      const match = line.trim().match(/^\[PARAGRAPH style=(?:Title|Subtitle)\]\s*(.+)$/i);
      if (match?.[1]) points.add(match[1].trim());
    });
  });
  return points;
}

function answerContent(text) {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  const points = lines
    .filter((line) => /^[-*•]\s+/.test(line))
    .map((line) => line.replace(/^[-*•]\s+/, '').trim())
    .filter(Boolean);
  if (points.length && points.length === lines.length) {
    return { points, paragraphs: [] };
  }
  return { points: [], paragraphs: text.split(/\n\s*\n/).filter(Boolean) };
}

function focusTerms(question) {
  const ignored = new Set([
    '내부', '문서', '보고서', '알려줘', '보여줘', '내용', '결과', '전체', '가장',
    '어떻게', '무엇', '관련', '요약', '분석', '에서', '으로', '까지', '부터',
  ]);
  const suffixes = ['으로', '에서', '에게', '까지', '부터', '하고', '과', '와', '을', '를', '은', '는', '이', '가', '의'];
  return (String(question || '').toLowerCase().match(/[0-9a-z가-힣]{2,}/g) || [])
    .map((raw) => suffixes.reduce((term, suffix) => (
      term.endsWith(suffix) && term.length > suffix.length + 1
        ? term.slice(0, -suffix.length)
        : term
    ), raw))
    .filter((term) => !ignored.has(term) && !/^\d{1,4}(?:년|월|일)?$/.test(term));
}

function tableCells(point) {
  const cells = point.split('|').map((cell) => cell.trim()).filter(Boolean);
  return cells.length >= 2 ? cells : null;
}

function tablePresentation(points, question) {
  const terms = focusTerms(question);
  const candidates = [];
  for (let index = 0; index < points.length; index += 1) {
    const columns = tableCells(points[index]);
    if (!columns || columns.some((cell) => /\d/.test(cell))) continue;
    const rows = [];
    let cursor = index + 1;
    while (cursor < points.length) {
      const cells = tableCells(points[cursor]);
      if (!cells || cells.length !== columns.length) break;
      rows.push({ cells, pointIndex: cursor });
      cursor += 1;
    }
    if (!rows.length) continue;
    const searchable = [columns, ...rows.map((row) => row.cells)].flat().join(' ').toLowerCase();
    candidates.push({
      columns,
      rows,
      pointIndexes: new Set([index, ...rows.map((row) => row.pointIndex)]),
      score: terms.reduce((sum, term) => sum + (searchable.includes(term) ? 1 : 0), 0),
    });
  }
  return candidates.sort((left, right) => (
    right.score - left.score || right.rows.length - left.rows.length
  ))[0] || null;
}

function pointScore(point, terms) {
  const normalized = point.toLowerCase();
  const termScore = terms.reduce((sum, term) => sum + (normalized.includes(term) ? 10 : 0), 0);
  const quantified = /(?:%|\d[\d,.]*\s*(?:원|건|박|명|실))/.test(point) ? 2 : 0;
  const sentence = /[.!?다요]$/.test(point) ? 1 : 0;
  return termScore + quantified + sentence;
}

function answerPresentation(content, question, metadataPoints = new Set()) {
  if (!content.points.length) {
    return { lead: '', visiblePoints: [], detailPoints: [], table: null };
  }
  const table = tablePresentation(content.points, question);
  const tableIndexes = table?.pointIndexes || new Set();
  const candidates = content.points
    .map((point, index) => ({ point, index }))
    .filter(({ point, index }) => (
      !tableIndexes.has(index)
      && !metadataPoints.has(point)
      && !/^\d{4}년\s*\d{1,2}월\s*\|\s*[^|]+$/.test(point)
    ));
  const terms = focusTerms(question);
  const lead = [...candidates].sort((left, right) => (
    pointScore(right.point, terms) - pointScore(left.point, terms) || left.index - right.index
  ))[0] || null;
  const remaining = candidates.filter(({ index }) => index !== lead?.index).map(({ point }) => point);
  const visibleLimit = table ? 0 : 4;
  return {
    lead: lead?.point || '',
    visiblePoints: remaining.slice(0, visibleLimit),
    detailPoints: remaining.slice(visibleLimit),
    table,
  };
}

function emphasizedAnswerText(text) {
  return String(text).split(/(\d[\d,.]*\s*(?:억\s*원|만\s*원|천\s*원|%|건|박|명|실|일|개))/g)
    .filter(Boolean)
    .map((part, index) => /\d/.test(part) && /(?:억\s*원|만\s*원|천\s*원|%|건|박|명|실|일|개)$/.test(part)
      ? <strong className="rag-answer-card__metric" key={`${index}-${part}`}>{part}</strong>
      : part);
}

function sectionLabel(value) {
  return String(value || '').replace(/^\[DOCX\s+[^\]]+\]\s*/i, '').trim();
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
  return [item?.document_name, item?.document_version, sectionLabel(item?.section)]
    .filter((value) => typeof value === 'string' && value.trim())
    .join(' · ') || '근거 문서';
}

function sourceRows(sources, pdfLinks) {
  const matchedUrls = new Set();
  const rows = sources.map((source) => {
    const link = pdfLinks.find((item) => (
      (source.document_id && item.documentId === source.document_id)
      || item.label === source.document_name
    )) || (sources.length === 1 && pdfLinks.length === 1 ? pdfLinks[0] : null);
    if (link?.url) matchedUrls.add(link.url);
    return {
      key: source.evidence_id,
      label: source.document_name || '근거 문서',
      section: sectionLabel(source.section),
      snippet: source.snippet || '',
      url: link?.url || '',
    };
  });
  pdfLinks.forEach((link) => {
    if (!matchedUrls.has(link.url)) {
      rows.push({
        key: link.url,
        label: link.label || '근거 문서',
        section: '',
        snippet: '',
        url: link.url,
      });
    }
  });
  return rows;
}

/** RAG 답변을 비교형 본문, 후속 질문과 중복 제거된 PDF 링크로 렌더링한다. */
export function RagAnswerCard({ rag, pdfUrl = '', pdfSources = [], onFollowUp }) {
  const titleId = useId();
  const viewerTitleId = useId();
  const [viewerSource, setViewerSource] = useState(null);
  const answerText = getAnswerText(rag);
  const sourcePdfUrl = pdfUrl || getPdfUrl(rag);
  const pdfLinks = Array.from(new Map(
    [...pdfSources, ...(!pdfSources.length && sourcePdfUrl ? [{ label: rag?.document_name || '근거 문서', url: sourcePdfUrl }] : [])]
      .filter((item) => item.url)
      .map((item) => [item.url, item]),
  ).values());
  const comparison = compareContent(answerText, rag?.answer_type);
  const evidence = evidenceItems(rag);
  const content = comparison
    ? { points: [], paragraphs: comparison.prose }
    : answerContent(answerText);
  const presentation = answerPresentation(
    content,
    rag?.routing?.snapshot_question || rag?.routing?.context_question || '',
    evidenceMetadataPoints(evidence),
  );
  const sources = documentSources(evidence);
  const displayedSources = sourceRows(sources, pdfLinks);
  const citationRefs = citationReferences(rag, evidence);
  const responseStatus = String(rag?.status || rag?.response_status || '').toUpperCase();
  const isTerminalFailure = ['NO_EVIDENCE', 'ERROR', 'FAILED', 'GENERATION_FAILED'].includes(responseStatus);
  const candidateFollowUps = rag?.status === 'NEEDS_CLARIFICATION'
    ? rag?.clarification_options
    : rag?.follow_up_questions;
  const followUpQuestions = isTerminalFailure || !Array.isArray(candidateFollowUps)
    ? []
    : candidateFollowUps.filter((question) => typeof question === 'string' && question.trim());

  useEffect(() => {
    if (!viewerSource) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setViewerSource(null);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [viewerSource]);

  return (
    <article aria-labelledby={titleId} className="rag-answer-card">
      <div id={titleId} className="rag-answer-card__label">핵심 답변</div>
      <div className="rag-answer-card__body">
        {presentation.lead && <p className="rag-answer-card__lead">{emphasizedAnswerText(presentation.lead)}</p>}
        {presentation.table && (
          <div className="rag-answer-card__table-wrap">
            <table>
              <caption className="sr-only">질문 관련 내부 문서 근거 표</caption>
              <thead>
                <tr>{presentation.table.columns.map((column, index) => <th key={`${index}-${column}`} scope="col">{column}</th>)}</tr>
              </thead>
              <tbody>
                {presentation.table.rows.map((row, rowIndex) => (
                  <tr key={`${rowIndex}-${row.cells.join('|')}`}>
                    {row.cells.map((cell, cellIndex) => (
                      cellIndex === 0
                        ? <th key={`${cellIndex}-${cell}`} scope="row">{cell}</th>
                        : <td key={`${cellIndex}-${cell}`}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {presentation.visiblePoints.length > 0 && (
          <section className="rag-answer-card__supporting">
            <h3>함께 볼 내용</h3>
            <ul className="rag-answer-card__points">
              {presentation.visiblePoints.map((point) => <li key={point}>{emphasizedAnswerText(point)}</li>)}
            </ul>
          </section>
        )}
        {presentation.detailPoints.length > 0 && (
          <details className="rag-answer-card__details">
            <summary>상세 근거 {presentation.detailPoints.length}건</summary>
            <ul>{presentation.detailPoints.map((point) => <li key={point}>{emphasizedAnswerText(point)}</li>)}</ul>
          </details>
        )}
        {content.paragraphs.map((paragraph, index) => (
          <p key={`${index}-${paragraph.slice(0, 20)}`}>
            {emphasizedAnswerText(paragraph)}
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
      {displayedSources.length > 0 && (
        <section className="rag-answer-card__source-strip" aria-label="출처">
          <p>출처</p>
          <div className="rag-answer-card__source-list">
            {displayedSources.map((item) => item.url ? (
              <button
                key={item.key}
                type="button"
                title={item.snippet || `${item.label} 뷰어 열기`}
                onClick={() => setViewerSource(item)}
              >
                <FileText size={14} aria-hidden="true" />
                <b>{item.label}</b>
                {item.section && <small>{item.section}</small>}
                <span>뷰어 열기</span>
              </button>
            ) : (
              <div key={item.key} title={item.snippet || undefined}>
                <FileText size={14} aria-hidden="true" />
                <b>{item.label}</b>
                {item.section && <small>{item.section}</small>}
              </div>
            ))}
          </div>
        </section>
      )}
      {viewerSource && (
        <div
          className="rag-document-viewer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setViewerSource(null);
          }}
        >
          <section role="dialog" aria-modal="true" aria-labelledby={viewerTitleId}>
            <header>
              <div>
                <small>근거 문서</small>
                <h2 id={viewerTitleId}>{viewerSource.label}</h2>
              </div>
              <button type="button" aria-label="문서 뷰어 닫기" onClick={() => setViewerSource(null)}>
                <X size={20} aria-hidden="true" />
              </button>
            </header>
            <iframe src={viewerSource.url} title={`${viewerSource.label} 문서 본문`} />
          </section>
        </div>
      )}
    </article>
  );
}
