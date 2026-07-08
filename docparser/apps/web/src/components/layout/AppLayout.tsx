import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';

export function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden bg-neutral-50 dark:bg-neutral-900">
      <Sidebar />

      {/* Main content */}
      <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
        {/* Pages render their own Topbar and body */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
