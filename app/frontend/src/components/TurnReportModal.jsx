/**
 * 분석 결과 아티팩트를 공식 보고서 초안(Draft)으로 변환하는 모달 컴포넌트다.
 */
import React from "react";
import { Check, FileText, X } from "lucide-react";
import { AnalysisStatePanel } from "./analysis/AnalysisStatePanel";
import { analysisTitle } from "../utils/presentation";
import "./TurnReportModal.css";

/**
 * 보고서 초안 생성 및 미리보기 모달을 렌더링한다.
 * @param {object} props
 * @param {string} props.mode
 * @param {object} props.run
 * @param {string} props.viewType
 * @param {string} props.title
 * @param {Function} props.onTitleChange
 * @param {Function} props.onConfirm
 * @param {Function} props.onPreviewMode
 * @param {Function} props.onClose
 * @param {boolean} props.isSubmitting
 */
export function TurnReportModal({
  mode,
  run,
  viewType = "SUMMARY",
  title,
  onTitleChange,
  onConfirm,
  onPreviewMode,
  onClose,
  isSubmitting,
}) {
  const headingId = React.useId();
  const descriptionId = React.useId();
  const titleHelpId = React.useId();
  if (!mode || !run) return null;

  const metrics = Array.isArray(run.metrics) ? run.metrics : [];
  const rowCount = Array.isArray(run.table?.rows) ? run.table.rows.length : 0;
  const isTableView = String(viewType).toUpperCase() === "TABLE";
  const isDraft = mode === "draft";

  return (
    <div className="report-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className={isDraft ? "report-transfer-modal" : "report-transfer-modal report-transfer-modal--preview"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        aria-describedby={descriptionId}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="report-transfer-modal__header">
          <div className="report-transfer-modal__heading">
            <span className="report-transfer-modal__icon" aria-hidden="true"><FileText size={19} /></span>
            <div>
              <small>{isDraft ? "보고서 작성" : "분석 결과"}</small>
              <h2 id={headingId}>{isDraft ? "보고서 초안 구성" : "분석 결과 미리보기"}</h2>
              <p id={descriptionId}>{isDraft ? "선택한 분석 결과를 검토하고 보고서 편집용 초안으로 연결합니다." : "보고서로 옮기기 전에 분석 결과와 수치 근거를 확인합니다."}</p>
            </div>
          </div>
          <button type="button" className="report-transfer-modal__close" aria-label="닫기" onClick={onClose}><X size={18} /></button>
        </header>

        <div className={isDraft ? "report-transfer-modal__body" : "report-transfer-modal__body report-transfer-modal__body--preview"}>
          {isDraft ? (
            <>
              <label className="report-title-field">
                <span>보고서 제목 <em>필수</em></span>
                <input
                  value={title}
                  maxLength={120}
                  aria-describedby={titleHelpId}
                  onChange={(event) => onTitleChange(event.target.value)}
                />
                <small id={titleHelpId}>보고서 목록과 문서 상단에 표시되는 제목입니다.</small>
              </label>

              <section className="report-preview-summary" aria-label="선택한 분석 요약">
                <header>
                  <div>
                    <small>선택한 분석</small>
                    <h3>{analysisTitle(run)}</h3>
                  </div>
                  {isTableView && rowCount > 0
                    ? <span>{rowCount}개 행</span>
                    : metrics.length > 0 && <span>{metrics.length}개 지표</span>}
                </header>
                <div className="report-analysis-preview report-analysis-preview--selected-view">
                  <AnalysisStatePanel run={run} viewType={viewType} />
                </div>
              </section>
            </>
          ) : (
            <div className="report-analysis-preview">
              <AnalysisStatePanel run={run} />
            </div>
          )}
        </div>

        <footer className="report-transfer-modal__footer">
          <button type="button" className="report-transfer-modal__cancel" onClick={onClose}>취소</button>
          {isDraft ? (
            <button type="button" className="primary" aria-busy={isSubmitting} disabled={isSubmitting || !title.trim()} onClick={onConfirm}>
              <Check size={14} />{isSubmitting ? "생성 중..." : "초안 만들기"}
            </button>
          ) : (
            <button type="button" className="primary" onClick={onPreviewMode}>
              보고서 초안 만들기
            </button>
          )}
        </footer>
      </section>
    </div>
  );
}
