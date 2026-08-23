/** cookie 기반 세션 로그인을 처리하고 재인증 화면에도 재사용되는 인증 UI 모듈이다. */
import { Eye, EyeOff, KeyRound, ShieldCheck, UserRound } from "lucide-react";
import { useState } from "react";
import { AnalysisApiError, createAnalysisClient } from "../../api/analysisClient.ts";
import { ThemeToggle } from "../common/ThemeToggle";

function loginError(failure) {
  if (failure instanceof AnalysisApiError && failure.status === 401) return "아이디 또는 비밀번호를 확인해 주세요.";
  if (failure instanceof AnalysisApiError && failure.status >= 500) return "로그인 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.";
  if (failure instanceof TypeError) return "서버에 연결할 수 없습니다. 네트워크 연결을 확인해 주세요.";
  return failure instanceof Error ? failure.message : "인증 정보를 확인할 수 없습니다.";
}

/** 자격 증명을 세션 API에만 전송하고, 인증 완료 전에는 onAuthenticated를 호출하지 않는 로그인 화면이다. */
export function SessionLogin({ onAuthenticated, notice = "", embedded = false, theme = "light", onToggleTheme }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const nextUsername = username.trim().toLowerCase();
    if (!nextUsername || !password || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const session = await createAnalysisClient(fetch).login(nextUsername, password);
      onAuthenticated(session);
    } catch (failure) {
      setError(loginError(failure));
    } finally {
      setSubmitting(false);
    }
  };

  const Root = embedded ? "div" : "main";
  const themeClass = theme === "dark" ? "ppt-theme theme-dark" : "theme-light";
  return <Root className={`session-login ${themeClass} ${embedded ? "session-login-embedded" : ""}`}>
    <section className="session-login-card" aria-labelledby="session-login-title">
      {onToggleTheme && <ThemeToggle className="session-theme-toggle" theme={theme} onToggle={onToggleTheme} />}
      <div className="session-login-logo"><span>AS</span><b>ANSWERVICE</b></div>
      <small>안전한 로그인</small>
      <h1 id="session-login-title">로그인</h1>
      {notice && <p className="session-login-notice" role="status">{notice}</p>}
      <form onSubmit={submit}>
        <label>아이디
          <span><UserRound size={17} /><input aria-label="아이디" autoComplete="username" value={username} onChange={(event) => { setUsername(event.target.value); setError(""); }} aria-invalid={Boolean(error)} required /></span>
        </label>
        <label>비밀번호
          <span><KeyRound size={17} /><input aria-label="비밀번호" type={showPassword ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => { setPassword(event.target.value); setError(""); }} onKeyDown={(event) => setCapsLock(event.getModifierState("CapsLock"))} onKeyUp={(event) => setCapsLock(event.getModifierState("CapsLock"))} aria-invalid={Boolean(error)} required /><button className="password-visibility" type="button" aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 표시"} aria-pressed={showPassword} onClick={() => setShowPassword((visible) => !visible)}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></span>
        </label>
        {capsLock && <p className="session-caps-lock" role="status">Caps Lock이 켜져 있습니다.</p>}
        {error && <p className="session-login-error" role="alert">{error}</p>}
        <button className="primary" disabled={!username.trim() || password.length < 8 || submitting}>{submitting ? "로그인 중…" : "로그인"}</button>
      </form>
      <em><ShieldCheck size={13} />인증 정보는 암호화된 연결을 통해 전송됩니다.</em>
    </section>
  </Root>;
}
