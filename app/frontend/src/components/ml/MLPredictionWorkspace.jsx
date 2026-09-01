/** 승인된 ML capability 범위에서 객실 수요 예측을 요청하고 결과를 표시한다. */
import { useEffect, useMemo, useRef, useState } from "react";

import "./MLPredictionWorkspace.css";


const API_PREFIX = String(import.meta.env.VITE_BACKEND_BASE_URL || "").replace(/\/$/, "");
const DIALOG_ID = "ml-prediction-dialog";
const DIALOG_TITLE_ID = "ml-prediction-dialog-title";
const FORECAST_NUMBER_FIELDS = [
  "total_available_rooms",
  "predicted_occupied_rooms",
  "predicted_available_rooms",
  "predicted_occupancy_rate",
];
const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "select:not([disabled])",
  "input:not([disabled])",
  "details > summary",
  "[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");


/** ML API의 공개 오류 envelope에서 사용자에게 안전한 안내 문구만 선택한다. */
export function mlResponseErrorMessage(payload) {
  if (typeof payload?.error?.message === "string" && payload.error.message.trim()) {
    return payload.error.message;
  }
  if (typeof payload?.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }
  if (typeof payload?.detail?.reason === "string" && payload.detail.reason.trim()) {
    return payload.detail.reason;
  }
  return "ML 요청을 처리하지 못했습니다.";
}


async function requestJson(path, options = {}) {
  const response = await fetch(API_PREFIX + path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(mlResponseErrorMessage(payload));
  }
  return payload;
}


function formatRooms(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(
    Math.round(value),
  );
}


function formatPercent(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}


function formatKoreanDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? `${match[1]}.${match[2]}.${match[3]}.` : String(value || "");
}


function validForecastDay(day) {
  return Boolean(
    day
    && typeof day === "object"
    && /^\d{4}-\d{2}-\d{2}$/.test(String(day.target_date || ""))
    && FORECAST_NUMBER_FIELDS.every((field) => (
      typeof day[field] === "number" && Number.isFinite(day[field])
    ))
    && FORECAST_NUMBER_FIELDS.slice(0, 3).every((field) => day[field] >= 0)
    && day.predicted_occupancy_rate >= 0
    && day.predicted_occupancy_rate <= 1
  );
}


function buildForecastSummary(days) {
  const totalOccupied = days.reduce(
    (sum, day) => sum + day.predicted_occupied_rooms,
    0,
  );
  const totalAvailable = days.reduce(
    (sum, day) => sum + day.total_available_rooms,
    0,
  );
  return {
    totalOccupied,
    occupancyRate: totalAvailable > 0 ? totalOccupied / totalAvailable : null,
  };
}


