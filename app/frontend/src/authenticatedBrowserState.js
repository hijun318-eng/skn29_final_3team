/** 인증 사용자에게 귀속된 브라우저 임시 상태의 공통 namespace다. */
export const AUTHENTICATED_STORAGE_KEY_PREFIXES = Object.freeze([
  "answervice.",
  "answervice:",
]);

/**
 * 로그아웃·세션 만료 시 대화·질문·보고서 draft가 다음 계정에 이어지지 않게 제거한다.
 * 다른 애플리케이션이 같은 origin에 저장한 키는 건드리지 않는다.
 */
export function clearAuthenticatedBrowserState(storage = window.sessionStorage) {
  for (let index = storage.length - 1; index >= 0; index -= 1) {
    const key = storage.key(index);
    if (
      key
      && AUTHENTICATED_STORAGE_KEY_PREFIXES.some((prefix) => key.startsWith(prefix))
    ) {
      storage.removeItem(key);
    }
  }
}
