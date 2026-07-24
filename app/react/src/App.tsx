import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage.tsx';
import VocCustomerPage from './pages/VocCustomerPage.tsx';
import MonitoringPage from './pages/MonitoringPage.tsx';
import ChatQueryPage from './pages/ChatQueryPage.tsx';
import ReportListPage from './pages/ReportListPage.tsx';
import ReportEditorPage from './pages/ReportEditorPage.tsx';
import ExternalReviewPage from './pages/ExternalReviewPage.tsx';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const user = sessionStorage.getItem('sp_user');
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/voc" element={<VocCustomerPage />} />
        <Route path="/monitoring" element={<ProtectedRoute><MonitoringPage /></ProtectedRoute>} />
        <Route path="/chat" element={<ProtectedRoute><ChatQueryPage /></ProtectedRoute>} />
        <Route path="/reports" element={<ProtectedRoute><ReportListPage /></ProtectedRoute>} />
        <Route path="/reports/editor" element={<ProtectedRoute><ReportEditorPage /></ProtectedRoute>} />
        <Route path="/external-review" element={<ProtectedRoute><ExternalReviewPage /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
