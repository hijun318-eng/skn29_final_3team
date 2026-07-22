import { useState } from "react";
import { Bell, ChevronDown } from "lucide-react";

function SelectFilter({ label, value, options }) {
  return (
    <label className="filter-control">
      <span>{label}</span>
      <div className="select-wrap">
        <select defaultValue={value} aria-label={label}>
          {options.map((option) => <option key={option}>{option}</option>)}
        </select>
        <ChevronDown size={15} />
      </div>
    </label>
  );
}

export function Header() {
  const [language, setLanguage] = useState("KOR");

  const selectLanguage = (nextLanguage) => {
    setLanguage(nextLanguage);
    document.documentElement.lang = nextLanguage === "KOR" ? "ko" : "en";
  };

  return (
    <header className="top-header">
      <div className="headline">
        <p>OPERATION INTELLIGENCE</p>
        <h1>호텔 VOC 운영 대시보드</h1>
        <span>2026년 7월 2주차 — 7월 7일 ~ 7월 13일</span>
      </div>

      <div className="header-actions">
        <div className="filters">
          <SelectFilter label="호텔" value="SENSE PLACE 서울" options={["SENSE PLACE 서울", "비스타 SENSE PLACE", "그랜드 SENSE PLACE", "더글라스 하우스"]} />
          <SelectFilter label="시설" value="전체 시설" options={["전체 시설", "프론트 데스크", "객실", "레스토랑"]} />
          <label className="filter-control date-filter">
            <span>기간</span>
            <input type="text" defaultValue="2026년 7월 2주차" aria-label="기간" />
          </label>
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
        <button className="icon-button" aria-label="Notifications"><Bell size={20} /><i /></button>
        <button className="profile" aria-label="Open profile"><span>MS</span><div><b>Minji Song</b><small>Operations Manager</small></div></button>
      </div>
    </header>
  );
}
