/** 서버가 현재 역할에 승인한 문서만 내부 문서 검색의 시작 화면에 표시한다. */
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
                <span>{document.document_type} · {document.version} · {document.owner_team}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
