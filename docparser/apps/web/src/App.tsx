import { useEffect } from 'react';
import { RouterProvider } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { router }      from './router';
import { queryClient } from './lib/queryClient';
import { useUIStore }  from './store/uiStore';

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

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <KeyboardShortcuts />
      <RouterProvider router={router} />
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
      />
    </QueryClientProvider>
  );
}
