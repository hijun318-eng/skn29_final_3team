/** 보고서 활성·보관 목록과 안전한 lifecycle 동작을 제공하는 목록 모듈이다. */
import { memo, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArchiveRestore,
  ChevronRight,
  FilePlus2,
  Inbox,
  LoaderCircle,
  MoreHorizontal,
  RotateCcw,
  Search,
  ShieldAlert,
} from "lucide-react";

import { formatSeoulTime, reportStatusLabel } from "../reportPageLabels";

/** 서버 정의 목록과 보관 lifecycle을 렌더링하며 pending 중 교차 명령을 차단한다. */
export const ReportListView = memo(function ReportListView({
  createOpen,
  definitionCollection,
  definitionState,
  error,
  errorRef,
  newContent,
  newTitle,
  notice,
  onArchive,
  onCollectionChange,
  onCreate,
  onEdit,
  onOpen,
  onRefresh,
  onRestore,
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
  const archived = definitionCollection === "archived";
  const [lifecycleDialog, setLifecycleDialog] = useState(null);
  const dialogRef = useRef(null);
  const dialogCancelRef = useRef(null);

  useEffect(() => {
    if (!lifecycleDialog) return undefined;
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    const frame = window.requestAnimationFrame(() => dialogCancelRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      if (dialog?.open) dialog.close();
      window.requestAnimationFrame(() => lifecycleDialog.trigger?.focus?.());
    };
  }, [lifecycleDialog]);

  const requestLifecycleChange = (definition, action, event) => {
    const trigger = event.currentTarget.closest("details")?.querySelector("summary");
    event.currentTarget.closest("details")?.removeAttribute("open");
    setLifecycleDialog({ definition, action, trigger });
  };
  const confirmLifecycleChange = async (event) => {
    event.preventDefault();
    if (!lifecycleDialog) return;
    const { action, definition } = lifecycleDialog;
    const result = action === "archive"
      ? await onArchive(definition.definitionId)
      : await onRestore(definition.definitionId);
    if (result) setLifecycleDialog(null);
  };

  return (
    <div className="page-content enterprise-reports-list">
      <nav className="report-collection-tabs" aria-label="보고서 목록">
        <button type="button" aria-current={!archived ? "page" : undefined} disabled={Boolean(pending)} onClick={() => onCollectionChange("active")}>활성 보고서</button>
        <button type="button" aria-current={archived ? "page" : undefined} disabled={Boolean(pending)} onClick={() => onCollectionChange("archived")}><Archive size={14} aria-hidden="true" />보관함</button>
      </nav>
      <div className={`legacy-report-toolbar ${definitionState === "empty" ? "is-empty" : ""} ${archived ? "is-archived" : ""}`}>
        {!archived && <button type="button" className="primary" aria-expanded={createOpen} onClick={() => setCreateOpen(!createOpen)}>
          <FilePlus2 size={15} />새 보고서
        </button>}
        {definitionState === "ready" && <>
          <label className="report-search"><Search size={15} aria-hidden="true" /><span className="sr-only">보고서 검색</span><input aria-label="보고서 검색" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="보고서 제목으로 검색" /></label>
          <label><span>상태</span><select aria-label="보고서 상태" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">전체</option><option value="draft">초안</option><option value="approved">확정</option></select></label>
        </>}
        <button type="button" className="report-refresh" onClick={onRefresh} disabled={Boolean(pending)}><RotateCcw size={14} />새로고침</button>
      </div>
      {!archived && createOpen && <section className="report-create-shell">
        <form className="report-create-form" onSubmit={onCreate} aria-busy={pending === "create"}>
          <header><div><small>새 초안</small><h2>보고서 작성을 시작하세요</h2><p>제목만 입력해도 편집기로 바로 이동합니다.</p></div><button type="button" onClick={() => setCreateOpen(false)} disabled={Boolean(pending)}>닫기</button></header>
          <label><span>보고서 제목</span><input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="보고서 제목을 입력하세요." autoFocus required /></label>
          <label><span>첫 문단 <small>선택</small></span><textarea value={newContent} onChange={(event) => setNewContent(event.target.value)} placeholder="지금 작성하거나 편집기에서 나중에 입력할 수 있습니다." /></label>
          <footer><button type="button" onClick={() => setCreateOpen(false)} disabled={Boolean(pending)}>취소</button><button className="primary" disabled={Boolean(pending) || !newTitle.trim()}>{pending === "create" ? <LoaderCircle className="spin" size={14} /> : <FilePlus2 size={14} />}{pending === "create" ? "만드는 중" : "편집 시작"}</button></footer>
        </form>
      </section>}
      {error && <p ref={errorRef} tabIndex={-1} className="report-api-state error" role="alert">{/^40[13]/.test(error) ? <ShieldAlert size={17} /> : <AlertTriangle size={17} />}{error}</p>}
      {notice && <p className="report-api-state notion-editor-notice" role="status">{archived ? <ArchiveRestore size={17} /> : <Archive size={17} />}{notice}</p>}
      {definitionState === "loading" && <p className="report-api-state"><LoaderCircle className="spin" size={17} />{archived ? "보관한 보고서를 불러오는 중입니다." : "보고서를 불러오는 중입니다."}</p>}
      {definitionState === "empty" && !createOpen && <section className="report-empty-state"><span>{archived ? <Archive size={24} /> : <FilePlus2 size={24} />}</span><small>{archived ? "보관함" : "첫 보고서"}</small><h2>{archived ? "보관한 보고서가 없습니다" : "아직 작성한 보고서가 없습니다"}</h2><p>{archived ? "더 이상 사용하지 않는 보고서를 보관하면 여기에서 확정본을 열람하거나 복원할 수 있습니다." : "새 초안을 만들면 서버에 저장되고 편집 화면으로 바로 이동합니다."}</p>{!archived && <button type="button" className="primary" onClick={() => setCreateOpen(true)}><FilePlus2 size={15} />첫 보고서 만들기</button>}</section>}
      {definitionState === "error" && <p className="report-api-state error"><ShieldAlert size={17} />{archived ? "보관함을 불러오지 못했습니다." : "보고서 목록을 불러오지 못했습니다."}</p>}
      {definitionState === "ready" && <section className="card legacy-report-list"><div className="legacy-report-row legacy-report-head"><span>상태</span><span>버전·제목</span><span>구성</span><span>{archived ? "보관 시각" : "최근 변경"}</span><span>동작</span></div>{visibleDefinitions.map((definition) => {
        const actionPending = pending === `${archived ? "restore" : "archive"}:${definition.definitionId}`;
        const canOpenArchived = !archived || definition.status === "approved";
        return <article className="legacy-report-row" aria-busy={actionPending} key={`${definition.definitionId}-${definition.version}`}>
          <strong>{reportStatusLabel(definition.status)}</strong>
          <b>v{definition.version}<small>{definition.title}</small></b>
          <span>{definition.blocks.length}개 블록</span>
          <span>{archived && definition.archivedAt ? formatSeoulTime(definition.archivedAt) : definition.approvedAt ? formatSeoulTime(definition.approvedAt) : "편집 중"}</span>
          <nav className="legacy-report-actions" aria-label={`${definition.title} 동작`}>
            {!archived && <button className="edit" disabled={Boolean(pending)} onClick={() => onEdit(definition)}>{definition.status === "approved" ? "새 버전으로 편집" : "편집"}</button>}
            <button className="view" disabled={Boolean(pending) || !canOpenArchived} title={!canOpenArchived ? "보관된 초안은 복원 후 확인할 수 있습니다." : undefined} onClick={() => onOpen(definition)}>{canOpenArchived ? <>열람 <ChevronRight size={13} /></> : "확정본 없음"}</button>
            <details className="report-row-menu" inert={Boolean(pending) || undefined}>
              <summary aria-label={`${definition.title} 더보기`} aria-haspopup="menu"><MoreHorizontal size={16} aria-hidden="true" /></summary>
              <div role="menu">
                <button type="button" role="menuitem" disabled={Boolean(pending)} onClick={(event) => requestLifecycleChange(definition, archived ? "restore" : "archive", event)}>
                  {actionPending ? <LoaderCircle className="spin" size={14} /> : archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
                  {actionPending ? archived ? "복원 중" : "보관 중" : archived ? "복원" : "보관"}
                </button>
              </div>
            </details>
          </nav>
        </article>;
      })}</section>}
      {definitionState === "ready" && !visibleDefinitions.length && <p className="report-api-state"><Inbox size={17} />검색 조건에 맞는 보고서가 없습니다.</p>}
      {definitionState === "ready" && <p className="legacy-report-guide">{archived ? "보관한 보고서는 확정 문서만 읽을 수 있습니다. 다시 편집하려면 3점 메뉴에서 복원해 주세요." : "초안은 자유롭게 배치하고 서버에 저장할 수 있습니다. 확정본 편집 시 새 버전 초안이 생성됩니다."}</p>}
      {lifecycleDialog && <dialog
        ref={dialogRef}
        className="report-lifecycle-dialog"
        aria-labelledby="report-lifecycle-dialog-title"
        onCancel={(event) => {
          if (pending) event.preventDefault();
          else setLifecycleDialog(null);
        }}
      >
        <form onSubmit={confirmLifecycleChange}>
          <span className="report-lifecycle-dialog-icon">{lifecycleDialog.action === "archive" ? <Archive size={19} /> : <ArchiveRestore size={19} />}</span>
          <div><small>{lifecycleDialog.action === "archive" ? "보고서 보관" : "보고서 복원"}</small><h2 id="report-lifecycle-dialog-title">{lifecycleDialog.action === "archive" ? "이 보고서를 보관할까요?" : "이 보고서를 복원할까요?"}</h2><p><b>“{lifecycleDialog.definition.title}”</b>{lifecycleDialog.action === "archive" ? "의 모든 버전이 보관함으로 이동합니다. 예약은 중지되며 복원 전에는 편집하거나 실행할 수 없습니다." : "가 활성 목록으로 돌아갑니다. 보관할 때 중지된 예약은 자동으로 다시 켜지지 않습니다."}</p></div>
          {error && <p className="report-lifecycle-dialog-error" role="alert"><AlertTriangle size={15} />{error}</p>}
          <footer><button ref={dialogCancelRef} type="button" onClick={() => setLifecycleDialog(null)} disabled={Boolean(pending)}>취소</button><button type="submit" className="primary" disabled={Boolean(pending)}>{pending ? <LoaderCircle className="spin" size={14} /> : lifecycleDialog.action === "archive" ? <Archive size={14} /> : <ArchiveRestore size={14} />}{pending ? lifecycleDialog.action === "archive" ? "보관 중" : "복원 중" : lifecycleDialog.action === "archive" ? "보관" : "복원"}</button></footer>
        </form>
      </dialog>}
    </div>
  );
});
