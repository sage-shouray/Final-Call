import axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios';

// ─────────────────────────────────────────────────────────────────────────────
// Storage helpers
// key must match the `name` option in authStore's persist config
// ─────────────────────────────────────────────────────────────────────────────

const AUTH_KEY = 'docparser-auth';

function getAccessToken(): string | null {
  try {
    const raw = sessionStorage.getItem(AUTH_KEY);
    return raw ? (JSON.parse(raw)?.state?.accessToken ?? null) : null;
  } catch {
    return null;
  }
}

function getRefreshToken(): string | null {
  try {
    const raw = sessionStorage.getItem(AUTH_KEY);
    return raw ? (JSON.parse(raw)?.state?.refreshToken ?? null) : null;
  } catch {
    return null;
  }
}

function setStoredTokens(accessToken: string, refreshToken: string): void {
  try {
    const raw = sessionStorage.getItem(AUTH_KEY);
    const parsed = raw ? JSON.parse(raw) : { state: {} };
    parsed.state.accessToken = accessToken;
    parsed.state.refreshToken = refreshToken;
    sessionStorage.setItem(AUTH_KEY, JSON.stringify(parsed));
  } catch {
    // ignore storage errors
  }
}

function clearStoredTokens(): void {
  try {
    sessionStorage.removeItem(AUTH_KEY);
  } catch {
    // ignore
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Axios instance
// ─────────────────────────────────────────────────────────────────────────────

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '/api',
  timeout: 180_000,
  headers: { 'Content-Type': 'application/json' },
});

// ── Request interceptor ───────────────────────────────────────────────────────

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  config.headers['X-Request-ID'] = crypto.randomUUID();
  return config;
});

// ── Response interceptor ──────────────────────────────────────────────────────

// Tracks an in-flight refresh so concurrent 401s don't each trigger a refresh
let refreshPromise: Promise<string> | null = null;

async function doTokenRefresh(): Promise<string> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) throw new Error('No refresh token');

  const resp = await axios.post('/api/auth/refresh', { refresh_token: refreshToken });
  const { access_token, refresh_token: newRefresh } = resp.data;
  setStoredTokens(access_token, newRefresh);
  return access_token;
}

api.interceptors.response.use(
  // Success: auto-unwrap data envelope if present
  (response: AxiosResponse) => {
    if (response.data && 'data' in response.data) {
      return { ...response, data: response.data.data };
    }
    return response;
  },

  async (error: AxiosError) => {
    const original = error.config as AxiosRequestConfig & { _retry?: boolean };

    // 401 handling — attempt token refresh then retry
    if (
      error.response?.status === 401 &&
      !original._retry &&
      !original.url?.includes('/auth/refresh') &&
      !original.url?.includes('/auth/login')
    ) {
      original._retry = true;
      try {
        if (!refreshPromise) {
          refreshPromise = doTokenRefresh().finally(() => {
            refreshPromise = null;
          });
        }
        const newToken = await refreshPromise;
        if (original.headers) {
          original.headers.Authorization = `Bearer ${newToken}`;
        }
        return api(original);
      } catch {
        // Refresh failed — force logout
        clearStoredTokens();
        window.location.href = `/login?returnTo=${encodeURIComponent(window.location.pathname)}`;
        return Promise.reject(error);
      }
    }

    return Promise.reject(error);
  },
);

export default api;
