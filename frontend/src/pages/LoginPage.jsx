import { useState } from "react";
import { ArrowRight, Eye, EyeOff, LockKeyhole, ShieldCheck } from "lucide-react";
import { demoAccount, signInDemo } from "../services/demoAuth";

export function LoginPage() {
  const [email, setEmail] = useState(demoAccount.email);
  const [password, setPassword] = useState(demoAccount.password);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");

  const submit = (event) => {
    event.preventDefault();
    if (!signInDemo(email, password)) {
      setError("데모 계정 정보를 다시 확인해 주세요.");
      return;
    }
    const next = new URLSearchParams(window.location.search).get("next");
    window.location.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/");
  };

  return <main className="login-page">
    <section className="login-brand-panel">
      <a className="login-brand" href="/login" aria-label="Sense Place 로그인"><span><b>SP</b><i /></span><div><strong>SENSE PLACE</strong><small>Operation Intelligence</small></div></a>
      <div className="login-brand-copy"><p>OPERATION INTELLIGENCE</p><h1>SENSE PLACE<br />OPERATION INTELLIGENCE</h1><span>VOC와 운영 데이터를 연결해 중요한 이슈를 더 빠르게 발견하고 판단합니다.</span></div>
      <div className="login-security-note"><ShieldCheck size={18} /><span><b>관리자 전용 공간</b><small>허가된 운영 담당자만 접근할 수 있습니다.</small></span></div>
    </section>

    <section className="login-form-panel">
      <div className="login-form-wrap">
        <div className="login-heading"><span><LockKeyhole size={21} /></span><p>WELCOME BACK</p><h2>Sense Place 로그인</h2><small>운영 대시보드에 접속하려면 계정 정보를 입력하세요.</small></div>
        <form className="login-form" onSubmit={submit}>
          <label><span>이메일</span><input type="email" value={email} onChange={(event) => { setEmail(event.target.value); setError(""); }} autoComplete="username" required /></label>
          <label><span>비밀번호</span><div className="password-field"><input type={showPassword ? "text" : "password"} value={password} onChange={(event) => { setPassword(event.target.value); setError(""); }} autoComplete="current-password" required /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></div></label>
          {error && <p className="login-error" role="alert">{error}</p>}
          <button className="login-submit" type="submit">로그인 <ArrowRight size={17} /></button>
        </form>
        <div className="demo-account"><b>프런트엔드 데모 계정</b><span>{demoAccount.email}</span><span>{demoAccount.password}</span><small>현재 화면은 UI 검증용 목업이며 실제 인증 서버와 연결되지 않았습니다.</small></div>
      </div>
    </section>
  </main>;
}
