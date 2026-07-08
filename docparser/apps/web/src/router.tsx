import { lazy, Suspense } from 'react';
import {
  createBrowserRouter,
  Navigate,
  type RouteObject,
} from 'react-router-dom';
import { AppLayout } from '@/components/layout/AppLayout';
import { Spinner }     from '@/components/ui/Spinner';

// Lazy-loaded pages
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
  return <AppLayout />;
}

function defaultLandingPath(): string {
  try {
    const raw = localStorage.getItem('uvira-app-prefs');
    if (raw) {
      const prefs = JSON.parse(raw) as { defaultView?: string };
      if (prefs.defaultView === 'documents') return '/documents';
      if (prefs.defaultView === 'upload')    return '/upload';
    }
  } catch { /* ignore */ }
  return '/dashboard';
}

function GuestRoute() {
  return <Navigate to="/dashboard" replace />;
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
