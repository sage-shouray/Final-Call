import { lazy, Suspense } from 'react';
import {
  createBrowserRouter,
  Navigate,
  Outlet,
  type RouteObject,
} from 'react-router-dom';
import { AppLayout }   from '@/components/layout/AppLayout';
import { AdminLayout } from '@/components/layout/AdminLayout';
import { Spinner }     from '@/components/ui/Spinner';
import { useAuthStore } from '@/store/authStore';

// Lazy-loaded pages
const AdminPage           = lazy(() => import('@/pages/AdminPage'));
const AdminCompanyPage    = lazy(() => import('@/pages/AdminCompanyPage'));
const AdminCompanyNewPage = lazy(() => import('@/pages/AdminCompanyNewPage'));
const AdminBillingPage    = lazy(() => import('@/pages/AdminBillingPage'));
const AdminActivityPage   = lazy(() => import('@/pages/AdminActivityPage'));

const TeamPage           = lazy(() => import('@/pages/TeamPage'));

const LoginPage          = lazy(() => import('@/pages/LoginPage'));
const DashboardPage      = lazy(() => import('@/pages/DashboardPage'));
const UploadPage         = lazy(() => import('@/pages/UploadPage'));
const DocumentsPage      = lazy(() => import('@/pages/DocumentsPage'));
const DocumentDetailPage = lazy(() => import('@/pages/DocumentDetailPage'));
const NotFoundPage       = lazy(() => import('@/pages/NotFoundPage'));
const SettingsPage       = lazy(() => import('@/pages/SettingsPage'));
const ReportsPage        = lazy(() => import('@/pages/ReportsPage'));

function PageFallback() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Spinner size="lg" className="text-primary-500" />
    </div>
  );
}

function ProtectedRoute() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <AppLayout />;
}

function AdminRoute() {
  const { isAuthenticated, user } = useAuthStore((s) => ({ isAuthenticated: s.isAuthenticated, user: s.user }));
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (user?.role !== 'admin') return <Navigate to="/dashboard" replace />;
  return <AdminLayout />;
}

function defaultLandingPath(): string {
  // Role-aware landing: operators go straight to upload, managers to dashboard
  const role = useAuthStore.getState().user?.role ?? 'operator';
  if (role === 'operator') return '/upload';
  return '/dashboard';
}

// Redirect already-logged-in users away from /login
function GuestRoute() {
  const { isAuthenticated, user } = useAuthStore((s) => ({ isAuthenticated: s.isAuthenticated, user: s.user }));
  if (isAuthenticated) {
    // Admins land on the admin panel; everyone else on dashboard
    return <Navigate to={user?.role === 'admin' ? '/admin' : '/dashboard'} replace />;
  }
  return <Outlet />;
}

const routes: RouteObject[] = [
  // Public
  {
    element: <GuestRoute />,
    children: [{ path: '/login', element: <LoginPage /> }],
  },

  // Protected — inside AppLayout shell
  {
    element: <ProtectedRoute />,
    children: [
      { index: true, element: <Navigate to={defaultLandingPath()} replace /> },
      {
        path: '/dashboard',
        element: (
          <Suspense fallback={<PageFallback />}>
            <DashboardPage />
          </Suspense>
        ),
      },
      {
        path: '/upload',
        element: (
          <Suspense fallback={<PageFallback />}>
            <UploadPage />
          </Suspense>
        ),
      },
      {
        path: '/documents',
        element: (
          <Suspense fallback={<PageFallback />}>
            <DocumentsPage />
          </Suspense>
        ),
      },
      {
        path: '/documents/:id',
        element: (
          <Suspense fallback={<PageFallback />}>
            <DocumentDetailPage />
          </Suspense>
        ),
      },
      {
        path: '/reports',
        element: (
          <Suspense fallback={<PageFallback />}>
            <ReportsPage />
          </Suspense>
        ),
      },
      {
        path: '/settings',
        element: (
          <Suspense fallback={<PageFallback />}>
            <SettingsPage />
          </Suspense>
        ),
      },
      {
        path: '/team',
        element: (
          <Suspense fallback={<PageFallback />}>
            <TeamPage />
          </Suspense>
        ),
      },
    ],
  },

  // Admin panel — separate layout
  {
    path: '/admin',
    element: <AdminRoute />,
    children: [
      {
        index: true,
        element: <Suspense fallback={<PageFallback />}><AdminPage /></Suspense>,
      },
      {
        path: 'companies',
        element: <Navigate to="/admin" replace />,
      },
      {
        path: 'companies/new',
        element: <Suspense fallback={<PageFallback />}><AdminCompanyNewPage /></Suspense>,
      },
      {
        path: 'companies/:id',
        element: <Suspense fallback={<PageFallback />}><AdminCompanyPage /></Suspense>,
      },
      {
        path: 'billing',
        element: <Suspense fallback={<PageFallback />}><AdminBillingPage /></Suspense>,
      },
      {
        path: 'activity',
        element: <Suspense fallback={<PageFallback />}><AdminActivityPage /></Suspense>,
      },
    ],
  },

  // 404
  {
    path: '*',
    element: (
      <Suspense fallback={<PageFallback />}>
        <NotFoundPage />
      </Suspense>
    ),
  },
];

export const router = createBrowserRouter(routes);
