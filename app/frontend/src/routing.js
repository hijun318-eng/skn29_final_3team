/** 브라우저 pathname을 허용된 화면으로 해석하는 routing 계약 모듈이다. */
/** 브라우저와 상단 내비게이션이 공유하는 공개 페이지 경로 계약이다. */
export const PAGE_PATHS = { chat: "/agent", reports: "/reports", admin: "/admin" };

const ROUTES = { "/agent": { page: "chat" }, "/reports": { page: "reports" }, "/admin": { page: "admin" } };

function normalizePath(pathname) {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

/** pathname을 허용된 화면 계약으로 정규화하며 알 수 없는 경로는 notFound로 닫는다. */
export function resolveRoute(pathname) {
  const path = normalizePath(pathname);
  if (path === "/") return { page: "chat", path: PAGE_PATHS.chat, redirected: true };
  const matched = ROUTES[path];
  return matched ? { ...matched, path, redirected: false } : { page: "notFound", path, redirected: false };
}
