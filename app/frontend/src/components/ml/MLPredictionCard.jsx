import "./MLPredictionCard.css";

function formatRooms(value) {
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(
    Math.round(Number(value || 0)),
  );
}

function formatPercent(value) {
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(Number(value || 0));
}

/** ML 객실 수요 예측 결과를 기존 분석 대화의 응답 카드로 표시한다. */
export function MLPredictionCard({ prediction, onFollowUp }) {
  const forecasts = Array.isArray(prediction?.daily_forecasts) ? prediction.daily_forecasts : [];
  if (prediction?.status === "NEEDS_CLARIFICATION") {
    return (
      <section className="ml-prediction-card ml-prediction-card--notice" aria-label="ML 예측 조건 확인">
        <small>ML 객실 수요 예측</small>
        <h3>예측 조건을 확인해 주세요</h3>
        <p>{prediction.answer_text}</p>
        {prediction.clarification_options?.length > 0 && (
          <div className="ml-prediction-card__options">
            {prediction.clarification_options.map((option) => (
              <button type="button" key={option.value || option.label} onClick={() => onFollowUp?.(option.value || option.label)}>
                {option.label || option.value}
              </button>
            ))}
          </div>
        )}
      </section>
    );
  }
  return (
    <section className="ml-prediction-card" aria-label="ML 객실 수요 예측 결과">
      <header className="ml-prediction-card__header">
        <div>
          <small>ML 객실 수요 예측</small>
          <h3>{prediction?.property_id} 호텔</h3>
          <p>기준일 {prediction?.as_of} · 실적 데이터 {prediction?.feature_as_of || prediction?.as_of} 기준</p>
        </div>
        <span>{prediction?.horizon || forecasts.length}일 예측</span>
      </header>
      <div className="ml-prediction-card__summary">
        <div><span>모델</span><strong>{prediction?.model_version || "확인 불가"}</strong></div>
        <div><span>예측 기간</span><strong>{forecasts[0]?.target_date || "-"} ~ {forecasts.at(-1)?.target_date || "-"}</strong></div>
      </div>
      <div className="ml-prediction-card__days">
        {forecasts.map((day) => (
          <article key={day.target_date}>
            <time>{day.target_date}</time>
            <p>전체 <strong>{formatRooms(day.total_available_rooms)}실</strong> 중</p>
            <h4>{formatRooms(day.predicted_occupied_rooms)}실 <span>점유 예측</span></h4>
            <dl>
              <div><dt>예상 잔여</dt><dd>{formatRooms(day.predicted_available_rooms)}실</dd></div>
              <div><dt>예상 점유율</dt><dd>{formatPercent(day.predicted_occupancy_rate)}</dd></div>
            </dl>
          </article>
        ))}
      </div>
      <footer>
        <span>Trino query: {prediction?.provenance?.trino_query_id || "확인 불가"}</span>
        <span>{prediction?.provenance?.rag_called === false ? "RAG 미호출" : "분리 검증 필요"}</span>
      </footer>
    </section>
  );
}
