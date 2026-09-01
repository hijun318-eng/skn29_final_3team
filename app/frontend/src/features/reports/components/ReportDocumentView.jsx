/** 승인 미리보기와 최종 asset 준비 상태를 분리해 표시하는 문서 화면 모듈이다. */
import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  Check,
  Download,
  Expand,
  ExternalLink,
  Eye,
  LoaderCircle,
  LockKeyhole,
  Maximize2,
  Minimize2,
  RotateCcw,
  Send,
  Shrink,
} from "lucide-react";

import { ReportPageCanvas } from "../ReportPageCanvas";
import { formatSeoulTime, reportStatusLabel } from "../reportPageLabels";

/** 승인 미리보기와 최종문서 상태를 표시하며 pending 동안 충돌 명령을 잠그는 memo 화면이다. */
export const ReportDocumentView = memo(function ReportDocumentView({
  currencyControl,
  error,
  errorRef,
  finalDocument,
  finalDocumentState,
  isAdmin,
  isDirty,
  notice,
  onApprove,
  onLeave,
  onOpenFinalAsset,
  onReloadFinalDocument,
  onReturnToEditor,
  onRun,
  orientation,
  pages,
  pending,
  presentation,
  renderBlock,
  renderFooter,
  renderHeader,
  reportBlockCount,
  selectedDefinition,
}) {
  const approved = selectedDefinition.status === "approved";
  const archived = Boolean(selectedDefinition.archivedAt);
  const rootRef = useRef(null);
  const [fullscreen, setFullscreen] = useState(false);
  const fullscreenSupported = typeof document !== "undefined" && Boolean(document.fullscreenEnabled);

  useEffect(() => {
    const syncFullscreen = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  const toggleFullscreen = useCallback(async () => {
    if (!fullscreenSupported || !rootRef.current) return;
    try {
      if (document.fullscreenElement === rootRef.current) await document.exitFullscreen();
      else await rootRef.current.requestFullscreen();
    } catch {
      setFullscreen(false);
    }
  }, [fullscreenSupported]);

  return (
    <div ref={rootRef} className="page-content legacy-report-document generated-preview" data-report-render-root="screen-preview">
      <div className="legacy-document-actions">
        <button className="secondary" onClick={onLeave} disabled={Boolean(pending)}><ArrowLeft size={14} />보고서 목록</button>
        <div>{currencyControl}<div className="report-orientation-switch" role="group" aria-label="읽기 전용 A4 용지 방향"><button type="button" aria-pressed={orientation === "landscape"} disabled><Maximize2 size={14} />가로</button><button type="button" aria-pressed={orientation === "portrait"} disabled><Minimize2 size={14} />세로</button></div>{presentation}{fullscreenSupported && <button type="button" onClick={toggleFullscreen} aria-pressed={fullscreen}>{fullscreen ? <Shrink size={14} /> : <Expand size={14} />}{fullscreen ? "축소" : "전체화면"}</button>}{!archived && <button onClick={onReturnToEditor} disabled={Boolean(pending)}><ArrowLeft size={14} />{approved ? "새 버전으로 편집" : "편집으로 돌아가기"}</button>}{!archived && isAdmin && approved && <button onClick={onRun} disabled={Boolean(pending)}><Send size={14} />최신 데이터로 다시 생성</button>}</div>
      </div>
      {error && <p ref={errorRef} tabIndex={-1} className="report-api-state report-notice-shell error" role="alert"><AlertTriangle size={17} />{error}</p>}
      {notice && <p className="report-api-state report-notice-shell notion-editor-notice" role="status"><Check size={17} />{notice}</p>}
      {archived && <section className="report-archive-readonly" role="status"><Archive size={17} aria-hidden="true" /><div><b>보관된 보고서 · 읽기 전용</b><span>확정 문서는 계속 열람할 수 있습니다. 변경하거나 다시 실행하려면 목록에서 먼저 복원해 주세요.</span></div></section>}
      {!approved ? <section className="report-finalization-panel" aria-labelledby="report-finalization-title">
        <div className="report-finalization-copy"><span><Eye size={18} aria-hidden="true" /></span><div><small>확정 전 검토</small><h2 id="report-finalization-title">보고서 내용을 확인하세요</h2><p>내용과 용지를 확인한 뒤 보고서를 확정할 수 있습니다.</p></div></div>
        <div className="report-finalization-action">
          {isDirty ? <p className="report-finalization-blocker" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>저장되지 않은 변경이 있습니다. 편집 화면에서 저장한 뒤 확정해 주세요.</span></p> : <p><LockKeyhole size={15} aria-hidden="true" /><span>확정하면 버전 {selectedDefinition.version}은 수정할 수 없으며 PDF가 함께 생성됩니다.</span></p>}
          {archived ? <small>보관된 초안은 복원한 뒤 확정할 수 있습니다.</small> : isAdmin ? <button type="button" className="primary" onClick={onApprove} disabled={Boolean(pending) || isDirty}>{pending === "approve" ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <LockKeyhole size={15} aria-hidden="true" />}{pending === "approve" ? "확정 중" : "보고서 확정"}</button> : <small>보고서 확정은 관리자에게 요청해 주세요.</small>}
        </div>
      </section> : <section className="report-finalization-panel is-final" aria-labelledby="report-final-title" aria-busy={finalDocumentState === "loading"}>
        <div className="report-finalization-copy"><span><LockKeyhole size={18} aria-hidden="true" /></span><div><small>확정됨</small><h2 id="report-final-title">확정된 보고서입니다</h2><p>수정하려면 새 버전을 만드세요.</p></div></div>
        {finalDocumentState === "loading" && <p className="report-finalization-loading" role="status"><LoaderCircle className="spin" size={15} aria-hidden="true" />확정 문서 정보를 확인하는 중입니다.</p>}
        {finalDocumentState === "missing" && <p className="report-finalization-blocker" role="status"><AlertTriangle size={16} aria-hidden="true" /><span>이전 형식의 확정본이라 PDF 파일을 열 수 없습니다.</span></p>}
        {finalDocumentState === "error" && <button type="button" onClick={onReloadFinalDocument} disabled={Boolean(pending)}><RotateCcw size={14} aria-hidden="true" />문서 정보 다시 불러오기</button>}
        {finalDocumentState === "ready" && finalDocument && <div className="report-finalization-result"><dl><div><dt>확정 시각</dt><dd>{formatSeoulTime(finalDocument.confirmedAt)}</dd></div><div><dt>용지</dt><dd>A4 {finalDocument.orientation === "landscape" ? "가로" : "세로"}</dd></div><div><dt>포함된 분석 결과</dt><dd>{finalDocument.artifactVersions.length}개</dd></div></dl><nav aria-label="확정 문서 동작"><button type="button" onClick={() => onOpenFinalAsset("html", false)} disabled={Boolean(pending)}><ExternalLink size={14} aria-hidden="true" />웹 문서 열기</button><button type="button" className="primary" onClick={() => onOpenFinalAsset("pdf", false)} disabled={Boolean(pending)}><ExternalLink size={14} aria-hidden="true" />PDF 새 탭에서 열기</button><button type="button" onClick={() => onOpenFinalAsset("pdf", true)} disabled={Boolean(pending)}><Download size={14} aria-hidden="true" />PDF 다운로드</button></nav></div>}
      </section>}
      <section className="report-preview-meta-strip" aria-label="보고서 미리보기 정보"><b>{approved ? "확정 보고서" : "보고서 미리보기"}</b><span>{archived ? "보관 · " : ""}{reportStatusLabel(selectedDefinition.status)} · 버전 {selectedDefinition.version}</span><span>{reportBlockCount}개 블록</span><span>A4 {orientation === "landscape" ? "가로" : "세로"}</span>{selectedDefinition.approvedAt && <span>{formatSeoulTime(selectedDefinition.approvedAt)} 확정</span>}</section>
      <ReportPageCanvas className="report-screen-render-root" pages={pages} orientation={orientation} mode="preview" ariaLabel={`${selectedDefinition.title} A4 미리보기`} renderHeader={renderHeader} renderFooter={renderFooter} renderBlock={renderBlock} />
    </div>
  );
});
