export const PAGE_PATHS = {
  chat: "/agent",
  customer: "/customers",
  reports: "/reports",
  catalog: "/catalog",
  connections: "/connections",
};

export const CATALOG_TAB_PATHS = {
  catalog: "/catalog",
  ontology: "/catalog/ontology",
  tools: "/catalog/tools",
};

const ROUTES = {
  "/agent": { page: "chat" },
  "/customers": { page: "customer" },
  "/reports": { page: "reports" },
  "/catalog": { page: "catalog", catalogTab: "catalog" },
  "/catalog/ontology": { page: "catalog", catalogTab: "ontology" },
  "/catalog/tools": { page: "catalog", catalogTab: "tools" },
  "/connections": { page: "connections" },
};

function normalizePath(pathname) {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

export function resolveRoute(pathname) {
  const path = normalizePath(pathname);
  const matched = ROUTES[path];

  if (matched) return { ...matched, path, redirected: false };

  return {
    page: "chat",
    path: PAGE_PATHS.chat,
    redirected: true,
  };
}
