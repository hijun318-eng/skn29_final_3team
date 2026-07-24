import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage.tsx';
import VocCustomerPage from './pages/VocCustomerPage.tsx';
import MonitoringPage from './pages/MonitoringPage.tsx';
import ChatQueryPage from './pages/ChatQueryPage.tsx';
import ReportListPage from './pages/ReportListPage.tsx';
import ReportEditorPage from './pages/ReportEditorPage.tsx';
import ExternalReviewPage from './pages/ExternalReviewPage.tsx';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/voc" element={<VocCustomerPage />} />
        <Route path="/monitoring" element={<MonitoringPage />} />
        <Route path="/chat" element={<ChatQueryPage />} />
        <Route path="/reports" element={<ReportListPage />} />
        <Route path="/reports/editor" element={<ReportEditorPage />} />
        <Route path="/external-review" element={<ExternalReviewPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
