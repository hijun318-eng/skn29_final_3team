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

export function signInDemo(email, password) {
  if (email.trim().toLowerCase() !== demoAccount.email || password !== demoAccount.password) return null;
  const session = { name: demoAccount.name, role: demoAccount.role, email: demoAccount.email };
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  return session;
}

export function signOutDemo() {
  window.sessionStorage.removeItem(SESSION_KEY);
}
