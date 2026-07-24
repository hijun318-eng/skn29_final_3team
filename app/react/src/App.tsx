import { BrowserRouter, Routes, Route } from 'react-router-dom';

// ===== 임시 Placeholder 컴포넌트 =====

function LoginPage() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>로그인 (SP-01)</h1>
      <p style={{ color: 'var(--muted)', marginTop: '0.5rem' }}>
        직원 인증 화면
      </p>
    </div>
  );
}

function VOCPage() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>고객 VOC 제출 (SP-02)</h1>
      <p style={{ color: 'var(--muted)', marginTop: '0.5rem' }}>
        비로그인 · 링크 직접 진입 · 모바일
      </p>
    </div>
  );
}

function MonitoringPage() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>실시간 모니터링 (SP-03)</h1>
      <p style={{ color: 'var(--muted)', marginTop: '0.5rem' }}>
        운영자·실무자 기본 화면
      </p>
    </div>
  );
}

function ChatPage() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>대화형 조회 (SP-04)</h1>
      <p style={{ color: 'var(--muted)', marginTop: '0.5rem' }}>
        text-to-SQL (방식 B)
      </p>
    </div>
  );
}

function ReportsPage() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>보고서 목록 (SP-05a)</h1>
      <p style={{ color: 'var(--muted)', marginTop: '0.5rem' }}>
        탐색·생성·사본 허브
      </p>
    </div>
  );
}

function ReportEditorPage() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>보고서 에디터 (SP-05b)</h1>
      <p style={{ color: 'var(--muted)', marginTop: '0.5rem' }}>
        블록 에디터
      </p>
    </div>
  );
}

function ExternalReviewPage() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>외부 리뷰 (SP-06)</h1>
      <p style={{ color: 'var(--muted)', marginTop: '0.5rem' }}>
        관리자 · 외부↔내부 연결
      </p>
    </div>
  );
}

// ===== 메인 App 컴포넌트 =====

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/voc" element={<VOCPage />} />
        <Route path="/monitoring" element={<MonitoringPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/reports/:id/edit" element={<ReportEditorPage />} />
        <Route path="/external-review" element={<ExternalReviewPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
