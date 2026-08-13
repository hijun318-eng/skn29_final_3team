import { KeyRound, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { createAnalysisClient } from "../../api/analysisClient.ts";

export function SessionLogin({ onAuthenticated }) {
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    const nextToken = token.trim();
    if (!nextToken || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const session = await createAnalysisClient(fetch, nextToken).validateSession();
      onAuthenticated({ token: nextToken, role: session.role });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "인증 정보를 확인할 수 없습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="session-login">
    <section className="session-login-card" aria-labelledby="session-login-title">
      <div className="session-login-mark"><ShieldCheck size={30} /></div>
      <small>ANSWERVICE SECURE SESSION</small>
      <h1 id="session-login-title">서비스 인증</h1>
      <p>관리자가 발급한 액세스 토큰으로 현재 브라우저 탭의 세션을 시작합니다. 토큰은 빌드 파일이나 서버 로그에 저장되지 않습니다.</p>
      <form onSubmit={submit}>
        <label>액세스 토큰
          <span><KeyRound size={17} /><input aria-label="액세스 토큰" type="password" autoComplete="off" value={token} onChange={(event) => { setToken(event.target.value); setError(""); }} aria-invalid={Boolean(error)} required /></span>
        </label>
        {error && <p className="session-login-error" role="alert">{error}</p>}
        <button className="primary" disabled={!token.trim() || submitting}>{submitting ? "확인 중…" : "세션 시작"}</button>
      </form>
      <em>권한은 토큰에 연결된 서버 역할에 따라 적용됩니다.</em>
    </section>
  </main>;
}
