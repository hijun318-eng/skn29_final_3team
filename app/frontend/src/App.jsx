import { lazy, Suspense, useCallback, useEffect, useMemo, useState, useTransition } from "react";
import { AppHeader } from "./components/layout/AppHeader";
import { AppSidebar } from "./components/layout/AppSidebar";
import { SessionLogin } from "./components/auth/SessionLogin";
import { createAnalysisClient } from "./api/analysisClient.ts";
import { PAGE_PATHS, resolveRoute } from "./routing";

const AgentPage = lazy(() => import("./pages/AgentPage").then((module) => ({ default: module.AgentPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })));

const PAGE_META = {
  chat: ["데이터 분석", "자연어로 질문하면 지표와 기간을 해석해 데이터를 분석합니다."],
  reports: ["보고서", "분석 결과를 보고서로 구성하고 편집·검토합니다."],
  notFound: ["페이지를 찾을 수 없습니다", "현재 제공되는 경로를 확인해 주세요."],
};

function NotFoundPage({ onNavigate }) {
  return <section className="not-found" aria-labelledby="not-found-title"><span>404</span><h2 id="not-found-title">지원하지 않는 경로입니다.</h2><button className="primary" onClick={() => onNavigate(PAGE_PATHS.chat)}>데이터 분석으로 이동</button></section>;
}

function RoleAccessPage({ role, onNavigate }) {
  const canManageReports = role === "report_admin";
  return <section className="not-found" aria-labelledby="role-access-title"><span>403</span><h2 id="role-access-title">이 화면에 접근할 권한이 없습니다.</h2><p>{canManageReports ? "현재 계정은 보고서 관리 기능만 사용할 수 있습니다." : "현재 계정에 허용된 서비스 메뉴가 없습니다."}</p>{canManageReports && <button className="primary" onClick={() => onNavigate(PAGE_PATHS.reports)}>보고서 관리로 이동</button>}</section>;
}

export function App() {
  const [session, setSession] = useState();
  const [sessionNotice, setSessionNotice] = useState("");
  const [reportEditorMode, setReportEditorMode] = useState(false);
  const authToken = session?.token || "";
  const role = session?.role || "";
  const [route, setRoute] = useState(() => resolveRoute(window.location.pathname));
  const [menuOpen, setMenuOpen] = useState(() => window.matchMedia("(min-width: 901px)").matches);
  const [isPending, startTransition] = useTransition();
  const [title, description] = route.page === "reports"
    ? reportEditorMode
      ? ["보고서 편집", "검증된 분석 결과와 설명을 블록으로 구성하고 저장합니다."]
      : ["보고서", "분석 결과를 보고서로 구성하고 편집·검토합니다."]
    : PAGE_META[route.page];

  useEffect(() => {
    let active = true;
    createAnalysisClient(fetch).validateSession()
      .then((restored) => { if (active) setSession({ token: "", role: restored.role }); })
      .catch(() => { if (active) setSession(null); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const expireSession = () => setSessionNotice("세션이 만료되었습니다. 작성 중인 내용은 유지됩니다. 다시 로그인해 주세요.");
    window.addEventListener("answervice:session-expired", expireSession);
    return () => window.removeEventListener("answervice:session-expired", expireSession);
  }, []);

  useEffect(() => {
    const initialRoute = resolveRoute(window.location.pathname);
    if (initialRoute.redirected) { window.history.replaceState({}, "", initialRoute.path); setRoute(initialRoute); }
    const handlePopState = () => { if (window.matchMedia("(max-width: 900px)").matches) setMenuOpen(false); startTransition(() => setRoute(resolveRoute(window.location.pathname))); };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 901px)");
    const syncMenu = (event) => setMenuOpen(event.matches);
    desktop.addEventListener("change", syncMenu);
    return () => desktop.removeEventListener("change", syncMenu);
  }, []);

  const navigate = useCallback((nextPath) => {
    const nextRoute = resolveRoute(nextPath);
    if (nextRoute.path === route.path) {
      window.dispatchEvent(new CustomEvent("answervice:navigate", { detail: nextRoute.path }));
      if (window.matchMedia("(max-width: 900px)").matches) setMenuOpen(false);
      return;
    }
    window.history.pushState({}, "", nextRoute.path);
    if (window.matchMedia("(max-width: 900px)").matches) setMenuOpen(false);
    startTransition(() => setRoute(nextRoute));
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "instant" }));
  }, [route.path]);

  const handleReportEditorMode = useCallback((active) => {
    setReportEditorMode(active);
    if (window.matchMedia("(min-width: 901px)").matches) setMenuOpen(!active);
  }, []);

  useEffect(() => {
    if (role === "report_admin" && route.page === "chat") navigate(PAGE_PATHS.reports);
  }, [navigate, role, route.page]);

  const content = useMemo(() => {
    if (route.page === "notFound") return <NotFoundPage onNavigate={navigate} />;
    if (route.page === "reports") {
      if (!["hotel_analyst", "report_admin"].includes(role)) return <RoleAccessPage role={role} onNavigate={navigate} />;
      return <ReportsPage authToken={authToken} role={role} onEditorMode={handleReportEditorMode} />;
    }
    if (role !== "hotel_analyst") return <RoleAccessPage role={role} onNavigate={navigate} />;
    return <AgentPage authToken={authToken} onNavigate={navigate} />;
  }, [authToken, handleReportEditorMode, navigate, role, route.page]);

  if (session === undefined) return <main className="session-login ppt-theme"><div className="page-loading" role="status"><i /><b>세션을 확인하고 있습니다.</b></div></main>;
  if (!session) return <SessionLogin notice={sessionNotice} onAuthenticated={(nextSession) => { setSession(nextSession); setSessionNotice(""); }} />;

  const signOut = async () => {
    window.dispatchEvent(new CustomEvent("answervice:clear-drafts"));
    try { await createAnalysisClient(fetch, authToken).logout(); } finally { setSessionNotice(""); setSession(null); }
  };

  return <><div className={`app-shell ppt-theme ${menuOpen ? "" : "sidebar-collapsed"} ${reportEditorMode ? "report-editor-mode" : ""} ${isPending ? "is-page-pending" : ""} ${sessionNotice ? "session-locked" : ""}`} inert={sessionNotice ? true : undefined} aria-hidden={sessionNotice ? "true" : undefined}>
    <AppSidebar page={route.page} role={role} onNavigate={navigate} open={menuOpen} onClose={() => setMenuOpen(false)} />
    <div className="workspace"><AppHeader title={title} description={description} role={role} onMenu={() => setMenuOpen(true)} onSignOut={signOut} /><div className="page-progress" aria-hidden="true" /><main className="page-stage" key={route.path} aria-busy={isPending}><Suspense fallback={<div className="page-loading"><i /><b>페이지를 준비하고 있습니다.</b></div>}>{content}</Suspense></main></div>
  </div>{sessionNotice && <div className="session-reauth-layer" role="dialog" aria-modal="true" aria-label="세션 만료"><SessionLogin embedded notice={sessionNotice} onAuthenticated={(nextSession) => { setSession(nextSession); setSessionNotice(""); }} /></div>}</>;
}
