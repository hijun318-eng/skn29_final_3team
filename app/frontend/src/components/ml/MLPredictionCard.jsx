/** 대화형 객실 수요 예측의 추가 질문과 v4 결과 화면을 연결한다. */
import "./MLPredictionCard.css";
import { MLPredictionResult } from "./MLPredictionResult";
import "./MLPredictionWorkspace.css";

/** ML 객실 수요 예측 결과를 기존 분석 대화의 응답 카드로 표시한다. */
export function MLPredictionCard({ prediction, onFollowUp }) {
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
    <section className="ml-conversation-result" aria-label="기계학습 객실 수요 예측 결과">
      <MLPredictionResult result={prediction} />
    </section>
  );
}
