/** 분석 실행 Artifact의 사용자별 비파괴 보관함을 작은 목록 제어로 제공한다. */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Archive, ArchiveRestore, LoaderCircle, MoreHorizontal } from "lucide-react";

const RUN_LIMIT = 20;

function runStatusLabel(status) {
  return {
    RECEIVED: "대기 중",
    CLARIFYING: "입력 필요",
    SUCCEEDED: "완료",
    PARTIAL: "일부 완료",
    FAILED: "실패",
    BLOCKED: "차단됨",
    CANCELLED: "취소됨",
  }[status] || "확인 필요";
}

function runTime(value) {
  if (!value) return "시간 정보 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "시간 정보 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul",
  }).format(date);
}

/** 활성 목록과 보관함은 서버 projection을 각각 조회해 보관 직후의 stale 결과를 폐기한다. */
export function AnalysisArtifactCollection({ analysisClient }) {
  const [collection, setCollection] = useState("active");
  const [state, setState] = useState("loading");
  const [runs, setRuns] = useState([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");
  const [lifecycleDialog, setLifecycleDialog] = useState(null);
  const collectionRef = useRef(collection);
  const loadRequestRef = useRef(0);
  const lifecycleRequestRef = useRef(0);
  const dialogRef = useRef(null);
  const dialogCancelRef = useRef(null);

  const archived = collection === "archived";
  const loadRuns = useCallback(async (nextCollection) => {
    const request = ++loadRequestRef.current;
    setState("loading");
    setError("");
    try {
      const items = await analysisClient.listRuns({
        limit: RUN_LIMIT,
        approvedOnly: true,
        archived: nextCollection === "archived",
      });
      if (loadRequestRef.current !== request) return false;
      setRuns(items);
      setState(items.length ? "ready" : "empty");
      return true;
    } catch (cause) {
      if (loadRequestRef.current !== request) return false;
      setRuns([]);
      setState("error");
      setError(cause instanceof Error ? cause.message : "분석 결과를 불러오지 못했습니다.");
      return false;
    }
  }, [analysisClient]);

  useEffect(() => {
    collectionRef.current = collection;
    void loadRuns(collection);
    return () => { loadRequestRef.current += 1; };
  }, [collection, loadRuns]);

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

  useEffect(() => () => {
    loadRequestRef.current += 1;
    lifecycleRequestRef.current += 1;
  }, []);

  const chooseCollection = (nextCollection) => {
    if (pending || nextCollection === collection) return;
    setCollection(nextCollection);
  };

  const requestLifecycleChange = (run, action, event) => {
    const trigger = event.currentTarget.closest("details")?.querySelector("summary");
    event.currentTarget.closest("details")?.removeAttribute("open");
    setError("");
    setLifecycleDialog({ run, action, trigger });
  };

  const confirmLifecycleChange = async (event) => {
    event.preventDefault();
    if (!lifecycleDialog || pending) return;
    const { action, run } = lifecycleDialog;
    if (!run.artifact_id) return;
    const request = ++lifecycleRequestRef.current;
    const operation = `${action}:${run.artifact_id}`;
    setPending(operation);
    setError("");
    try {
      const receipt = action === "archive"
        ? await analysisClient.archiveArtifact(run.artifact_id)
        : await analysisClient.restoreArtifact(run.artifact_id);
      if (lifecycleRequestRef.current !== request) return;
      if (receipt.artifact_id !== run.artifact_id || receipt.archived !== (action === "archive")) {
        throw new Error("분석 Artifact 보관 상태를 확인할 수 없습니다.");
      }
      const refreshed = await loadRuns(collectionRef.current);
      if (lifecycleRequestRef.current !== request || !refreshed) return;
      setLifecycleDialog(null);
    } catch (cause) {
      if (lifecycleRequestRef.current !== request) return;
      setError(cause instanceof Error ? cause.message : "분석 Artifact 상태를 변경하지 못했습니다.");
    } finally {
      if (lifecycleRequestRef.current === request) setPending("");
    }
  };

  const pendingDialog = Boolean(pending);
  return <section className="analysis-artifact-collection" aria-labelledby="analysis-artifact-collection-title">
    <div className="analysis-artifact-collection-heading">
      <p id="analysis-artifact-collection-title">분석 결과</p>
      <button type="button" className="analysis-artifact-refresh" onClick={() => void loadRuns(collection)} disabled={pendingDialog || state === "loading"}>새로고침</button>
    </div>
    <nav className="analysis-artifact-tabs" aria-label="분석 결과 목록">
      <button type="button" aria-current={!archived ? "page" : undefined} disabled={pendingDialog} onClick={() => chooseCollection("active")}>활성</button>
      <button type="button" aria-current={archived ? "page" : undefined} disabled={pendingDialog} onClick={() => chooseCollection("archived")}>보관함</button>
    </nav>
    {state === "loading" && <p className="analysis-artifact-state"><LoaderCircle className="spin" size={14} />불러오는 중</p>}
    {state === "error" && <p className="analysis-artifact-state error" role="alert"><AlertTriangle size={14} />{error}</p>}
    {state === "empty" && <p className="analysis-artifact-empty">{archived ? "보관한 분석 결과가 없습니다." : "표시할 분석 결과가 없습니다."}</p>}
    {state === "ready" && <ul className="analysis-artifact-run-list">
      {runs.map((run) => {
        const action = archived ? "restore" : "archive";
        const actionPending = pending === `${action}:${run.artifact_id}`;
        return <li key={run.request_id} aria-busy={actionPending}>
          <div>
            <strong>{run.question}</strong>
            <small>{runStatusLabel(run.status)} · {runTime(run.completed_at || run.started_at)}</small>
            {archived && run.artifact_archived_at && <small>보관됨 · {runTime(run.artifact_archived_at)}</small>}
          </div>
          {run.artifact_id && <details className="analysis-artifact-row-menu" inert={pendingDialog || undefined}>
            <summary aria-label={`${run.question} 더보기`} aria-haspopup="menu"><MoreHorizontal size={16} aria-hidden="true" /></summary>
            <div role="menu">
              <button type="button" role="menuitem" disabled={pendingDialog} onClick={(event) => requestLifecycleChange(run, action, event)}>
                {actionPending ? <LoaderCircle className="spin" size={14} /> : archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
                {actionPending ? archived ? "복원 중" : "보관 중" : archived ? "복원" : "보관"}
              </button>
            </div>
          </details>}
        </li>;
      })}
    </ul>}
    <p className="analysis-artifact-guide">보관은 영구 삭제가 아닙니다. 기존 보고서는 계속 열람할 수 있지만, 보관한 결과는 새 보고서와 Assistant의 분석 원본에서 제외됩니다.</p>
    {lifecycleDialog && <dialog
      ref={dialogRef}
      className="app-lifecycle-dialog"
      aria-labelledby="analysis-artifact-lifecycle-dialog-title"
      onCancel={(event) => {
        if (pendingDialog) event.preventDefault();
        else setLifecycleDialog(null);
      }}
    >
      <form onSubmit={confirmLifecycleChange}>
        <span className="app-lifecycle-dialog-icon">{lifecycleDialog.action === "archive" ? <Archive size={19} /> : <ArchiveRestore size={19} />}</span>
        <div><small>{lifecycleDialog.action === "archive" ? "분석 결과 보관" : "분석 결과 복원"}</small><h2 id="analysis-artifact-lifecycle-dialog-title">{lifecycleDialog.action === "archive" ? "이 분석 결과를 보관할까요?" : "이 분석 결과를 복원할까요?"}</h2><p><b>“{lifecycleDialog.run.question}”</b>{lifecycleDialog.action === "archive" ? "은 영구 삭제되지 않으며 기존 보고서 열람에는 영향을 주지 않습니다. 다만 새 보고서와 Assistant 분석 원본에서는 제외됩니다." : "이 활성 분석 결과 목록으로 돌아가 새 보고서와 Assistant 분석 원본에 다시 사용할 수 있습니다."}</p></div>
        {error && <p className="app-lifecycle-dialog-error" role="alert"><AlertTriangle size={15} />{error}</p>}
        <footer><button ref={dialogCancelRef} type="button" onClick={() => setLifecycleDialog(null)} disabled={pendingDialog}>취소</button><button type="submit" className="primary" disabled={pendingDialog}>{pendingDialog ? <LoaderCircle className="spin" size={14} /> : lifecycleDialog.action === "archive" ? <Archive size={14} /> : <ArchiveRestore size={14} />}{pendingDialog ? lifecycleDialog.action === "archive" ? "보관 중" : "복원 중" : lifecycleDialog.action === "archive" ? "보관" : "복원"}</button></footer>
      </form>
    </dialog>}
  </section>;
}
