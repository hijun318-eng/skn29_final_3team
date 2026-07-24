import { useState, useCallback, useEffect } from 'react';
import { apiLogin, apiLogout, type User, type UserRole } from '../lib/api';

interface AuthState {
  user: User | null;
  loading: boolean;
  error: string | null;
}

function mapRoleCode(roleCode: string): UserRole {
  switch (roleCode) {
    case 'OPERATIONS_MANAGER':
      return 'admin';
    case 'FACILITY_MANAGER':
      return 'staff';
    case 'EXTERNAL_REVIEWER':
      return 'guest';
    default:
      return 'guest';
  }
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
        const isLocked = String(res.error.code).toUpperCase() === 'LOCKED';
        setState({ user: null, loading: false, error: res.error.message });
        return { success: false, locked: isLocked };
      }
      const d = res.data;
      const user: User = {
        id: d.user_id,
        name: d.display_name,
        email: '',
        role: mapRoleCode(d.role_code),
      };
      setState({ user, loading: false, error: null });
      sessionStorage.setItem('sp_user', JSON.stringify(user));
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
