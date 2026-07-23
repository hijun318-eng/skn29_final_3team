import { useState } from "react";
import { ChevronDown, LogOut, UserRound } from "lucide-react";
import { getDemoSession, signOutDemo } from "../../services/demoAuth";
import { NotificationBell } from "../common/NotificationBell";

function SelectFilter({ label, value, options, onChange }) {
  const selectProps = onChange ? { value, onChange } : { defaultValue: value };
  return (
    <label className="filter-control">
      <span>{label}</span>
      <div className="select-wrap">
        <select aria-label={label} {...selectProps}>
          {options.map((option) => <option key={option}>{option}</option>)}
        </select>
        <ChevronDown size={15} />
      </div>
    </label>
  );
}

export function Header() {
  const [profileOpen, setProfileOpen] = useState(false);
  const session = getDemoSession();
  const [language, setLanguage] = useState("KOR");
  const periods = {
    "2026년 7월 1주차": "7월 1일 ~ 7월 6일",
    "2026년 7월 2주차": "7월 7일 ~ 7월 13일",
    "2026년 7월 3주차": "7월 14일 ~ 7월 20일",
    "2026년 7월 4주차": "7월 21일 ~ 7월 27일",
    "2026년 8월 1주차": "7월 28일 ~ 8월 3일",
  };
  const [period, setPeriod] = useState("2026년 7월 2주차");

  const selectLanguage = (nextLanguage) => {
    setLanguage(nextLanguage);
    document.documentElement.lang = nextLanguage === "KOR" ? "ko" : "en";
  };

  return (
    <header className="top-header admin-page-header">
      <div className="headline">
        <p>OPERATION INTELLIGENCE</p>
        <h1>호텔 운영 및 VOC 대시보드</h1>
        <span>{period} — {periods[period]}</span>
      </div>

      <div className="header-actions">
        <div className="filters">
          <SelectFilter label="호텔" value="SENSE PLACE 서울" options={["SENSE PLACE 서울", "비스타 SENSE PLACE", "그랜드 SENSE PLACE", "더글라스 하우스"]} />
          <SelectFilter label="시설" value="전체 시설" options={["전체 시설", "프론트 데스크", "객실", "레스토랑"]} />
          <SelectFilter label="기간" value={period} options={Object.keys(periods)} onChange={(event) => setPeriod(event.target.value)} />
          <SelectFilter label="채널" value="전체 채널" options={["전체 채널", "OTA", "네이버", "구글", "카카오"]} />
        </div>
        <div className="language-switch" role="group" aria-label="언어 선택">
          {['KOR', 'ENG'].map((option) => (
            <button
              className={language === option ? "is-active" : ""}
              key={option}
              type="button"
              aria-pressed={language === option}
              onClick={() => selectLanguage(option)}
            >
              {option}
            </button>
          ))}
        </div>
        <NotificationBell />
        <div className="profile-wrap">
          <button className="profile" type="button" aria-label="프로필 메뉴 열기" aria-expanded={profileOpen} onClick={() => setProfileOpen((value) => !value)}><span>MS</span><div><b>{session?.name || "Minji Song"}</b><small>{session?.role || "Operations Manager"}</small></div><ChevronDown size={14} /></button>
          {profileOpen && <div className="profile-menu"><div><UserRound size={16} /><span><b>{session?.name || "Minji Song"}</b><small>{session?.email || "manager@senseplace.kr"}</small></span></div><button type="button" onClick={() => { signOutDemo(); window.location.replace("/login"); }}><LogOut size={15} />로그아웃</button></div>}
        </div>
      </div>
    </header>
  );
}
