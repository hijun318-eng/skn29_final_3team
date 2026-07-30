import { lazy, Suspense, useCallback, useEffect, useMemo, useState, useTransition } from "react";
import { AppHeader } from "./components/layout/AppHeader";
import { AppSidebar } from "./components/layout/AppSidebar";
import { PAGE_PATHS, resolveRoute } from "./routing";

const AgentPage = lazy(() => import("./pages/AgentPage").then((module) => ({ default: module.AgentPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })));
const CatalogPage = lazy(() => import("./pages/CatalogPage").then((module) => ({ default: module.CatalogPage })));
const ConnectionsPage = lazy(() => import("./pages/ConnectionsPage").then((module) => ({ default: module.ConnectionsPage })));

const PAGE_META = {
  chat: ["분석 Agent", "자연어 질문으로 승인된 기업 데이터를 수집·분석합니다."],
  reports: ["정기 보고서", "일일·주간·월간 비즈니스 인사이트를 생성하고 검토합니다."],
  catalog: ["데이터 카탈로그", "사일로 DB의 연결 정보와 데이터 제품·온톨로지를 탐색합니다."],
  connections: ["DB 연결 관리", "이기종 데이터 소스의 connector와 catalog 상태를 관리합니다."],
  notFound: ["페이지를 찾을 수 없습니다", "현재 승인된 P0/P1 경로만 이용할 수 있습니다."],
};

function NotFoundPage({ onNavigate }) {
  return (
    <section className="not-found" aria-labelledby="not-found-title">
      <span>404</span>
      <h2 id="not-found-title">승인되지 않은 경로입니다.</h2>
      <p>P2 Tool과 고객 360은 I5 이후 별도 Gate 승인 전까지 제공하지 않습니다.</p>
      <button className="primary" onClick={() => onNavigate(PAGE_PATHS.chat)}>분석 Agent로 이동</button>
    </section>
  );
}

export function App() {
  const [route, setRoute] = useState(() => resolveRoute(window.location.pathname));
  const [menuOpen, setMenuOpen] = useState(false);
  const [isPending, startTransition] = useTransition();
  const page = route.page;
  const [title, description] = PAGE_META[page];

  useEffect(() => {
    const initialRoute = resolveRoute(window.location.pathname);
    if (initialRoute.redirected) {
      window.history.replaceState({}, "", initialRoute.path);
      setRoute(initialRoute);
    }

    const handlePopState = () => {
      startTransition(() => setRoute(resolveRoute(window.location.pathname)));
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback((nextPath) => {
    const nextRoute = resolveRoute(nextPath);
    if (nextRoute.path === route.path) return;

    window.history.pushState({}, "", nextRoute.path);
    startTransition(() => setRoute(nextRoute));
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "instant" }));
  }, [route.path]);

  const content = useMemo(() => {
    if (page === "notFound") return <NotFoundPage onNavigate={navigate} />;
    if (page === "reports") return <ReportsPage />;
    if (page === "connections") return <ConnectionsPage />;
    if (page === "catalog") {
      return (
        <CatalogPage
          onManageConnections={() => navigate("/connections")}
        />
      );
    }
    return <AgentPage />;
  }, [navigate, page]);

  return (
    <div className={`app-shell ${isPending ? "is-page-pending" : ""}`}>
      <AppSidebar
        page={page}
        onNavigate={navigate}
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
      />
      <div className="workspace">
        <AppHeader title={title} description={description} onMenu={() => setMenuOpen(true)} />
        <div className="page-progress" aria-hidden="true" />
        <main className="page-stage" key={route.path} aria-busy={isPending}>
          <Suspense fallback={<div className="page-loading"><i /><b>페이지를 준비하고 있습니다.</b></div>}>
            {content}
          </Suspense>
        </main>
      </div>
    </div>
  );
}
