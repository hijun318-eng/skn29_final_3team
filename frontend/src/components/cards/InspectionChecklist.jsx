import { Check, Circle } from "lucide-react";
import { useState } from "react";

const initialItems = [
  { id: 1, text: "프론트 데스크 추가 인력 배치 검토", meta: "긴급", done: false },
  { id: 2, text: "체크인 키오스크 운영 시간 연장", meta: "긴급", done: false },
  { id: 3, text: "하우스키핑 청결 체크리스트 재점검", meta: "높음", done: true },
  { id: 4, text: "PMS 시스템 응답속도 진단 의뢰", meta: "높음", done: false },
  { id: 5, text: "레스토랑 온라인 예약 채널 확대", meta: "보통", done: false },
  { id: 6, text: "Wi-Fi AP 증설 및 펌웨어 업데이트", meta: "보통", done: true },
];

export function InspectionChecklist() {
  const [items, setItems] = useState(initialItems);
  const toggle = (id) => setItems(items.map((item) => item.id === id ? { ...item, done: !item.done } : item));
  return (
    <article className="card bottom-card checklist-card">
      <div className="section-heading"><div><p>완료 {items.filter((item) => item.done).length}/{items.length}건</p><h2>권장 점검 항목</h2></div><span className="completion">{Math.round(items.filter((item) => item.done).length / items.length * 100)}%</span></div>
      <div className="checklist">
        {items.map((item) => <button className={item.done ? "check-item check-item--done" : "check-item"} onClick={() => toggle(item.id)} key={item.id}>
          <span className="check-icon">{item.done ? <Check size={15} /> : <Circle size={15} />}</span>
          <span><b>{item.text}</b><small>{item.meta}</small></span>
        </button>)}
      </div>
    </article>
  );
}
