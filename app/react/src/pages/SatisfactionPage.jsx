import { useMemo, useState } from "react";
import { Check, ChevronDown, LockKeyhole, Send, Sparkles } from "lucide-react";

import "../styles/satisfaction.css";
import { publishLiveVoc } from "../services/liveVoc";
import { VocPhotoUpload } from "../components/common/VocPhotoUpload";

const FACILITIES = {
  breakfast: { icon: "🥐", name: "조식 레스토랑", location: "비스타 SENSE PLACE 서울 · 2F" },
  forestPark: { icon: "🌳", name: "포레스트 파크", location: "SENSE PLACE 호텔앤리조트 · 야외 공간" },
  walkerhillLibrary: { icon: "📚", name: "SENSE PLACE 라이브러리", location: "그랜드 SENSE PLACE 서울 · 2F" },
  riverPark: { icon: "🏊", name: "리버파크 (야외수영장)", location: "SENSE PLACE 호텔앤리조트 · 야외" },
  skyard: { icon: "🌇", name: "SKYARD", location: "비스타 SENSE PLACE 서울 · 4F" },
  wellnessProgram: { icon: "🧘", name: "웰니스 프로그램", location: "비스타 SENSE PLACE 서울 · 3F 웰니스 클럽" },
  douglasGarden: { icon: "🌿", name: "더글라스 가든", location: "더글라스 하우스 옆" },
  walkee: { icon: "🥾", name: "SENSE PLACE 레저 전문가, 워키", location: "SENSE PLACE 호텔앤리조트" },
  walkingTrail: { icon: "🚶", name: "SENSE PLACE 산책로", location: "SENSE PLACE 호텔앤리조트 · 아차산" },
  vistaFitness: { icon: "💪", name: "웰니스 클럽 피트니스", location: "비스타 SENSE PLACE 서울" },
  vistaPool: { icon: "🏊", name: "웰니스 클럽 수영장", location: "비스타 SENSE PLACE 서울" },
  vSpa: { icon: "💆", name: "V SPA", location: "비스타 SENSE PLACE 서울" },
  grandFitness: { icon: "🏋️", name: "피트니스 센터", location: "그랜드 SENSE PLACE 서울" },
  grandPool: { icon: "🏊", name: "실내 수영장", location: "그랜드 SENSE PLACE 서울" },
  tennisPark: { icon: "🎾", name: "테네즈 파크", location: "그랜드 SENSE PLACE 서울" },
  douglasLibrary: { icon: "📖", name: "더글라스 라이브러리", location: "더글라스 하우스" },
  multiRoom: { icon: "🎱", name: "멀티룸", location: "더글라스 하우스" },
  cu: { icon: "🛒", name: "CU 편의점", location: "SENSE PLACE 호텔앤리조트" },
  blooming: { icon: "💐", name: "블루밍 (꽃집)", location: "SENSE PLACE 호텔앤리조트" },
  pharmacy: { icon: "💊", name: "약국", location: "SENSE PLACE 호텔앤리조트" },
  evCharger: { icon: "🔌", name: "전기차 충전기", location: "주차타워 1F · 비스타 주차장 B3F" },
  casino: { icon: "🎰", name: "SENSE PLACE 카지노", location: "SENSE PLACE 호텔앤리조트 · B1F" },
};

const RATINGS = [
  { value: 5, emoji: "😍", label: "매우 만족" },
  { value: 4, emoji: "😊", label: "만족" },
  { value: 3, emoji: "😐", label: "보통" },
  { value: 2, emoji: "😕", label: "불편" },
  { value: 1, emoji: "😡", label: "매우 불만" },
];

const REASONS = ["대기시간", "직원 응대", "청결", "시설 상태", "혼잡", "온도", "소음", "음식 품질", "좌석 부족", "기타"];

