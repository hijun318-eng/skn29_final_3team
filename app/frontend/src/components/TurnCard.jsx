/**
 * 멀티턴 대화의 각 턴(Turn)을 엔터프라이즈 BI 표준 레이아웃으로 렌더링하는 카드 컴포넌트다.
 */

import React from "react";
import { ArrowRight, FileText, Search } from "lucide-react";
import { EnterpriseChart } from "./charts/EnterpriseChart";

/**
 * 3대 라우트(ANALYSIS, PRESENTATION, REPORT_ACTION)별 턴 카드를 렌더링한다.
 * @param {object} props
 * @param {object} props.turn
 * @param {Function} [props.onOpenEvidence]
 * @param {Function} [props.onCreateReportDraft]
 * @param {Function} [props.onNavigate]
 */
export function TurnCard({
  turn,
  onSelectOption,
  onOpenEvidence,
  onCreateReportDraft,
  onNavigate,
}) {
  const slots = turn?.resolved_slots || {};
  const disambiguationOptions = (
    slots?.disambiguation_options
    || turn?.run?.disambiguationOptions
    || turn?.run?.error?.disambiguation_options
    || turn?.disambiguation_options
    || []
  );
  const isClarification = (
    turn?.status === "CLARIFICATION_REQUIRED"
    || slots?.ambiguity_status === "NEEDS_CLARIFICATION"
    || disambiguationOptions.length > 0
  );
  const isAnalysis = !isClarification && turn?.route === "ANALYSIS";
  const isPresentation = !isClarification && turn?.route === "PRESENTATION";
  const isReportAction = !isClarification && turn?.route === "REPORT_ACTION";

  const analysisResult = turn?.analysisData?.data?.result || turn?.run?.result;
  const chartData = analysisResult?.chart || turn?.run?.chart;
  const tableData = analysisResult?.table || turn?.run?.table;
  const summaryText = analysisResult?.summary || turn?.artifact_summary || turn?.run?.summary;

  const clarificationType = slots?.clarification_type || turn?.run?.error?.clarification_type || "metric";

  const chartSeries = (chartData?.y_fields || []).map((y) => ({
    key: y,
    label: y,
    unit: analysisResult?.metrics?.[0]?.unit || "",
  }));

  return (
    <article className="turn-card">
      {/* 사용자 질문 */}
      <div className="turn-user-section">
        <div className="turn-user-bubble">
          <span className="user-icon">👤</span>
          <span className="user-text">{turn?.user_message || turn?.question}</span>
        </div>
      </div>

      {/* 턴 본문 렌더링 */}
      <div className="turn-body-section">
        {/* 0. CLARIFICATION_REQUIRED 모호성 해소 턴 */}
        {isClarification && (
          <div className="clarification-turn-content" style={{ padding: "16px", borderRadius: "8px", background: "var(--color-surface-subtle, #f8f9fa)", border: "1px solid var(--color-border, #e5e7eb)" }}>
            <div className="clarification-header" style={{ marginBottom: "12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 600, color: "var(--color-text-primary, #111827)" }}>
                <Search size={16} color="var(--color-primary, #2563eb)" />
                <span>{clarificationType === "period" ? "분석 기간을 선택해 주세요" : "분석 지표를 선택해 주세요"}</span>
              </div>
              <p style={{ margin: "4px 0 0 24px", fontSize: "13px", color: "var(--color-text-secondary, #6b7280)" }}>
                {turn?.run?.error?.message || "질문이 여러 지표 또는 기간으로 해석될 수 있습니다. 계속 진행하려면 분석할 기준을 선택해 주세요."}
              </p>
            </div>

            {disambiguationOptions.length > 0 && (
              <div className="disambiguation-options-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "10px", marginTop: "12px" }}>
                {disambiguationOptions.map((opt, idx) => {
                  const label = opt.label || opt.value || opt.metric_id;
                  const desc = opt.description;
                  return (
                    <button
                      key={opt.value || opt.metric_id || label || idx}
                      type="button"
                      className="disambiguation-option-card"
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "flex-start",
                        textAlign: "left",
                        padding: "12px 14px",
                        borderRadius: "8px",
                        border: "1px solid var(--color-border, #d1d5db)",
                        background: "var(--color-surface, #ffffff)",
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                      }}
                      onClick={() => onSelectOption?.(opt)}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", width: "100%", alignItems: "center", marginBottom: "4px" }}>
                        <strong style={{ fontSize: "14px", color: "var(--color-text-primary, #1f2937)" }}>{label}</strong>
                        <span style={{ fontSize: "11px", padding: "2px 6px", borderRadius: "4px", background: "var(--color-primary-light, #eff6ff)", color: "var(--color-primary, #2563eb)" }}>
                          {opt.clarification_type === "period" ? "기간" : "지표"}
                        </span>
                      </div>
                      {desc && (
                        <p style={{ margin: 0, fontSize: "12px", color: "var(--color-text-secondary, #4b5563)", lineHeight: "1.4" }}>
                          {desc}
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
          <div className="analysis-turn-content">
            {summaryText && (
              <div className="turn-summary-box">
                <p className="turn-summary-text">{summaryText}</p>
              </div>
            )}

            {/* KPI 요약 칩 */}
            {analysisResult?.metrics && analysisResult.metrics.length > 0 && (
              <div className="turn-kpis-grid">
                {analysisResult.metrics.map((m) => (
                  <div key={m.metric_id} className="turn-kpi-card">
                    <span className="kpi-label">{m.label || m.metric_id}</span>
                    <span className="kpi-value">
                      {typeof m.value === "number" ? m.value.toLocaleString("ko-KR") : m.value || "-"}
                    </span>
                    {m.unit && <span className="kpi-unit">{m.unit}</span>}
                  </div>
                ))}
              </div>
            )}

            {/* 차트 시각화 */}
            {chartData && tableData && tableData.rows?.length > 0 && (
              <div className="turn-chart-container">
                <EnterpriseChart
                  data={tableData.rows}
                  xKey={chartData.x_field}
                  xLabel={chartData.x_field}
                  series={chartSeries}
                  type={chartData.chart_type || "bar"}
                />
              </div>
            )}

            {/* 데이터 테이블 */}
            {tableData && tableData.rows?.length > 0 && (
              <div className="turn-table-container">
                <table className="analysis-table">
                  <thead>
                    <tr>
                      {tableData.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tableData.rows.map((row, idx) => (
                      <tr key={idx}>
                        {tableData.columns.map((c) => (
                          <td key={c} className={typeof row[c] === "number" ? "is-numeric" : ""}>
                            {typeof row[c] === "number"
                              ? row[c].toLocaleString("ko-KR")
                              : String(row[c] ?? "-")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* 하단 리포트 담기 액션 버튼 */}
            {turn?.artifact_id && onCreateReportDraft && (
              <div className="turn-actions-bar">
                <button
                  type="button"
                  className="ghost-button-sm"
                  onClick={() => onCreateReportDraft(turn)}
                >
                  <FileText size={13} />
                  <span>이 결과를 보고서 초안에 담기</span>
                </button>
              </div>
            )}
          </div>
        )}

        {/* 2. PRESENTATION 턴 */}
        {isPresentation && (
          <div className="presentation-view-card">
            <div className="presentation-badge">
              <span className="icon">⚡</span>
              <span>Trino 원천 쿼리 재실행 없이 <strong>{turn?.view_type || "TABLE"}</strong> 뷰로 전환했습니다.</span>
            </div>
            <p className="presentation-desc">
              이전 분석 아티팩트 데이터를 보존한 채 ViewSpec을 불변 생성했습니다.
            </p>
          </div>
        )}

        {/* 3. REPORT_ACTION 턴 */}
        {isReportAction && (
          <div className="report-action-card">
            <div className="report-action-header">
              <span className="report-icon">📑</span>
              <div>
                <h4>보고서 초안(Draft) 결합 완료</h4>
                <p className="report-desc">
                  대화에서 생성된 {turn?.source_turn_ids?.length || 2}개 분석 결과가 보고서 블록으로 연결되었습니다.
                </p>
              </div>
            </div>
            <div className="report-action-footer">
              <button
                type="button"
                className="primary-button-sm"
                onClick={() => onNavigate?.("reports")}
              >
                <span>보고서 편집기(/reports)로 이동하기</span>
                <ArrowRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
