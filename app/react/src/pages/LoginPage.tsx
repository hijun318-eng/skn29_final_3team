/**
 * SP-01 로그인 화면
 * @see SensePlace_목업_v1.2.html — #sp01
 */

import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../components/Layout.tsx';
import { useAuth } from '../hooks/useAuth.ts';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [userId, setUserId] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [locked, setLocked] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = userId.trim().length > 0 && password.trim().length > 0;

  const handleLogin = useCallback(async () => {
    if (submitting) return;
    if (!canSubmit) return;
    setSubmitting(true);
    setError('');

    const result = await login(userId.trim(), password);

    if (result.success) {
      navigate('/monitoring');
    } else {
      setError('아이디 또는 비밀번호가 올바르지 않습니다');
      setLocked(result.locked);
    }
    setSubmitting(false);
  }, [userId, password, submitting, canSubmit, login, navigate]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && canSubmit) {
      handleLogin();
    }
  };

  return (
    <Layout showTopbar={false}>
      <div className="center-wrap">
        <div className="card" style={{ width: 400, padding: '34px 30px' }}>
          <div style={{ textAlign: 'center', marginBottom: 26 }}>
            <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--brand-2)', letterSpacing: -0.5 }}>
              SensePlace
            </div>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              호텔 운영 지원 서비스
            </div>
          </div>

          {locked && (
            <div
              style={{
                fontSize: 12.5,
                background: '#fef2f2',
                border: '1px solid #fecaca',
                color: '#b91c1c',
                padding: '9px 12px',
                borderRadius: 8,
                marginBottom: 14,
              }}
            >
              🔒 5회 연속 실패로 잠금되었습니다 — 4:32 남음
            </div>
          )}

          <label className="form-label" style={{ display: 'block' }}>아이디</label>
          <input
            className="form-input"
            placeholder="staff.id"
            value={userId}
            onChange={(e) => { setUserId(e.target.value); setError(''); }}
            onKeyDown={handleKeyDown}
          />

          <label
            className="form-label"
            style={{ display: 'flex', justifyContent: 'space-between', marginTop: 14 }}
          >
            비밀번호
            <span
              style={{ cursor: 'pointer', color: 'var(--muted)', fontWeight: 500 }}
              onClick={() => setShowPw(!showPw)}
            >
              {showPw ? '🙈 숨김' : '👁 표시'}
            </span>
          </label>
          <input
            className="form-input"
            type={showPw ? 'text' : 'password'}
            placeholder="••••••••"
            value={password}
            onChange={(e) => { setPassword(e.target.value); setError(''); }}
            onKeyDown={handleKeyDown}
          />

          {error && (
            <div style={{ fontSize: 12, color: '#dc2626', margin: '2px 0 8px' }}>
              ⚠ {error}
            </div>
          )}

          <button
            className="btn primary"
            style={{ width: '100%', padding: 12, marginTop: 8 }}
            disabled={!canSubmit}
            onClick={handleLogin}
          >
            {submitting ? '로그인 중…' : '로그인'}
          </button>

          <div className="note" style={{ textAlign: 'center', marginTop: 16 }}>
            데모: 아이디·비밀번호 입력 후 로그인 → 모니터링 이동<br />
            &quot;lock&quot; 입력 시 잠금(423) 상태 미리보기
          </div>
        </div>
      </div>
    </Layout>
  );
}
