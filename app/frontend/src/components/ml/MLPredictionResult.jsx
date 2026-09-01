/** 객실 수요 예측의 범위·세부 유형·실적 비교를 표시한다. */
import { useEffect, useMemo, useState } from "react";


const API_PREFIX = String(import.meta.env.VITE_BACKEND_BASE_URL || "").replace(/\/$/, "");
const HOTEL_NAMES = {
  GRAND: "그랜드 워커힐 서울",
  VISTA: "비스타 워커힐 서울",
  DOUGLAS: "더글러스 하우스",
};
const ROOM_TYPE_NAMES = {
  G_CLUB: "그랜드 클럽",
  G_DELUXE: "그랜드 딜럭스",
  G_SUITE: "그랜드 스위트",
  V_DELUXE: "비스타 딜럭스",
  V_SPA: "비스타 스파",
  V_SUITE: "비스타 스위트",
  D_DELUXE: "더글러스 딜럭스",
  D_SUITE: "더글러스 스위트",
  D_TRAD: "더글러스 전통 스위트",
};


function formatRooms(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("ko-KR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
}


function formatPercent(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}


function formatDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? `${match[1]}.${match[2]}.${match[3]}.` : String(value || "");
}


function intervalValue(day, key, fallback) {
  const value = day?.prediction_interval?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}


function validDay(day) {
  return Boolean(
    day
    && /^\d{4}-\d{2}-\d{2}$/.test(String(day.target_date || ""))
    && ["total_available_rooms", "predicted_occupied_rooms", "predicted_available_rooms", "predicted_occupancy_rate"]
      .every((field) => typeof day[field] === "number" && Number.isFinite(day[field])),
  );
}


/** 일별 예측선과 95% 예측 범위를 자료 범위에 맞춰 표시한다. */
export function MLForecastChart({ days }) {
  if (!days.length || !days.every(validDay)) return null;
  const width = 640;
  const height = 180;
  const padding = 10;
  const lower = days.map((day) => intervalValue(day, "lower_95", day.predicted_occupied_rooms));
  const upper = days.map((day) => intervalValue(day, "upper_95", day.predicted_occupied_rooms));
  const dataMin = Math.min(...lower);
  const dataMax = Math.max(...upper);
  const margin = Math.max((dataMax - dataMin) * 0.12, 1);
  const yMin = Math.max(0, dataMin - margin);
  const yMax = dataMax + margin;
  const scaleX = (index) => padding + (
    days.length === 1 ? (width - padding * 2) / 2 : index * (width - padding * 2) / (days.length - 1)
  );
  const scaleY = (value) => padding + (yMax - value) * (height - padding * 2) / (yMax - yMin);
  const points = days.map((day, index) => `${scaleX(index)},${scaleY(day.predicted_occupied_rooms)}`).join(" ");
  const band = [
    ...upper.map((value, index) => `${scaleX(index)},${scaleY(value)}`),
    ...lower.slice().reverse().map(
      (value, index) => `${scaleX(days.length - 1 - index)},${scaleY(value)}`,
    ),
  ].join(" ");

  return (
    <section className="ml-workspace__chart" aria-labelledby="ml-forecast-chart-heading">
      <div className="ml-workspace__section-heading">
        <div><h3 id="ml-forecast-chart-heading">예상 판매 객실 추이</h3><p>선은 예측값, 음영은 95% 예측 범위입니다.</p></div>
        <span>{days.length}일</span>
      </div>
      <div className="ml-workspace__chart-frame">
        <div className="ml-workspace__chart-y-axis" aria-hidden="true">
          <span>{formatRooms(yMax)}</span><span>{formatRooms((yMax + yMin) / 2)}</span><span>{formatRooms(yMin)}</span>
        </div>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="예상 판매 객실과 95% 예측 범위">
          <line x1={padding} y1={padding} x2={width - padding} y2={padding} />
          <line x1={padding} y1={height / 2} x2={width - padding} y2={height / 2} />
          <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} />
          <polygon className="ml-workspace__chart-band" points={band} />
          <polyline points={points} />
        </svg>
      </div>
      <div className="ml-workspace__chart-axis"><span>{formatDate(days[0].target_date)}</span><span>{formatDate(days.at(-1).target_date)}</span></div>
    </section>
  );
}


/** 목표일 실제 실적의 적재 상태와 자동 오차 비교 결과를 표시한다. */
function ActualComparison({ executionId }) {
  const [comparison, setComparison] = useState(null);
  useEffect(() => {
    let active = true;
    fetch(`${API_PREFIX}/analysis/ml/${executionId}/comparison`, { credentials: "include" })
      .then(async (response) => (response.ok ? response.json() : Promise.reject(new Error())))
      .then((payload) => { if (active) setComparison(payload); })
      .catch(() => { if (active) setComparison({ status: "UNAVAILABLE" }); });
    return () => { active = false; };
  }, [executionId]);
  if (!comparison) return <p className="ml-workspace__result-state">실제값을 확인하고 있습니다.</p>;
  if (comparison.status === "PENDING") return <p className="ml-workspace__result-state">목표일 실적이 들어오면 예측과 자동 비교합니다.</p>;
  if (comparison.status !== "COMPLETE") return null;
  return (
    <section className="ml-workspace__actuals">
      <div className="ml-workspace__section-heading"><div><h3>예측과 실제 실적</h3><p>목표일 실적 적재 후 자동 계산한 결과입니다.</p></div></div>
      <div className="ml-workspace__kpis">
        <article><span>실제 판매 객실박</span><strong>{formatRooms(comparison.metrics?.actual_total)}</strong></article>
        <article><span>평균 절대 오차</span><strong>{formatRooms(comparison.metrics?.mae_rooms)}실</strong></article>
        <article><span>가중 절대 오차율</span><strong>{formatPercent(comparison.metrics?.wape)}</strong></article>
      </div>
    </section>
  );
}


