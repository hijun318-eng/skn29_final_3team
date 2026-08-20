/** 인증된 애플리케이션 셸의 세션·권한·라우팅·lazy loading 경계를 조정하는 모듈이다. */
import { lazy, Suspense, useCallback, useEffect, useMemo, useState, useTransition } from "react";
import { AppHeader } from "./components/layout/AppHeader";
import { AppSidebar } from "./components/layout/AppSidebar";
import { SessionLogin } from "./components/auth/SessionLogin";
import { createAnalysisClient } from "./api/analysisClient.ts";
import { CAPABILITY, hasCapability } from "./authorization.ts";
import { PAGE_PATHS, resolveRoute } from "./routing";

const AgentPage = lazy(() => import("./pages/AgentPage").then((module) => ({ default: module.AgentPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })));

const PAGE_META = {
  chat: ["데이터 분석", "자연어로 질문하면 지표와 기간을 해석해 데이터를 분석합니다."],
  reports: ["보고서", "분석 결과를 보고서로 구성하고 편집·검토합니다."],
  notFound: ["페이지를 찾을 수 없습니다", "현재 제공되는 경로를 확인해 주세요."],
};

/** 알 수 없는 경로를 표시하고 유효한 분석 경로로만 복귀시킨다. */
function NotFoundPage({ onNavigate }) {
  return <section className="not-found" aria-labelledby="not-found-title"><span>404</span><h2 id="not-found-title">지원하지 않는 경로입니다.</h2><button className="primary" onClick={() => onNavigate(PAGE_PATHS.chat)}>데이터 분석으로 이동</button></section>;
}

/** 세션 역할에 허용되지 않은 화면을 차단하고 가능한 허용 경로만 안내한다. */
function RoleAccessPage({ canUseReports, onNavigate }) {
  return <section className="not-found" aria-labelledby="role-access-title"><span>403</span><h2 id="role-access-title">이 화면에 접근할 권한이 없습니다.</h2><p>{canUseReports ? "현재 계정은 보고서 기능만 사용할 수 있습니다." : "현재 계정에 허용된 서비스 메뉴가 없습니다."}</p>{canUseReports && <button className="primary" onClick={() => onNavigate(PAGE_PATHS.reports)}>보고서로 이동</button>}</section>;
}

