/** 승인된 ML capability 범위에서 객실 수요 예측을 요청하고 결과를 표시한다. */
import { useEffect, useMemo, useState } from "react";

import "./MLPredictionWorkspace.css";


const API_PREFIX = String(
  import.meta.env.VITE_BACKEND_BASE_URL || "",
).replace(/\/$/, "");


async function requestJson(path, options = {}) {
  const response = await fetch(API_PREFIX + path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      payload.error?.message
        || payload.detail
        || "ML 요청을 처리하지 못했습니다.",
    );
  }
  return payload;
}


function formatRooms(value) {
  return new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: 0,
  }).format(Math.round(Number(value || 0)));
}


function formatPercent(value) {
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(Number(value || 0));
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

  useEffect(() => {
    let active = true;
    requestJson("/ml/capabilities")
      .then((data) => {
        if (!active) return;
        setCapability(data);
        const first = data.properties?.[0];
        if (first) {
          setPropertyId(String(first.property_id));
          setAsOf(String(first.max_as_of));
        }
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      });
    return () => {
      active = false;
    };
  }, []);

  const selectedProperty = useMemo(
    () => capability?.properties?.find(
      (item) => String(item.property_id) === propertyId,
    ),
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
          horizon: Number(horizon),
        }),
      });
      setResult(data);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  if (!Array.isArray(capability?.properties) || capability.properties.length === 0) {
    return null;
  }

  return (
    <section className={"ml-workspace " + (open ? "is-open" : "")}>
      <button
        className="ml-workspace__trigger"
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="ml-workspace__trigger-kicker">ROOM DEMAND</span>
        <strong>ML 객실 예측</strong>
      </button>

      {open && (
        <div className="ml-workspace__panel">
          <header className="ml-workspace__header">
            <div>
              <p>POINT-IN-TIME FORECAST</p>
              <h2>향후 객실 수요 예측</h2>
            </div>
            <button
              type="button"
              className="ml-workspace__close"
              onClick={() => setOpen(false)}
              aria-label="ML 예측 패널 닫기"
            >
              닫기
            </button>
          </header>

          <form
            className="ml-workspace__form"
            onSubmit={submitPrediction}
          >
            <label>
              호텔
              <select
                value={propertyId}
                onChange={changeProperty}
                disabled={!capability || loading}
                required
              >
                {(capability?.properties || []).map((property) => (
                  <option
                    key={property.property_id}
                    value={property.property_id}
                  >
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
              <select
                value={horizon}
                onChange={(event) => setHorizon(event.target.value)}
                disabled={loading}
              >
                {[1, 3, 7].map((days) => (
                  <option key={days} value={days}>
                    향후 {days}일
                  </option>
                ))}
              </select>
            </label>
            <button
              className="ml-workspace__submit"
              type="submit"
              disabled={
                loading || !propertyId || !asOf || !capability
              }
            >
              {loading ? "이력 데이터 조회 중" : "ML 예측 실행"}
            </button>
          </form>

          {capability?.synthetic_training_data && (
            <p className="ml-workspace__notice">
              합성 과거 데이터로 학습한 검증 모델입니다. 결과는 운영
              의사결정 전 실제 PMS 데이터로 재검증해야 합니다.
            </p>
          )}

          {error && (
            <div className="ml-workspace__error" role="alert">
              {error}
            </div>
          )}

          {result && (
            <div className="ml-workspace__result">
              <div className="ml-workspace__result-meta">
                <div>
                  <span>호텔</span>
                  <strong>{result.property_id}</strong>
                </div>
                <div>
                  <span>기준일</span>
                  <strong>{result.as_of}</strong>
                </div>
                <div>
                  <span>실적 데이터 기준</span>
                  <strong>{result.feature_as_of || result.as_of}</strong>
                </div>
                <div>
                  <span>모델</span>
                  <strong>{result.model_version}</strong>
                </div>
              </div>
              <div className="ml-workspace__days">
                {result.daily_forecasts?.map((day) => (
                  <article key={day.target_date}>
                    <time>{day.target_date}</time>
                    <p>
                      전체{" "}
                      <strong>
                        {formatRooms(day.total_available_rooms)}실
                      </strong>{" "}
                      중
                    </p>
                    <h3>
                      {formatRooms(day.predicted_occupied_rooms)}실
                      <span>점유 예측</span>
                    </h3>
                    <dl>
                      <div>
                        <dt>예상 잔여</dt>
                        <dd>
                          {formatRooms(day.predicted_available_rooms)}실
                        </dd>
                      </div>
                      <div>
                        <dt>예상 점유율</dt>
                        <dd>
                          {formatPercent(
                            day.predicted_occupancy_rate,
                          )}
                        </dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>
              <footer>
                <span>
                  Trino query:{" "}
                  {result.provenance?.trino_query_id || "확인 불가"}
                </span>
                <span>RAG 호출: 없음</span>
              </footer>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
