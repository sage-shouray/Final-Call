import { useEffect, useState } from 'react';
import { RouterProvider } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { Toaster, ToastBar, toast } from 'react-hot-toast';
import { X } from 'lucide-react';
import { router }      from './router';
import { queryClient } from './lib/queryClient';
import { useUIStore }  from './store/uiStore';
import { useAuthStore } from './store/authStore';
import { api } from './lib/api';

const SETTINGS_KEY = 'uvira-app-prefs';

function applyStoredPrefs() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    const prefs = raw ? (JSON.parse(raw) as { compactSidebar?: boolean; theme?: 'light' | 'dark' }) : {};
    if (prefs.compactSidebar) useUIStore.getState().setSidebarCollapsed(true);
    // Apply the saved theme on every boot — default to light if none saved yet.
    document.documentElement.classList.toggle('dark', prefs.theme === 'dark');
  } catch {
    document.documentElement.classList.remove('dark');
  }
}
applyStoredPrefs();

// One-time migration: clear any auth tokens left in localStorage from before
// the switch to sessionStorage, so old sessions can't bypass login.
try { localStorage.removeItem('docparser-auth'); } catch { /* ignore */ }

function KeyboardShortcuts() {
  const { toggleSidebar } = useUIStore();

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        document.getElementById('global-search')?.focus();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault();
        toggleSidebar();
      }
    }
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [toggleSidebar]);

  return null;
}

// Validates the stored token against the server on every app load.
// If the token is missing, expired, or rejected → force logout so the
// login page is shown instead of a broken authenticated state.
function SessionGuard({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false);
  const { isAuthenticated, logout } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated) {
      setChecked(true);
      return;
    }
    // Verify the stored token is still accepted by the server
    api.get('/auth/me')
      .then(() => setChecked(true))
      .catch(() => {
        // Token rejected (expired / invalid) — clear local state and show login
        logout();
        setChecked(true);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);   // run once on mount only

  if (!checked) {
    // Show a blank screen while we verify — prevents a flash of protected content
    return (
      <div className="flex h-screen items-center justify-center bg-neutral-50 dark:bg-neutral-950">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-neutral-300 border-t-indigo-600" />
      </div>
    );
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <KeyboardShortcuts />
      <SessionGuard>
        <RouterProvider router={router} />
      </SessionGuard>
      <Toaster
        position="bottom-right"
        gutter={8}
        toastOptions={{
          duration: 4000,
          style: {
            fontFamily:   'var(--ff-body)',
            fontSize:     '0.875rem',
            borderRadius: '0.75rem',
            boxShadow:    '0 4px 20px -4px rgba(0,0,0,0.18)',
            padding:      '10px 14px',
            maxWidth:     '380px',
          },
          success: {
            duration: 3500,
            style: { background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0' },
            iconTheme: { primary: '#16a34a', secondary: '#f0fdf4' },
          },
          error: {
            duration: Infinity,
            style: { background: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca' },
            iconTheme: { primary: '#dc2626', secondary: '#fef2f2' },
          },
          loading: {
            style: { background: '#eef2ff', color: '#3730a3', border: '1px solid #c7d2fe' },
          },
        }}
      >
        {(t) => (
          <ToastBar toast={t}>
            {({ icon, message }) => (
              <>
                {icon}
                <div className="flex-1">{message}</div>
                {/* Every toast — including the never-auto-dismissing error ones —
                    gets an explicit close button so it can always be cleared
                    without needing to reload the page. */}
                {t.type !== 'loading' && (
                  <button
                    type="button"
                    onClick={() => toast.dismiss(t.id)}
                    aria-label="Dismiss notification"
                    className="ml-1 shrink-0 rounded-md p-1 opacity-60 hover:opacity-100 hover:bg-black/5 transition-all"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </>
            )}
          </ToastBar>
        )}
      </Toaster>
    </QueryClientProvider>
  );
}
