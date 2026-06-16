import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore, loginUser, logoutUser } from '@/store/authStore';
import type { LoginCredentials } from '@/types';

export function useAuth() {
  const navigate  = useNavigate();
  const store     = useAuthStore();

  const login = useCallback(
    async (credentials: LoginCredentials, returnTo = '/dashboard') => {
      await loginUser(credentials);
      navigate(returnTo, { replace: true });
    },
    [navigate],
  );

  const logout = useCallback(async () => {
    await logoutUser();
    navigate('/login', { replace: true });
  }, [navigate]);

  return {
    user:            store.user,
    isAuthenticated: store.isAuthenticated,
    role:            store.user?.role ?? null,
    login,
    logout,
  };
}
