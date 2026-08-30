/** 서버가 현재 역할에 승인한 문서만 내부 문서 검색의 시작 화면에 표시한다. */
const DOCUMENT_TYPE_LABELS = Object.freeze({
  GUIDE: "업무 안내서",
  MANUAL: "업무 매뉴얼",
  OPERATIONS_MANUAL: "운영 매뉴얼",
  POLICY: "정책 문서",
  PROCEDURE: "업무 절차서",
  REGULATION: "업무 규정",
});

/** 서버 문서 유형을 원시 enum 대신 사용자에게 읽기 쉬운 한국어 명칭으로 변환한다. */
export function ragDocumentTypeLabel(value) {
  const normalized = typeof value === "string" ? value.trim().toUpperCase() : "";
  return DOCUMENT_TYPE_LABELS[normalized] || "내부 문서";
}

function documentMeta(document) {
  return [
    ragDocumentTypeLabel(document?.document_type),
    document?.version,
    document?.owner_team,
  ].filter((value) => typeof value === "string" && value.trim()).join(" · ");
}

/** 현재 역할에 승인된 내부 문서를 한국어 메타데이터와 함께 안내한다. */
export default function RagEmptyState({ documents = [], loading = false, error = "", onBack }) {
  return (
    <section className="chat-empty-state rag-empty-state">
      <small>내부 문서 검색</small>
      <h2>승인된 내부 문서를 확인하세요</h2>
      <p>이 화면에서 입력한 질문은 내부지침 검색으로 명시 전송됩니다.</p>
      <div className="rag-help-actions">
        {onBack && <button type="button" onClick={onBack}>데이터 분석으로 돌아가기</button>}
      </div>
      <div className="rag-help-panel" aria-live="polite">
        <strong>현재 역할로 열람 가능한 승인 문서</strong>
        {loading && <p role="status">문서 목록을 확인하고 있습니다.</p>}
        {!loading && error && <p role="alert">{error}</p>}
        {!loading && !error && documents.length === 0 && <p>열람 가능한 승인 문서가 없습니다.</p>}
        {!loading && !error && documents.length > 0 && (
          <ul className="rag-document-list">
            {documents.map((document) => (
              <li key={document.manual_id}>
                <strong>{document.title}</strong>
                <span>{documentMeta(document)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
