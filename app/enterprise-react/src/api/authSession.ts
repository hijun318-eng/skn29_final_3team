const STORAGE_KEY = "answervice.auth.token";

export function getAuthorizationHeader(): string {
  const token = sessionStorage.getItem(STORAGE_KEY)?.trim();
  if (!token) throw new Error("로그인 토큰을 먼저 입력해 주세요.");
  return `Bearer ${token}`;
}

export function hasAuthSession(): boolean {
  return Boolean(sessionStorage.getItem(STORAGE_KEY)?.trim());
}

export function saveAuthSession(token: string): void {
  const normalized = token.trim();
  if (!normalized) throw new Error("로그인 토큰은 비어 있을 수 없습니다.");
  sessionStorage.setItem(STORAGE_KEY, normalized);
}

export function clearAuthSession(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
