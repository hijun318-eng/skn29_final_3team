/** 인증된 애플리케이션 셸의 세션·권한·라우팅·lazy loading 경계를 조정하는 모듈이다. */
import { lazy, Suspense, useCallback, useEffect, useMemo, useState, useTransition } from "react";
import { AppHeader } from "./components/layout/AppHeader";
import { SessionLogin } from "./components/auth/SessionLogin";
import { createAdminClient } from "./api/adminClient.ts";
import { createAnalysisClient } from "./api/analysisClient.ts";
import { clearAuthenticatedBrowserState } from "./authenticatedBrowserState.js";
import { CAPABILITY, hasCapability } from "./authorization.ts";
import { PAGE_PATHS, resolveRoute } from "./routing";
import { REPORT_BUILDER_V2 } from "./features/reports/reportBuilderFlags";
import { nextTheme, readTheme, saveTheme } from "./themePreference";

const AgentPage = lazy(() => import("./pages/AgentPage").then((module) => ({ default: module.AgentPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })));
const AdminPage = lazy(() => import("./pages/AdminPage").then((module) => ({ default: module.AdminPage })));

const PAGE_META = {
  chat: ["데이터 분석", "자연어로 질문하면 지표와 기간을 해석해 데이터를 분석합니다."],
  reports: ["보고서", "분석 결과를 보고서로 구성하고 편집·검토합니다."],
  admin: ["관리자", "현재 계정의 운영 권한과 연결된 관리 기능을 확인합니다."],
  notFound: ["페이지를 찾을 수 없습니다", "현재 제공되는 경로를 확인해 주세요."],
};

/** 알 수 없는 경로를 표시하고 유효한 분석 경로로만 복귀시킨다. */
function NotFoundPage({ onNavigate }) {
  return <section className="not-found" aria-labelledby="not-found-title"><span>404</span><h2 id="not-found-title">지원하지 않는 경로입니다.</h2><button className="primary" onClick={() => onNavigate(PAGE_PATHS.chat)}>데이터 분석으로 이동</button></section>;
}

/** 세션 역할에 허용되지 않은 화면을 차단하고 가능한 허용 경로만 안내한다. */
function RoleAccessPage({ canUseReports, canUseAdmin, onNavigate }) {
  const allowedPath = canUseReports ? PAGE_PATHS.reports : canUseAdmin ? PAGE_PATHS.admin : "";
  const allowedLabel = canUseReports ? "보고서로 이동" : "관리자로 이동";
  return <section className="not-found" aria-labelledby="role-access-title"><span>403</span><h2 id="role-access-title">이 화면에 접근할 권한이 없습니다.</h2><p>{allowedPath ? "현재 계정에서 사용할 수 있는 화면으로 이동해 주세요." : "현재 계정에 허용된 서비스 메뉴가 없습니다."}</p>{allowedPath && <button className="primary" onClick={() => onNavigate(allowedPath)}>{allowedLabel}</button>}</section>;
}

