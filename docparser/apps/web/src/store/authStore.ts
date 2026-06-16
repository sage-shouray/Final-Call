import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { User, LoginCredentials, AuthTokens } from '@/types';

interface AuthState {
  user:            User | null;
  accessToken:     string | null;
  refreshToken:    string | null;
  isAuthenticated: boolean;
}

interface AuthActions {
  setTokens: (tokens: AuthTokens, user: User) => void;
  logout:    () => void;
  /** Called by the API interceptor after a silent token refresh. */
  updateAccessToken: (accessToken: string, refreshToken: string) => void;
}

export type AuthStore = AuthState & AuthActions;

export const useAuthStore = create<AuthStore>()(
  persist(
    (set) => ({
      // ── State ──────────────────────────────────────────────────────────────
      user:            null,
      accessToken:     null,
      refreshToken:    null,
      isAuthenticated: false,

      // ── Actions ────────────────────────────────────────────────────────────
      setTokens(tokens, user) {
        set({
          accessToken:     tokens.access_token,
          refreshToken:    tokens.refresh_token,
          user,
          isAuthenticated: true,
        });
      },

      logout() {
        set({
          user:            null,
          accessToken:     null,
          refreshToken:    null,
          isAuthenticated: false,
        });
      },

      updateAccessToken(accessToken, refreshToken) {
        set({ accessToken, refreshToken });
      },
    }),
    {
      name:    'docparser-auth',   // must match AUTH_KEY in api.ts
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        user:         state.user,
        accessToken:  state.accessToken,
        refreshToken: state.refreshToken,
        // rehydrate isAuthenticated from stored tokens
        isAuthenticated: !!state.accessToken,
      }),
    },
  ),
);

// ── Standalone login / logout helpers (not inside React components) ──────────

export async function loginUser(credentials: LoginCredentials): Promise<void> {
  const { default: api } = await import('@/lib/api');
  const resp = await api.post<{ access_token: string; refresh_token: string; token_type: string; expires_in: number; user: User }>(
    '/auth/login',
    credentials,
  );
  const { user, ...tokens } = resp.data as { user: User; access_token: string; refresh_token: string; token_type: string; expires_in: number };
  useAuthStore.getState().setTokens(tokens as AuthTokens, user);
}

export async function logoutUser(): Promise<void> {
  try {
    const { default: api } = await import('@/lib/api');
    const refresh = useAuthStore.getState().refreshToken;
    if (refresh) {
      await api.post('/auth/logout', { refresh_token: refresh });
    }
  } catch {
    // proceed with local logout even if server call fails
  } finally {
    useAuthStore.getState().logout();
  }
}
