/** 애플리케이션의 라이트·다크 표시 모드를 전환하는 공통 버튼 모듈이다. */
import { Moon, Sun } from "lucide-react";

/** 현재 표시 모드와 다음 동작을 함께 알려 주는 접근 가능한 테마 전환 버튼이다. */
export function ThemeToggle({ theme, onToggle, className = "" }) {
  const dark = theme === "dark";
  const actionLabel = dark ? "라이트 모드로 전환" : "다크 모드로 전환";
  return <button className={`theme-toggle ${className}`.trim()} type="button" aria-label={actionLabel} aria-pressed={dark} title={actionLabel} onClick={onToggle}>
    {dark ? <Moon size={15} /> : <Sun size={15} />}
    <span>{dark ? "다크" : "라이트"}</span>
  </button>;
}