/** 세션·권한·라우팅 경계를 소유하며, 인증 확인 전에는 보호된 화면을 렌더링하지 않는다. */
export function App() {
  const [session, setSession] = useState();
  const [sessionNotice, setSessionNotice] = useState("");
  const [theme, setTheme] = useState(() => readTheme());
  const [reportEditorMode, setReportEditorMode] = useState(false);
  const [reportDirty, setReportDirty] = useState(false);
  const role = session?.role || "";
  const capabilities = session?.capabilities;
  const canRunAnalysis = hasCapability(capabilities, CAPABILITY.runAnalysis);
  const canDraftReport = hasCapability(capabilities, CAPABILITY.draftReport);
  const canManageReports = hasCapability(capabilities, CAPABILITY.manageReport);
  const canManageSystem = hasCapability(capabilities, CAPABILITY.manageSystem);
  const canUseReports = canDraftReport || canManageReports;
  const canUseAdmin = canManageSystem;
  const adminClient = useMemo(() => canUseAdmin ? createAdminClient(undefined, fetch) : null, [canUseAdmin]);
  const [route, setRoute] = useState(() => resolveRoute(window.location.pathname));
  const [isPending, startTransition] = useTransition();
  const themeClass = theme === "dark" ? "ppt-theme theme-dark" : "theme-light";
  const toggleTheme = useCallback(() => setTheme(nextTheme), []);
  const [title, description] = route.page === "reports"
    ? reportEditorMode
      ? ["보고서 편집", "근거가 연결된 분석 결과와 설명을 블록으로 구성하고 저장합니다."]
      : ["보고서", "분석 결과를 보고서로 구성하고 편집·검토합니다."]
    : PAGE_META[route.page];

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    saveTheme(theme);
  }, [theme]);

  useEffect(() => {
    let active = true;
    createAnalysisClient(fetch).validateSession()
      .then((restored) => { if (active) setSession(restored); })
      .catch(() => {
        if (active) {
          clearAuthenticatedBrowserState();
          setSession(null);
        }
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const updateDirty = (event) => setReportDirty(Boolean(event.detail));
    window.addEventListener("answervice:report-dirty", updateDirty);
    return () => window.removeEventListener("answervice:report-dirty", updateDirty);
  }, []);

  useEffect(() => {
    const expireSession = () => {
      clearAuthenticatedBrowserState();
      setReportDirty(false);
      setSessionNotice("세션이 만료되었습니다. 안전을 위해 사용자 임시 상태를 지웠습니다. 다시 로그인해 주세요.");
      setSession(null);
    };
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
      startTransition(() => setRoute(resolveRoute(window.location.pathname)));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [reportDirty, route.path]);

  const navigate = useCallback((nextPath) => {
    const nextRoute = resolveRoute(nextPath);
    if (nextRoute.path === route.path) {
      window.dispatchEvent(new CustomEvent("answervice:navigate", { detail: nextRoute.path }));
      return;
    }
    if (reportDirty && !window.confirm("저장하지 않은 보고서 변경사항이 있습니다. 페이지를 이동할까요?")) return;
    window.history.pushState({}, "", nextRoute.path);
    startTransition(() => setRoute(nextRoute));
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "instant" }));
  }, [reportDirty, route.path]);

  const handleReportEditorMode = useCallback((active) => setReportEditorMode(active), []);

  useEffect(() => {
    if (!canRunAnalysis && route.page === "chat") {
      if (canUseReports) navigate(PAGE_PATHS.reports);
      else if (canUseAdmin) navigate(PAGE_PATHS.admin);
    }
  }, [canRunAnalysis, canUseAdmin, canUseReports, navigate, route.page]);

  const content = useMemo(() => {
    if (route.page === "notFound") return <NotFoundPage onNavigate={navigate} />;
    if (route.page === "reports") {
      if (!canUseReports) return <RoleAccessPage canUseReports={false} canUseAdmin={canUseAdmin} onNavigate={navigate} />;
      return <ReportsPage
        role={role}
        isAdmin={canManageReports}
        onEditorMode={handleReportEditorMode}
        theme={theme}
        onToggleTheme={toggleTheme}
      />;
    }
    if (route.page === "admin") {
      if (!canUseAdmin) return <RoleAccessPage canUseReports={canUseReports} canUseAdmin={false} onNavigate={navigate} />;
      return <AdminPage role={role} client={adminClient} />;
    }
    if (!canRunAnalysis) return <RoleAccessPage canUseReports={canUseReports} canUseAdmin={canUseAdmin} onNavigate={navigate} />;
    return <AgentPage canDraftReport={canDraftReport} onNavigate={navigate} />;
  }, [adminClient, canDraftReport, canManageReports, canRunAnalysis, canUseAdmin, canUseReports, handleReportEditorMode, navigate, role, route.page, theme, toggleTheme]);

  if (session === undefined) return <main className={`session-login ${themeClass}`}><div className="page-loading" role="status"><i /><b>세션을 확인하고 있습니다.</b></div></main>;
  if (!session) return <SessionLogin theme={theme} onToggleTheme={toggleTheme} notice={sessionNotice} onAuthenticated={(nextSession) => { setSession(nextSession); setSessionNotice(""); }} />;

  const signOut = async () => {
    if (reportDirty && !window.confirm("저장하지 않은 보고서 변경사항이 있습니다. 로그아웃할까요?")) return;
    window.dispatchEvent(new CustomEvent("answervice:clear-drafts"));
    try {
      await createAnalysisClient(fetch).logout();
    } finally {
      clearAuthenticatedBrowserState();
      setReportDirty(false);
      setSessionNotice("");
      setSession(null);
    }
  };

  return <div className={`app-shell ${themeClass} ${reportEditorMode ? "report-editor-mode" : ""} ${reportEditorMode && REPORT_BUILDER_V2 ? "report-builder-v2-mode" : ""} ${isPending ? "is-page-pending" : ""}`}>
    <div className="workspace"><AppHeader page={route.page} title={title} description={description} role={role} capabilities={capabilities} theme={theme} onNavigate={navigate} onSignOut={signOut} onToggleTheme={toggleTheme} /><div className="page-progress" aria-hidden="true" /><main className="page-stage" key={route.path} aria-busy={isPending}><Suspense fallback={<div className="page-loading"><i /><b>페이지를 준비하고 있습니다.</b></div>}>{content}</Suspense></main></div>
  </div>;
}
