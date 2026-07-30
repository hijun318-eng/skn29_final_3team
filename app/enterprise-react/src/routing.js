export const PAGE_PATHS = {
  chat: "/agent",
  reports: "/reports",
  catalog: "/catalog",
  connections: "/catalog/connections",
};

const ROUTES = {
  "/agent": { page: "chat" },
  "/reports": { page: "reports" },
  "/catalog": { page: "catalog" },
  "/catalog/connections": { page: "connections" },
};

function normalizePath(pathname) {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

export function resolveRoute(pathname) {
  const path = normalizePath(pathname);
  if (path === "/") return { page: "chat", path: PAGE_PATHS.chat, redirected: true };
  if (path === "/connections") return { page: "connections", path: PAGE_PATHS.connections, redirected: true };
  const matched = ROUTES[path];

  if (matched) return { ...matched, path, redirected: false };

  return {
    page: "notFound",
    path,
    redirected: false,
  };
}
