import { apiPost } from "./apiClient";

const SESSION_KEY = "senseplace.demo.session";

export const demoAccount = {
  email: "manager@senseplace.kr",
  password: "demo1234",
  name: "Minji Song",
  role: "Operations Manager",
};

export function getDemoSession() {
  try {
    return JSON.parse(window.sessionStorage.getItem(SESSION_KEY));
  } catch {
    return null;
  }
}

export async function signInDemo(email, password) {
  // Django API 호출 시도
  try {
    const res = await apiPost("/auth/login/", { username: email, password });
    if (res && res.data && !res.error) {
      const session = {
        name: res.data.display_name || res.data.username || demoAccount.name,
        role: res.data.role_code || demoAccount.role,
        email: email,
      };
      window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
      return session;
    }
  } catch (e) {
    // API 실패 시 fallback 진행
    console.warn("Django API 로그인 실패, 데모 fallback 사용:", e.message);
  }

  // Fallback: 기존 하드코딩 인증
  if (email.trim().toLowerCase() !== demoAccount.email || password !== demoAccount.password) return null;
  const session = { name: demoAccount.name, role: demoAccount.role, email: demoAccount.email };
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  return session;
}

export async function signOutDemo() {
  try {
    await apiPost("/auth/logout/");
  } catch {
    // ignore
  }
  window.sessionStorage.removeItem(SESSION_KEY);
}
