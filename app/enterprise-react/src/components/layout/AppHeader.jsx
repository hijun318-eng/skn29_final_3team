import { Menu, Moon, Sun } from "lucide-react";

export function AppHeader({ title, description, onMenu, menuOpen, theme, onThemeToggle }) {
  return (
    <header className="topbar">
      <button className="mobile-menu" onClick={onMenu} aria-label="메뉴 열기" aria-controls="main-navigation" aria-expanded={menuOpen}>
        <Menu size={20} />
      </button>
      <div>
        <h1>{title}</h1>
        <span>{description}</span>
      </div>
      <div className="top-actions">
        <span className="live"><i />Synthetic</span>
        <button onClick={onThemeToggle} aria-label={`${theme === "dark" ? "라이트" : "다크"} 테마로 전환`}>
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <div className="avatar">A</div>
      </div>
    </header>
  );
}