/** API가 반환한 일별 점유율만 이용해 추이를 그린다. */
export function MLForecastChart({ days }) {
  if (!Array.isArray(days) || days.length === 0 || !days.every(validForecastDay)) return null;
  const width = 640;
  const height = 180;
  const horizontalPadding = 8;
  const verticalPadding = 6;
  const drawableWidth = width - horizontalPadding * 2;
  const drawableHeight = height - verticalPadding * 2;
  const coordinates = days.map((day, index) => {
    const ratio = day.predicted_occupancy_rate;
    const x = horizontalPadding + (
      days.length === 1 ? drawableWidth / 2 : (index / (days.length - 1)) * drawableWidth
    );
    const y = verticalPadding + (1 - ratio) * drawableHeight;
    return { x, y };
  });
  const points = coordinates.map(({ x, y }) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const occupancyRates = days.map((day) => day.predicted_occupancy_rate);
  const chartDescription = [
    `${formatKoreanDate(days[0].target_date)}부터 ${formatKoreanDate(days.at(-1).target_date)}까지 예상 점유율 추이`,
    `최저 ${formatPercent(Math.min(...occupancyRates))}`,
    `최고 ${formatPercent(Math.max(...occupancyRates))}`,
    `마지막 날 ${formatPercent(occupancyRates.at(-1))}`,
  ].join(", ");

  return (
    <section className="ml-workspace__chart" aria-labelledby="ml-forecast-chart-heading">
      <div className="ml-workspace__section-heading">
        <div>
          <h3 id="ml-forecast-chart-heading">예상 점유율 추이</h3>
          <p>예측 기간의 일별 변화를 보여줍니다.</p>
        </div>
        <span>{days.length}일</span>
      </div>
      <div className="ml-workspace__chart-frame">
        <div className="ml-workspace__chart-y-axis" aria-hidden="true">
          <span>100%</span><span>50%</span><span>0%</span>
        </div>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={chartDescription}
          preserveAspectRatio="none"
        >
          <line x1={horizontalPadding} y1={verticalPadding} x2={width - horizontalPadding} y2={verticalPadding} />
          <line x1={horizontalPadding} y1={height / 2} x2={width - horizontalPadding} y2={height / 2} />
          <line x1={horizontalPadding} y1={height - verticalPadding} x2={width - horizontalPadding} y2={height - verticalPadding} />
          <polyline points={points} />
          {coordinates.length === 1 && (
            <circle cx={coordinates[0].x} cy={coordinates[0].y} r="5" />
          )}
        </svg>
      </div>
      <div className="ml-workspace__chart-axis" aria-hidden="true">
        <span>{formatKoreanDate(days[0].target_date)}</span>
        {days.length > 1 && <span>{formatKoreanDate(days.at(-1).target_date)}</span>}
      </div>
    </section>
  );
}


/** 예측 결과의 사용자 요약과 선택형 상세 정보를 표시한다. */
export function MLPredictionResult({ result }) {
  const forecasts = result?.daily_forecasts;
  if (!Array.isArray(forecasts) || !forecasts.every(validForecastDay)) {
    return <div className="ml-workspace__result"><p className="ml-workspace__result-state is-error" role="alert">예측 결과 형식을 확인할 수 없습니다. 잠시 후 다시 요청해 주세요.</p></div>;
  }
  if (forecasts.length === 0) {
    return <div className="ml-workspace__result"><p className="ml-workspace__result-state" role="status">선택한 기간에 표시할 예측 결과가 없습니다.</p></div>;
  }
  const days = forecasts;
  const summary = buildForecastSummary(days);

  return (
    <div className="ml-workspace__result" aria-live="polite">
      <div className="ml-workspace__result-meta">
        <div><span>호텔</span><strong title={String(result.property_id)}>{result.property_id}</strong></div>
        <div><span>예측 기준일</span><strong>{formatKoreanDate(result.as_of)}</strong></div>
        <div><span>실적 데이터 기준</span><strong>{formatKoreanDate(result.feature_as_of || result.as_of)}</strong></div>
      </div>

      <section className="ml-workspace__summary" aria-labelledby="ml-forecast-summary-heading">
        <div className="ml-workspace__section-heading">
          <div>
            <h3 id="ml-forecast-summary-heading">예측 요약</h3>
            <p>선택한 기간의 객실 수요를 한눈에 확인하세요.</p>
          </div>
        </div>
        <div className="ml-workspace__kpis">
          <article><span>예측 기간</span><strong>{days.length}일</strong></article>
          <article><span>기간 예상 점유율</span><strong>{formatPercent(summary.occupancyRate)}</strong></article>
          <article><span>누적 예상 판매 객실박</span><strong>{formatRooms(summary.totalOccupied)}객실박</strong></article>
        </div>
      </section>

      <MLForecastChart days={days} />

      <section className="ml-workspace__model-info" aria-labelledby="ml-model-info-heading">
        <div className="ml-workspace__section-heading">
          <div>
            <h3 id="ml-model-info-heading">사용 모델</h3>
            <p>{result.model_version || "모델 정보 없음"}</p>
          </div>
        </div>
      </section>

      {days.length > 0 && (
        <details className="ml-workspace__details">
          <summary><span>일별 예측 상세 보기</span><strong>{days.length}일</strong></summary>
          <div className="ml-workspace__table-scroll">
            <table>
              <thead><tr>
                <th scope="col">날짜</th><th scope="col">전체 객실</th>
                <th scope="col">예상 판매</th><th scope="col">예상 잔여</th>
                <th scope="col">예상 점유율</th>
              </tr></thead>
              <tbody>
                {days.map((day) => (
                  <tr key={day.target_date}>
                    <th scope="row">{formatKoreanDate(day.target_date)}</th>
                    <td>{formatRooms(day.total_available_rooms)}실</td>
                    <td>{formatRooms(day.predicted_occupied_rooms)}실</td>
                    <td>{formatRooms(day.predicted_available_rooms)}실</td>
                    <td>{formatPercent(day.predicted_occupancy_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {(result.model_version || result.provenance?.trino_query_id) && (
        <details className="ml-workspace__technical-details">
          <summary>기술 상세</summary>
          <dl>
            {result.provenance?.trino_query_id && (
              <div><dt>조회 식별자</dt><dd>{result.provenance.trino_query_id}</dd></div>
            )}
          </dl>
        </details>
      )}
    </div>
  );
}


/** ML runtime이 제공한 property와 기간만 선택할 수 있는 예측 작업영역이다. */
export default function MLPredictionWorkspace() {
  const [open, setOpen] = useState(false);
  const [capability, setCapability] = useState(null);
  const [propertyId, setPropertyId] = useState("");
  const [asOf, setAsOf] = useState("");
  const [horizon, setHorizon] = useState(7);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const triggerRef = useRef(null);
  const panelRef = useRef(null);
  const closeRef = useRef(null);

  useEffect(() => {
    let active = true;
    requestJson("/ml/capabilities")
      .then((data) => {
        if (!active) return;
        setCapability(data);
        const minimumHorizon = Number(data.min_horizon_days || 1);
        const maximumHorizon = Number(data.max_horizon_days || minimumHorizon);
        setHorizon(Math.min(maximumHorizon, Math.max(minimumHorizon, 7)));
        const first = data.properties?.[0];
        if (first) {
          setPropertyId(String(first.property_id));
          setAsOf(String(first.max_as_of));
        }
      })
      .catch((requestError) => { if (active) setError(requestError.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusFrame = window.requestAnimationFrame(() => closeRef.current?.focus());
    function handleDialogKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(panelRef.current?.querySelectorAll(FOCUSABLE_SELECTOR) || []);
      if (focusable.length === 0) {
        event.preventDefault();
        panelRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleDialogKeyDown);
    return () => {
      document.body.style.overflow = previousBodyOverflow;
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleDialogKeyDown);
      triggerRef.current?.focus();
    };
  }, [open]);

  const selectedProperty = useMemo(
    () => capability?.properties?.find((item) => String(item.property_id) === propertyId),
    [capability, propertyId],
  );

  function changeProperty(event) {
    const nextProperty = event.target.value;
    const nextCapability = capability?.properties?.find(
      (item) => String(item.property_id) === nextProperty,
    );
    setPropertyId(nextProperty);
    setAsOf(String(nextCapability?.max_as_of || ""));
    setResult(null);
  }

  async function submitPrediction(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await requestJson("/analysis/ml", {
        method: "POST",
        body: JSON.stringify({
          property_id: propertyId,
          as_of: asOf,
          horizon_days: Number(horizon),
        }),
      });
      setResult(data);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  if (!Array.isArray(capability?.properties) || capability.properties.length === 0) return null;

  return (
    <section className={"ml-workspace " + (open ? "is-open" : "")}>
      <button
        ref={triggerRef}
        className="ml-workspace__trigger"
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-controls={DIALOG_ID}
        aria-expanded={open}
      >
        <span>객실 수요</span><strong>ML 예측</strong>
      </button>

      {open && (
        <>
          <div
            className="ml-workspace__scrim"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div
            ref={panelRef}
            id={DIALOG_ID}
            className="ml-workspace__panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby={DIALOG_TITLE_ID}
            tabIndex={-1}
          >
            <header className="ml-workspace__header">
              <div><p>객실 수요 예측</p><h2 id={DIALOG_TITLE_ID}>향후 객실 수요 예측</h2></div>
              <button
                ref={closeRef}
                type="button"
                className="ml-workspace__close"
                onClick={() => setOpen(false)}
                aria-label="ML 예측 패널 닫기"
              >닫기</button>
            </header>

            <div className="ml-workspace__scroll">
              <form className="ml-workspace__form" onSubmit={submitPrediction} aria-busy={loading}>
                <label>
                  호텔
                  <select value={propertyId} onChange={changeProperty} disabled={!capability || loading} required>
                    {(capability?.properties || []).map((property) => (
                      <option key={property.property_id} value={property.property_id}>
                        {property.property_id}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  예측 기준일
                  <input
                    type="date"
                    value={asOf}
                    min={selectedProperty?.min_as_of || undefined}
                    max={selectedProperty?.max_as_of || undefined}
                    onChange={(event) => setAsOf(event.target.value)}
                    onInput={(event) => setAsOf(event.currentTarget.value)}
                    disabled={!capability || loading}
                    required
                  />
                </label>
                <label>
                  예측 기간
                  <input
                    type="number"
                    value={horizon}
                    onChange={(event) => setHorizon(event.target.value)}
                    min={capability?.min_horizon_days || 1}
                    max={capability?.max_horizon_days || 1}
                    disabled={loading}
                    required
                  />
                  <small className="ml-workspace__field-hint">
                    현재 모델은 {capability?.min_horizon_days || 1}일부터{" "}
                    {capability?.max_horizon_days || 1}일까지 선택할 수 있습니다.
                  </small>
                </label>
                <button
                  className="ml-workspace__submit"
                  type="submit"
                  disabled={loading || !propertyId || !asOf || !capability}
                >{loading ? "이력 데이터 조회 중" : "예측 실행"}</button>
              </form>

              {capability?.synthetic_training_data && (
                <p className="ml-workspace__notice">
                  합성 과거 데이터로 학습한 검증 모델입니다. 결과는 실제 PMS 데이터로 다시 확인한 뒤 활용해 주세요.
                </p>
              )}
              {error && <div className="ml-workspace__error" role="alert">{error}</div>}
              {result && <MLPredictionResult result={result} />}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
