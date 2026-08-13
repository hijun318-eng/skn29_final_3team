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

  return <main className="session-login ppt-theme">
    <section className="session-login-card" aria-labelledby="session-login-title">
      <div className="session-login-logo"><span>AS</span><b>ANSWERVICE</b></div>
      <small>SECURE SESSION</small>
      <h1 id="session-login-title">로그인</h1>
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
      <em><ShieldCheck size={13} />인증 정보는 암호화된 연결을 통해 전송됩니다.</em>
    </section>
  </main>;
}
