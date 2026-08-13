import { KeyRound, ShieldCheck, UserRound } from "lucide-react";
import { useState } from "react";
import { createAnalysisClient } from "../../api/analysisClient.ts";

export function SessionLogin({ onAuthenticated }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    const nextUsername = username.trim().toLowerCase();
    if (!nextUsername || !password || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const session = await createAnalysisClient(fetch).login(nextUsername, password);
      onAuthenticated({ token: session.session_token, role: session.role });
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
      <p>발급받은 계정으로 로그인하세요. 권한에 따라 분석 또는 보고서 관리 화면으로 안전하게 연결됩니다.</p>
      <form onSubmit={submit}>
        <label>아이디
          <span><UserRound size={17} /><input aria-label="아이디" autoComplete="username" value={username} onChange={(event) => { setUsername(event.target.value); setError(""); }} aria-invalid={Boolean(error)} required /></span>
        </label>
        <label>비밀번호
          <span><KeyRound size={17} /><input aria-label="비밀번호" type="password" autoComplete="current-password" value={password} onChange={(event) => { setPassword(event.target.value); setError(""); }} aria-invalid={Boolean(error)} required /></span>
        </label>
        {error && <p className="session-login-error" role="alert">{error}</p>}
        <button className="primary" disabled={!username.trim() || password.length < 8 || submitting}>{submitting ? "로그인 중…" : "로그인"}</button>
      </form>
      <em>계정에는 hotel_analyst 또는 report_admin 권한이 적용됩니다.</em>
    </section>
  </main>;
}
