import { useMemo, useState } from "react";
import { Bot, Check, ChevronRight, Clock3, MapPin, Send, Sparkles } from "lucide-react";
import "../styles/hospitality.css";

const EXPERIENCES = [
  { score: 5, emoji: "😍", label: "매우 만족" }, { score: 4, emoji: "😊", label: "만족" },
  { score: 3, emoji: "😐", label: "보통" }, { score: 2, emoji: "😕", label: "불편" },
  { score: 1, emoji: "😡", label: "매우 불만" },
];

const FACILITIES = [
  { icon: "🥐", name: "Breakfast", time: "06:30 – 10:00", location: "비스타 2F · 더뷔페" },
  { icon: "💪", name: "Fitness", time: "06:00 – 22:00", location: "비스타 3F · 웰니스 클럽" },
  { icon: "🏊", name: "Pool", time: "06:00 – 21:30", location: "비스타 3F · 실내 수영장" },
  { icon: "☕", name: "Lounge", time: "10:00 – 22:00", location: "그랜드 Lobby · 더파빌리온" },
  { icon: "💆", name: "Spa", time: "10:00 – 21:00", location: "비스타 3F · V SPA" },
  { icon: "🍽️", name: "Restaurant", time: "12:00 – 22:00", location: "SENSE PLACE 다이닝" },
  { icon: "🚗", name: "Parking", time: "24 Hours", location: "주차타워 · 발렛 데스크" },
];

function BrandHeader({ step }) {
  return <header className="hospitality-brand"><a href="/">SENSE PLACE</a><span>{step}</span></header>;
}

function ExperienceScale({ value, onChange, compact = false }) {
  return <div className={`experience-scale ${compact ? "is-compact" : ""}`}>
    {EXPERIENCES.map((item) => <button type="button" key={item.score} className={value === item.score ? "is-selected" : ""} aria-pressed={value === item.score} onClick={() => onChange(item.score)}><span>{item.emoji}</span>{!compact && <small>{item.label}</small>}</button>)}
  </div>;
}

export function GuestGuidePage() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const guest = params.get("name") || "Guest Name";
  const [score, setScore] = useState(null);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);

  return <main className="hospitality-page"><div className="hospitality-shell">
    <BrandHeader step="YOUR STAY" />
    <section className="welcome-block"><p>Good Afternoon,</p><h1>{guest}</h1><span><Check size={13} /> 체크인 완료되었습니다.</span><small>SENSE PLACE에서의 편안한 여정을 시작해 보세요.</small></section>
    <section className="app-section"><div className="app-section__title"><div><p>EXPLORE SENSE PLACE</p><h2>호텔 시설 안내</h2></div><span>Today</span></div>
      <div className="facility-guide-grid">{FACILITIES.map((facility) => <article className="guide-facility-card" key={facility.name}><div className="guide-facility-icon">{facility.icon}</div><div><h3>{facility.name}</h3><p><Clock3 size={11} />{facility.time}</p><p><MapPin size={11} />{facility.location}</p></div><ChevronRight size={16} /></article>)}</div>
    </section>
    <section className="concierge-card"><div className="concierge-heading"><span><Bot size={19} /></span><div><p>AI CONCIERGE</p><h2>지금, 이렇게 이용해 보세요</h2></div><i>LIVE</i></div>
      <ul><li><span>01</span><p><b>현재 수영장이 가장 한산합니다.</b><small>여유로운 이용을 원하시면 지금 방문해 보세요.</small></p></li><li><span>02</span><p><b>조식 혼잡 예상 시간은 오전 8:00~9:00입니다.</b><small>오전 7:30 이전 이용을 추천드립니다.</small></p></li><li><span>03</span><p><b>라운지 Happy Hour는 오후 6시부터입니다.</b><small>한강 전망 좌석은 조기 마감될 수 있습니다.</small></p></li></ul>
    </section>
    <section className="quick-survey-card"><div className="survey-kicker"><Sparkles size={15} /><span>TODAY'S EXPERIENCE</span></div><h2>현재까지 호텔 이용은<br />만족스러우신가요?</h2><ExperienceScale value={score} onChange={setScore} compact />
      {score && <div className="quick-comment"><label htmlFor="today-comment">의견 남기기 <span>(선택)</span></label><textarea id="today-comment" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="더 나은 경험을 위해 의견을 들려주세요." maxLength={300} /><button type="button" onClick={() => setSent(true)}>{sent ? <><Check size={16} /> 전달 완료</> : <><Send size={15} /> 의견 보내기</>}</button></div>}
    </section><footer className="hospitality-footer">SENSE PLACE HOTELS &amp; RESORTS · SEOUL</footer>
  </div></main>;
}

