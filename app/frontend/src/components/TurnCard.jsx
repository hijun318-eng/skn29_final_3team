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
  onOpenEvidence,
  onCreateReportDraft,
  onNavigate,
}) {
  const slots = turn?.resolved_slots || {};
  const isAnalysis = turn?.route === "ANALYSIS";
  const isPresentation = turn?.route === "PRESENTATION";
  const isReportAction = turn?.route === "REPORT_ACTION";

  const analysisResult = turn?.analysisData?.data?.result;
  const chartData = analysisResult?.chart;
  const tableData = analysisResult?.table;
  const summaryText = analysisResult?.summary || turn?.artifact_summary;

  const routeLabel = isAnalysis
    ? "심층 분석 (AST 검증)"
    : isPresentation
    ? "시각화 전환 (Trino 0건)"
    : "보고서 연계 (Draft 연결)";

  const chartSeries = (chartData?.y_fields || []).map((y) => ({
    key: y,
    label: y,
    unit: analysisResult?.metrics?.[0]?.unit || "",
  }));

  return (
    <article className="turn-card">
      <header className="turn-header">
        <div className="turn-header-left">
          <span className="turn-index-pill">Turn #{(turn?.turn_index ?? 0) + 1}</span>
          <span className={`turn-route-badge route-${String(turn?.route || "analysis").toLowerCase()}`}>
            {routeLabel}
          </span>
          <time className="turn-timestamp">
            {turn?.created_at ? new Date(turn.created_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : ""}
          </time>
        </div>
        <div className="turn-header-right">
          {isAnalysis && onOpenEvidence && (
            <button
              type="button"
              className="ghost-button-sm"
              onClick={() => onOpenEvidence(turn)}
            >
              <Search size={13} />
              <span>거버넌스 근거</span>
            </button>
          )}
        </div>
      </header>

      {/* 사용자 질문 및 슬롯 상속 칩 */}
      <div className="turn-user-section">
        <div className="turn-user-bubble">
          <span className="user-icon">👤</span>
          <span className="user-text">{turn?.user_message}</span>
        </div>

        {/* 확정된 슬롯 스트립 */}
        {(slots.metric_id || slots.time_range || slots.dimension_fields?.length > 0 || turn?.view_type) && (
          <div className="turn-slots-strip">
            {slots.metric_id && (
              <span className={`slot-chip ${slots.is_inherited_metric ? "inherited" : "specified"}`}>
                {slots.is_inherited_metric ? "⚡ 지표 상속: " : "🎯 지표: "}
                {slots.metric_id}
              </span>
            )}
            {slots.time_range && (
              <span className={`slot-chip ${slots.is_inherited_period ? "inherited" : "specified"}`}>
                {slots.is_inherited_period ? "📅 기간 상속: " : "📅 기간: "}
                {slots.time_range.start} ~ {slots.time_range.end_exclusive}
              </span>
            )}
            {slots.dimension_fields?.map((d) => (
              <span
                key={d.column || d}
                className={`slot-chip ${slots.is_inherited_dimension ? "inherited" : "specified"}`}
              >
                {slots.is_inherited_dimension ? "🏢 차원 상속: " : "🏢 차원: "}
                {d.column || d}
              </span>
            ))}
            {turn?.view_type && (
              <span className="slot-chip view">
                📊 뷰: {turn.view_type}
              </span>
            )}
          </div>
        )}
      </div>

      {/* 턴 본문 렌더링 */}
      <div className="turn-body-section">
        {/* 1. ANALYSIS 턴 */}
        {isAnalysis && (
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
