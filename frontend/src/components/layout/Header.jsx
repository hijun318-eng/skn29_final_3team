import { useState } from "react";
import { ChevronDown, LogIn, LogOut, UserRound } from "lucide-react";
import { getDemoSession, signOutDemo } from "../../services/demoAuth";
import { NotificationBell } from "../common/NotificationBell";

export function HeaderUtilities() {
  const [profileOpen, setProfileOpen] = useState(false);
  const session = getDemoSession();
  const [language, setLanguage] = useState("KOR");

  const selectLanguage = (nextLanguage) => {
    setLanguage(nextLanguage);
    document.documentElement.lang = nextLanguage === "KOR" ? "ko" : "en";
  };

  return <div className="header-utilities">
        <div className="header-live-status"><i /><span><b>실시간 연결</b><small>마지막 갱신 10:42:18</small></span></div>
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
          {session ? <><button className="profile" type="button" aria-label="프로필 메뉴 열기" aria-expanded={profileOpen} onClick={() => setProfileOpen((value) => !value)}><span>MS</span><ChevronDown size={14} /></button>
          {profileOpen && <div className="profile-menu"><div><UserRound size={16} /><span><b>{session.name || "Minji Song"}</b><small>{session.email || "manager@senseplace.kr"}</small></span></div><button type="button" onClick={() => { signOutDemo(); window.location.replace("/login"); }}><LogOut size={15} />로그아웃</button></div>}</> : <a className="header-login" href="/login"><LogIn size={14} />로그인</a>}
        </div>
        <span className="app-version">ver 1.0</span>
      </div>;
}

export function Header({ eyebrow = "EXTERNAL REVIEW INTELLIGENCE", title = "외부 리뷰 데이터", description }) {
  return (
    <header className="top-header admin-page-header">
      <div className="headline">
        <p>{eyebrow}</p>
        <h1>{title}</h1>
        <span>{description}</span>
      </div>
      <HeaderUtilities />
    </header>
  );
}