const RATING_ITEMS = ["Breakfast", "Room", "Pool", "Fitness", "Staff", "Cleanliness"];
const ISSUE_ITEMS = ["체크인", "조식", "객실", "시설", "주차", "직원 응대", "청결", "기타"];

function StarRating({ value, onChange, label }) {
  return <div className="star-rating" aria-label={`${label} 별점`}>{[1,2,3,4,5].map((star) => <button type="button" key={star} aria-label={`${star}점`} className={star <= value ? "is-filled" : ""} onClick={() => onChange(star)}>★</button>)}</div>;
}

export function StayReviewPage() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const room = params.get("room") || "1208"; const from = params.get("from") || "2026.08.07"; const to = params.get("to") || "2026.08.10"; const hotel = params.get("hotel") || "Grand SENSE PLACE Seoul";
  const [overall, setOverall] = useState(null);
  const [ratings, setRatings] = useState({ Breakfast:5, Room:5, Pool:4, Fitness:4, Staff:5, Cleanliness:5 });
  const [issues, setIssues] = useState([]); const [comment, setComment] = useState(""); const [submitted, setSubmitted] = useState(false);
  const toggleIssue = (issue) => setIssues((items) => items.includes(issue) ? items.filter((item) => item !== issue) : [...items, issue]);

  if (submitted) return <main className="hospitality-page hospitality-complete"><section><div><Check size={30} /></div><p>THANK YOU</p><h1>소중한 리뷰를<br />남겨주셔서 감사합니다.</h1><span>고객님의 의견을 세심히 살펴<br />더 나은 SENSE PLACE 경험으로 보답하겠습니다.</span></section></main>;

  return <main className="hospitality-page"><div className="hospitality-shell review-shell"><BrandHeader step="STAY REVIEW" />
    <section className="review-thanks"><p>Thank You</p><h1>호텔을 이용해 주셔서<br />감사합니다.</h1><small>고객님의 소중한 경험을 들려주세요.</small></section>
    <section className="booking-card"><div><span>ROOM</span><strong>{room}</strong></div><div><span>STAY</span><strong>{from} <i>—</i> {to}</strong></div><p>{hotel}</p></section>
    <section className="overall-card"><p>OVERALL EXPERIENCE</p><h2>이번 숙박은 어떠셨나요?</h2><ExperienceScale value={overall} onChange={setOverall} /></section>
    <section className="detailed-card"><div className="review-section-title"><span>01</span><div><p>DETAILS</p><h2>시설별 만족도</h2></div></div><div className="rating-list">{RATING_ITEMS.map((item) => <div key={item}><span>{item}</span><StarRating label={item} value={ratings[item]} onChange={(value) => setRatings((current) => ({...current,[item]:value}))} /></div>)}</div></section>
    <section className="detailed-card"><div className="review-section-title"><span>02</span><div><p>IMPROVEMENT</p><h2>불편했던 점</h2><small>해당 항목을 모두 선택해 주세요.</small></div></div><div className="issue-grid">{ISSUE_ITEMS.map((issue) => <button type="button" key={issue} className={issues.includes(issue) ? "is-selected" : ""} onClick={() => toggleIssue(issue)}><i>{issues.includes(issue) && <Check size={13} />}</i>{issue}</button>)}</div></section>
    <section className="detailed-card review-comment"><div className="review-section-title"><span>03</span><div><p>YOUR VOICE</p><h2>추가 의견 작성</h2></div></div><textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} placeholder="기억에 남은 순간이나 개선되었으면 하는 점을 자유롭게 남겨주세요." /><small>{comment.length} / 500</small></section>
    <button className="review-submit" type="button" disabled={!overall} onClick={() => setSubmitted(true)}>리뷰 제출 <Send size={17} /></button><p className="review-privacy">작성하신 리뷰는 서비스 개선 목적으로 안전하게 관리됩니다.</p><footer className="hospitality-footer">SENSE PLACE HOTELS &amp; RESORTS · SEOUL</footer>
  </div></main>;
}