export function SatisfactionPage() {
  const initialFacilityKey = useMemo(() => new URLSearchParams(window.location.search).get("facility") || "breakfast", []);
  const [facilityKey, setFacilityKey] = useState(FACILITIES[initialFacilityKey] ? initialFacilityKey : "breakfast");
  const [facilityMenuOpen, setFacilityMenuOpen] = useState(false);
  const facility = FACILITIES[facilityKey];
  const [rating, setRating] = useState(null);
  const [reasons, setReasons] = useState([]);
  const [comment, setComment] = useState("");
  const [photos, setPhotos] = useState([]);
  const [submitted, setSubmitted] = useState(false);

  const toggleReason = (reason) => {
    setReasons((current) => current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason]);
  };

  const selectFacility = (key) => {
    setFacilityKey(key);
    setFacilityMenuOpen(false);
    setRating(null);
    setReasons([]);
    const url = new URL(window.location.href);
    url.searchParams.set("facility", key);
    window.history.replaceState({}, "", url);
  };

  const submitFeedback = (event) => {
    event.preventDefault();
    if (!rating) return;
    const facilityMap = { breakfast: "breakfast", forestPark: "lobby", walkerhillLibrary: "lobby", riverPark: "lobby", skyard: "lobby", wellnessProgram: "rooms", douglasGarden: "lobby", walkee: "lobby", walkingTrail: "lobby", vistaFitness: "rooms", vistaPool: "rooms", vSpa: "rooms", grandFitness: "rooms", grandPool: "rooms", tennisPark: "lobby", douglasLibrary: "lobby", multiRoom: "lobby", cu: "lobby", blooming: "lobby", pharmacy: "lobby", evCharger: "parking", casino: "lobby" };
    publishLiveVoc({ facilityId: facilityMap[facilityKey] || "lobby", facilityName: facility.name, rating, comment, reasons, photos, source: "facility-feedback" });
    setSubmitted(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  if (submitted) {
    return (
      <main className="satisfaction-page satisfaction-page--complete">
        <section className="thank-you-card" aria-live="polite">
          <div className="thank-you-mark"><Check size={32} strokeWidth={1.7} /></div>
          <p className="feedback-eyebrow">THANK YOU</p>
          <h1>소중한 의견을<br />전해주셔서 감사합니다.</h1>
          <p>{facility.name}에서의 다음 경험이<br />더욱 특별할 수 있도록 세심히 살피겠습니다.</p>
          <button type="button" onClick={() => { setSubmitted(false); setRating(null); setReasons([]); setComment(""); setPhotos([]); }}>
            새로운 의견 남기기
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="satisfaction-page">
      <div className="feedback-shell">
        <header className="feedback-header">
          <a className="walkerhill-wordmark" href="/" aria-label="SENSE PLACE 홈">SENSE PLACE</a>
          <span>GUEST EXPERIENCE</span>
        </header>

        <section className="feedback-intro">
          <p className="feedback-eyebrow">SERVICE EXPERIENCE</p>
          <h1>서비스 이용 만족도</h1>
          <button className="facility-card" type="button" aria-expanded={facilityMenuOpen} aria-controls="facility-menu" onClick={() => setFacilityMenuOpen((open) => !open)}>
            <div className="facility-icon" aria-hidden="true">{facility.icon}</div>
            <div>
              <span>{facility.location}</span>
              <h2>{facility.name}</h2>
            </div>
            <ChevronDown size={18} aria-hidden="true" />
          </button>
          {facilityMenuOpen && (
            <div className="facility-menu" id="facility-menu" role="listbox" aria-label="시설 선택">
              {Object.entries(FACILITIES).map(([key, item]) => (
                <button className={key === facilityKey ? "facility-option is-selected" : "facility-option"} type="button" role="option" aria-selected={key === facilityKey} key={key} onClick={() => selectFacility(key)}>
                  <span className="facility-option__icon" aria-hidden="true">{item.icon}</span>
                  <span><b>{item.name}</b><small>{item.location}</small></span>
                  {key === facilityKey && <Check size={16} />}
                </button>
              ))}
            </div>
          )}
          <p className="feedback-guide">이용 경험을 알려주시면<br />더 나은 서비스를 제공하겠습니다.</p>
        </section>

        <form className="feedback-form" onSubmit={submitFeedback}>
          <section className="rating-section" aria-labelledby="rating-title">
            <div className="rating-heading">
              <h2 id="rating-title">오늘의 경험은 어떠셨나요?</h2>
              <p>가장 가까운 표정을 선택해 주세요</p>
            </div>
            <div className="rating-grid">
              {RATINGS.map((item) => (
                <button
                  className={rating === item.value ? "rating-button is-selected" : "rating-button"}
                  key={item.value}
                  type="button"
                  aria-pressed={rating === item.value}
                  onClick={() => { setRating(item.value); setReasons([]); }}
                >
                  <span className="rating-emoji" aria-hidden="true">{item.emoji}</span>
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </section>

          {rating && (
            <section className="reason-section">
              <div className="section-title-row">
                <div><h2>어떤 점이 인상적이었나요?</h2><p>복수 선택 가능</p></div>
                <Sparkles size={18} aria-hidden="true" />
              </div>
              <div className="reason-chips">
                {REASONS.map((reason) => (
                  <button
                    className={reasons.includes(reason) ? "reason-chip is-selected" : "reason-chip"}
                    key={reason}
                    type="button"
                    aria-pressed={reasons.includes(reason)}
                    onClick={() => toggleReason(reason)}
                  >
                    {reasons.includes(reason) && <Check size={13} strokeWidth={2.5} />}{reason}
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="comment-section">
            <label htmlFor="feedback-comment">추가 의견 <span>(선택)</span></label>
            <div className="comment-box">
              <textarea
                id="feedback-comment"
                value={comment}
                maxLength={300}
                placeholder="더 나은 서비스를 위해 자유롭게 의견을 남겨주세요."
                onChange={(event) => setComment(event.target.value)}
              />
              <span>{comment.length} / 300</span>
            </div>
          </section>

          <VocPhotoUpload id="feedback-photos" files={photos} onChange={setPhotos} />

          <button className="feedback-submit" type="submit" disabled={!rating}>
            <span>피드백 보내기</span><Send size={17} strokeWidth={1.8} />
          </button>
          <p className="privacy-note"><LockKeyhole size={12} /> 보내주신 의견은 서비스 개선 목적으로만 활용됩니다.</p>
        </form>

        <footer>SENSE PLACE HOTELS &amp; RESORTS <span>·</span> SEOUL</footer>
      </div>
    </main>
  );
}
