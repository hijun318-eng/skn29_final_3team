/**
 * 분석 결과 아티팩트를 공식 보고서 초안(Draft)으로 변환하는 모달 컴포넌트다.
 */
import React from "react";
import { Check, X } from "lucide-react";
import { AnalysisStatePanel } from "./analysis/AnalysisStatePanel";

/**
 * 보고서 초안 생성 및 미리보기 모달을 렌더링한다.
 * @param {object} props
 * @param {string} props.mode
 * @param {object} props.run
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
  title,
  onTitleChange,
  onConfirm,
  onPreviewMode,
  onClose,
  isSubmitting,
}) {
  if (!mode || !run) return null;

  return (
    <div className="report-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className={`report-transfer-modal ${mode === "preview" ? "report-transfer-modal--preview" : ""}`}
        role="dialog"
        aria-modal="true"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <small>분석 결과</small>
            <h2>{mode === "draft" ? "보고서 초안 구성" : "분석 결과 미리보기"}</h2>
          </div>
          <button aria-label="닫기" onClick={onClose}><X size={18} /></button>
        </header>

        {mode === "draft" && (
          <label className="report-title-field" style={{ padding: "0 20px" }}>
            <span style={{ display: "block", fontSize: "12px", color: "#8da2be", marginBottom: "6px" }}>보고서 제목</span>
            <input
              style={{ width: "100%", height: "38px", padding: "0 10px", borderRadius: "6px", border: "1px solid #1d2a3d", background: "#0a0f18", color: "#fff" }}
              value={title}
              maxLength={120}
              onChange={(e) => onTitleChange(e.target.value)}
            />
          </label>
        )}

        {mode === "preview" ? (
          <div className="report-analysis-preview" style={{ padding: "16px 20px" }}>
            <AnalysisStatePanel run={run} />
          </div>
        ) : (
          <div className="report-preview-summary">
            <small>분석 질문</small>
            <b>{run.question}</b>
            <p>{run.summary}</p>
            {run.metrics && run.metrics.length > 0 && (
              <dl>
                {run.metrics.map((metric) => (
                  <div key={metric.metricId || metric.metric_id}>
                    <dt>{metric.label}</dt>
                    <dd>
                      {typeof metric.value === "number" ? metric.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : String(metric.value ?? "없음")} {metric.unit || ""}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        )}

        <footer>
          <button onClick={onClose}>취소</button>
          {mode === "draft" ? (
            <button className="primary" disabled={isSubmitting || !title.trim()} onClick={onConfirm}>
              <Check size={14} />{isSubmitting ? "생성 중..." : "초안 만들기"}
            </button>
          ) : (
            <button className="primary" onClick={onPreviewMode}>
              보고서 초안 만들기
            </button>
          )}
        </footer>
      </section>
    </div>
  );
}
