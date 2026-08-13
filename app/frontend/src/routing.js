export const PAGE_PATHS = { chat: "/agent", reports: "/reports" };

const ROUTES = { "/agent": { page: "chat" }, "/reports": { page: "reports" } };

function normalizePath(pathname) {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

export function resolveRoute(pathname) {
  const path = normalizePath(pathname);
  if (path === "/") return { page: "chat", path: PAGE_PATHS.chat, redirected: true };
  const matched = ROUTES[path];
  return matched ? { ...matched, path, redirected: false } : { page: "notFound", path, redirected: false };
}
