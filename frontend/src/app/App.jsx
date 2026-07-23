import { DashboardPage } from "../pages/DashboardPage";
import { SatisfactionPage } from "../pages/SatisfactionPage";
import { GuestGuidePage, StayReviewPage } from "../pages/HospitalityPages";
import { EvidenceReviewPage } from "../pages/EvidenceReviewPage";
import { ExecutiveBriefingPage } from "../pages/ExecutiveBriefingPage";
import { MonitoringPage } from "../pages/MonitoringPage";
import { IssueAnalysisPage } from "../pages/IssueAnalysisPage";
import { LoginPage } from "../pages/LoginPage";
import { getDemoSession } from "../services/demoAuth";

export function App() {
  const currentPath = window.location.pathname;
  const publicPaths = ["/feedback", "/guest-guide", "/stay-review"];
  const isPublicPath = publicPaths.some((path) => currentPath.startsWith(path));

  if (currentPath.startsWith("/login")) {
    if (getDemoSession()) {
      window.location.replace("/");
      return null;
    }
    return <LoginPage />;
  }

  if (!isPublicPath && !getDemoSession()) {
    window.location.replace(`/login?next=${encodeURIComponent(`${currentPath}${window.location.search}`)}`);
    return null;
  }

  if (window.location.pathname.startsWith("/feedback")) {
    return <SatisfactionPage />;
  }
  if (window.location.pathname.startsWith("/guest-guide")) {
    return <GuestGuidePage />;
  }
  if (window.location.pathname.startsWith("/stay-review")) {
    return <StayReviewPage />;
  }
  if (window.location.pathname.startsWith("/evidence-review")) {
    return <EvidenceReviewPage />;
  }
  if (window.location.pathname.startsWith("/reports")) {
    return <ExecutiveBriefingPage />;
  }
  if (window.location.pathname.startsWith("/monitoring")) {
    return <MonitoringPage />;
  }
  if (window.location.pathname.startsWith("/issues")) {
    return <IssueAnalysisPage />;
  }

  return <DashboardPage />;
}