/** 세션·권한·라우팅 경계를 소유하며, 인증 확인 전에는 보호된 화면을 렌더링하지 않는다. */
export function App() {
  const [session, setSession] = useState();
  const [sessionNotice, setSessionNotice] = useState("");
  const [reportEditorMode, setReportEditorMode] = useState(false);
  const [reportDirty, setReportDirty] = useState(false);
  const role = session?.role || "";
  const capabilities = session?.capabilities;
  const canRunAnalysis = hasCapability(capabilities, CAPABILITY.runAnalysis);
  const canDraftReport = hasCapability(capabilities, CAPABILITY.draftReport);
  const canManageReports = hasCapability(capabilities, CAPABILITY.manageReport);
  const canUseReports = canDraftReport || canManageReports;
  const [route, setRoute] = useState(() => resolveRoute(window.location.pathname));
  const [menuOpen, setMenuOpen] = useState(() => window.matchMedia("(min-width: 1101px)").matches);
  const [isPending, startTransition] = useTransition();
  const [title, description] = route.page === "reports"
    ? reportEditorMode
      ? ["보고서 편집", "근거가 연결된 분석 결과와 설명을 블록으로 구성하고 저장합니다."]
      : ["보고서", "분석 결과를 보고서로 구성하고 편집·검토합니다."]
    : PAGE_META[route.page];

  useEffect(() => {
    let active = true;
    createAnalysisClient(fetch).validateSession()
      .then((restored) => { if (active) setSession(restored); })
      .catch(() => { if (active) setSession(null); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const updateDirty = (event) => setReportDirty(Boolean(event.detail));
    window.addEventListener("answervice:report-dirty", updateDirty);
    return () => window.removeEventListener("answervice:report-dirty", updateDirty);
  }, []);

  useEffect(() => {
    const expireSession = () => setSessionNotice("세션이 만료되었습니다. 작성 중인 내용은 유지됩니다. 다시 로그인해 주세요.");
    window.addEventListener("answervice:session-expired", expireSession);
    return () => window.removeEventListener("answervice:session-expired", expireSession);
  }, []);

  useEffect(() => {
    const initialRoute = resolveRoute(window.location.pathname);
    if (initialRoute.redirected) { window.history.replaceState({}, "", initialRoute.path); setRoute(initialRoute); }
    const handlePopState = () => {
      if (reportDirty && !window.confirm("저장하지 않은 보고서 변경사항이 있습니다. 페이지를 이동할까요?")) {
        window.history.pushState({}, "", route.path);
        return;
      }
      if (window.matchMedia("(max-width: 1100px)").matches) setMenuOpen(false);
      startTransition(() => setRoute(resolveRoute(window.location.pathname)));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [reportDirty, route.path]);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1101px)");
    const syncMenu = (event) => setMenuOpen(event.matches);
    desktop.addEventListener("change", syncMenu);
    return () => desktop.removeEventListener("change", syncMenu);
  }, []);

  const navigate = useCallback((nextPath) => {
    const nextRoute = resolveRoute(nextPath);
    if (nextRoute.path === route.path) {
      window.dispatchEvent(new CustomEvent("answervice:navigate", { detail: nextRoute.path }));
      if (window.matchMedia("(max-width: 1100px)").matches) setMenuOpen(false);
      return;
    }
    if (reportDirty && !window.confirm("저장하지 않은 보고서 변경사항이 있습니다. 페이지를 이동할까요?")) return;
    window.history.pushState({}, "", nextRoute.path);
    if (window.matchMedia("(max-width: 1100px)").matches) setMenuOpen(false);
    startTransition(() => setRoute(nextRoute));
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "instant" }));
  }, [reportDirty, route.path]);

  const handleReportEditorMode = useCallback((active) => {
    setReportEditorMode(active);
    setMenuOpen(window.matchMedia("(min-width: 1101px)").matches && !active);
  }, []);

  useEffect(() => {
    if (!canRunAnalysis && canUseReports && route.page === "chat") navigate(PAGE_PATHS.reports);
  }, [canRunAnalysis, canUseReports, navigate, route.page]);

  const content = useMemo(() => {
    if (route.page === "notFound") return <NotFoundPage onNavigate={navigate} />;
    if (route.page === "reports") {
      if (!canUseReports) return <RoleAccessPage canUseReports={false} onNavigate={navigate} />;
      return <ReportsPage role={role} isAdmin={canManageReports} onEditorMode={handleReportEditorMode} />;
    }
    if (!canRunAnalysis) return <RoleAccessPage canUseReports={canUseReports} onNavigate={navigate} />;
    return <AgentPage onNavigate={navigate} />;
  }, [canManageReports, canRunAnalysis, canUseReports, handleReportEditorMode, navigate, role, route.page]);

  if (session === undefined) return <main className="session-login ppt-theme"><div className="page-loading" role="status"><i /><b>세션을 확인하고 있습니다.</b></div></main>;
  if (!session) return <SessionLogin notice={sessionNotice} onAuthenticated={(nextSession) => { setSession(nextSession); setSessionNotice(""); }} />;

  const signOut = async () => {
    if (reportDirty && !window.confirm("저장하지 않은 보고서 변경사항이 있습니다. 로그아웃할까요?")) return;
    window.dispatchEvent(new CustomEvent("answervice:clear-drafts"));
    try { await createAnalysisClient(fetch).logout(); } finally { setSessionNotice(""); setSession(null); }
  };

  return <><div className={`app-shell ppt-theme ${menuOpen ? "" : "sidebar-collapsed"} ${reportEditorMode ? "report-editor-mode" : ""} ${isPending ? "is-page-pending" : ""} ${sessionNotice ? "session-locked" : ""}`} inert={sessionNotice ? true : undefined} aria-hidden={sessionNotice ? "true" : undefined}>
    <AppSidebar page={route.page} role={role} capabilities={capabilities} onNavigate={navigate} open={menuOpen} onClose={() => setMenuOpen(false)} />
    <div className="workspace"><AppHeader title={title} description={description} role={role} onMenu={() => setMenuOpen(true)} onSignOut={signOut} /><div className="page-progress" aria-hidden="true" /><main className="page-stage" key={route.path} aria-busy={isPending}><Suspense fallback={<div className="page-loading"><i /><b>페이지를 준비하고 있습니다.</b></div>}>{content}</Suspense></main></div>
  </div>{sessionNotice && <div className="session-reauth-layer" role="dialog" aria-modal="true" aria-label="세션 만료"><SessionLogin embedded notice={sessionNotice} onAuthenticated={(nextSession) => { setSession(nextSession); setSessionNotice(""); }} /></div>}</>;
}
