/** 보고서 정의 검색·상태 필터·생성·열기 진입점을 제공하는 목록 모듈이다. */
import { memo } from "react";
import {
  AlertTriangle,
  ChevronRight,
  FilePlus2,
  Inbox,
  LoaderCircle,
  RotateCcw,
  Search,
  ShieldAlert,
} from "lucide-react";

import { formatSeoulTime, reportStatusLabel } from "../reportPageLabels";

/** 서버 정의 목록과 생성 폼을 렌더링하며 pending 중 교차 open/create 경합을 차단한다. */
export const ReportListView = memo(function ReportListView({
  createOpen,
  definitionState,
  error,
  errorRef,
  newContent,
  newTitle,
  onCreate,
  onEdit,
  onOpen,
  onRefresh,
  pending,
  query,
  setCreateOpen,
  setNewContent,
  setNewTitle,
  setQuery,
  setStatusFilter,
  statusFilter,
  visibleDefinitions,
}) {
  return (
    <div className="page-content enterprise-reports-list">
      <div className={`legacy-report-toolbar ${definitionState === "empty" ? "is-empty" : ""}`}>
        <button type="button" className="primary" aria-expanded={createOpen} onClick={() => setCreateOpen(!createOpen)}>
          <FilePlus2 size={15} />새 보고서
        </button>
        {definitionState === "ready" && <>
          <label className="report-search"><Search size={15} aria-hidden="true" /><span className="sr-only">보고서 검색</span><input aria-label="보고서 검색" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="보고서 제목으로 검색" /></label>
          <label><span>상태</span><select aria-label="보고서 상태" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">전체</option><option value="draft">초안</option><option value="approved">확정</option></select></label>
        </>}
        <button type="button" className="report-refresh" onClick={onRefresh} disabled={Boolean(pending)}><RotateCcw size={14} />새로고침</button>
      </div>
      {createOpen && <section className="report-create-shell">
        <form className="report-create-form" onSubmit={onCreate} aria-busy={pending === "create"}>
          <header><div><small>새 초안</small><h2>보고서 작성을 시작하세요</h2><p>제목만 입력해도 편집기로 바로 이동합니다.</p></div><button type="button" onClick={() => setCreateOpen(false)} disabled={Boolean(pending)}>닫기</button></header>
          <label><span>보고서 제목</span><input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="보고서 제목을 입력하세요." autoFocus required /></label>
          <label><span>첫 문단 <small>선택</small></span><textarea value={newContent} onChange={(event) => setNewContent(event.target.value)} placeholder="지금 작성하거나 편집기에서 나중에 입력할 수 있습니다." /></label>
          <footer><button type="button" onClick={() => setCreateOpen(false)} disabled={Boolean(pending)}>취소</button><button className="primary" disabled={Boolean(pending) || !newTitle.trim()}>{pending === "create" ? <LoaderCircle size={14} /> : <FilePlus2 size={14} />}{pending === "create" ? "만드는 중" : "편집 시작"}</button></footer>
        </form>
      </section>}
      {error && <p ref={errorRef} tabIndex={-1} className="report-api-state error" role="alert">{/^40[13]/.test(error) ? <ShieldAlert size={17} /> : <AlertTriangle size={17} />}{error}</p>}
      {definitionState === "loading" && <p className="report-api-state"><LoaderCircle size={17} />보고서를 불러오는 중입니다.</p>}
      {definitionState === "empty" && !createOpen && <section className="report-empty-state"><span><FilePlus2 size={24} /></span><small>첫 보고서</small><h2>아직 작성한 보고서가 없습니다</h2><p>새 초안을 만들면 서버에 저장되고 편집 화면으로 바로 이동합니다.</p><button type="button" className="primary" onClick={() => setCreateOpen(true)}><FilePlus2 size={15} />첫 보고서 만들기</button></section>}
      {definitionState === "error" && <p className="report-api-state error"><ShieldAlert size={17} />보고서 목록을 불러오지 못했습니다.</p>}
      {definitionState === "ready" && <section className="card legacy-report-list"><div className="legacy-report-row legacy-report-head"><span>상태</span><span>버전·제목</span><span>구성</span><span>최근 변경</span><span>동작</span></div>{visibleDefinitions.map((definition) => <article className="legacy-report-row" key={`${definition.definitionId}-${definition.version}`}><strong>{reportStatusLabel(definition.status)}</strong><b>v{definition.version}<small>{definition.title}</small></b><span>{definition.blocks.length}개 블록</span><span>{definition.approvedAt ? formatSeoulTime(definition.approvedAt) : "편집 중"}</span><nav className="legacy-report-actions" aria-label={`${definition.title} 동작`}><button className="edit" disabled={Boolean(pending)} onClick={() => onEdit(definition)}>{definition.status === "approved" ? "새 버전으로 편집" : "편집"}</button><button className="view" disabled={Boolean(pending)} onClick={() => onOpen(definition)}>열람 <ChevronRight size={13} /></button></nav></article>)}</section>}
      {definitionState === "ready" && !visibleDefinitions.length && <p className="report-api-state"><Inbox size={17} />검색 조건에 맞는 보고서가 없습니다.</p>}
      {definitionState === "ready" && <p className="legacy-report-guide">초안은 자유롭게 배치하고 서버에 저장할 수 있습니다. 확정본 편집 시 새 버전 초안이 생성됩니다.</p>}
    </div>
  );
});