/** 호텔·일별·객실 유형별 예측과 영향 요인 및 검증 상태를 표시한다. */
export function MLPredictionResult({ result }) {
  const rawDays = result?.daily_forecasts;
  const days = Array.isArray(rawDays) ? rawDays : [];
  const roomTypes = Array.isArray(result?.room_type_forecasts) ? result.room_type_forecasts : [];
  const summary = useMemo(() => {
    const predicted = days.reduce((sum, day) => sum + day.predicted_occupied_rooms, 0);
    const capacity = days.reduce((sum, day) => sum + day.total_available_rooms, 0);
    return { predicted, occupancy: capacity > 0 ? predicted / capacity : null };
  }, [days]);
  if (!Array.isArray(rawDays) || !days.every(validDay)) {
    return <div className="ml-workspace__result"><p className="ml-workspace__result-state is-error" role="alert">예측 결과 형식을 확인할 수 없습니다.</p></div>;
  }
  if (!days.length) {
    return <div className="ml-workspace__result"><p className="ml-workspace__result-state" role="status">선택한 기간에 표시할 예측 결과가 없습니다.</p></div>;
  }
  return (
    <div className="ml-workspace__result" aria-live="polite">
      <div className="ml-workspace__result-meta">
        <div><span>호텔</span><strong>{HOTEL_NAMES[result.property_id] || result.property_id}</strong></div>
        <div><span>예측 기준일</span><strong>{formatDate(result.as_of)}</strong></div>
        <div><span>실적 기준일</span><strong>{formatDate(result.feature_as_of)}</strong></div>
      </div>
      <section className="ml-workspace__summary">
        <div className="ml-workspace__section-heading"><div><h3>예측 요약</h3><p>판매 가능 객실을 기준으로 계산했습니다.</p></div></div>
        <div className="ml-workspace__kpis">
          <article><span>예측 기간</span><strong>{days.length}일</strong></article>
          <article><span>기간 예상 점유율</span><strong>{formatPercent(summary.occupancy)}</strong></article>
          <article><span>예상 판매 객실박</span><strong>{formatRooms(summary.predicted)}</strong></article>
        </div>
      </section>
      <MLForecastChart days={days} />
      <details className="ml-workspace__details">
        <summary><span>일별 예측 상세</span><strong>{days.length}일</strong></summary>
        <div className="ml-workspace__table-scroll"><table><thead><tr><th>날짜</th><th>판매 가능</th><th>예상 판매</th><th>95% 범위</th><th>예상 점유율</th></tr></thead><tbody>
          {days.map((day) => <tr key={day.target_date}><th>{formatDate(day.target_date)}</th><td>{formatRooms(day.total_available_rooms)}실</td><td>{formatRooms(day.predicted_occupied_rooms)}실</td><td>{formatRooms(intervalValue(day, "lower_95", day.predicted_occupied_rooms))}~{formatRooms(intervalValue(day, "upper_95", day.predicted_occupied_rooms))}실</td><td>{formatPercent(day.predicted_occupancy_rate)}</td></tr>)}
        </tbody></table></div>
      </details>
      {roomTypes.length > 0 && <details className="ml-workspace__details">
        <summary><span>객실 유형별 예측과 영향 요인</span><strong>{roomTypes.length}건</strong></summary>
        <div className="ml-workspace__table-scroll"><table><thead><tr><th>날짜</th><th>객실 유형</th><th>예상 판매</th><th>검증 상태</th><th>주요 영향</th></tr></thead><tbody>
          {roomTypes.map((row) => <tr key={`${row.target_date}-${row.room_type_code}`}><th>{formatDate(row.target_date)}</th><td>{ROOM_TYPE_NAMES[row.room_type_code] || row.room_type_code}</td><td>{formatRooms(row.predicted_rooms)}실</td><td>{row.quality_scope?.status === "APPROVED" ? "검증 통과" : "운영 미승인"}</td><td>{row.influencing_factors?.[0]?.label || "—"}</td></tr>)}
        </tbody></table></div>
      </details>}
      {result.execution_id && <ActualComparison executionId={result.execution_id} />}
      <details className="ml-workspace__technical-details"><summary>기술 상세</summary><dl><div><dt>모델 버전</dt><dd>{result.model_version}</dd></div><div><dt>실적 조회</dt><dd>{result.provenance?.trino_query_id}</dd></div><div><dt>운영 신호 조회</dt><dd>{result.provenance?.signal_query_id || "해당 없음"}</dd></div></dl></details>
    </div>
  );
}
