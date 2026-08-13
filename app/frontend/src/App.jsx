import { lazy, Suspense, useCallback, useEffect, useMemo, useState, useTransition } from "react";
import { AppHeader } from "./components/layout/AppHeader";
import { AppSidebar } from "./components/layout/AppSidebar";
import { SessionLogin } from "./components/auth/SessionLogin";
import { PAGE_PATHS, resolveRoute } from "./routing";

const AgentPage = lazy(() => import("./pages/AgentPage").then((module) => ({ default: module.AgentPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })));

const PAGE_META = {
  chat: ["분석 Agent", "질문과 조회 기간을 입력해 통합 데이터를 분석합니다."],
  reports: ["Report", "서버에 저장된 보고서 초안을 작성하고 조회합니다."],
  notFound: ["페이지를 찾을 수 없습니다", "현재 제공되는 경로를 확인해 주세요."],
};

function NotFoundPage({ onNavigate }) {
  return <section className="not-found" aria-labelledby="not-found-title"><span>404</span><h2 id="not-found-title">지원하지 않는 경로입니다.</h2><button className="primary" onClick={() => onNavigate(PAGE_PATHS.chat)}>분석 Agent로 이동</button></section>;
}

function RoleAccessPage({ role, onNavigate }) {
  const canManageReports = role === "report_admin";
  return <section className="not-found" aria-labelledby="role-access-title"><span>403</span><h2 id="role-access-title">분석 Agent 접근 권한이 없습니다.</h2><p>분석은 hotel_analyst 계정에서만 실행할 수 있습니다.</p>{canManageReports && <button className="primary" onClick={() => onNavigate(PAGE_PATHS.reports)}>Report 관리로 이동</button>}</section>;
}

export function App() {
  const [session, setSession] = useState(null);
  const authToken = session?.token || "";
  const role = session?.role || "";
  const [route, setRoute] = useState(() => resolveRoute(window.location.pathname));
  const [menuOpen, setMenuOpen] = useState(true);
  const [isPending, startTransition] = useTransition();
  const [title, description] = route.page === "reports" && role === "report_admin"
    ? ["Report", "서버에 저장된 보고서 정의, 실행, 예약을 관리합니다."]
    : PAGE_META[route.page];

  useEffect(() => {
    const initialRoute = resolveRoute(window.location.pathname);
    if (initialRoute.redirected) { window.history.replaceState({}, "", initialRoute.path); setRoute(initialRoute); }
    const handlePopState = () => { setMenuOpen(false); startTransition(() => setRoute(resolveRoute(window.location.pathname))); };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback((nextPath) => {
    const nextRoute = resolveRoute(nextPath);
    if (nextRoute.path === route.path) {
      window.dispatchEvent(new CustomEvent("answervice:navigate", { detail: nextRoute.path }));
      setMenuOpen(false);
      return;
    }
    window.history.pushState({}, "", nextRoute.path);
    setMenuOpen(false);
    startTransition(() => setRoute(nextRoute));
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "instant" }));
  }, [route.path]);

  useEffect(() => {
    if (role === "report_admin" && route.page === "chat") navigate(PAGE_PATHS.reports);
  }, [navigate, role, route.page]);

  const content = useMemo(() => {
    if (route.page === "notFound") return <NotFoundPage onNavigate={navigate} />;
    if (route.page === "reports") return <ReportsPage authToken={authToken} role={role} />;
    if (role !== "hotel_analyst") return <RoleAccessPage role={role} onNavigate={navigate} />;
    return <AgentPage authToken={authToken} onNavigate={navigate} />;
  }, [authToken, navigate, role, route.page]);

  if (!session) return <SessionLogin onAuthenticated={setSession} />;

  const signOut = () => setSession(null);

  return <div className={`app-shell ppt-theme ${menuOpen ? "" : "sidebar-collapsed"} ${isPending ? "is-page-pending" : ""}`}>
    <AppSidebar page={route.page} role={role} onNavigate={navigate} open={menuOpen} onClose={() => setMenuOpen(false)} />
    <div className="workspace"><AppHeader title={title} description={description} onMenu={() => setMenuOpen(true)} onSignOut={signOut} /><div className="page-progress" aria-hidden="true" /><main className="page-stage" key={route.path} aria-busy={isPending}><Suspense fallback={<div className="page-loading"><i /><b>페이지를 준비하고 있습니다.</b></div>}>{content}</Suspense></main></div>
  </div>;
}
