/** 표시 모드 기본값·저장소 복원·전환 규칙을 소유하는 브라우저 설정 모듈이다. */
export const THEME_STORAGE_KEY = "answervice.theme";

/** 저장된 값이 명시적 dark일 때만 다크를 복원하고 나머지는 기본 라이트로 닫는다. */
export function readTheme(storage = window.localStorage) {
  try { return storage.getItem(THEME_STORAGE_KEY) === "dark" ? "dark" : "light"; }
  catch { return "light"; }
}

/** 현재 표시 모드에서 반대 모드로 전환한다. */
export function nextTheme(theme) {
  return theme === "dark" ? "light" : "dark";
}

/** 선택한 표시 모드를 비민감 사용자 환경설정으로 저장하며 저장소 차단은 화면에 전파하지 않는다. */
export function saveTheme(theme, storage = window.localStorage) {
  try { storage.setItem(THEME_STORAGE_KEY, theme); }
  catch { /* 현재 화면 선택은 유지하고 다음 방문에서만 기본 라이트로 복귀한다. */ }
}
