import { useState, useCallback, useEffect } from 'react';
import { apiLogin, apiLogout, type User } from '../lib/api';

interface AuthState {
  user: User | null;
  loading: boolean;
  error: string | null;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    user: null,
    loading: false,
    error: null,
  });

  const login = useCallback(async (staffId: string, password: string) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await apiLogin(staffId, password);
      if (res.error) {
        setState({ user: null, loading: false, error: res.error.message });
        return { success: false, locked: res.error.code === 'E_AUTH' };
      }
      setState({ user: res.data.user, loading: false, error: null });
      sessionStorage.setItem('sp_user', JSON.stringify(res.data.user));
      return { success: true, locked: false };
    } catch {
      setState({ user: null, loading: false, error: '로그인 실패' });
      return { success: false, locked: false };
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // ignore
    }
    sessionStorage.removeItem('sp_user');
    setState({ user: null, loading: false, error: null });
  }, []);

  useEffect(() => {
    const saved = sessionStorage.getItem('sp_user');
    if (saved) {
      try {
        setState({ user: JSON.parse(saved), loading: false, error: null });
      } catch {
        // ignore
      }
    }
  }, []);

  return { ...state, login, logout };
}
