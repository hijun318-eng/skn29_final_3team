/** 내부 문서 검색을 시작할 수 있도록 업무 영역과 안전한 예시 질문을 제시한다. */
import { useState } from "react";

const AREAS = [
  "공통 업무", "개인정보", "보고서", "알림·협조", "대화형 분석", "고객응대",
  "고객의견", "외부 후기", "객실", "예약·입퇴실·결제", "취소·환불·보상",
  "식음", "레저", "시설", "안전", "주차·행사·로비",
];

const RECOMMENDED = [
  "고객 불만은 어떻게 처리해?",
  "시설 문제가 발생하면 먼저 뭘 해야 해?",
  "환불 기준 알려줘",
  "개인정보가 잘못 전달됐을 때 어떻게 해야 해?",
  "안전사고 발생 시 대응 절차 알려줘",
];

const EXAMPLES = [
  ["처리 방법", "분실물 접수 후 어떻게 처리해?"],
  ["즉시 대응", "고객이 객실에서 쓰러졌어. 지금 뭘 해야 해?"],
  ["판단 기준", "시설 문제를 긴급 상황으로 보는 기준이 뭐야?"],
  ["규정 확인", "예약 취소하면 환불 가능한가?"],
  ["비교", "시설 장애와 안전사고 대응은 어떻게 달라?"],
  ["요약", "고객응대 지침에서 중요한 내용만 알려줘."],
];

/** 사용자가 선택한 문서 영역이나 예시를 실제 질의 callback으로 전달한다. */
export default function RagEmptyState({ onAsk }) {
  const [view, setView] = useState("");
  const [selected, setSelected] = useState("");
  return (
    <section className="chat-empty-state rag-empty-state">
      <small>내부 문서 검색</small>
      <h2>무엇을 확인하시겠어요?</h2>
      <p>업무 매뉴얼과 내부 지침을 기준으로 답변합니다.</p>
      <div className="rag-help-actions">
        <button type="button" onClick={() => { setView("documents"); setSelected(""); }}>문서 목록 보기</button>
        <button type="button" onClick={() => { setView("examples"); setSelected(""); }}>질문 예시 보기</button>
      </div>
      {view === "documents" && (
        <div className="rag-help-panel">
          <strong>확인할 수 있는 업무 영역</strong>
          <div className="rag-area-list">
            {AREAS.map((area) => (
              <button key={area} type="button" onClick={() => setSelected(area)}>{area}</button>
            ))}
          </div>
          {selected && <p className="rag-area-note"><strong>{selected}</strong><br />처리 절차, 판단 기준, 즉시 보고 조건을 질문할 수 있습니다.</p>}
        </div>
      )}
      {view === "examples" && (
        <div className="rag-help-panel rag-example-list">
          {EXAMPLES.map(([label, question]) => (
            <button key={label} type="button" onClick={() => onAsk(question)}>
              <strong>{label}</strong><span>{question}</span>
            </button>
          ))}
        </div>
      )}
      {!view && (
        <div className="rag-recommended">
          <strong>추천 질문</strong>
          {RECOMMENDED.map((question) => (
            <button key={question} type="button" onClick={() => onAsk(question)}>{question}</button>
          ))}
        </div>
      )}
    </section>
  );
}
